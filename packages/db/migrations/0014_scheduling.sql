-- ============================================================================
-- 0014_scheduling.sql
-- Cron-triggered model runs, and scheduled/incremental connection syncs.
--
-- Both features share one shape: a "when is this due" timestamp column the
-- worker polls (`next_run_at` / `sync_next_run_at`), computed by the API from
-- a cron expression at write time (services already anticipated this:
-- models.trigger_mode/cron_schedule and connections.sync_mode/sync_schedule
-- existed since 0003 but were never wired to anything that reads them).
--
-- Connections, not a new table: the existing connections columns
-- (sync_mode, sync_schedule) already commit to "one managed sync target per
-- connection" as the day-one shape. Rather than introduce a second,
-- differently-shaped config table, this migration completes that shape with
-- the columns a schedulable/incremental sync needs to be self-contained:
-- which schema.table, the dataset it feeds, and (incremental only) the
-- primary key + cursor columns and progress. Flagged for review: syncing
-- several tables from one connection on independent schedules needs a
-- separate per-target config table — a natural extension, not built here,
-- since the existing schema already committed to one schedule per
-- connection.
--
-- Worker discovery (mirrors 0010's list_orphaned_workspace_schemas: a
-- SECURITY DEFINER function enumerates candidates across every workspace —
-- something no ordinary RLS-scoped query can do without already knowing
-- which workspace to look in — and the worker re-verifies/acts on each one
-- through the normal RLS-scoped path, never trusting the bypass for the
-- actual mutation).
-- ============================================================================

ALTER TABLE models ADD COLUMN next_run_at timestamptz;

ALTER TABLE connections
    ADD COLUMN sync_source_schema      text,
    ADD COLUMN sync_source_table       text,
    ADD COLUMN sync_dataset_name       text,
    ADD COLUMN sync_dataset_id         uuid REFERENCES datasets(id) ON DELETE SET NULL,
    ADD COLUMN sync_primary_key_column text,
    ADD COLUMN sync_cursor_column      text,
    ADD COLUMN sync_last_cursor_value  text,
    ADD COLUMN sync_next_run_at        timestamptz,
    ADD CONSTRAINT chk_connections_incremental_needs_cursor
        CHECK (sync_mode <> 'incremental'
               OR (sync_primary_key_column IS NOT NULL AND sync_cursor_column IS NOT NULL));

-- ---- worker discovery (SECURITY DEFINER; bypass is read-only enumeration,
--      never the mutation itself) --------------------------------------------
CREATE FUNCTION list_queued_model_runs() RETURNS TABLE(run_id uuid, workspace_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT mr.id, p.workspace_id
      FROM model_runs mr
      JOIN models m ON m.id = mr.model_id
      JOIN projects p ON p.id = m.project_id
     WHERE mr.status = 'queued'
     ORDER BY mr.queued_at
$$;

-- A NULL next_run_at means "schedule set, never fired yet" — treated as due
-- immediately so a freshly-scheduled model/sync doesn't sit idle until the
-- worker (the only place that parses cron expressions, via croniter) has
-- had a chance to compute its first real occurrence. Flagged for review:
-- this means a newly-scheduled job fires once right away and follows the
-- schedule thereafter, rather than waiting for the first natural occurrence
-- — a conservative, simple, honestly-documented day-one choice.
CREATE FUNCTION list_due_cron_models() RETURNS TABLE(model_id uuid, workspace_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT m.id, p.workspace_id
      FROM models m
      JOIN projects p ON p.id = m.project_id
     WHERE m.trigger_mode = 'cron'
       AND (m.next_run_at IS NULL OR m.next_run_at <= now())
     ORDER BY m.next_run_at NULLS FIRST
$$;

CREATE FUNCTION list_due_scheduled_syncs() RETURNS TABLE(connection_id uuid, workspace_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT c.id, c.workspace_id
      FROM connections c
     WHERE c.sync_schedule IS NOT NULL
       AND (c.sync_next_run_at IS NULL OR c.sync_next_run_at <= now())
     ORDER BY c.sync_next_run_at NULLS FIRST
$$;

REVOKE EXECUTE ON FUNCTION list_queued_model_runs() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION list_due_cron_models() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION list_due_scheduled_syncs() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION list_queued_model_runs() TO platform_app;
GRANT EXECUTE ON FUNCTION list_due_cron_models() TO platform_app;
GRANT EXECUTE ON FUNCTION list_due_scheduled_syncs() TO platform_app;
