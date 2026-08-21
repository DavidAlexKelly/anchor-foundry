-- 0058, continued: the policies that reach the workspace through a parent row.
--
-- 0058 replaced the eleven policies whose predicate was exactly
-- `rls_can_access_workspace(workspace_id)`. That took the ontology search from
-- 4.5s to 1.9s and stopped there, because the biggest remaining piece was a
-- *different* shape of the same mistake:
--
--     SELECT ot.id, (SELECT array_agg(...) FROM object_type_properties p
--                     WHERE p.object_type_id = ot.id AND p.visibility = 'hidden')
--       FROM object_types ot WHERE ot.workspace_id = $1;     -- 815ms
--
-- `object_type_properties` has no `workspace_id` of its own, so its policy asks
-- the question through its parent:
--
--     EXISTS (SELECT 1 FROM object_types ot
--              WHERE ot.id = object_type_properties.object_type_id
--                AND rls_can_access_workspace(ot.workspace_id))
--
-- Same per-row function call, one join further out - and it fires once per
-- *property*, not once per type. Measured on its own: 815ms of the 912ms that
-- `list_types` still cost after 0058. The eight policies below are that shape,
-- and the substitution is the same one: the caller's accessible set, asked for
-- once, tested per row.
--
-- **Three policies are deliberately left alone.** `canvas_apps`, `connections`
-- and `resources` each combine a workspace predicate with a *project* one
-- inside a single CASE or OR. `rls_can_access_project` needs the identical
-- treatment and does not have it yet (26 policies, several shapes) - and
-- converting half of a mixed expression would leave the row cost unchanged
-- while making the remaining half harder to find. They go with the project
-- half, as one piece.
--
-- Equivalence is unchanged and untouched: these rewrite *where the question is
-- asked from*, not what it asks. `tests/test_rls_workspace_ids.py` compares the
-- two predicates directly, and it is the same predicate here.

-- The four action tables, which reach the workspace through `action_types`.
DROP POLICY action_criteria_isolation ON action_criteria;
CREATE POLICY action_criteria_isolation ON action_criteria
    USING (EXISTS (SELECT 1 FROM action_types at
                    WHERE at.id = action_criteria.action_type_id
                      AND at.workspace_id = ANY (rls_workspace_ids())));

DROP POLICY action_parameters_isolation ON action_parameters;
CREATE POLICY action_parameters_isolation ON action_parameters
    USING (EXISTS (SELECT 1 FROM action_types at
                    WHERE at.id = action_parameters.action_type_id
                      AND at.workspace_id = ANY (rls_workspace_ids())));

DROP POLICY action_rules_isolation ON action_rules;
CREATE POLICY action_rules_isolation ON action_rules
    USING (EXISTS (SELECT 1 FROM action_types at
                    WHERE at.id = action_rules.action_type_id
                      AND at.workspace_id = ANY (rls_workspace_ids())));

DROP POLICY action_runs_isolation ON action_runs;
CREATE POLICY action_runs_isolation ON action_runs
    USING (EXISTS (SELECT 1 FROM action_types at
                    WHERE at.id = action_runs.action_type_id
                      AND at.workspace_id = ANY (rls_workspace_ids())));

-- The three that reach it through `object_types`. `object_type_properties` is
-- the one the measurement above is about; the other two are the same shape and
-- are converted with it rather than left to be found again later.
DROP POLICY oi_isolation ON object_instances;
CREATE POLICY oi_isolation ON object_instances
    USING (EXISTS (SELECT 1 FROM object_types ot
                    WHERE ot.id = object_instances.object_type_id
                      AND ot.workspace_id = ANY (rls_workspace_ids())));

DROP POLICY otp_isolation ON object_type_properties;
CREATE POLICY otp_isolation ON object_type_properties
    USING (EXISTS (SELECT 1 FROM object_types ot
                    WHERE ot.id = object_type_properties.object_type_id
                      AND ot.workspace_id = ANY (rls_workspace_ids())));

DROP POLICY otv_isolation ON object_type_versions;
CREATE POLICY otv_isolation ON object_type_versions
    USING (EXISTS (SELECT 1 FROM object_types ot
                    WHERE ot.id = object_type_versions.object_type_id
                      AND ot.workspace_id = ANY (rls_workspace_ids())));

-- And the workspace table itself, where the id *is* the workspace id.
DROP POLICY ws_isolation ON workspaces;
CREATE POLICY ws_isolation ON workspaces
    USING (id = ANY (rls_workspace_ids()));
