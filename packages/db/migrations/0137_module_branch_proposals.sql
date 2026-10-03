-- ============================================================================
-- 0137 — protected modules and branch proposals (§700; Foundry `workshop`
-- p.617-618)
-- ============================================================================
--
-- > "When on the main branch, protected Workshop modules show a Save to new
-- > branch option instead of Save and publish, requiring all changes to be
-- > made on a branch rather than directly to main." (p.617)
-- > "When you are ready to merge your changes to main, create a proposal."
-- > "After a proposal is created, assigned reviewers are notified to review
-- > the changes … Reviewers can then approve or reject the change by
-- > selecting the appropriate Approve or Reject button" (p.618)
--
-- **`protected` is on the module**, because p.617 protects a module, not a
-- branch: main is what nobody may write to directly. The API refuses a save
-- or a revert to a protected module's main, and its merge needs an approved
-- proposal.
--
-- **A proposal is a state of its branch**, not a resource beside it: one
-- branch is one set of changes and has at most one review in flight, and the
-- review is of the branch's document *as it is now*. So a save to a branch
-- whose proposal was approved sends it back to `open` - the approval was of a
-- document that no longer exists, and keeping it would let a reviewed change
-- carry an unreviewed one onto a protected main.
--
-- **Who saved last is kept** so the API can refuse an approval from the person
-- whose changes are being approved. p.618's "assigned reviewers" are the
-- module's other editors here: there is no per-proposal assignment, and the
-- one rule that has to hold without it is that nobody reviews their own work.
-- ============================================================================

ALTER TABLE canvas_apps
    ADD COLUMN protected boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN canvas_apps.protected IS
    'p.617: main is changed only by merging a branch whose proposal was approved.';

CREATE TYPE branch_proposal_status AS ENUM ('open', 'approved', 'rejected');

ALTER TABLE canvas_app_branches
    ADD COLUMN proposal_status branch_proposal_status,
    ADD COLUMN proposed_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN proposed_at     timestamptz,
    ADD COLUMN reviewed_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN reviewed_at     timestamptz,
    ADD COLUMN last_saved_by   uuid REFERENCES users(id) ON DELETE SET NULL;

COMMENT ON COLUMN canvas_app_branches.proposal_status IS
    'p.618: NULL is no proposal; a save after a review sends it back to open.';

-- The branch's creator saved it first, so they are its last saver until
-- somebody else saves it.
UPDATE canvas_app_branches SET last_saved_by = created_by WHERE last_saved_by IS NULL;
