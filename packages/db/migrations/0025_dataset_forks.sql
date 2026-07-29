-- ============================================================================
-- 0025_dataset_forks.sql
-- Fork a dataset at a version into a new, independent dataset.
--
-- The roadmap item is explicit that this is the *small* version of
-- branching: copy a version into a separate dataset to experiment against,
-- not git-style branch/merge semantics. That framing survived contact -
-- nothing here knows how to merge a fork back, on purpose, because deciding
-- what a merge means for tabular data is the large lift the item warns
-- about.
--
-- It also got more useful than it looked. 0022 lets a model refuse to run on
-- failing input and 0023 lets a dataset refuse a version that breaks its
-- shape; both are things you want on in production, and both mean you now
-- need somewhere else to try the change that would trip them.
--
-- **`origin = 'fork'` rather than reusing 'upload'.** A fork did not come
-- from a file somebody uploaded, and labelling it as though it did would
-- make the origin column lie in the one place a user looks to answer "where
-- did this data come from". Adding the enum value costs one line; the lie
-- would cost every future reader.
--
-- **Provenance is a column pair, not an edge in the pipeline graph.**
-- `forked_from_dataset_id` / `forked_from_version` record exactly what was
-- copied. It is deliberately *not* added to §28's graph: that graph answers
-- "what recomputes when this changes", and a fork never recomputes - it is a
-- one-time copy, and drawing an edge would imply a live dependency that does
-- not exist. The provenance shows on the dataset itself instead.
--
-- **`forked_from_dataset_id` carries no foreign key, deliberately**, the
-- same way `dataset_versions.produced_by_id` already doesn't. This is a
-- historical statement - "this data was copied from dataset X at version 2"
-- - and that statement does not stop being true when X is deleted. The
-- alternatives are both worse: ON DELETE CASCADE would delete the fork,
-- destroying the independence this feature exists to provide, and ON DELETE
-- SET NULL nulls only the id and leaves the version behind, which is the
-- half-record the CHECK below refuses (found by the test asserting a fork
-- survives its source's deletion - it failed on exactly that constraint).
-- A reader that cannot resolve the id renders the fact without the link.
--
-- **The bytes are copied, not shared.** "New, independent dataset" is the
-- requirement, and pointing two datasets at one storage key would make
-- deleting the original silently empty the fork (delete removes the
-- dataset's whole prefix).
-- ============================================================================

-- IF NOT EXISTS because an enum value cannot be dropped: if this migration
-- is ever edited and re-applied against a database that already ran it, the
-- columns can be dropped and recreated but the label cannot.
ALTER TYPE dataset_origin ADD VALUE IF NOT EXISTS 'fork';

ALTER TABLE datasets
    ADD COLUMN forked_from_dataset_id uuid,
    ADD COLUMN forked_from_version integer;

COMMENT ON COLUMN datasets.forked_from_dataset_id IS
    'The dataset this one was forked from. Intentionally not a foreign key: '
    'a historical record, which stays true after that dataset is deleted.';

-- Either both provenance columns are set or neither is: half a provenance
-- record is worse than none, because it reads as though the information is
-- there.
ALTER TABLE datasets ADD CONSTRAINT datasets_fork_provenance_complete
    CHECK ((forked_from_dataset_id IS NULL) = (forked_from_version IS NULL));

CREATE INDEX idx_datasets_forked_from ON datasets (forked_from_dataset_id)
    WHERE forked_from_dataset_id IS NOT NULL;
