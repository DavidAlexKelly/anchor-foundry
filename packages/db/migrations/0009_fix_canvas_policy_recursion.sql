-- ============================================================================
-- 0009_fix_canvas_policy_recursion.sql
-- app_isolation (canvas_apps) subselects canvas_app_shares, whose
-- apps_isolation subselects canvas_apps — PostgreSQL raises "infinite
-- recursion detected in policy for relation canvas_apps" the first time
-- either table is read under RLS. Same fix pattern as 0008: move the
-- cross-table lookups into SECURITY DEFINER helpers (owner execution
-- bypasses RLS inside the helper, cutting the cycle).
-- ============================================================================

-- Is the calling user in any group the app is shared with?
CREATE FUNCTION rls_app_shared_with_user(p_app_id uuid) RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
          FROM canvas_app_shares s
          JOIN group_members gm ON gm.group_id = s.group_id
         WHERE s.canvas_app_id = p_app_id
           AND gm.user_id = rls_current_user_id()
    )
$$;

-- Owning project of an app, resolved without invoking canvas_apps policies.
CREATE FUNCTION rls_app_project_id(p_app_id uuid) RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT project_id FROM canvas_apps WHERE id = p_app_id
$$;

REVOKE EXECUTE ON FUNCTION rls_app_shared_with_user(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION rls_app_project_id(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rls_app_shared_with_user(uuid) TO platform_app;
GRANT EXECUTE ON FUNCTION rls_app_project_id(uuid) TO platform_app;

DROP POLICY app_isolation ON canvas_apps;
CREATE POLICY app_isolation ON canvas_apps
    USING (
        rls_can_access_project(project_id)
        OR (publish_scope = 'workspace'
            AND EXISTS (SELECT 1 FROM projects p
                         WHERE p.id = canvas_apps.project_id
                           AND rls_can_access_workspace(p.workspace_id)))
        OR (publish_scope = 'groups' AND rls_app_shared_with_user(id))
    );

DROP POLICY apps_isolation ON canvas_app_shares;
CREATE POLICY apps_isolation ON canvas_app_shares
    USING (rls_can_access_project(rls_app_project_id(canvas_app_id)));
