-- ============================================================================
-- 0002_hierarchy.sql
-- Workspaces (bounded contexts with hard data isolation) and projects
-- (working folders). Spec §4, §16.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- workspaces — bounded contexts within an org. Stores s3_prefix, pg_schema,
-- search_prefix for isolation enforcement (spec §16, §4 "Workspace Isolation").
-- ----------------------------------------------------------------------------
CREATE TABLE workspaces (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id  uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    slug             text NOT NULL
                         CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'),
    description      text NOT NULL DEFAULT '',
    -- Isolation anchors. Set once at creation and never changed: IAM policies,
    -- the pg schema, and OpenSearch index templates are derived from these.
    -- Format (spec §8): s3 prefix "workspace-{slug}/", pg schema "ws_{short}",
    -- search prefix "ws-{short}-".
    s3_prefix        text NOT NULL,
    pg_schema        text NOT NULL,
    search_prefix    text NOT NULL,
    archived_at      timestamptz,
    created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organisation_id, slug),
    UNIQUE (s3_prefix),
    UNIQUE (pg_schema),
    UNIQUE (search_prefix)
);

CREATE INDEX idx_workspaces_org ON workspaces (organisation_id);

CREATE TRIGGER trg_workspaces_updated BEFORE UPDATE ON workspaces
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Isolation anchors are immutable after creation. An UPDATE that changed
-- s3_prefix/pg_schema/search_prefix would silently break IAM/RLS/index
-- scoping, so the database refuses it outright.
CREATE FUNCTION forbid_isolation_anchor_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.s3_prefix    IS DISTINCT FROM OLD.s3_prefix
    OR NEW.pg_schema    IS DISTINCT FROM OLD.pg_schema
    OR NEW.search_prefix IS DISTINCT FROM OLD.search_prefix THEN
        RAISE EXCEPTION 'workspace isolation anchors (s3_prefix, pg_schema, search_prefix) are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_workspaces_isolation_immutable BEFORE UPDATE ON workspaces
    FOR EACH ROW EXECUTE FUNCTION forbid_isolation_anchor_change();

-- ----------------------------------------------------------------------------
-- workspace_members — user OR group membership with a role (spec §16).
-- Exactly one of user_id / group_id is set.
-- ----------------------------------------------------------------------------
CREATE TABLE workspace_members (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id          uuid REFERENCES users(id) ON DELETE CASCADE,
    group_id         uuid REFERENCES groups(id) ON DELETE CASCADE,
    role             workspace_role NOT NULL,
    added_by         uuid REFERENCES users(id) ON DELETE SET NULL,
    added_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(user_id, group_id) = 1)
);

CREATE UNIQUE INDEX uq_workspace_members_user
    ON workspace_members (workspace_id, user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX uq_workspace_members_group
    ON workspace_members (workspace_id, group_id) WHERE group_id IS NOT NULL;
CREATE INDEX idx_workspace_members_user ON workspace_members (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_workspace_members_group ON workspace_members (group_id) WHERE group_id IS NOT NULL;

-- ----------------------------------------------------------------------------
-- projects — working folders inside a workspace. Toggle between inherited
-- and custom permissions (spec §16).
-- ----------------------------------------------------------------------------
CREATE TABLE projects (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    slug             text NOT NULL
                         CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'),
    description      text NOT NULL DEFAULT '',
    permission_mode  project_permission_mode NOT NULL DEFAULT 'inherited',
    archived_at      timestamptz,
    created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, slug)
);

CREATE INDEX idx_projects_workspace ON projects (workspace_id);

CREATE TRIGGER trg_projects_updated BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ----------------------------------------------------------------------------
-- project_members — user OR group membership with a role, including 'none'
-- to explicitly revoke a workspace-inherited grant (spec §9, §16).
-- Only consulted when projects.permission_mode = 'custom'.
-- ----------------------------------------------------------------------------
CREATE TABLE project_members (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id          uuid REFERENCES users(id) ON DELETE CASCADE,
    group_id         uuid REFERENCES groups(id) ON DELETE CASCADE,
    role             project_role NOT NULL,
    added_by         uuid REFERENCES users(id) ON DELETE SET NULL,
    added_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(user_id, group_id) = 1)
);

CREATE UNIQUE INDEX uq_project_members_user
    ON project_members (project_id, user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX uq_project_members_group
    ON project_members (project_id, group_id) WHERE group_id IS NOT NULL;
CREATE INDEX idx_project_members_user ON project_members (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_project_members_group ON project_members (group_id) WHERE group_id IS NOT NULL;
