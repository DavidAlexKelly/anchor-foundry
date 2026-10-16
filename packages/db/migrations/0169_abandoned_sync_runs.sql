-- A sync the API was running when it stopped is said to have failed (§950).
--
-- 0165 did this for model, code and action runs, and missed one more table
-- with a 'running' state. The API opens a sync run, extracts and ingests, and
-- closes it in a later transaction (`services/sync.py`); a task replaced by a
-- deploy, killed for memory or lost with its host in between left the run
-- 'running' for good. The connection's sync health then reported its latest
-- run as still going, and the pipeline view drew it in flight, for ever.
--
-- The same function grows a fourth interval, with a default, so a worker from
-- before this migration - calling it with three - keeps working through a
-- rollout. Postgres resolves that call to this function; the three-argument
-- one has to go, or the call would match both.
-- deploy-safe: the four-argument function created next takes the previous
-- worker's three-argument call through its default, so nothing it runs fails.
DROP FUNCTION fail_abandoned_runs(interval, interval, interval);

CREATE FUNCTION fail_abandoned_runs(p_model_runs interval, p_code_runs interval,
                                    p_action_runs interval,
                                    p_sync_runs interval DEFAULT '30 minutes')
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    failed integer := 0;
    n integer;
    why constant text := 'the worker stopped while this ran; run it again';
BEGIN
    UPDATE model_runs
       SET status = 'failed', finished_at = now(), error_message = why
     WHERE status = 'running' AND started_at < now() - p_model_runs;
    GET DIAGNOSTICS n = ROW_COUNT;
    failed := failed + n;

    UPDATE code_test_runs
       SET status = 'errored', finished_at = now(), error = why
     WHERE status = 'running' AND started_at < now() - p_code_runs;
    GET DIAGNOSTICS n = ROW_COUNT;
    failed := failed + n;

    UPDATE code_preview_runs
       SET status = 'errored', finished_at = now(), error = why
     WHERE status = 'running' AND started_at < now() - p_code_runs;
    GET DIAGNOSTICS n = ROW_COUNT;
    failed := failed + n;

    UPDATE action_runs
       SET status = 'failed', finished_at = now(), failure_category = 'unclassified',
           error = 'the platform stopped while this ran; submit it again'
     WHERE status = 'running' AND started_at < now() - p_action_runs;
    GET DIAGNOSTICS n = ROW_COUNT;
    failed := failed + n;

    UPDATE sync_runs
       SET status = 'failed', finished_at = now(),
           error = 'the platform stopped while this sync ran; run it again'
     WHERE status = 'running' AND started_at < now() - p_sync_runs;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN failed + n;
END;
$$;

REVOKE EXECUTE ON FUNCTION fail_abandoned_runs(interval, interval, interval, interval) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fail_abandoned_runs(interval, interval, interval, interval) TO platform_app;
