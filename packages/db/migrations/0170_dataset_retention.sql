-- How many versions of a dataset to keep, and which ones may go (§964;
-- docs/decisions/0005-dataset-retention.md).
--
-- Every version of every dataset has always been kept whole, and nothing
-- deleted one: a dataset synced hourly for a year is 8,760 copies of itself,
-- and the bill grows for ever. Decision 0005 chose the shape of the remedy and
-- left it unbuilt until somebody could see what it would remove first. This is
-- that half: the policy and the answer to "what would it remove". Nothing here
-- deletes anything; the sweeper that does is the next unit, and it reads the
-- same function the report does, so the two cannot disagree.
--
-- * `datasets.retention_versions`: keep the newest N versions; NULL, the
--   default, keeps everything, as every dataset does today (0005 §1, §4).
-- * `dataset_versions.expired_at`: when a version's bytes were removed. The row
--   stays, still true about what the data was (0005 §2).
ALTER TABLE datasets
    ADD COLUMN retention_versions integer
        CHECK (retention_versions IS NULL OR retention_versions >= 1);

ALTER TABLE dataset_versions
    ADD COLUMN expired_at timestamptz;

-- The versions a dataset's policy lets go, oldest first. Never:
--
-- * the current version (0005 §3);
-- * one of the newest N;
-- * one a transactional export still needs. Such an export (§748) reads every
--   version after the last one it sent, and the version before each APPEND to
--   tell what it added, so every version from its `last_version` on is held
--   until it has moved past. One that has sent nothing yet sends the current
--   view whole, which is already held;
-- * one whose file another version still reads. **A rollback does not copy**
--   (§361): the version it writes points at the old version's own key, so
--   rolling back to v3 makes v8 read v3's file, and expiring v3 would delete
--   the current data. A version goes only if every other row naming its file,
--   in any dataset, is going with it or already gone, and no dataset's current
--   location is that file.
--
-- A fork copies its source's bytes when it is made (0005 §3), so it holds
-- nothing here. SECURITY DEFINER because the answer must count every export
-- and every version that shares a file, including ones the asking user cannot
-- see; the API asks only about a dataset it has already read under that
-- user's own policies, and the worker one dataset at a time.
--
-- Asked with a number of versions to keep rather than the stored one, so the
-- dataset's screen can show what a policy would remove before it is saved:
-- decision 0005's order, and one definition for the report, the preview and
-- the sweeper. NULL keeps everything.
CREATE FUNCTION expirable_dataset_versions_keeping(p_dataset uuid, p_keep integer)
RETURNS TABLE (version_number integer, s3_manifest_key text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    WITH policy AS (
        SELECT current_version, p_keep AS retention_versions
          FROM datasets
         WHERE id = p_dataset AND p_keep IS NOT NULL
    ), newest AS (
        SELECT max(version_number) AS n FROM dataset_versions WHERE dataset_id = p_dataset
    ), held AS (
        SELECT min(last_version) AS from_version
          FROM exports
         WHERE dataset_id = p_dataset
           AND last_version IS NOT NULL
           -- As text: an enum value added by 0145 cannot be named in a function
           -- body created in the same transaction, which a fresh database is.
           AND mode::text IN ('efficient_mirror', 'incremental', 'incremental_truncate',
                              'append_only')
    ), candidates AS (
        SELECT v.version_number, v.s3_manifest_key
          FROM dataset_versions v, policy, newest, held
         WHERE v.dataset_id = p_dataset
           AND v.expired_at IS NULL
           AND v.version_number <> policy.current_version
           AND v.version_number <= newest.n - policy.retention_versions
           AND (held.from_version IS NULL OR v.version_number < held.from_version)
    )
    SELECT c.version_number, c.s3_manifest_key
      FROM candidates c
     WHERE c.s3_manifest_key IS NULL
        OR (NOT EXISTS (
                SELECT 1 FROM dataset_versions other
                 WHERE other.s3_manifest_key = c.s3_manifest_key
                   AND other.expired_at IS NULL
                   AND NOT (other.dataset_id = p_dataset
                            AND other.version_number IN (SELECT version_number FROM candidates)))
            AND NOT EXISTS (SELECT 1 FROM datasets d WHERE d.s3_location = c.s3_manifest_key))
     ORDER BY c.version_number
$$;

-- What the dataset's own policy lets go: the report and the sweeper.
CREATE FUNCTION expirable_dataset_versions(p_dataset uuid)
RETURNS TABLE (version_number integer, s3_manifest_key text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT e.version_number, e.s3_manifest_key
      FROM expirable_dataset_versions_keeping(
               p_dataset, (SELECT retention_versions FROM datasets WHERE id = p_dataset)) e
$$;

-- What the shared-file check looks a key up by.
CREATE INDEX idx_dataset_versions_manifest_key ON dataset_versions (s3_manifest_key);

REVOKE EXECUTE ON FUNCTION expirable_dataset_versions_keeping(uuid, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION expirable_dataset_versions(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION expirable_dataset_versions_keeping(uuid, integer) TO platform_app;
GRANT EXECUTE ON FUNCTION expirable_dataset_versions(uuid) TO platform_app;
