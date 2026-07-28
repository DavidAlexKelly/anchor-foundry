-- ============================================================================
-- 0018_sync_schema_drift.sql
-- Schema drift detection on connection syncs (roadmap Connections item 6).
--
-- The problem: a source adds, drops, or retypes a column and nothing says so.
-- The sync succeeds, the dataset quietly gains or loses a column, and whatever
-- depends on it downstream (a model's SQL, an object-type mapping, a canvas
-- widget) breaks later, somewhere else, with an error that points nowhere near
-- the cause.
--
-- What is compared, and why it isn't the connection's setup-time schema:
-- the roadmap's phrasing was "compare against what was recorded at
-- connection-setup time", but nothing records a schema at setup time today,
-- and adding that would mean (a) a discovery round trip on every sync - which
-- for the object-storage connector means listing and downloading files just to
-- read their headers - and (b) comparing against a baseline that goes stale
-- the moment anyone edits the connection. Comparing each new dataset version's
-- schema against the previous version's is free (both schemas are already
-- computed on the way through), connector-agnostic, and describes what
-- actually landed rather than what a stale baseline said should land. The
-- trade-off, recorded here so it isn't rediscovered: this detects drift one
-- sync *after* it happens rather than warning before the write, it cannot see
-- a change in a source column nobody syncs, and - because the wire format
-- between source and DuckDB is CSV, whose types are re-inferred - it reports
-- the type the data *landed* as, not the type the source declares. A column
-- retyped in the source but whose values still read the same way (bigint ->
-- text on digits, or any retype of an all-NULL column) is invisible here. That
-- is the right trade for the purpose: what breaks a downstream consumer is the
-- shape of the dataset, which is exactly what this compares.
--
-- NULL means "nothing to report" - covers both the first version of a dataset
-- (no baseline to compare against) and a sync whose schema was unchanged, so
-- `WHERE schema_changes IS NOT NULL` is exactly "runs that drifted". Storing
-- an empty object for the common case would make every healthy run carry a
-- payload for no reason.
--
-- Shape: {"added": [{"name","data_type"}], "removed": [...],
--         "retyped": [{"name","from","to"}]}
-- Only non-empty keys are present.
-- ============================================================================

ALTER TABLE sync_runs ADD COLUMN schema_changes jsonb;

COMMENT ON COLUMN sync_runs.schema_changes IS
    'Schema diff vs the previous dataset version, or NULL when unchanged or '
    'first version. Written by both the API''s inline sync and the worker''s '
    'scheduled job.';

-- Partial index: the interesting query is "show me the runs that drifted",
-- and drifted runs are the rare case.
CREATE INDEX idx_sync_runs_drift ON sync_runs (connection_id, started_at DESC)
    WHERE schema_changes IS NOT NULL;
