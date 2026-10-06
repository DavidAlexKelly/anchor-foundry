-- §829: the caller's organisation once per statement, in `users` and `groups`.
--
-- `rls_user_org_id()` is SECURITY DEFINER, so the planner cannot inline it,
-- and `users_same_org` and `groups_same_org` called it bare - once per row,
-- as 0155 found `rls_workspace_ids()` being called. `users` holds every
-- tenant's people (68,974 on a copy of the development database), so any
-- listing of them paid that call on every one: the pipeline's *View as*
-- picker took 180 ms to return four people. As an InitPlan it is computed
-- once, and the same listing scans in 15 ms - or, filtered by organisation
-- as the listings now are (§829), reads the four by index in 7 ms.
--
-- The answer is unchanged: within one statement a STABLE function returns
-- the same value whether it is asked once or 68,974 times.

ALTER POLICY users_same_org ON users
    USING ((current_setting('app.service', true) = 'worker')
           OR (organisation_id = (SELECT rls_user_org_id())));

ALTER POLICY groups_same_org ON groups
    USING ((current_setting('app.service', true) = 'worker')
           OR (organisation_id = (SELECT rls_user_org_id())));
