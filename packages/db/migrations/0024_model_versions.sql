-- ============================================================================
-- 0024_model_versions.sql
-- Give a model's *definition* the same history its output already has.
--
-- The asymmetry this fixes has been in the schema since 0003 and got worse
-- with every step this branch added. `model_runs.output_version` points at
-- the exact dataset version each run produced, so run history is auditable
-- against data - but nothing records the *code* that produced it. Editing a
-- model overwrites its source in place. So "which query produced this
-- number?" has been unanswerable for any run older than the last edit, and
-- since 0021 a bad edit propagates to every downstream dataset on the next
-- worker pass without anybody approving it.
--
-- Same shape as dataset versioning, deliberately: an append-only table of
-- numbered snapshots, with the live row (`models.code`) holding the current
-- one. Nothing about the current-state read path changes.
--
-- **Rollback appends, it does not rewind.** Restoring version 2 writes a new
-- version 5 whose content equals version 2's, rather than moving a pointer
-- back. History is then a true record of what the model was at every point,
-- including the fact that somebody reverted - and a run stamped with version
-- 5 still resolves to exactly one piece of code. Rewinding would make
-- `model_runs.model_version` ambiguous the moment anyone rolled back twice.
--
-- **A version snapshots the code *and* the inputs.** Aliases are half the
-- contract: restoring code that says `FROM orders` into a model whose inputs
-- were renamed would restore something that cannot run. The inputs are
-- copied into jsonb rather than referenced through model_inputs, because a
-- history record must not change when the live input set does - the same
-- reason 0022 stores what the gate saw on the run.
--
-- **What is deliberately *not* a definition change:** trigger_mode,
-- cron_schedule, input_health_policy, name, description. Those are how and
-- when a model runs, not what it computes, and versioning them would fill
-- the history with entries nobody wants to roll back to. `language` is
-- immutable after creation, so it needs no version of its own.
-- ============================================================================

CREATE TABLE model_versions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id       uuid NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    version_number integer NOT NULL CHECK (version_number > 0),
    code           text NOT NULL,
    -- [{"dataset_id": ..., "input_alias": ...}] as it stood when saved.
    inputs         jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- Set when this version was created by restoring an earlier one, so the
    -- history can say "reverted to v2" rather than showing an unexplained
    -- reappearance of old code.
    restored_from  integer,
    created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_id, version_number)
);

CREATE INDEX idx_model_versions_model ON model_versions (model_id, version_number DESC);

-- RLS is byte-for-byte the shape 0006 gives model_inputs and model_runs:
-- reachable through the model, resolved by the rls_can_access_project
-- SECURITY DEFINER helper rather than a subselect that could recurse (the
-- class of bug 0008/0009 fixed).
ALTER TABLE model_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY mv_isolation ON model_versions
    USING (EXISTS (SELECT 1 FROM models m
                   WHERE m.id = model_id
                     AND rls_can_access_project(m.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON model_versions TO platform_app;

-- Which definition a run actually executed. NULL for every run that happened
-- before this migration - those genuinely have no answer, and inventing one
-- by pointing them at the backfilled v1 would claim knowledge the platform
-- does not have.
ALTER TABLE model_runs ADD COLUMN model_version uuid
    REFERENCES model_versions(id) ON DELETE SET NULL;

COMMENT ON COLUMN model_runs.model_version IS
    'The model definition this run executed. NULL for runs that predate '
    'migration 0024 - unknown, not v1.';

-- Backfill: every existing model gets a version 1 from its current state, so
-- "every model has at least one version" holds from here on and the API
-- never has to special-case a model with an empty history.
INSERT INTO model_versions (model_id, version_number, code, inputs, created_by, created_at)
SELECT m.id, 1, m.code,
       COALESCE(
           (SELECT jsonb_agg(jsonb_build_object(
                       'dataset_id', mi.dataset_id, 'input_alias', mi.input_alias)
                   ORDER BY mi.input_alias)
              FROM model_inputs mi WHERE mi.model_id = m.id),
           '[]'::jsonb),
       m.created_by, m.created_at
  FROM models m;
