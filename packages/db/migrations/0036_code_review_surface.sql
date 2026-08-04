-- ============================================================================
-- 0036_code_review_surface.sql
-- Line-anchored comments and per-file resolution (ROADMAP phase 2, item 2.7).
--
-- Migration 0031 built the governance half of code review: proposals, reviews,
-- blockers, and a gate. What it has no room for is the conversation - a
-- reviewer who wants to say "this join is wrong" about *line 14* has nowhere
-- to put it but the single `comment` on their verdict, which is a review of
-- the whole proposal.
--
-- Two tables, and one rule shared between them.
--
-- **The rule: editing a proposal invalidates what was said about it.** 0031
-- already applies this to approvals, through `code_proposals.files_updated_at`
-- - an approval older than the last edit approved something else. A line
-- anchor is the same claim in a sharper form: line 14 of the code somebody
-- read is not line 14 of the code somebody else will apply. So both tables
-- record the `files_updated_at` they were written against, and both derive
-- staleness by comparing rather than by being reset. Deriving beats resetting
-- here for the reason it usually does: a reset is a write that can be missed,
-- and a comparison cannot be.
--
-- **A stale comment is shown, not hidden.** It said something true about the
-- code it was written against, and hiding it would lose the reason a change
-- was made. It is marked instead, which is what "outdated" means everywhere
-- else this pattern appears.
-- ============================================================================

-- Which side of the diff a comment hangs on. The diff a reviewer reads is
-- live-vs-proposed (services/code.py's `get_proposal`), so these are its two
-- columns and not "old"/"new" in the abstract.
CREATE TYPE code_comment_side AS ENUM ('live', 'proposed');

-- ----------------------------------------------------------------------------
-- code_proposal_comments - a remark about one line of one file.
--
-- `model_id` rather than a path: paths are derived from model names
-- (services/code.py's `file_path`), so a rename would silently re-anchor every
-- comment on the file to whatever now holds that name.
-- ----------------------------------------------------------------------------
CREATE TABLE code_proposal_comments (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id  uuid NOT NULL REFERENCES code_proposals(id) ON DELETE CASCADE,
    model_id     uuid NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    side         code_comment_side NOT NULL,
    -- 1-based, into that side's full text. NULL is a remark about the file as
    -- a whole, which is a real thing to want and is not the same as line 1.
    line         integer CHECK (line IS NULL OR line > 0),
    body         text NOT NULL CHECK (btrim(body) <> ''),
    author_id    uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    -- The proposal's `files_updated_at` when this was written. A comment whose
    -- anchor predates the current one points at a line that has since moved.
    anchored_at  timestamptz NOT NULL,
    -- Resolution is per comment and never undone by an edit: a thread somebody
    -- marked settled stays settled, because unsettling it silently would put
    -- the conversation back without anybody saying anything.
    resolved_at  timestamptz,
    resolved_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    CHECK ((resolved_at IS NULL) = (resolved_by IS NULL))
);

CREATE INDEX idx_code_proposal_comments_proposal
    ON code_proposal_comments (proposal_id, model_id, line);

COMMENT ON COLUMN code_proposal_comments.anchored_at IS
    'The proposal files_updated_at this was written against (db 0036). A '
    'comment older than the current one is outdated: its line number refers '
    'to code that has since changed. Shown and marked, never hidden.';

-- ----------------------------------------------------------------------------
-- code_proposal_file_marks - "I have read this file".
--
-- One row per reviewer per file, and the same staleness rule: a mark made
-- before the last edit says somebody read a file that no longer exists in that
-- form. Upserted rather than toggled with a delete, so re-marking after an
-- edit is one statement.
-- ----------------------------------------------------------------------------
CREATE TABLE code_proposal_file_marks (
    proposal_id uuid NOT NULL REFERENCES code_proposals(id) ON DELETE CASCADE,
    model_id    uuid NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    reviewer_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    marked_at   timestamptz NOT NULL DEFAULT now(),
    -- Same derivation as above, and the reason this is not just `marked_at`:
    -- clock skew between the mark and the edit would otherwise decide whether
    -- a file counts as read.
    anchored_at timestamptz NOT NULL,
    PRIMARY KEY (proposal_id, model_id, reviewer_id)
);

-- ----------------------------------------------------------------------------
-- RLS. Both reach their project through code_proposals, the same way
-- code_proposal_files and code_proposal_reviews do (0031).
-- ----------------------------------------------------------------------------
ALTER TABLE code_proposal_comments ENABLE ROW LEVEL SECURITY;
CREATE POLICY cpc_isolation ON code_proposal_comments
    USING (EXISTS (SELECT 1 FROM code_proposals p
                   WHERE p.id = proposal_id
                     AND rls_can_access_project(p.project_id)));

ALTER TABLE code_proposal_file_marks ENABLE ROW LEVEL SECURITY;
CREATE POLICY cpfm_isolation ON code_proposal_file_marks
    USING (EXISTS (SELECT 1 FROM code_proposals p
                   WHERE p.id = proposal_id
                     AND rls_can_access_project(p.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON code_proposal_comments TO platform_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON code_proposal_file_marks TO platform_app;
