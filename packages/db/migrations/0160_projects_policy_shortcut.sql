-- §825: the projects policy answers the common case without resolving a role.
--
-- `proj_isolation` asked `rls_can_access_project(id)` of every row, and that is
-- `effective_project_role` - a plpgsql role resolution of several lookups - per
-- project. Counting the development workspace's 10,078 projects took 210 ms
-- for its owner and 659 ms for an editor, and every read of `projects` paid it,
-- including the one that finds a single project by slug.
--
-- **A shortcut in front of it, not a replacement.** An `inherited` project in a
-- workspace the caller can reach is one `rls_can_access_project` grants: the
-- role then follows the workspace role, which `rls_workspace_ids()` says exists
-- (`tests/test_rls_workspace_ids.py`), and an org owner's or admin's
-- workspaces are in that set too. So the new disjunct only ever admits rows
-- the old predicate admits, and every other row - a `custom` project, with its
-- direct and group grants and revocations - still goes to the full rule. Who
-- can see what does not change; `tests/test_rls_project_ids.py` reads both
-- through the policy now, per access route.
--
-- Why not 0060's whole-set rewrite, which 0061 reverted and §824 re-measured
-- and rejected: an org owner's project set is every project in the
-- organisation, built once per statement, and that cost more than it saved on
-- small reads. This shortcut needs only the workspace set, which is a handful
-- of ids, computed once per statement (0155's form).
--
-- Measured on a copy of the development database: counting the workspace's
-- projects 210 -> 13 ms (owner) and 659 -> 7 ms (editor).

DROP POLICY proj_isolation ON projects;
CREATE POLICY proj_isolation ON projects
    USING (rls_worker_for_workspace(workspace_id)
           OR (permission_mode = 'inherited'
               AND workspace_id = ANY ((SELECT rls_workspace_ids())::uuid[]))
           OR rls_can_access_project(id));
