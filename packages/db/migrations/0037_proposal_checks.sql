-- ============================================================================
-- 0037_proposal_checks.sql
-- Checks that run on a proposal and block it (ROADMAP phase 2, item 2.8).
--
-- The item asks for "lint and schema-compatibility checks that run on a
-- proposal and block merge", reusing the existing quality-gate machinery. Both
-- halves of that machinery already exist and neither runs at review time:
--
--   * 0023 gave a dataset a `schema_policy`, enforced by a trigger on
--     `dataset_versions`. A proposal that removes a column from a strict
--     dataset's transform is therefore *already* refused - by the database, at
--     run time, hours after somebody approved it.
--   * 2.6 gave the API a way to run a transform over a sample of its inputs
--     and report the schema it produces, without writing anything.
--
-- Putting the second in front of the first is the whole item: find out at
-- review time what the database would refuse at run time.
--
-- **A check result is a claim about a version of the files**, the same shape
-- 0036 gave comments. It records the `files_updated_at` it ran against, and a
-- result older than that is stale - it describes code nobody will apply. Stale
-- results are shown and marked, never silently believed.
--
-- **A failing check blocks; an absent one does not.** A gate that engages by
-- default would leave every project that turns review on unable to apply
-- anything until somebody finds the button - which is the argument 0031 already
-- made for review itself being off by default, and it applies with more force
-- here because a check costs real work to run. The review surface says loudly
-- when checks have not run against the current files; it does not pretend that
-- silence is a pass.
-- ============================================================================

-- pass    the check ran and found nothing
-- warn    it found something a reviewer should see, which does not block
-- fail    it found something that would break, which blocks applying
-- error   the check could not run - not the same as passing, and not the same
--         as failing: nobody has been told anything about the code.
CREATE TYPE code_check_status AS ENUM ('pass', 'warn', 'fail', 'error');

CREATE TABLE code_proposal_checks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id  uuid NOT NULL REFERENCES code_proposals(id) ON DELETE CASCADE,
    -- Which file it is about. NULL is a check about the proposal as a whole.
    model_id     uuid REFERENCES models(id) ON DELETE CASCADE,
    -- The check's own name, e.g. 'transform_runs' or 'schema_compatible'.
    -- Free text rather than an enum: adding a check should not be a migration,
    -- and the set of checks is application knowledge, not a shape the database
    -- has any use for.
    name         text NOT NULL CHECK (btrim(name) <> ''),
    status       code_check_status NOT NULL,
    -- One sentence, already phrased for whoever has to act on it.
    summary      text NOT NULL DEFAULT '',
    -- Anything structured the surface wants to render - a schema diff, a list
    -- of columns. Never the only place a reason lives; `summary` always says it
    -- in words too.
    detail       jsonb NOT NULL DEFAULT '{}'::jsonb,
    ran_at       timestamptz NOT NULL DEFAULT now(),
    ran_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    -- The proposal's files_updated_at this ran against (0036's rule).
    anchored_at  timestamptz NOT NULL,
    -- One current result per check per file: re-running replaces rather than
    -- appends, because a list of every time a check ran is a log, and what a
    -- reviewer needs is the answer.
    UNIQUE (proposal_id, model_id, name)
);

-- NULLS NOT DISTINCT: a proposal-wide check has model_id NULL, and without
-- this the UNIQUE above would let it be inserted any number of times - Postgres
-- treats NULLs as distinct in a unique constraint by default, which is exactly
-- the case this table has.
ALTER TABLE code_proposal_checks
    DROP CONSTRAINT code_proposal_checks_proposal_id_model_id_name_key,
    ADD CONSTRAINT code_proposal_checks_one_current_result
        UNIQUE NULLS NOT DISTINCT (proposal_id, model_id, name);

CREATE INDEX idx_code_proposal_checks_proposal
    ON code_proposal_checks (proposal_id, ran_at DESC);

COMMENT ON COLUMN code_proposal_checks.anchored_at IS
    'The proposal files_updated_at this ran against (db 0037, same rule as '
    '0036). A result older than the current one describes code nobody will '
    'apply: shown, marked stale, and not counted as a gate.';

ALTER TABLE code_proposal_checks ENABLE ROW LEVEL SECURITY;
CREATE POLICY cpck_isolation ON code_proposal_checks
    USING (EXISTS (SELECT 1 FROM code_proposals p
                   WHERE p.id = proposal_id
                     AND rls_can_access_project(p.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON code_proposal_checks TO platform_app;
