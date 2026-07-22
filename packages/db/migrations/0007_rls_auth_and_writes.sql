-- ============================================================================
-- 0007_rls_auth_and_writes.sql
-- Two RLS refinements discovered while building the API layer:
--
-- 1. Auth-time user lookup. The JWT middleware (spec §9 step 5) must look a
--    user up by cognito_sub BEFORE app.user_id can be set — the generic
--    users policy would return nothing at that point. A narrow SELECT policy
--    keyed on app.cognito_sub (set by the middleware from the validated
--    token) permits exactly that one row.
--
-- 2. INSERT paths. The FOR ALL policies' WITH CHECK expressions evaluate
--    helper functions that query the table for the row being inserted, which
--    is not yet visible — so creation would always be denied. Explicit
--    INSERT policies express creation rights directly:
--      * workspaces: org owners/admins create workspaces
--      * projects:   workspace admins/editors create projects
--    (Permissive policies are OR-ed, so these add to, not replace, the
--    existing isolation policies.)
-- ============================================================================

CREATE POLICY users_auth_lookup ON users FOR SELECT
    USING (
        cognito_sub IS NOT NULL
        AND cognito_sub = current_setting('app.cognito_sub', true)
    );

CREATE FUNCTION rls_is_org_admin(p_org_id uuid) RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM users u
        WHERE u.id = rls_current_user_id()
          AND u.organisation_id = p_org_id
          AND u.org_role IN ('owner', 'admin')
          AND u.status = 'active'
    )
$$;

CREATE POLICY ws_insert ON workspaces FOR INSERT
    WITH CHECK (rls_is_org_admin(organisation_id));

CREATE POLICY proj_insert ON projects FOR INSERT
    WITH CHECK (
        effective_workspace_role(rls_current_user_id(), workspace_id)
            IN ('admin', 'editor')
        OR rls_worker_for_workspace(workspace_id)
    );

-- Organisation must also be readable during the auth bootstrap (middleware
-- attaches org context, §9 step 6) via the same cognito_sub keyhole.
CREATE POLICY org_auth_lookup ON organisations FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM users u
        WHERE u.organisation_id = organisations.id
          AND u.cognito_sub IS NOT NULL
          AND u.cognito_sub = current_setting('app.cognito_sub', true)
    ));
