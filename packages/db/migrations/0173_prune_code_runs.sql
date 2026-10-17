-- Old code test and preview runs are deleted (§972).
--
-- A test run stores the repository's whole working set, up to 4 MB (db 0071),
-- because an uncommitted edit exists nowhere else; a preview stores its file,
-- up to 512 KB, and the rows it produced (db 0092). One row each per press of
-- the button, and nothing ever deleted one. Nothing reads them past the
-- newest ten either: the panels ask for a branch's or a file's latest ten, and
-- a run by its id from one of those. So a team running tests all day added
-- hundreds of megabytes a day to the database, read for an afternoon and kept
-- for good.
--
-- `prune_code_runs` deletes a run that has finished, is older than
-- `p_older`, and is not among the newest `p_keep` of its own list - a
-- branch's test runs, a file's previews - which also keeps the repository's
-- newest ten, the list a panel shows with no branch chosen. At most `p_batch`
-- rows a table a call, so the nightly sweep calls until nothing is left and
-- no one statement holds the tables for long. SECURITY DEFINER because the
-- sweep reads every workspace's runs, as 0165's does.
CREATE FUNCTION prune_code_runs(p_older interval DEFAULT '30 days',
                                p_keep integer DEFAULT 10,
                                p_batch integer DEFAULT 5000)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    deleted integer := 0;
    n integer;
BEGIN
    DELETE FROM code_test_runs
     WHERE id IN (
        SELECT id FROM (
            SELECT id, finished_at, queued_at,
                   row_number() OVER (PARTITION BY repo_id, branch
                                      ORDER BY queued_at DESC) AS place
              FROM code_test_runs) ranked
         WHERE ranked.place > p_keep
           AND ranked.finished_at IS NOT NULL
           AND ranked.queued_at < now() - p_older
         LIMIT p_batch);
    GET DIAGNOSTICS n = ROW_COUNT;
    deleted := deleted + n;

    DELETE FROM code_preview_runs
     WHERE id IN (
        SELECT id FROM (
            SELECT id, finished_at, queued_at,
                   row_number() OVER (PARTITION BY repo_id, path
                                      ORDER BY queued_at DESC) AS place
              FROM code_preview_runs) ranked
         WHERE ranked.place > p_keep
           AND ranked.finished_at IS NOT NULL
           AND ranked.queued_at < now() - p_older
         LIMIT p_batch);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN deleted + n;
END;
$$;

REVOKE EXECUTE ON FUNCTION prune_code_runs(interval, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION prune_code_runs(interval, integer, integer) TO platform_app;
