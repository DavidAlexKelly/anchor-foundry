-- Revert 0060's policy changes. The function stays; the policies go back.
--
-- **0060 was correct and unshippable, and the second half of that sentence is
-- the point.** `rls_project_ids()` is equivalent to `rls_can_access_project`
-- - `tests/test_rls_project_ids.py` proves it over real rows and over four
-- constructed cases the corpus cannot supply, and thirteen mutants die on it.
-- It is also 5x slower on the endpoint that matters most.
--
-- **What 0058/0059 got right and 0060 got wrong is a cost model, not a rule.**
-- The set idiom replaces a per-*row* cost with a per-*statement* one. That is
-- a win exactly when the statement is paid once. It is a loss when something
-- upstream already loops.
--
-- `v_user_projects` is that something. It resolves `effective_project_role`
-- **per project**, and `GET /workspaces/{id}/projects` joins it - so on a
-- workspace holding 881 projects the endpoint runs the role resolution 881
-- times, and each of those now built an 881-element array of its own. Measured
-- on the dev database:
--
--     GET /projects, before 0060 ..... 4.4s
--     GET /projects, with 0060 ...... 22.1s
--
-- and the browser suite went from ~30 minutes to **1h33m**, with nine tests
-- failing on timeouts that have nothing to do with what they check.
--
-- The workspace half does not have this shape and stays: `rls_workspace_ids()`
-- returns a handful of ids, and nothing in the application loops per
-- workspace. The difference is not the idiom, it is what the idiom is
-- multiplied by.
--
-- **`rls_project_ids()` is kept, unused, with its tests.** It is the correct
-- answer to a question this schema cannot afford to ask yet, and deleting it
-- would mean re-deriving and re-proving it after `v_user_projects` is fixed -
-- which is the actual prerequisite, and is its own unit. The 4.4s baseline is
-- not acceptable either; it was simply not made worse.

DROP POLICY apps_isolation ON canvas_app_shares;
CREATE POLICY apps_isolation ON canvas_app_shares
    USING (rls_can_access_project(rls_app_project_id(canvas_app_id)));

DROP POLICY appv_isolation ON canvas_app_versions;
CREATE POLICY appv_isolation ON canvas_app_versions
    USING (EXISTS (SELECT 1 FROM canvas_apps a WHERE a.id = canvas_app_versions.canvas_app_id AND rls_can_access_project(a.project_id)));

DROP POLICY app_isolation ON canvas_apps;
CREATE POLICY app_isolation ON canvas_apps
    USING (rls_can_access_project(project_id) OR (publish_scope = 'workspace'::app_publish_scope AND rls_can_access_workspace(rls_project_workspace_id(project_id))) OR (publish_scope = 'groups'::app_publish_scope AND rls_app_shared_with_user(id)));

DROP POLICY code_branch_isolation ON code_branches;
CREATE POLICY code_branch_isolation ON code_branches
    USING (EXISTS (SELECT 1 FROM code_repos r WHERE r.id = code_branches.repo_id AND rls_can_access_project(r.project_id)));

DROP POLICY ccs_isolation ON code_change_sets;
CREATE POLICY ccs_isolation ON code_change_sets
    USING (rls_can_access_project(project_id));

DROP POLICY code_commit_isolation ON code_commits;
CREATE POLICY code_commit_isolation ON code_commits
    USING (EXISTS (SELECT 1 FROM code_repos r WHERE r.id = code_commits.repo_id AND rls_can_access_project(r.project_id)));

DROP POLICY cpck_isolation ON code_proposal_checks;
CREATE POLICY cpck_isolation ON code_proposal_checks
    USING (EXISTS (SELECT 1 FROM code_proposals p WHERE p.id = code_proposal_checks.proposal_id AND rls_can_access_project(p.project_id)));

DROP POLICY cpc_isolation ON code_proposal_comments;
CREATE POLICY cpc_isolation ON code_proposal_comments
    USING (EXISTS (SELECT 1 FROM code_proposals p WHERE p.id = code_proposal_comments.proposal_id AND rls_can_access_project(p.project_id)));

DROP POLICY cpfm_isolation ON code_proposal_file_marks;
CREATE POLICY cpfm_isolation ON code_proposal_file_marks
    USING (EXISTS (SELECT 1 FROM code_proposals p WHERE p.id = code_proposal_file_marks.proposal_id AND rls_can_access_project(p.project_id)));

DROP POLICY cpf_isolation ON code_proposal_files;
CREATE POLICY cpf_isolation ON code_proposal_files
    USING (EXISTS (SELECT 1 FROM code_proposals p WHERE p.id = code_proposal_files.proposal_id AND rls_can_access_project(p.project_id)));

DROP POLICY cpr_isolation ON code_proposal_reviews;
CREATE POLICY cpr_isolation ON code_proposal_reviews
    USING (EXISTS (SELECT 1 FROM code_proposals p WHERE p.id = code_proposal_reviews.proposal_id AND rls_can_access_project(p.project_id)));

DROP POLICY cp_isolation ON code_proposals;
CREATE POLICY cp_isolation ON code_proposals
    USING (rls_can_access_project(project_id));

DROP POLICY repo_isolation ON code_repos;
CREATE POLICY repo_isolation ON code_repos
    USING (rls_can_access_project(project_id));

DROP POLICY conn_isolation ON connections;
CREATE POLICY conn_isolation ON connections
    USING (CASE scope WHEN 'workspace'::connection_scope THEN rls_can_access_workspace(workspace_id) ELSE rls_can_access_project(project_id) END);

DROP POLICY dsx_isolation ON dataset_expectations;
CREATE POLICY dsx_isolation ON dataset_expectations
    USING (EXISTS (SELECT 1 FROM datasets d WHERE d.id = dataset_expectations.dataset_id AND rls_can_access_project(d.project_id)));

DROP POLICY dsv_isolation ON dataset_versions;
CREATE POLICY dsv_isolation ON dataset_versions
    USING (EXISTS (SELECT 1 FROM datasets d WHERE d.id = dataset_versions.dataset_id AND rls_can_access_project(d.project_id)));

DROP POLICY ds_isolation ON datasets;
CREATE POLICY ds_isolation ON datasets
    USING (rls_can_access_project(project_id));

DROP POLICY mi_isolation ON model_inputs;
CREATE POLICY mi_isolation ON model_inputs
    USING (EXISTS (SELECT 1 FROM models m WHERE m.id = model_inputs.model_id AND rls_can_access_project(m.project_id)));

DROP POLICY mr_isolation ON model_runs;
CREATE POLICY mr_isolation ON model_runs
    USING (EXISTS (SELECT 1 FROM models m WHERE m.id = model_runs.model_id AND rls_can_access_project(m.project_id)));

DROP POLICY mv_isolation ON model_versions;
CREATE POLICY mv_isolation ON model_versions
    USING (EXISTS (SELECT 1 FROM models m WHERE m.id = model_versions.model_id AND rls_can_access_project(m.project_id)));

DROP POLICY model_isolation ON models;
CREATE POLICY model_isolation ON models
    USING (rls_can_access_project(project_id));

DROP POLICY ots_isolation ON object_type_sources;
CREATE POLICY ots_isolation ON object_type_sources
    USING (EXISTS (SELECT 1 FROM datasets d WHERE d.id = object_type_sources.dataset_id AND rls_can_access_project(d.project_id)));

DROP POLICY pm_isolation ON project_members;
CREATE POLICY pm_isolation ON project_members
    USING (rls_can_access_project(project_id));

DROP POLICY proj_isolation ON projects;
CREATE POLICY proj_isolation ON projects
    USING (rls_worker_for_workspace(workspace_id) OR rls_can_access_project(id));

DROP POLICY resource_isolation ON resources;
CREATE POLICY resource_isolation ON resources
    USING (CASE WHEN project_id IS NULL THEN rls_can_access_workspace(workspace_id) ELSE rls_can_access_project(project_id) END);
