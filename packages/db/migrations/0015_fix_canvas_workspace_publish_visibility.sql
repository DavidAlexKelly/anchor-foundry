-- ============================================================================
-- 0015_fix_canvas_workspace_publish_visibility.sql
-- canvas_apps' app_isolation policy (0009) resolves an app's owning
-- project's workspace_id with a subselect on `projects` itself:
--
--     EXISTS (SELECT 1 FROM projects p WHERE p.id = canvas_apps.project_id
--                                        AND rls_can_access_workspace(p.workspace_id))
--
-- `projects` is itself RLS-protected (proj_isolation, 0006): for a
-- permission_mode='custom' project that explicitly revokes a user
-- (project_members role='none'), that row is invisible to them entirely —
-- so the subselect returns zero rows and the "published to the whole
-- workspace" escape hatch silently never fires for exactly the case it
-- exists to serve: a workspace member with no access to the app's own
-- project. Same shape of bug as 0008/0009 (a policy reading a table whose
-- own RLS can hide the very row the policy needs), fixed the same way — a
-- SECURITY DEFINER helper that resolves the workspace_id without invoking
-- `projects`' policy.
-- ============================================================================

CREATE FUNCTION rls_project_workspace_id(p_project_id uuid) RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT workspace_id FROM projects WHERE id = p_project_id
$$;

REVOKE EXECUTE ON FUNCTION rls_project_workspace_id(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rls_project_workspace_id(uuid) TO platform_app;

DROP POLICY app_isolation ON canvas_apps;
CREATE POLICY app_isolation ON canvas_apps
    USING (
        rls_can_access_project(project_id)
        OR (publish_scope = 'workspace'
            AND rls_can_access_workspace(rls_project_workspace_id(project_id)))
        OR (publish_scope = 'groups' AND rls_app_shared_with_user(id))
    );
