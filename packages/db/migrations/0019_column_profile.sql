-- ============================================================================
-- 0019_column_profile.sql
-- Column-level profiling for a dataset version (roadmap Datasets item 1).
--
-- Preview today is a raw row grid: the first hundred rows and nothing else.
-- That answers "what does a row look like" and none of the questions someone
-- actually has about unfamiliar data - how complete is this column, how many
-- distinct values, what range does it span. This column caches those answers.
--
-- Computed lazily on first request rather than at version-creation time, and
-- that is the deliberate part. The roadmap said "computed once per dataset
-- version and cached alongside it", which this satisfies, but eager
-- computation would mean adding a DuckDB aggregate pass to *every* path that
-- creates a version - upload, both sync paths, both model paths, action
-- write-back - to produce something nobody may ever look at. Lazily means one
-- call site, no write-path cost, and the same "computed once" guarantee: a
-- version's data never changes (a new version is a new row), so a profile is
-- valid forever once written and never needs invalidating.
--
-- Shape: [{"name","data_type","null_count","null_rate","distinct_count",
--          "min","max"}] - min/max as text, since they have to hold whatever
-- the column's type is and this is display metadata, not something anything
-- computes against. Absent (NULL) means "not profiled yet", which is why the
-- read path returns it as a nullable object rather than an empty list.
-- ============================================================================

ALTER TABLE dataset_versions ADD COLUMN column_profile jsonb;

COMMENT ON COLUMN dataset_versions.column_profile IS
    'Per-column statistics for this version, computed on first request and '
    'cached forever (a version''s data is immutable). NULL means not yet '
    'profiled, not "no columns".';
