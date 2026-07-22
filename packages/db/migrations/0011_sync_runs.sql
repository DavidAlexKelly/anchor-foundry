-- ============================================================================
-- 0011_sync_runs.sql
-- Connection sync history (spec §"Connections" sync modes, §17 trigger sync).
-- One row per sync execution. Day one the API executes full syncs inline and
-- records them here; this table is also the handoff point for the worker's
-- scheduled/large syncs in a later milestone — the schema is written for
-- both callers.
-- ============================================================================

CREATE TABLE sync_runs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id uuid NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    dataset_id    uuid REFERENCES datasets(id) ON DELETE SET NULL,
    requested_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    mode          sync_mode NOT NULL,
    source_table  text NOT NULL CHECK (length(source_table) BETWEEN 1 AND 320),
    status        text NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'succeeded', 'failed')),
    rows_synced   bigint NOT NULL DEFAULT 0 CHECK (rows_synced >= 0),
    error         text,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);

CREATE INDEX idx_sync_runs_connection ON sync_runs (connection_id, started_at DESC);

GRANT SELECT, INSERT, UPDATE ON sync_runs TO platform_app;

-- Visibility follows the connection: the subselect triggers conn_isolation,
-- whose helpers are SECURITY DEFINER — one hop, no cycle back to sync_runs.
ALTER TABLE sync_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY sync_runs_isolation ON sync_runs
    USING (EXISTS (SELECT 1 FROM connections c WHERE c.id = sync_runs.connection_id));
