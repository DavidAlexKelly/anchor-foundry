-- ============================================================================
-- 0090_original_upload.sql
-- Remember the file somebody uploaded, so it can be parsed again
-- (§362; `dataset-preview` p.14, p.24).
--
-- > "Here, users can also apply additional parsing options to drop jagged
-- >  rows, change encoding, or add additional columns like file path, byte
-- >  offset for row, import timestamp, or row number." (p.14)
--
-- **The bytes have been kept since the first upload ever ran; nothing could
-- find them.** `routes/datasets.upload_dataset` writes the file verbatim to
-- `{prefix}original/{filename}` with the comment "export everything §11
-- includes what you gave us", and then the filename is thrown away: it is not
-- on this row, the export route serves parquet or a converted CSV instead, and
-- `StorageGateway` cannot list a prefix. So every upload since has paid to
-- store a second copy that no code path can reach.
--
-- One column fixes that, and it is the column this feature needs: a re-parse
-- reads the file as given and converts it again with different options, which
-- is only possible because the original was never thrown away.
--
-- **Null means "uploaded before this migration", and it stays null.** A
-- backfill would have to list the bucket, which is exactly the operation the
-- gateway does not offer, and guessing a filename to rebuild a key would be
-- worse than saying so: a dataset whose original cannot be named is one this
-- platform will decline to re-parse, with that reason.
--
-- **The filename, not the key.** The key is derived from it and the dataset's
-- own storage prefix (`storage_prefix(ws_prefix, dataset_id)`), which is
-- computed in one place already; storing the whole key would put the layout in
-- a second place and let the two disagree the first time it changes.
-- ============================================================================

ALTER TABLE datasets ADD COLUMN original_filename text;

COMMENT ON COLUMN datasets.original_filename IS
    'The name of the file this dataset was uploaded from, as stored under '
    '{prefix}original/ (db 0090). The key is derived from it rather than '
    'stored, so the storage layout stays defined in one place. Null for '
    'uploads predating this column and for datasets that were never uploaded '
    '- a sync or model output has no original file, and re-parsing asks for '
    'one.';
