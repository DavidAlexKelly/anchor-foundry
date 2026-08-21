-- The project half of 0058/0059.
--
-- 0058 and 0059 took the ontology search from 4.5s to 0.37s by replacing a
-- per-row call to `rls_can_access_workspace` with a per-query set. Three
-- policies were left whole there because they mix a workspace predicate with a
-- *project* one, and `rls_can_access_project` had the identical problem across
-- twenty-five policies. This is that half, and it closes the three.
--
-- **The rule is longer, so the set is longer.** `effective_project_role` has
-- five outcomes and two of them are revocations (`docs`: spec §9). Reading it
-- as a set, a caller reaches a project when:
--
--   1. it is the worker's own workspace - every project in it, whatever the
--      permission mode says, because there is no user for a role to resolve
--      against;
--   2. they are an active org owner or admin of the project's organisation;
--   3. the project is in `inherited` mode and they can see its workspace;
--   4. it is in `custom` mode and they have a **direct** entry that is not
--      `none`;
--   5. it is in `custom` mode, they have *no* direct entry, and some group
--      entry grants a real role.
--
-- 4 and 5 are the subtle pair and the order between them is the rule: a direct
-- entry always wins, **including a revocation**, because "explicit, per-user
-- assignments are more specific than group grants". Hence the `NOT EXISTS` in
-- 5 rather than a plain union - without it a user revoked by name would be let
-- back in by a group.
--
-- **`rls_workspace_ids()` is the gate on 3, 4 and 5**, standing in for
-- `effective_workspace_role(...) IS NOT NULL`, and it is equivalent rather
-- than merely close: the two workspaces it adds beyond plain membership are
-- the worker's and an org admin's, and branches 1 and 2 have already granted
-- every project in both.
--
-- `tests/test_rls_project_ids.py` checks all of that against real rows, per
-- route - and **builds** the two cases the corpus cannot supply. The shared
-- dev database holds 267 direct `none` entries and exactly one group entry, so
-- "a direct none beats a group grant" and "every group entry is none" have
-- nothing to be sampled from; a suite without those would report full
-- agreement on the two rules most likely to be wrong.

CREATE FUNCTION rls_project_ids() RETURNS uuid[]
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COALESCE(array_agg(DISTINCT id), '{}'::uuid[])
    FROM (
        SELECT p.id
          FROM projects p
         WHERE current_setting('app.service', true) = 'worker'
           AND p.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
        UNION ALL
        SELECT p.id
          FROM projects p
          JOIN workspaces w ON w.id = p.workspace_id
          JOIN users u ON u.organisation_id = w.organisation_id
         WHERE u.id = rls_current_user_id()
           AND u.org_role IN ('owner', 'admin')
           AND u.status = 'active'
        UNION ALL
        SELECT p.id
          FROM projects p
         WHERE p.permission_mode = 'inherited'
           AND p.workspace_id = ANY (rls_workspace_ids())
        UNION ALL
        SELECT p.id
          FROM projects p
          JOIN project_members pm
            ON pm.project_id = p.id AND pm.user_id = rls_current_user_id()
         WHERE p.permission_mode = 'custom'
           AND pm.role <> 'none'
           AND p.workspace_id = ANY (rls_workspace_ids())
        UNION ALL
        SELECT p.id
          FROM projects p
         WHERE p.permission_mode = 'custom'
           AND p.workspace_id = ANY (rls_workspace_ids())
           AND NOT EXISTS (SELECT 1 FROM project_members pm
                            WHERE pm.project_id = p.id
                              AND pm.user_id = rls_current_user_id())
           AND EXISTS (SELECT 1 FROM project_members pm
                         JOIN group_members gm ON gm.group_id = pm.group_id
                        WHERE pm.project_id = p.id
                          AND gm.user_id = rls_current_user_id()
                          AND pm.role <> 'none')
    ) s
    WHERE id IS NOT NULL
$$;

DROP POLICY apps_isolation ON canvas_app_shares;
CREATE POLICY apps_isolation ON canvas_app_shares
    USING (rls_app_project_id(canvas_app_id) = ANY (rls_project_ids()));

DROP POLICY appv_isolation ON canvas_app_versions;
CREATE POLICY appv_isolation ON canvas_app_versions
    USING (EXISTS (SELECT 1 FROM canvas_apps a
             WHERE a.id = canvas_app_versions.canvas_app_id
               AND a.project_id = ANY (rls_project_ids())));

DROP POLICY code_branch_isolation ON code_branches;
CREATE POLICY code_branch_isolation ON code_branches
    USING (EXISTS (SELECT 1 FROM code_repos r
             WHERE r.id = code_branches.repo_id
               AND r.project_id = ANY (rls_project_ids())));

DROP POLICY ccs_isolation ON code_change_sets;
CREATE POLICY ccs_isolation ON code_change_sets
    USING (project_id = ANY (rls_project_ids()));

DROP POLICY code_commit_isolation ON code_commits;
CREATE POLICY code_commit_isolation ON code_commits
    USING (EXISTS (SELECT 1 FROM code_repos r
             WHERE r.id = code_commits.repo_id
               AND r.project_id = ANY (rls_project_ids())));

DROP POLICY cpck_isolation ON code_proposal_checks;
CREATE POLICY cpck_isolation ON code_proposal_checks
    USING (EXISTS (SELECT 1 FROM code_proposals p
             WHERE p.id = code_proposal_checks.proposal_id
               AND p.project_id = ANY (rls_project_ids())));

DROP POLICY cpc_isolation ON code_proposal_comments;
CREATE POLICY cpc_isolation ON code_proposal_comments
    USING (EXISTS (SELECT 1 FROM code_proposals p
             WHERE p.id = code_proposal_comments.proposal_id
               AND p.project_id = ANY (rls_project_ids())));

DROP POLICY cpfm_isolation ON code_proposal_file_marks;
CREATE POLICY cpfm_isolation ON code_proposal_file_marks
    USING (EXISTS (SELECT 1 FROM code_proposals p
             WHERE p.id = code_proposal_file_marks.proposal_id
               AND p.project_id = ANY (rls_project_ids())));

DROP POLICY cpf_isolation ON code_proposal_files;
CREATE POLICY cpf_isolation ON code_proposal_files
    USING (EXISTS (SELECT 1 FROM code_proposals p
             WHERE p.id = code_proposal_files.proposal_id
               AND p.project_id = ANY (rls_project_ids())));

DROP POLICY cpr_isolation ON code_proposal_reviews;
CREATE POLICY cpr_isolation ON code_proposal_reviews
    USING (EXISTS (SELECT 1 FROM code_proposals p
             WHERE p.id = code_proposal_reviews.proposal_id
               AND p.project_id = ANY (rls_project_ids())));

DROP POLICY cp_isolation ON code_proposals;
CREATE POLICY cp_isolation ON code_proposals
    USING (project_id = ANY (rls_project_ids()));

DROP POLICY repo_isolation ON code_repos;
CREATE POLICY repo_isolation ON code_repos
    USING (project_id = ANY (rls_project_ids()));

DROP POLICY dsx_isolation ON dataset_expectations;
CREATE POLICY dsx_isolation ON dataset_expectations
    USING (EXISTS (SELECT 1 FROM datasets d
             WHERE d.id = dataset_expectations.dataset_id
               AND d.project_id = ANY (rls_project_ids())));

DROP POLICY dsv_isolation ON dataset_versions;
CREATE POLICY dsv_isolation ON dataset_versions
    USING (EXISTS (SELECT 1 FROM datasets d
             WHERE d.id = dataset_versions.dataset_id
               AND d.project_id = ANY (rls_project_ids())));

DROP POLICY ds_isolation ON datasets;
CREATE POLICY ds_isolation ON datasets
    USING (project_id = ANY (rls_project_ids()));

DROP POLICY mi_isolation ON model_inputs;
CREATE POLICY mi_isolation ON model_inputs
    USING (EXISTS (SELECT 1 FROM models m
             WHERE m.id = model_inputs.model_id
               AND m.project_id = ANY (rls_project_ids())));

DROP POLICY mr_isolation ON model_runs;
CREATE POLICY mr_isolation ON model_runs
    USING (EXISTS (SELECT 1 FROM models m
             WHERE m.id = model_runs.model_id
               AND m.project_id = ANY (rls_project_ids())));

DROP POLICY mv_isolation ON model_versions;
CREATE POLICY mv_isolation ON model_versions
    USING (EXISTS (SELECT 1 FROM models m
             WHERE m.id = model_versions.model_id
               AND m.project_id = ANY (rls_project_ids())));

DROP POLICY model_isolation ON models;
CREATE POLICY model_isolation ON models
    USING (project_id = ANY (rls_project_ids()));

DROP POLICY ots_isolation ON object_type_sources;
CREATE POLICY ots_isolation ON object_type_sources
    USING (EXISTS (SELECT 1 FROM datasets d
             WHERE d.id = object_type_sources.dataset_id
               AND d.project_id = ANY (rls_project_ids())));

DROP POLICY pm_isolation ON project_members;
CREATE POLICY pm_isolation ON project_members
    USING (project_id = ANY (rls_project_ids()));

DROP POLICY proj_isolation ON projects;
-- The original read `rls_worker_for_workspace(workspace_id) OR
-- rls_can_access_project(id)`. The worker half is redundant here: branch 1 of
-- `rls_project_ids()` already contains every project in the worker's own
-- workspace, so the set answers both halves on its own.
CREATE POLICY proj_isolation ON projects
    USING (id = ANY (rls_project_ids()));

-- The three that mix the two scopes, left whole by 0059 and closed here now
-- that both sets exist. Each keeps its own shape exactly; only the two
-- predicates inside it change.
DROP POLICY app_isolation ON canvas_apps;
CREATE POLICY app_isolation ON canvas_apps
    USING (project_id = ANY (rls_project_ids())
           OR (publish_scope = 'workspace'::app_publish_scope
               AND rls_project_workspace_id(project_id) = ANY (rls_workspace_ids()))
           OR (publish_scope = 'groups'::app_publish_scope
               AND rls_app_shared_with_user(id)));

DROP POLICY conn_isolation ON connections;
CREATE POLICY conn_isolation ON connections
    USING (CASE scope
               WHEN 'workspace'::connection_scope
                   THEN workspace_id = ANY (rls_workspace_ids())
               ELSE project_id = ANY (rls_project_ids())
           END);

DROP POLICY resource_isolation ON resources;
CREATE POLICY resource_isolation ON resources
    USING (CASE
               WHEN project_id IS NULL THEN workspace_id = ANY (rls_workspace_ids())
               ELSE project_id = ANY (rls_project_ids())
           END);
