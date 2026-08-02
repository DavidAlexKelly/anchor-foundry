-- ============================================================================
-- 0030_code_change_sets.sql
-- Let one edit span several transforms (ROADMAP Code item 2).
--
-- `docs/decisions/0001-where-code-lives.md` settled that the Code pillar is a
-- surface over `model_versions` rather than a second store, because a run is
-- pinned to the exact definition that produced it (0024) and a git ref cannot
-- promise that. What survived that decision as genuinely missing is the
-- *change set*: today a save writes one version row per model, so "these
-- three transforms changed together, for one reason" cannot be said. A commit
-- message with no commit to attach it to is the gap this table fills.
--
-- **A change set groups versions; it does not contain code.** The code stays
-- in model_versions, which is still where a run resolves. Removing the group
-- would not lose a line of source - it would only lose the knowledge that
-- three edits were one intention, which is exactly the sort of thing that
-- belongs in its own table rather than duplicated into each row.
--
-- **Membership is nullable, and stays that way.** Every version written
-- before this migration has no change set, and every save from the inline
-- Models editor still writes one without a change set. Backfilling a
-- synthetic single-model change set onto those would be inventing an
-- intention nobody expressed - the same reason 0024 refused to point
-- pre-migration runs at a backfilled v1. History therefore reads as a
-- timeline of two kinds of entry, which is the truth about how this codebase
-- got edited.
--
-- **Nothing deletes a change set.** There is no delete endpoint, by design: a
-- record of what happened must not change when somebody tidies up. The FK is
-- ON DELETE SET NULL only so that dropping a whole project cannot deadlock on
-- cascade ordering between this table and model_versions - not as a licence
-- to remove one.
-- ============================================================================

CREATE TABLE code_change_sets (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    -- The commit message. Required and non-empty: a change set exists to say
    -- why several edits belong together, and an unlabelled one says nothing
    -- the individual versions did not already say.
    summary     text NOT NULL CHECK (btrim(summary) <> ''),
    description text NOT NULL DEFAULT '',
    created_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_code_change_sets_project
    ON code_change_sets (project_id, created_at DESC);

-- RLS in the shape 0006 gives every project-scoped table: resolved through
-- the rls_can_access_project SECURITY DEFINER helper rather than a subselect
-- against `projects`, which is itself RLS-protected and can legitimately hide
-- the row a policy needs (the 0008/0009/0015 bug class).
ALTER TABLE code_change_sets ENABLE ROW LEVEL SECURITY;
CREATE POLICY ccs_isolation ON code_change_sets
    USING (rls_can_access_project(project_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON code_change_sets TO platform_app;

ALTER TABLE model_versions ADD COLUMN change_set_id uuid
    REFERENCES code_change_sets(id) ON DELETE SET NULL;

CREATE INDEX idx_model_versions_change_set
    ON model_versions (change_set_id) WHERE change_set_id IS NOT NULL;

COMMENT ON COLUMN model_versions.change_set_id IS
    'The multi-model edit this version was part of, or NULL for a standalone '
    'save - including every version written before migration 0030. NULL means '
    '"not part of one", never "unknown".';
