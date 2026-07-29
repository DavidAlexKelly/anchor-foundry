-- ============================================================================
-- 0026_instance_store_cutover.sql
-- Stop Postgres owning object-instance identity.
--
-- Roadmap Objects item 1 moves instances into OpenSearch. `object_instances`
-- stays as the fallback store and the local-dev default, but it is no longer
-- *the* place an instance exists - so a foreign key from `action_runs`
-- asserting "this id is a row in that table" becomes false the moment a
-- deployment flips over, and `ON DELETE SET NULL` would quietly erase which
-- instance every historical write-back touched.
--
-- Found by writing the backfill's test rather than by reading the schema:
-- the backfill rewrites `action_runs.instance_id` to the deterministic id
-- the new store uses, and that UPDATE cannot satisfy a foreign key into a
-- table the row does not live in.
--
-- The column stays, and it stays a uuid - the new ids are uuid5 of
-- (source_id, primary_key) precisely so that this identifier's *type* did
-- not have to change with its backing store. What it loses is the
-- referential guarantee, which is the same trade §34 made for
-- `datasets.forked_from_dataset_id` and §14's schema already made for
-- `dataset_versions.produced_by_id`: a run record is a historical statement
-- about what happened, and it stays true after the thing it names is gone.
-- ============================================================================

ALTER TABLE action_runs DROP CONSTRAINT action_runs_instance_id_fkey;

COMMENT ON COLUMN action_runs.instance_id IS
    'The object instance this run wrote to. Deliberately not a foreign key: '
    'instances may live in OpenSearch rather than object_instances, and a '
    'run record is a historical statement that outlives its subject.';
