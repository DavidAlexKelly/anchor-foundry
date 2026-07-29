-- ============================================================================
-- 0022_model_health_gating.sql
-- Let a model refuse to run on input data that failed its quality checks.
--
-- 0020 made bad data detectable; 0021 made it *propagate automatically*. A
-- model on an upstream trigger runs the moment its input gains a version,
-- and its output is the next model's input, so one bad upload now reaches
-- the end of a chain with nobody having looked at it. This closes that
-- loop: `models.input_health_policy` decides what a run does when an input
-- dataset's health is `fail`.
--
--   ignore  today's behaviour, and the default - see below
--   warn    run anyway, but record what was wrong on the run
--   block   refuse to run; the run is recorded as failed with the reason
--
-- **The default is `ignore`, deliberately.** Defaulting to `block` would
-- silently change what every existing model does the moment this migration
-- applies - a model that has been running fine for months would start
-- failing because someone once added a check to one of its inputs. Gating
-- is opt-in per model; the roadmap item asked for "let a model's run be
-- configured to refuse", and configured is the operative word.
--
-- **`warn` records rather than refuses, and that is the point of having
-- it.** It is the mode you turn on first, to find out how often your inputs
-- would have blocked a run, before you commit to blocking them. Without it
-- the only way to learn that is to break your own pipeline.
--
-- **The gate is a reader, which is what makes it work at all.** 0020's
-- health results are computed on demand and cached, and that migration
-- flagged the one thing it could not do: "alert at the moment a bad version
-- lands, because there is no reader to trigger the computation." A gate
-- checking its inputs before every run *is* that reader. It computes health
-- if there is no cached result, so a policy of `block` is enforced against
-- data nobody has opened - which is exactly the automated case that needs
-- it most. That is also the cost, stated plainly: a gated run pays for one
-- DuckDB pass per input the first time each version is seen.
--
-- **Only `fail` gates.** `warn` health means only warn-severity rules or
-- unevaluatable ones tripped (0020's `error`-is-not-`fail` distinction), and
-- a rule that could not be evaluated has not proven the data bad - blocking
-- a pipeline on it would punish a broken rule, not bad data. `none` (no
-- rules) never gates: a dataset nobody has written checks for is not
-- evidence of anything.
-- ============================================================================

CREATE TYPE model_health_policy AS ENUM ('ignore', 'warn', 'block');

ALTER TABLE models
    ADD COLUMN input_health_policy model_health_policy NOT NULL DEFAULT 'ignore';

COMMENT ON COLUMN models.input_health_policy IS
    'What a run does when an input dataset''s data-quality health is '
    '''fail'': ignore (default), warn (run and record), block (refuse).';

-- What the gate actually saw, per input, at the moment it decided. Written
-- on every run whose policy is not 'ignore', whether or not it blocked.
--
-- On the run rather than derived at read time on purpose: health is cached
-- per dataset *version* and invalidated whenever the rules change (0020), so
-- re-deriving "why did this run block" a week later can give a different
-- answer than the one the run was actually refused on. A blocked run is a
-- thing someone will come back to and argue with; it has to carry its own
-- evidence.
--
-- Shape: [{"dataset_id": ..., "name": ..., "version": n, "status": "fail",
--          "failing": ["email: 3 null value(s)"]}]
ALTER TABLE model_runs ADD COLUMN input_health jsonb;

COMMENT ON COLUMN model_runs.input_health IS
    'Per-input dataset health as the gate saw it, captured at run time; '
    'NULL when the model''s input_health_policy was ''ignore''.';
