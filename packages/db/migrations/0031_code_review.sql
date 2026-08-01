-- ============================================================================
-- 0031_code_review.sql
-- Review-gated promotion for transform code (ROADMAP Code item 4).
--
-- The item asks for "a PR-like review step before a change to a transform's
-- code takes effect on whichever branch/environment is considered live", and
-- names "branch-to-environment mapping" as part of the scope. **There are no
-- branches and no environments here**, and 0030's decision doc explains why
-- there never will be a branch: `models.code` is the live definition and
-- `model_runs.model_version` pins every run to the exact row that produced
-- it. So "live" means the project, and the review step gates the write that
-- makes a definition live rather than gating a merge between two refs.
--
-- **A proposal is not a definition.** Its files live here rather than in
-- model_versions, because model_versions is what a run resolves against and
-- must never contain code that nobody approved. Applying a proposal writes
-- the versions - through the same 0030 change set path - and only then does
-- the code exist as a definition. Nothing runs a proposal.
--
-- **Each file records the version it was written against.** Without that,
-- approving a proposal and applying it a week later silently overwrites
-- whatever happened in between: the classic lost update, and one that a
-- reviewer's approval would appear to have blessed. Applying re-checks the
-- base and refuses if the file moved.
--
-- **Editing a proposal invalidates the approvals it already had**, which is
-- why `files_updated_at` exists as a column rather than being derived from
-- the files' own timestamps. Approve-then-swap-the-code is otherwise a way to
-- get arbitrary code past a reviewer who read something else.
--
-- **Nobody approves their own proposal.** Enforced in the service rather than
-- as a CHECK, because the check needs the proposal's author and a constraint
-- cannot reach it - but stated here because it is a rule about the data, not
-- about a screen.
--
-- **Review is off by default** (`projects.require_code_review`). Turning it on
-- for every existing project would break the way every existing project is
-- edited, and a gate nobody chose is a gate people route around.
-- ============================================================================

CREATE TYPE code_proposal_state AS ENUM ('open', 'applied', 'withdrawn');
CREATE TYPE code_review_verdict AS ENUM ('approve', 'request_changes');

ALTER TABLE projects ADD COLUMN require_code_review boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN projects.require_code_review IS
    'When true, a transform''s code can only change by applying an approved '
    'proposal - direct saves from the Models editor and ungated change sets '
    'are refused. Off by default: a gate nobody chose is a gate people route '
    'around.';

CREATE TABLE code_proposals (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    summary          text NOT NULL CHECK (btrim(summary) <> ''),
    description      text NOT NULL DEFAULT '',
    state            code_proposal_state NOT NULL DEFAULT 'open',
    -- What it became. Set exactly when state becomes 'applied', so the review
    -- record and the change set it produced point at each other and neither
    -- has to be inferred from timestamps.
    change_set_id    uuid REFERENCES code_change_sets(id) ON DELETE SET NULL,
    created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    -- Bumped whenever the proposed files change; an approval older than this
    -- is an approval of code that is no longer being proposed.
    files_updated_at timestamptz NOT NULL DEFAULT now(),
    closed_by        uuid REFERENCES users(id) ON DELETE SET NULL,
    closed_at        timestamptz,
    CHECK ((state = 'open') = (closed_at IS NULL)),
    CHECK ((state = 'applied') = (change_set_id IS NOT NULL))
);

CREATE INDEX idx_code_proposals_project
    ON code_proposals (project_id, state, created_at DESC);

CREATE TABLE code_proposal_files (
    proposal_id  uuid NOT NULL REFERENCES code_proposals(id) ON DELETE CASCADE,
    model_id     uuid NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    code         text NOT NULL,
    -- The model version this was written against. Applying re-checks it.
    base_version integer NOT NULL CHECK (base_version > 0),
    PRIMARY KEY (proposal_id, model_id)
);

CREATE TABLE code_proposal_reviews (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id uuid NOT NULL REFERENCES code_proposals(id) ON DELETE CASCADE,
    reviewer_id uuid REFERENCES users(id) ON DELETE SET NULL,
    verdict     code_review_verdict NOT NULL,
    comment     text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_code_proposal_reviews_proposal
    ON code_proposal_reviews (proposal_id, created_at DESC);

-- Reviews are append-only in the same sense every history table here is: a
-- reviewer who changes their mind leaves a second review, so the record shows
-- that they did. Nothing updates or deletes a row.

ALTER TABLE code_proposals ENABLE ROW LEVEL SECURITY;
CREATE POLICY cp_isolation ON code_proposals
    USING (rls_can_access_project(project_id));

ALTER TABLE code_proposal_files ENABLE ROW LEVEL SECURITY;
CREATE POLICY cpf_isolation ON code_proposal_files
    USING (EXISTS (SELECT 1 FROM code_proposals p
                   WHERE p.id = proposal_id
                     AND rls_can_access_project(p.project_id)));

ALTER TABLE code_proposal_reviews ENABLE ROW LEVEL SECURITY;
CREATE POLICY cpr_isolation ON code_proposal_reviews
    USING (EXISTS (SELECT 1 FROM code_proposals p
                   WHERE p.id = proposal_id
                     AND rls_can_access_project(p.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON code_proposals TO platform_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON code_proposal_files TO platform_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON code_proposal_reviews TO platform_app;
