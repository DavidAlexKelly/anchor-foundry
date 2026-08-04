-- ============================================================================
-- 0039_proposals_over_commits.sql
-- A proposal can describe a publish (ROADMAP phase 2, joining 2.5 and 2.7).
--
-- The gap this closes was created by building both halves of Code Repositories
-- correctly and separately. Migration 0031 made proposals a request to change
-- `models`; 0033 made repositories hold commits; 0038 let a commit be published
-- to a model. Nothing joined them, so a project with `require_code_review` on
-- could not publish at all - `transform_publish` refuses, because letting it
-- through would make the gate avoidable by putting the code in a repository
-- first.
--
-- **A commit-backed proposal stores no files.** Its files are *derived* from
-- the commit's declared transforms at read time. That is not a shortcut, it is
-- the stronger property: 0031 keeps `files_updated_at` and invalidates
-- approvals whenever the proposed code changes, because a proposal whose files
-- can be swapped after approval is a way to get arbitrary code past a reviewer.
-- A commit is immutable, so the code under review **cannot** change - and
-- retargeting the proposal at a different commit is a visible edit that bumps
-- `files_updated_at` like any other.
--
-- **What can still change underneath is the live definition**, which is what
-- `code_proposal_files.base_version` guards for a file-backed proposal. A
-- commit-backed one derives the same check from the model's current version at
-- read time, so both kinds refuse to apply over work nobody reviewed.
--
-- **A commit-backed proposal may create transforms that do not exist yet**, and
-- that is why comments needed a second anchor. `code_proposal_comments.model_id`
-- (0036) is NOT NULL, which is right for a change to an existing transform and
-- impossible for a file that will produce a new one. A comment on such a file
-- anchors to its repository path instead - the thing that is stable across the
-- publish, and the thing the reviewer is actually looking at.
-- ============================================================================

ALTER TABLE code_proposals
    ADD COLUMN source_repo_id   uuid REFERENCES code_repos(id) ON DELETE RESTRICT,
    ADD COLUMN source_commit_id uuid REFERENCES code_commits(id) ON DELETE RESTRICT;

-- Both or neither: a commit with no repository cannot be scoped to a project's
-- access rules, and a repository with no commit does not say what to publish.
ALTER TABLE code_proposals
    ADD CONSTRAINT code_proposals_source_is_whole
        CHECK ((source_repo_id IS NULL) = (source_commit_id IS NULL));

-- ON DELETE RESTRICT on both, deliberately. A proposal is a record of what was
-- asked for and what was said about it; one whose commit vanished would be a
-- review of nothing, and `code_commits.parent_id` already takes the same
-- position for the same reason (0033).

CREATE INDEX idx_code_proposals_source
    ON code_proposals (source_repo_id, source_commit_id)
 WHERE source_repo_id IS NOT NULL;

COMMENT ON COLUMN code_proposals.source_commit_id IS
    'The commit this proposal asks to publish (db 0039). When set, the '
    'proposal has no code_proposal_files rows - its files are derived from the '
    'commit''s declared transforms, and applying it publishes rather than '
    'writing a change set.';

-- ----------------------------------------------------------------------------
-- Comments anchor to a model *or* to a path.
--
-- Existing rows all have a model and no path, which is what the CHECK below
-- requires of them, so nothing is migrated.
-- ----------------------------------------------------------------------------
ALTER TABLE code_proposal_comments
    ALTER COLUMN model_id DROP NOT NULL,
    ADD COLUMN source_path text;

ALTER TABLE code_proposal_comments
    ADD CONSTRAINT code_proposal_comments_one_anchor
        CHECK (num_nonnulls(model_id, source_path) = 1);

COMMENT ON COLUMN code_proposal_comments.source_path IS
    'Set instead of model_id when the file this comments on has no model yet - '
    'a commit-backed proposal (db 0039) may create transforms that do not '
    'exist until it is applied.';

-- ----------------------------------------------------------------------------
-- The same, for checks and for "I have read this file".
-- ----------------------------------------------------------------------------
ALTER TABLE code_proposal_checks
    ADD COLUMN source_path text;

COMMENT ON COLUMN code_proposal_checks.source_path IS
    'Which file a check is about when that file has no model yet (db 0039). '
    'model_id stays NULL in that case; a check about the proposal as a whole '
    'has neither.';

-- The one-current-result rule from 0037 has to cover the new key too, or a
-- check on a not-yet-created transform could be inserted any number of times.
ALTER TABLE code_proposal_checks
    DROP CONSTRAINT code_proposal_checks_one_current_result,
    ADD CONSTRAINT code_proposal_checks_one_current_result
        UNIQUE NULLS NOT DISTINCT (proposal_id, model_id, source_path, name);

-- The primary key was (proposal_id, model_id, reviewer_id). It has to go first:
-- a column in a primary key cannot be made nullable, and Postgres says so.
-- Replaced with a unique constraint that treats NULLs as equal, so one reviewer
-- still marks one file once.
ALTER TABLE code_proposal_file_marks
    DROP CONSTRAINT code_proposal_file_marks_pkey;

ALTER TABLE code_proposal_file_marks
    ALTER COLUMN model_id DROP NOT NULL,
    ADD COLUMN source_path text;

ALTER TABLE code_proposal_file_marks
    ADD CONSTRAINT code_proposal_file_marks_one_anchor
        CHECK (num_nonnulls(model_id, source_path) = 1),
    ADD CONSTRAINT code_proposal_file_marks_one_per_reviewer
        UNIQUE NULLS NOT DISTINCT (proposal_id, model_id, source_path, reviewer_id);
