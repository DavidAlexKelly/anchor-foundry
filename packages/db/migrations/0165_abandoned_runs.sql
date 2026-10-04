-- Runs a worker that stopped will never finish, said to have failed (§870).
--
-- The worker marks a model run, a code test run or a code preview run
-- 'running' and commits that before the work starts, so the claim is visible
-- (§853), and the API opens an action run in one transaction and closes it in
-- another. If the process stops part-way - a deploy replacing its task, an
-- out-of-memory kill, a lost host - the row stays 'running' for good. A model
-- set to run on new upstream data is then never enqueued again, because the
-- rule is "nothing queued or running" (0021); the run's page says it is still
-- going; an action's metrics count it as running for ever; and nothing
-- anywhere says otherwise.
--
-- So a run still 'running' long after any run could have finished is failed,
-- with a sentence saying why. "Long after" is the caller's to say, from the
-- limits it runs under (`jobs/model_runs.py`). A run that was in fact alive
-- and finishes later still writes its real outcome over this one: the worker's
-- final update does not ask what the status was.
CREATE FUNCTION fail_abandoned_runs(p_model_runs interval, p_code_runs interval,
                                    p_action_runs interval)
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
    RETURN failed + n;
END;
$$;

REVOKE EXECUTE ON FUNCTION fail_abandoned_runs(interval, interval, interval) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fail_abandoned_runs(interval, interval, interval) TO platform_app;
