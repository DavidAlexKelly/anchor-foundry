-- ============================================================================
-- 0091_file_verdicts.sql
-- A verdict per file, not just a mark (§366; `code-repositories` p.55).
--
-- > "To keep track of your progress while reviewing the changes in a pull
-- >  request, you can approve or reject each file individually." (p.55)
--
-- **This is a column, not a table, and finding that out is the whole of the
-- §216 check.** `code-repositories.md` marks per-file approve/reject as ○,
-- which overstates it: db 0036 already gives every reviewer a per-file mark,
-- and — the part that is hard to get right — anchors it to the proposal's
-- `files_updated_at`, so editing a file unreads it for everybody who had read
-- it. A second per-file table beside that one would be §191's hazard: two
-- places recording what a reviewer thinks of a file, disagreeing the first
-- time one of them forgets the anchor.
--
-- **Nullable, and an existing mark stays a mark.** A backfill setting every
-- "I have read this" to 'approved' would invent approvals nobody gave, on the
-- one surface where an invented approval is worst. So a row with no verdict
-- keeps meaning exactly what it meant.
--
-- **Four states where Foundry documents three**, deliberately: not looked at,
-- looked at, approved, rejected. "I have read this and I am not sure yet" is a
-- real position on a large diff and is what the existing button already means;
-- collapsing it into 'approved' would be a regression wearing parity's badge.
--
-- The anchor carries this for free, and that is the reason to extend rather
-- than add: a verdict given before an edit is a verdict about code that is no
-- longer proposed, and `_file_marks` already drops marks whose `anchored_at`
-- is older than the proposal's.
-- ============================================================================

CREATE TYPE code_file_verdict AS ENUM ('approved', 'rejected');

ALTER TABLE code_proposal_file_marks
    ADD COLUMN verdict code_file_verdict;

COMMENT ON COLUMN code_proposal_file_marks.verdict IS
    'p.55''s per-file approve/reject (db 0091). NULL means the file was read '
    'and no verdict given, which is what every mark meant before this column '
    'existed - never backfilled, because an invented approval is the worst '
    'kind to invent.';
