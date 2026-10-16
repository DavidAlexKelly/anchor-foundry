-- An export run is recorded as running while it runs (§968).
--
-- A run from the API wrote its row only when it had finished. A large
-- export can take longer than the sixty seconds CloudFront waits for an
-- answer, so the person who pressed Run was told 504 while it carried on,
-- and there was nothing to say it was still going - not to them, and not to
-- whoever pressed Run again, starting a second run that sends the same rows
-- to the same destination. Now the run opens a row first and the outcome
-- completes it, so a run that outlasts its request (§967) can answer with
-- that row, and the history shows it in flight.
--
-- * 'running' joins the statuses, with no error, as 'succeeded' has none.
-- * One running run per export: a second is refused while the first goes on.
-- * A run whose API stopped under it is failed by the same sweep as every
--   other run with a running state (0165, 0169), through a fifth interval.

-- deploy-safe: widened in the same transaction, so the previous API, which
-- writes only 'succeeded' and 'failed', is checked by a constraint that still
-- admits both.
ALTER TABLE export_runs DROP CONSTRAINT export_runs_status_check;
ALTER TABLE export_runs ADD CONSTRAINT export_runs_status_check
    CHECK (status IN ('running', 'succeeded', 'failed'));

-- deploy-safe: as above; the rows the previous API writes still pass.
ALTER TABLE export_runs DROP CONSTRAINT export_runs_error_matches_status;
ALTER TABLE export_runs ADD CONSTRAINT export_runs_error_matches_status CHECK (
    (status = 'failed' AND error IS NOT NULL)
    OR (status IN ('running', 'succeeded') AND error IS NULL)
);

CREATE UNIQUE INDEX export_runs_one_running ON export_runs (export_id)
    WHERE status = 'running';

-- deploy-safe: the five-argument function created next takes the previous
-- worker's four-argument call through its default, so nothing it runs fails.
DROP FUNCTION fail_abandoned_runs(interval, interval, interval, interval);

CREATE FUNCTION fail_abandoned_runs(p_model_runs interval, p_code_runs interval,
                                    p_action_runs interval,
                                    p_sync_runs interval DEFAULT '30 minutes',
                                    p_export_runs interval DEFAULT '30 minutes')
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
    failed := failed + n;

    UPDATE export_runs
       SET status = 'failed', finished_at = now(),
           error = 'the platform stopped while this export ran; run it again'
     WHERE status = 'running' AND started_at < now() - p_export_runs;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN failed + n;
END;
$$;

REVOKE EXECUTE ON FUNCTION fail_abandoned_runs(interval, interval, interval, interval, interval)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fail_abandoned_runs(interval, interval, interval, interval, interval)
    TO platform_app;
