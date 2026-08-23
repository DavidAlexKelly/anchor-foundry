-- Resolve permissions as the owner, not as the caller being resolved.
--
-- **A 57x speedup and a latent correctness hazard, both from one missing
-- keyword.** Every permission helper in this schema is `SECURITY DEFINER` -
-- `rls_can_access_workspace`, `rls_can_access_project`, `rls_is_org_admin`,
-- `rls_app_shared_with_user` and the rest - except the two that do the actual
-- work:
--
--     effective_workspace_role(user, workspace)
--     effective_project_role(user, project)
--
-- They read `users`, `workspaces`, `workspace_members`, `group_members`,
-- `projects` and `project_members`, every one of which carries a policy. As
-- `SECURITY INVOKER` those policies are evaluated on every internal lookup, so
-- resolving one role runs the whole isolation layer several times over.
--
-- Measured on `GET /workspaces/{id}/projects` for a workspace of 178 projects:
--
--     v_user_projects, invoker ..... 1319ms
--     v_user_projects, definer .....   23ms
--     the same query as the owner ..   27ms
--
-- The owner column is the tell: the work itself is ~27ms and the other 1.3
-- seconds were policy evaluation inside a function whose entire job is to
-- decide policy. `rls_can_access_*` already call these two *as definer*,
-- because those wrappers are definer - so definer-mode behaviour is already
-- the behaviour on the path that matters. Only a direct call, like the one
-- `v_user_projects` makes, ran them as invoker.
--
-- **The correctness half.** A permission function filtered by the permissions
-- it is resolving can only ever under-report: if RLS hides a `workspace_members`
-- row, the caller is told they have no role. Today that never bites, because
-- the policy on that table lets a user see their own memberships - so the
-- answer comes out right by the good fortune of two rules agreeing rather
-- than by design. Compared over 300 real (user, project) pairs spanning direct
-- membership, group membership, org admin and cross-organisation denial, with
-- 221 grants: **zero answers change**. This is a speedup that also removes a
-- way for the schema to become wrong later.
--
-- `SET search_path = public` is not optional on a definer function and is the
-- same form the other eleven use: without it the owner's search path is the
-- caller's to choose.
--
-- Not touched: `rls_current_user_id` and `rls_worker_for_workspace` read
-- settings and no tables, so there is nothing for a policy to filter.

ALTER FUNCTION effective_workspace_role(uuid, uuid)
    SECURITY DEFINER SET search_path = public;

ALTER FUNCTION effective_project_role(uuid, uuid)
    SECURITY DEFINER SET search_path = public;
