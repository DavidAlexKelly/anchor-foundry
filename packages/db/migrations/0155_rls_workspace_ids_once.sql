-- §804: `rls_workspace_ids()` once per statement, not once per row.
--
-- Roadmap phase 3, E.4 measured it: listing the first page of a 10,000-object
-- type took a second, and counting it half a second, with every query under a
-- millisecond's work. The rest was the row-level policies. `oi_isolation`
-- checks each object's type with a correlated `EXISTS` whose condition calls
-- `rls_workspace_ids()` - a SECURITY DEFINER function, so the planner cannot
-- inline it - and while a table's statistics are fresh from a sync the planner
-- runs that check row by row: 10,000 rows, 20,000 calls, ~470 ms. Once
-- autovacuum has analysed the table it picks a hashed subplan and the cost
-- vanishes, which is why it looked fine in `psql` an hour later.
--
-- `(SELECT rls_workspace_ids())` is an InitPlan: evaluated once per statement
-- whatever the planner thinks of the table. The function is STABLE, so it
-- returns one answer within a statement already - this changes when it is
-- computed, never what it says. The `::uuid[]` keeps `= ANY (...)` reading it
-- as an array rather than as a subquery's rows.
--
-- Every policy that calls it is rewritten, from `pg_policies`, rather than
-- listed by hand: twenty-five of them, and a hand list is the one that goes
-- stale. `apps/api/tests/test_rls_policies.py` refuses a policy written the
-- old way in a later migration.
--
-- `rls_can_access_project(project_id)` (42 policies) is not touched. It takes
-- the row's own project, so there is nothing to hoist without replacing it
-- with `rls_project_ids()` - which decides access by a different route, and is
-- a change to who can see what rather than to when it is computed.

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT schemaname, tablename, policyname, qual, with_check
          FROM pg_policies
         WHERE qual LIKE '%rls_workspace_ids()%' OR with_check LIKE '%rls_workspace_ids()%'
    LOOP
        IF r.qual LIKE '%rls_workspace_ids()%' THEN
            EXECUTE format('ALTER POLICY %I ON %I.%I USING (%s)',
                           r.policyname, r.schemaname, r.tablename,
                           replace(r.qual, 'rls_workspace_ids()',
                                   '(SELECT rls_workspace_ids())::uuid[]'));
        END IF;
        IF r.with_check LIKE '%rls_workspace_ids()%' THEN
            EXECUTE format('ALTER POLICY %I ON %I.%I WITH CHECK (%s)',
                           r.policyname, r.schemaname, r.tablename,
                           replace(r.with_check, 'rls_workspace_ids()',
                                   '(SELECT rls_workspace_ids())::uuid[]'));
        END IF;
    END LOOP;
END
$$;
