-- ============================================================================
-- 0143_dataset_files.sql
-- Parity `docs/parity/datasets-lineage.md` §1.3, §1.4; Foundry
-- `dataset-preview` p.10, p.24 (§746).
--
-- > "If the filename and schema of the new file are identical to a previous
-- > upload, you can update data in the existing dataset. If the filename is
-- > different from previous uploads, you can append data to an existing
-- > dataset." (p.10)
--
-- An uploaded dataset received one file until now, and db 0090 recorded its
-- name on the dataset. p.10 makes an uploaded dataset a **set of named files**:
-- a file of a new name joins the set, and one of a name already there replaces
-- it. So the set is a table, one row per file the dataset currently holds, and
-- every version of the dataset is the files in it read together.
--
-- **The bytes stay where db 0090's always were**, `{prefix}original/{name}`,
-- and a name maps to one key, so replacing a file overwrites its original. The
-- versions already written are untouched (each has its own Parquet), so a
-- rollback still returns to exactly what an earlier version held.
--
-- `version_number` is the version the file last wrote, so a version made by
-- adding or replacing one can say which (`dataset_provenance`): the dataset's
-- own `original_filename` names only the first.
--
-- Backfilled from `datasets.original_filename`, which is every upload since
-- db 0090; an upload older than that kept no name and has no file to list,
-- the same refusal db 0090 already makes.
-- ============================================================================

CREATE TABLE dataset_files (
    dataset_id   uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    filename     text NOT NULL CHECK (length(filename) BETWEEN 1 AND 255),
    uploaded_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at  timestamptz NOT NULL DEFAULT now(),
    version_number integer NOT NULL CHECK (version_number >= 1),
    PRIMARY KEY (dataset_id, filename)
);

ALTER TABLE dataset_files ENABLE ROW LEVEL SECURITY;
CREATE POLICY dataset_files_isolation ON dataset_files
    USING (EXISTS (SELECT 1 FROM datasets d WHERE d.id = dataset_files.dataset_id
                   AND rls_can_access_project(d.project_id)));
GRANT SELECT, INSERT, UPDATE, DELETE ON dataset_files TO platform_app;

-- An upload's first version is 1 (`create_from_upload`).
INSERT INTO dataset_files (dataset_id, filename, uploaded_by, uploaded_at, version_number)
SELECT id, original_filename, created_by, created_at, 1
  FROM datasets
 WHERE origin = 'upload' AND original_filename IS NOT NULL
ON CONFLICT DO NOTHING;

-- **The parsing options a dataset was last read with** (p.24: "These
-- parameters are stored in the schema of a dataset."). §362 kept them only in the audit
-- entry because an uploaded dataset received one file, so a stored set had
-- no second reader. A file added later is that reader: without them, adding
-- one would read every file the default way again and silently undo the
-- re-parse that made the dataset right. NULL is the default read.
ALTER TABLE datasets ADD COLUMN parse_options jsonb;
