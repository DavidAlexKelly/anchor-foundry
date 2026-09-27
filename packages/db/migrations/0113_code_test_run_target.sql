-- ============================================================================
-- 0113_code_test_run_target.sql
-- Running the tests in one file (§530; `code-repositories` p.13).
--
--     "Click the [Test] button to run all unit tests defined in the current
--      file." (p.13)
--
-- **A narrowing of the run, not a second mechanism**: the same working set is
-- stored and the same worker runs pytest over it; `target` is the path pytest
-- is handed instead of the whole directory. NULL is every test in the
-- repository, which is what a run was before this column.
--
-- The path is the repository's own spelling, normalised by the API (no `..`,
-- no leading slash), and the worker checks again that it stays inside the
-- directory it runs in.
-- ============================================================================

ALTER TABLE code_test_runs
    ADD COLUMN target text CHECK (target IS NULL OR (length(target) BETWEEN 1 AND 1024));
