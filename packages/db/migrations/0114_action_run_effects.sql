-- ============================================================================
-- 0114_action_run_effects.sql
-- Undoing an action that created, deleted or changed other objects (§551;
-- `action-types` p.154-156).
--
--     "Reverting a delete action is supported …" (p.156, which then needs a
--      section on what to do when the revert toast has gone)
--
-- 0076 recorded a run's subject - its properties before and after - and, for
-- a run that also created, deleted or changed other objects, a sentence in
-- `revert_unsupported` saying the undo would leave them behind. That sentence
-- was the honest answer while nothing recorded those objects. This records
-- them, so the undo can put each back:
--
--   [{"kind": "create", "object_type_id", "source_id", "primary_key",
--     "properties"}                  -- delete it again
--    {"kind": "remove", ..., "properties", "subject"}  -- write it back
--    {"kind": "modify", ..., "instance_id", "before", "after"}]  -- restore it
--
-- **Only the apply path can know this**, for 0076's reason: once the version
-- is committed its rows look like every other row. A run recorded before this
-- column keeps its sentence and stays refused, which is still true of it.
-- ============================================================================

ALTER TABLE action_runs
    ADD COLUMN revert_effects jsonb
        CHECK (revert_effects IS NULL OR jsonb_typeof(revert_effects) = 'array');
