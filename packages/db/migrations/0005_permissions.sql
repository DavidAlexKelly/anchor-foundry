-- ============================================================================
-- 0005_permissions.sql
-- Permission resolution functions and views (spec §9 resolution algorithm,
-- §16 "Permission Functions"). These are the single source of truth for
-- authorisation; the API and row-level security both call them, so the two
-- enforcement layers cannot drift apart.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- effective_workspace_role(user_id, workspace_id) → workspace_role | NULL
--
-- Spec §16: "resolves a user's role considering direct membership, group
-- membership, and org admin status. Returns the highest applicable role or
-- null if no access."
--
-- Resolution order (spec §9):
--   1. org owner/admin  → 'admin' (full access to everything in the org)
--   2. highest of direct + group workspace memberships
--   3. NULL — for the API this means the workspace "does not exist" for
--      this user (404, not 403).
-- ----------------------------------------------------------------------------
CREATE FUNCTION effective_workspace_role(p_user_id uuid, p_workspace_id uuid)
RETURNS workspace_role
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    WITH target AS (
        SELECT w.id, w.organisation_id
        FROM workspaces w
        WHERE w.id = p_workspace_id
    ),
    org_admin AS (
        SELECT 'admin'::workspace_role AS role
        FROM users u
        JOIN target t ON t.organisation_id = u.organisation_id
        WHERE u.id = p_user_id
          AND u.org_role IN ('owner', 'admin')
          AND u.status = 'active'
    ),
    memberships AS (
        -- Direct membership
        SELECT wm.role
        FROM workspace_members wm
        JOIN target t ON t.id = wm.workspace_id
        WHERE wm.user_id = p_user_id
        UNION ALL
        -- Membership via any group the user belongs to
        SELECT wm.role
        FROM workspace_members wm
        JOIN target t ON t.id = wm.workspace_id
        JOIN group_members gm ON gm.group_id = wm.group_id
        WHERE gm.user_id = p_user_id
    ),
    ranked AS (
        SELECT role,
               CASE role
                   WHEN 'admin'  THEN 3
                   WHEN 'editor' THEN 2
                   WHEN 'viewer' THEN 1
               END AS rank
        FROM memberships
    )
    SELECT COALESCE(
        (SELECT role FROM org_admin),
        (SELECT role FROM ranked ORDER BY rank DESC LIMIT 1)
    );
$$;

-- ----------------------------------------------------------------------------
-- effective_project_role(user_id, project_id) → project_role | NULL
--
-- Spec §16: "resolves a user's role considering custom permissions or
-- workspace inheritance. Handles the 'none' revocation role."
--
-- Resolution (spec §9):
--   1. org owner/admin → 'owner' (full access; not revocable by 'none' —
--      "full access to everything in the org" is unconditional in the spec).
--   2. No workspace access → NULL (the project does not exist for this user).
--   3. permission_mode = 'inherited' → map workspace role:
--        admin → owner, editor → editor, viewer → viewer.
--      (Mapping not stated verbatim in the spec; this is the conservative
--      rank-preserving mapping. Flagged for review.)
--   4. permission_mode = 'custom' → consult project_members:
--        a. A DIRECT user entry always wins, including 'none' (explicit,
--           per-user assignments are more specific than group grants).
--        b. Otherwise group entries: if any grant a real role, take the
--           highest; if the only entries are 'none', access is revoked.
--        c. No entry at all → NULL. Conservative choice: in custom mode
--           silence means no access rather than falling back to workspace
--           inheritance; the admin opted out of inheritance deliberately.
--           Flagged for review.
--      'none' resolves to NULL (no access), never returned to callers.
-- ----------------------------------------------------------------------------
CREATE FUNCTION effective_project_role(p_user_id uuid, p_project_id uuid)
RETURNS project_role
LANGUAGE plpgsql STABLE PARALLEL SAFE
AS $$
DECLARE
    v_workspace_id  uuid;
    v_mode          project_permission_mode;
    v_org_id        uuid;
    v_is_org_admin  boolean;
    v_ws_role       workspace_role;
    v_direct        project_role;
    v_group         project_role;
    v_group_has_any boolean;
BEGIN
    SELECT p.workspace_id, p.permission_mode, w.organisation_id
      INTO v_workspace_id, v_mode, v_org_id
      FROM projects p
      JOIN workspaces w ON w.id = p.workspace_id
     WHERE p.id = p_project_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    -- 1. Org owners/admins have full access to everything in the org (§9).
    SELECT EXISTS (
        SELECT 1 FROM users u
        WHERE u.id = p_user_id
          AND u.organisation_id = v_org_id
          AND u.org_role IN ('owner', 'admin')
          AND u.status = 'active'
    ) INTO v_is_org_admin;

    IF v_is_org_admin THEN
        RETURN 'owner';
    END IF;

    -- 2. Without workspace membership the project does not exist for the user.
    v_ws_role := effective_workspace_role(p_user_id, v_workspace_id);
    IF v_ws_role IS NULL THEN
        RETURN NULL;
    END IF;

    -- 3. Inherited mode: rank-preserving mapping from workspace role.
    IF v_mode = 'inherited' THEN
        RETURN CASE v_ws_role
            WHEN 'admin'  THEN 'owner'::project_role
            WHEN 'editor' THEN 'editor'::project_role
            WHEN 'viewer' THEN 'viewer'::project_role
        END;
    END IF;

    -- 4. Custom mode.
    SELECT pm.role INTO v_direct
      FROM project_members pm
     WHERE pm.project_id = p_project_id AND pm.user_id = p_user_id;

    IF FOUND THEN
        IF v_direct = 'none' THEN
            RETURN NULL;        -- explicit revocation (§9)
        END IF;
        RETURN v_direct;
    END IF;

    SELECT
        bool_or(true),
        (SELECT pm2.role
           FROM project_members pm2
           JOIN group_members gm2 ON gm2.group_id = pm2.group_id
          WHERE pm2.project_id = p_project_id
            AND gm2.user_id = p_user_id
            AND pm2.role <> 'none'
          ORDER BY CASE pm2.role
                       WHEN 'owner'  THEN 3
                       WHEN 'editor' THEN 2
                       WHEN 'viewer' THEN 1
                   END DESC
          LIMIT 1)
      INTO v_group_has_any, v_group
      FROM project_members pm
      JOIN group_members gm ON gm.group_id = pm.group_id
     WHERE pm.project_id = p_project_id
       AND gm.user_id = p_user_id;

    IF v_group_has_any IS TRUE THEN
        RETURN v_group;         -- highest non-'none' group role, or NULL if
    END IF;                     -- every group entry was 'none' (revoked)

    RETURN NULL;                -- no custom entry → no access (see header)
END;
$$;

-- ----------------------------------------------------------------------------
-- v_user_workspaces — all workspaces a user can access with their role
-- (spec §16: "Used as the base for all workspace queries").
-- ----------------------------------------------------------------------------
CREATE VIEW v_user_workspaces AS
SELECT
    u.id                                        AS user_id,
    w.id                                        AS workspace_id,
    effective_workspace_role(u.id, w.id)        AS role,
    w.organisation_id,
    w.name,
    w.slug,
    w.description,
    w.s3_prefix,
    w.pg_schema,
    w.search_prefix,
    w.archived_at,
    w.created_at,
    w.updated_at
FROM users u
CROSS JOIN workspaces w
WHERE u.organisation_id = w.organisation_id
  AND effective_workspace_role(u.id, w.id) IS NOT NULL;

-- ----------------------------------------------------------------------------
-- v_user_projects — all projects a user can access with their role (§16).
-- ----------------------------------------------------------------------------
CREATE VIEW v_user_projects AS
SELECT
    u.id                                        AS user_id,
    p.id                                        AS project_id,
    p.workspace_id,
    effective_project_role(u.id, p.id)          AS role,
    p.name,
    p.slug,
    p.description,
    p.permission_mode,
    p.archived_at,
    p.created_at,
    p.updated_at
FROM users u
JOIN workspaces w ON w.organisation_id = u.organisation_id
JOIN projects p   ON p.workspace_id = w.id
WHERE effective_project_role(u.id, p.id) IS NOT NULL;
