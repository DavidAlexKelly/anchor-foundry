-- ============================================================================
-- 0145_transactional_export_modes.sql
-- Decision 0020 §4; parity `docs/parity/data-connection.md` §2 (Exports);
-- Foundry `data-connection` p.195-196 (§748).
--
-- 0069 built two of p.195-196's six table export modes because "four of them
-- are defined over a transaction log this platform does not keep". db 0144
-- gave every dataset version its transaction type, and these are the four:
--
--   'efficient_mirror'     p.195's "Efficiently mirror dataset to external
--                          table (recommended)" - the unexported transactions
--                          of the current view, truncating first when one of
--                          them is a SNAPSHOT
--   'incremental'          p.196's "Export incrementally" - the same without
--                          ever truncating
--   'incremental_truncate' p.196's "Export incrementally with truncation" -
--                          truncate, then the unexported transactions
--   'append_only'          p.196's "Export incrementally and fail if not
--                          APPEND"
--
-- What each sends is `exports.plan`'s. A run now also keeps one sentence of
-- what it did (`export_runs.detail`): "sent the rows v6, v7 added" and "cleared
-- the table, then sent the whole view at v8" are two runs that both say
-- `succeeded`, and p.206's history is where somebody tells them apart.
-- ============================================================================

ALTER TYPE export_mode ADD VALUE IF NOT EXISTS 'efficient_mirror';
ALTER TYPE export_mode ADD VALUE IF NOT EXISTS 'incremental';
ALTER TYPE export_mode ADD VALUE IF NOT EXISTS 'incremental_truncate';
ALTER TYPE export_mode ADD VALUE IF NOT EXISTS 'append_only';

ALTER TABLE export_runs ADD COLUMN detail text;
