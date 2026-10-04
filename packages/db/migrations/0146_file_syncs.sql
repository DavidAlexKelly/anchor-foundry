-- ============================================================================
-- 0146_file_syncs.sql
-- Decision 0021; parity `docs/parity/data-connection.md` §2 (File-based
-- syncs); Foundry `data-connection` p.160-164 (§749).
--
-- > "Each run will ingest all files nested in the external system's
-- > subdirectory, including files ingested in previous runs, and commit a
-- > SNAPSHOT transaction to the output dataset containing exactly those
-- > files." (p.160)
--
-- An S3 sync read one object. p.160's unit is a **subfolder**, and its four
-- modes are a transaction type and a filter on which of the subfolder's files
-- a run takes. So a connection's managed sync target can now be a folder:
--
--   sync_mode = 'files'        the subfolder is `sync_source_schema`
--   sync_file_transaction      p.160's "Transaction type" (decision 0020)
--   sync_file_filters          p.164's filters, as `file_syncs.parse_filters`
--                              reads them
--
-- **`sync_files` is what "Exclude files already synced" remembers**: every
-- file a sync has ever taken, by path, with the size and modified time it had
-- then. It is not the dataset's current files (that is `dataset_files`, §746):
-- p.162's trailing window shows only a run's new files and must still know
-- the old ones were taken.
-- ============================================================================

ALTER TYPE sync_mode ADD VALUE IF NOT EXISTS 'files';

ALTER TABLE connections
    ADD COLUMN sync_file_transaction text
        CHECK (sync_file_transaction IN ('SNAPSHOT', 'APPEND', 'UPDATE')),
    ADD COLUMN sync_file_filters jsonb;

CREATE TABLE sync_files (
    connection_id uuid NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    path          text NOT NULL CHECK (length(path) BETWEEN 1 AND 1024),
    size          bigint NOT NULL CHECK (size >= 0),
    modified      text,
    synced_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (connection_id, path)
);

ALTER TABLE sync_files ENABLE ROW LEVEL SECURITY;
-- Seeing what a source's sync took is seeing the source.
CREATE POLICY sync_files_isolation ON sync_files
    USING (EXISTS (
        SELECT 1 FROM connections c
         WHERE c.id = sync_files.connection_id
           AND rls_can_access_connection(c.scope, c.workspace_id, c.project_id)));
GRANT SELECT, INSERT, UPDATE, DELETE ON sync_files TO platform_app;

-- A synced file is one of its dataset's files (`dataset_files`, §746), named
-- by its path under the subfolder, and a path is longer than an upload's name.
ALTER TABLE dataset_files DROP CONSTRAINT dataset_files_filename_check;
ALTER TABLE dataset_files ADD CONSTRAINT dataset_files_filename_check
    CHECK (length(filename) BETWEEN 1 AND 1024);
