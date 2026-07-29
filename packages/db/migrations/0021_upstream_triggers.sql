-- ============================================================================
-- 0021_upstream_triggers.sql
-- Make trigger_mode = 'upstream' actually fire.
--
-- 'upstream' has been a legal model_trigger enum value since 0003, the API's
-- PATCH route has accepted it since models.py was written, and the shared
-- TypeScript contract lists it - but nothing has ever polled for it. A model
-- set to 'upstream' silently never ran. This migration closes that gap:
-- when a new version of any of a model's input datasets appears, the model
-- becomes due, and the worker enqueues a run.
--
-- Watermark, not a queue: a `models.upstream_watermark` timestamp records
-- "the newest input version this model has already reacted to". A model is
-- due when any input dataset has a version created after it. Compared with
-- the alternatives:
--   * a trigger on dataset_versions INSERT that enqueues model_runs directly
--     would be exact, but puts scheduling policy in a database trigger where
--     it cannot be reasoned about, retried, or rate-limited, and would fire
--     inside whatever transaction produced the version (an upload's failed
--     commit would still have enqueued runs).
--   * an event/outbox table would be the "right" answer at scale, but it is
--     a second thing to poll, drain, and garbage-collect for no behavioural
--     gain at this size.
-- The watermark mirrors next_run_at's shape exactly (a timestamp column the
-- worker polls, advanced by the worker after it acts), so 'upstream' and
-- 'cron' are the same machine with a different due-ness predicate.
--
-- Self-loop guard: versions the model itself produced
-- (produced_by_kind = 'model' AND produced_by_id = the model) are excluded.
-- A model whose output dataset is also one of its inputs is legal today and
-- would otherwise re-trigger itself forever, one run per poll, with no way
-- for a user to stop it short of editing the model.
--
-- Flagged for review - the mutual-dependency case is NOT solved here: models
-- A -> B -> A (each an input to the other) will oscillate, one run each per
-- poll pass, because each run legitimately produces a new version the other
-- is watching. Detecting that needs the whole dependency graph, not one
-- model's inputs, and belongs with the lineage/DAG view where the graph is
-- actually materialised. Documented rather than half-solved.
--
-- Coalescing: a model with a run already 'queued' or 'running' is not
-- re-enqueued. Ten versions landing between two poll passes produce one run,
-- not ten, and a slow model cannot accumulate a backlog it will never drain.
-- The watermark only advances when a run is actually enqueued, so a version
-- that arrives while a run is in flight still triggers the next one.
-- ============================================================================

-- NULL means "never reacted to anything yet". Deliberately treated as
-- '-infinity' rather than "due immediately": a model switched to 'upstream'
-- fires as soon as it sees any input version, including ones that predate
-- the switch. That matches the cron convention in 0014 (a NULL next_run_at
-- is due now) - a newly-configured trigger fires once promptly and settles
-- into reacting to genuinely new data thereafter.
ALTER TABLE models ADD COLUMN upstream_watermark timestamptz;

COMMENT ON COLUMN models.upstream_watermark IS
    'Newest input dataset_versions.created_at this upstream-triggered model '
    'has already reacted to. Advanced by the worker when it enqueues a run.';

-- Feeds list_due_upstream_models: the predicate is "an input version newer
-- than the watermark", which reads dataset_versions by dataset_id ordered by
-- created_at.
CREATE INDEX idx_dataset_versions_dataset_created
    ON dataset_versions (dataset_id, created_at DESC);

-- ---- worker discovery (SECURITY DEFINER; the bypass is read-only
--      enumeration across every workspace, exactly as 0014 does for cron -
--      the worker re-verifies each model through a workspace-scoped
--      connection before inserting anything) ----------------------------------
CREATE FUNCTION list_due_upstream_models() RETURNS TABLE(model_id uuid, workspace_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT m.id, p.workspace_id
      FROM models m
      JOIN projects p ON p.id = m.project_id
     WHERE m.trigger_mode = 'upstream'
       AND NOT EXISTS (
           SELECT 1 FROM model_runs mr
            WHERE mr.model_id = m.id AND mr.status IN ('queued', 'running')
       )
       AND EXISTS (
           SELECT 1
             FROM model_inputs mi
             JOIN dataset_versions dv ON dv.dataset_id = mi.dataset_id
            WHERE mi.model_id = m.id
              AND dv.created_at > COALESCE(m.upstream_watermark, '-infinity'::timestamptz)
              -- IS DISTINCT FROM, not =: produced_by_kind/id are nullable
              -- (uploads leave them NULL), and a plain NOT (a = b) is NULL
              -- rather than TRUE when either side is NULL, which would
              -- filter out every uploaded version - i.e. silently break the
              -- common case in exactly the way this feature exists to fix.
              AND NOT (dv.produced_by_kind IS NOT DISTINCT FROM 'model'
                       AND dv.produced_by_id IS NOT DISTINCT FROM m.id)
       )
     ORDER BY m.upstream_watermark NULLS FIRST
$$;

REVOKE EXECUTE ON FUNCTION list_due_upstream_models() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION list_due_upstream_models() TO platform_app;
