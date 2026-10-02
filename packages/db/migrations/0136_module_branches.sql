-- ============================================================================
-- 0136 — module branches (§698; Foundry `workshop` p.193, p.617-620)
-- ============================================================================
--
-- > "When developing on a branch, you may need to rebase before merging your
-- > Workshop changes into main if main has changed since your last save.
-- > Rebasing applies your branch's changes to the latest main version of the
-- > module and surfaces any merge conflicts that must be resolved." (p.193)
--
-- **A branch is a second head of one module**, not a copy of it: the same
-- `canvas_apps` row, the same id, the same published version, and a document
-- of its own that main's viewers never see. `canvas_apps.definition` stays
-- main's head, so nothing that reads a module today changes.
--
-- **`base_version` is what makes "rebase required" a fact rather than a
-- guess.** It is the main version the branch was taken from (or last rebased
-- onto). Main having saved past it is p.193's "if main has changed since your
-- last save", and it is also the common ancestor a rebase merges against -
-- `canvas_app_versions` already keeps that version's document, so a branch
-- needs to store only the number.
--
-- **Named, and unique per module**, because p.618's dialog is "Name the
-- branch" and a branch selector lists names. `main` is refused here rather
-- than in the API alone: it is the name of the other head, and a branch
-- called `main` would make every "merge into main" ambiguous.
--
-- **A merged branch is deleted, not kept.** Its changes become a main
-- version with a description naming it (the same generated-description rule
-- p.192 gives a revert), which is the record; a branch row kept after its
-- merge would be a second head that can no longer be merged.
--
-- Visible to whoever can see the module's project, as its versions are (0006,
-- 0061): a branch is a draft of the module, so it has the module's audience
-- for drafts - its project - and never the published audience.
-- ============================================================================

CREATE TABLE canvas_app_branches (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canvas_app_id  uuid NOT NULL REFERENCES canvas_apps(id) ON DELETE CASCADE,
    name           text NOT NULL
                       CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$')
                       CHECK (lower(name) <> 'main'),
    definition     jsonb NOT NULL,
    base_version   integer NOT NULL CHECK (base_version >= 0),
    -- How many times the branch has been saved, so a reader can tell "taken
    -- from main and never touched" from "worked on".
    save_count     integer NOT NULL DEFAULT 0 CHECK (save_count >= 0),
    created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (canvas_app_id, name)
);

CREATE INDEX idx_canvas_app_branches_app ON canvas_app_branches (canvas_app_id);
CREATE TRIGGER trg_canvas_app_branches_updated BEFORE UPDATE ON canvas_app_branches
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN canvas_app_branches.base_version IS
    'The main version this branch was taken from or last rebased onto (p.193). '
    'Main past it means a rebase is required before merging.';

ALTER TABLE canvas_app_branches ENABLE ROW LEVEL SECURITY;
CREATE POLICY canvas_app_branches_isolation ON canvas_app_branches
    USING (EXISTS (SELECT 1 FROM canvas_apps a
                    WHERE a.id = canvas_app_branches.canvas_app_id
                      AND rls_can_access_project(a.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON canvas_app_branches TO platform_app;
