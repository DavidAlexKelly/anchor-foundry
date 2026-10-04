-- ============================================================================
-- 0144_transaction_types.sql
-- Decision 0020; parity `docs/parity/datasets-lineage.md` §1.3,
-- `data-connection.md` §2. Foundry `data-integration` p.22-26 (§747).
--
-- > "The way dataset files are modified in a transaction depends on the
-- > transaction type. There are four possible transaction types: SNAPSHOT,
-- > APPEND, UPDATE, and DELETE." (p.22)
--
-- Every version here is still a complete view (one Parquet per version, as
-- db 0001 made it). What it did not record is **how it relates to the one
-- before**, which is the thing p.22's types say and the thing decision 0014
-- §2 found four export modes need. A version now says it:
--
--   SNAPSHOT  a new view; nothing before it is part of this one
--   APPEND    the previous view plus rows; no row of it changed
--   UPDATE    the previous view with rows added, changed or removed
--
-- DELETE is not a value. p.24's DELETE removes files from the view, and
-- nothing here removes rows without also possibly changing others: an action
-- that deletes an object writes UPDATE. A type with no writer would be a
-- promise nothing keeps.
--
-- **No default once the backfill is done**, so a writer that does not say
-- which it is fails rather than being filed as a SNAPSHOT by omission - the
-- lesson of db 0023's trigger, which caught writers nobody listed.
--
-- The backfill claims only what the history can show:
--   * listener archives only ever add events            -> APPEND
--   * an action rewrote rows of the view it read        -> UPDATE
--   * an incremental sync (it stored a cursor, db 0127) merged by key after
--     its first run, and may have replaced rows         -> UPDATE
--   * everything else wrote a whole view                -> SNAPSHOT
-- An UPDATE that in fact only added rows is under-claimed, which is the safe
-- direction: what reads the type (an incremental export) refuses an UPDATE
-- and re-exports a SNAPSHOT, and neither duplicates a row.
-- ============================================================================

ALTER TABLE dataset_versions
    ADD COLUMN transaction_type text NOT NULL DEFAULT 'SNAPSHOT'
        CHECK (transaction_type IN ('SNAPSHOT', 'APPEND', 'UPDATE'));

UPDATE dataset_versions SET transaction_type = 'APPEND'
 WHERE produced_by_kind = 'listener';

UPDATE dataset_versions SET transaction_type = 'UPDATE'
 WHERE produced_by_kind IN ('action', 'action_batch');

UPDATE dataset_versions SET transaction_type = 'UPDATE'
 WHERE produced_by_kind = 'sync' AND sync_cursor_value IS NOT NULL AND version_number > 1;

ALTER TABLE dataset_versions ALTER COLUMN transaction_type DROP DEFAULT;
