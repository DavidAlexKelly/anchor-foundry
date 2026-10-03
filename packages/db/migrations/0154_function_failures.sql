-- §773: the Function rule (`action-types` p.22), and p.166's two function
-- failures, now that an action can call one.
--
-- > "Function failure: The action failed because the underlying function
-- > failed. This failure mode is only possible for function-backed actions.
-- > User-facing function failure: The function backing the action threw an
-- > error intended to be displayed to the user." (`action-types` p.166)
--
-- 0079 left both out of the CHECK until there was a function to fail; the
-- Function rule (decision 0018 option B) is that function. A user-facing one
-- is the query's own `error('...')`.

ALTER TABLE action_runs DROP CONSTRAINT action_runs_failure_category_check;

ALTER TABLE action_runs
    ADD CONSTRAINT action_runs_failure_category_check
        CHECK (failure_category IS NULL OR failure_category IN (
            'invalid_parameter',
            'authentication',
            'scale_limit',
            'side_effect',
            'function',
            'user_facing_function',
            'conflict',
            'unclassified'
        ));

-- p.22's Function rule, the rule that makes those failures possible.
ALTER TYPE action_rule_kind ADD VALUE IF NOT EXISTS 'function';
