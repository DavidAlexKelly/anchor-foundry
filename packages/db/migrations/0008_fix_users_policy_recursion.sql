-- ============================================================================
-- 0008_fix_users_policy_recursion.sql
-- The users_same_org policy (0006) resolved the caller's organisation with a
-- subselect on users itself; evaluating the policy re-invokes the policy —
-- PostgreSQL raises "infinite recursion detected in policy for relation
-- users" the moment the table is read under RLS. Replace the subselect with
-- a SECURITY DEFINER helper (executes as the table owner, bypassing RLS
-- inside, exactly like the other rls_* helpers from 0006).
-- ============================================================================

CREATE FUNCTION rls_user_org_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT u.organisation_id FROM users u WHERE u.id = rls_current_user_id()
$$;

DROP POLICY users_same_org ON users;
CREATE POLICY users_same_org ON users
    USING (
        current_setting('app.service', true) = 'worker'
        OR organisation_id = rls_user_org_id()
    );

-- groups/organisations policies from 0006 use the same self-referential
-- shape if they subselect users; groups_same_org subselects users (not
-- groups) so it does not recurse, but route it through the helper anyway for
-- one canonical code path and to avoid per-row subselect plans.
DROP POLICY groups_same_org ON groups;
CREATE POLICY groups_same_org ON groups
    USING (
        current_setting('app.service', true) = 'worker'
        OR organisation_id = rls_user_org_id()
    );
