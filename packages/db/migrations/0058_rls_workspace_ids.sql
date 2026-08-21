-- Make workspace isolation cost one evaluation per query instead of one per row.
--
-- **The measurement, before the change.** A bare
-- `SELECT id FROM object_types WHERE workspace_id = $1` returning 425 rows took
-- **237ms**, and the plan put every millisecond in one place:
--
--     Bitmap Heap Scan on object_types  (actual time=3.865..237.697 rows=425)
--       Filter: rls_can_access_workspace(workspace_id)
--
-- The same query as the owner role, which bypasses row-level security, is 5ms.
-- So the isolation predicate was ~98% of the cost, at 0.56ms per row.
--
-- **Why, and why it is not a missing index.** `rls_can_access_workspace` is
-- STABLE, so Postgres may hoist it out of a loop - but only when its argument
-- is a constant. `object_types.workspace_id` is a *column*, so the planner
-- treats it as varying and calls the function once per row, even though the
-- WHERE clause has already pinned that column to a single value. Each call runs
-- a four-CTE function over `workspaces`, `users`, `workspace_members` and
-- `group_members`, all of which carry policies of their own. The tables are
-- small and correctly indexed; the cost is the calling, not the looking.
--
-- **The fix is the standard idiom**: ask *which workspaces can this caller
-- see* once, and test membership of that answer per row.
-- `rls_workspace_ids()` takes **no arguments**, which is the whole point - a
-- zero-argument STABLE function is a constant expression, so the planner
-- evaluates it a single time per query and the per-row work becomes an array
-- containment check.
--
-- **Equivalence is the thing that matters here, not speed.** This is the
-- security backstop, and a faster predicate that admits one extra row is a
-- data leak rather than an optimisation. So the new function is built from the
-- same three sources `effective_workspace_role` resolves, plus the worker
-- path, rather than from a rewrite of the rule:
--
--   * the worker's single workspace (`rls_worker_for_workspace`),
--   * every workspace in the organisation of an active org owner/admin,
--   * direct workspace membership,
--   * workspace membership held through a group.
--
-- `effective_workspace_role` returns non-NULL exactly when one of the last
-- three matches, and `rls_can_access_workspace` is that OR the worker path -
-- so the two predicates agree by construction. `tests/test_rls_workspace_ids.py`
-- asserts it over every (user, workspace) pair the dev database holds rather
-- than trusting the argument.
--
-- SECURITY DEFINER for the same reason `rls_can_access_workspace` already is:
-- it reads `workspace_members`, which is itself one of the tables this policy
-- protects, and a policy that consulted a protected table as the caller would
-- fail closed - the recurring RLS bug class this repo has hit three times
-- (0008, 0009, 0015).

CREATE FUNCTION rls_workspace_ids() RETURNS uuid[]
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COALESCE(array_agg(DISTINCT id), '{}'::uuid[])
    FROM (
        -- The worker, which is scoped to exactly one workspace.
        SELECT nullif(current_setting('app.workspace_id', true), '')::uuid AS id
         WHERE current_setting('app.service', true) = 'worker'
        UNION ALL
        -- An org owner or admin sees every workspace in their organisation.
        SELECT w.id
          FROM workspaces w
          JOIN users u ON u.organisation_id = w.organisation_id
         WHERE u.id = rls_current_user_id()
           AND u.org_role IN ('owner', 'admin')
           AND u.status = 'active'
        UNION ALL
        -- Direct membership.
        SELECT wm.workspace_id
          FROM workspace_members wm
         WHERE wm.user_id = rls_current_user_id()
        UNION ALL
        -- Membership through a group.
        SELECT wm.workspace_id
          FROM workspace_members wm
          JOIN group_members gm ON gm.group_id = wm.group_id
         WHERE gm.user_id = rls_current_user_id()
    ) s
    WHERE id IS NOT NULL
$$;

COMMENT ON FUNCTION rls_workspace_ids() IS
    'Workspaces the current context can see, as one array. Zero-argument so the '
    'planner evaluates it once per query; equivalent to rls_can_access_workspace '
    'per workspace (migration 0058).';

-- The eleven policies whose predicate was exactly
-- `rls_can_access_workspace(workspace_id)`. Every one is FOR ALL, to PUBLIC,
-- with no WITH CHECK, so each is replaced in kind - the only change is how the
-- same question is asked.
--
-- `rls_can_access_workspace` itself stays: other policies take a workspace id
-- that is not a plain column of the row being filtered, and for those the
-- argument really does vary.
DROP POLICY ot_isolation ON object_types;
CREATE POLICY ot_isolation ON object_types
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY action_types_isolation ON action_types;
CREATE POLICY action_types_isolation ON action_types
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY code_blob_isolation ON code_blobs;
CREATE POLICY code_blob_isolation ON code_blobs
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY lt_isolation ON link_types;
CREATE POLICY lt_isolation ON link_types
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY object_search_isolation ON object_searches;
CREATE POLICY object_search_isolation ON object_searches
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY object_type_group_members_isolation ON object_type_group_members;
CREATE POLICY object_type_group_members_isolation ON object_type_group_members
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY object_type_groups_isolation ON object_type_groups;
CREATE POLICY object_type_groups_isolation ON object_type_groups
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY object_type_views_isolation ON object_type_views;
CREATE POLICY object_type_views_isolation ON object_type_views
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY shared_properties_isolation ON shared_properties;
CREATE POLICY shared_properties_isolation ON shared_properties
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY value_types_isolation ON value_types;
CREATE POLICY value_types_isolation ON value_types
    USING (workspace_id = ANY (rls_workspace_ids()));

DROP POLICY wm_isolation ON workspace_members;
CREATE POLICY wm_isolation ON workspace_members
    USING (workspace_id = ANY (rls_workspace_ids()));
