-- ============================================================================
-- 0016_scheduled_instance_sync.sql
-- Scheduled (worker-driven) object-type-source sync.
--
-- object_type_source sync (0012) reads the mapped dataset's *current*
-- Parquet snapshot in full and upserts every row by primary key
-- (mark-and-sweep removal of anything no longer present) — this is already
-- the right approach for this domain, not a stopgap: the underlying dataset
-- is itself replaced wholesale on every upload/sync/model run, not an
-- append log, so there is no "rows changed since a cursor" to filter on the
-- way connections.sync_cursor_column can. A true incremental mode doesn't
-- fit here the way it does for connection sync (0014).
--
-- What day-one sync is actually missing is what connection sync was
-- missing before 0014: a way to handle a dataset bigger than the
-- interactive request/response cycle wants to carry
-- (MAX_INSTANCE_SYNC_ROWS = 20,000 in services/instances.py) and a way to
-- run periodically without a human clicking "sync now". Same shape as
-- 0014's connections columns and worker-discovery function; the worker's
-- own row cap is allowed to be far larger since it isn't bounded by one
-- HTTP request/response.
-- ============================================================================

ALTER TABLE object_type_sources
    ADD COLUMN sync_schedule   text,
    ADD COLUMN sync_next_run_at timestamptz;

CREATE FUNCTION list_due_object_source_syncs() RETURNS TABLE(source_id uuid, workspace_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT s.id, ot.workspace_id
      FROM object_type_sources s
      JOIN object_types ot ON ot.id = s.object_type_id
     WHERE s.sync_schedule IS NOT NULL
       AND (s.sync_next_run_at IS NULL OR s.sync_next_run_at <= now())
     ORDER BY s.sync_next_run_at NULLS FIRST
$$;

REVOKE EXECUTE ON FUNCTION list_due_object_source_syncs() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION list_due_object_source_syncs() TO platform_app;
