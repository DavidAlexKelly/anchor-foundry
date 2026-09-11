-- Why an action failed, in p.165's own vocabulary (§323; `action-types`
-- p.164-166).
--
--     "Action metrics display the near real-time usage of an action type over
--      the last 30 days… Success/failure metrics: Monitor the current status of
--      your actions with success and failure counts." (p.164)
--
--     "Action metrics do not require action logs to be displayed. **Unlike
--      action logs, action metrics track failures.**" (p.165)
--
--     "Action metrics have a variety of categories of failures that may be
--      displayed. These categories are: Invalid parameter failure… Scale limit
--      failure… Authentication failure… Side effect failure… Function failure…
--      User-facing function failure… Conflict failure… Unclassified failure."
--      (p.165-166)
--
-- **The column exists because two of p.166's categories were unreachable.**
-- `action_runs` has recorded failures since db 0013, and 515 of them are in
-- this build's development database — but every one is a *dataset engine*
-- error, because that is the only failure that happens after `open_run`. A
-- submission refused for an invalid parameter, or for failing the action's
-- submission criteria, is answered with a 422 before any run exists.
--
-- So the two failure kinds a person actually causes were the two the metric
-- could never show, and p.165's whole sentence — "unlike action logs, action
-- metrics track failures" — was true of this platform only for the failures
-- nobody submitted.
--
-- **Classified when it fails, not when it is read.** The alternative is to
-- pattern-match `error` text at query time, and that is the same defect §313
-- found in a different shape: a category derived from a message is a category
-- that changes when somebody rewords the message, silently and in the past
-- tense. The writer knows which refusal it raised; nothing later does.
--
-- **Nullable, and the null is `succeeded`.** A category on a run that worked
-- would be a column with a meaning for one value of another column, and every
-- reader would have to know that. `NULL` here means "did not fail", which is
-- what `status` already says.

ALTER TABLE action_runs
    ADD COLUMN failure_category text
        CHECK (failure_category IS NULL OR failure_category IN (
            -- p.165: "submitted with a parameter or parameters that are not
            -- valid within the context of the action".
            'invalid_parameter',
            -- p.166: "did not pass the security submission criteria".
            'authentication',
            -- p.166: "affected more than the permitted limit of object types".
            'scale_limit',
            -- p.166: "failed due to a webhook or an incorrectly configured
            -- side effect".
            'side_effect',
            -- p.166: "failed due to a conflict, such as a concurrent
            -- modification".
            'conflict',
            -- p.166's last, and the honest home for a dataset engine error
            -- this platform cannot attribute more precisely.
            'unclassified'
        ));

-- p.166's two function categories — `function` and `user_facing_function` —
-- are **deliberately absent from the CHECK**. Both are documented as "only
-- possible for function-backed actions", and Functions are ○ in
-- `ontology.md` §1.3: a value nothing can produce is a category that would sit
-- in every dropdown and never appear, which is §214's control that looks like
-- it works. They go in when there is a function to fail.

-- Counting failures by category over p.164's window, per action type.
CREATE INDEX idx_action_runs_failures
    ON action_runs (action_type_id, started_at DESC)
    WHERE status = 'failed';
