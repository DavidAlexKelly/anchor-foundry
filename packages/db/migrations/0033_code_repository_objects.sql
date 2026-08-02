-- ============================================================================
-- 0033_code_repository_objects.sql
-- Multi-file repositories with branches (ROADMAP.md phase 2, item 2.1).
-- Decided in docs/decisions/0003-repository-storage.md - read that first; the
-- reasoning lives there and is not repeated here.
--
-- Git's data model without git, and without trees: content-addressed blobs,
-- and a commit carrying a flat {path: sha} manifest for the whole snapshot.
-- A repository here is tens of files, so a diff being a dict comparison and a
-- checkout being one join is worth more than the subtree sharing trees buy.
--
-- What must not break: `model_runs.model_version` resolves to exactly one
-- piece of code, forever (migration 0024). Repositories are where code is
-- *authored*; publishing creates a `model_versions` row that copies the source
-- in. The copy is the point - a record of what ran must not change when a
-- branch does.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- code_blobs - file contents, deduplicated by hash within a workspace.
--
-- Keyed by (workspace_id, sha256) rather than by hash alone. A shared blob
-- table would make "does this hash exist?" a cross-tenant question, and
-- existence is information; RLS can only be a visibility backstop if rows
-- belong to a workspace.
-- ----------------------------------------------------------------------------
CREATE TABLE code_blobs (
    workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- Hex SHA-256 of the content. Computed by the API, not the database: the
    -- same function has to run before a write to know whether one is needed.
    sha256        text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    content       text NOT NULL,
    size_bytes    integer NOT NULL CHECK (size_bytes >= 0),
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, sha256)
);

-- ----------------------------------------------------------------------------
-- code_commits - an immutable snapshot of a whole repository.
--
-- `manifest` is {path: sha256} for every file in the snapshot, not a delta.
-- Immutable once written, which is what makes a commit id safe to store on a
-- model version.
-- ----------------------------------------------------------------------------
CREATE TABLE code_commits (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id      uuid NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    -- NULL for the first commit in a repository.
    parent_id    uuid REFERENCES code_commits(id) ON DELETE RESTRICT,
    manifest     jsonb NOT NULL DEFAULT '{}'::jsonb,
    message      text NOT NULL DEFAULT '' CHECK (length(message) <= 4000),
    created_by   uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_code_commits_repo ON code_commits (repo_id, created_at DESC);
CREATE INDEX idx_code_commits_parent ON code_commits (parent_id);

-- ON DELETE RESTRICT on parent_id, deliberately: deleting a commit that
-- something is built on would leave a history with a hole in it, and history
-- with a hole is worse than history that is long.

-- ----------------------------------------------------------------------------
-- code_branches - mutable pointers into an immutable history.
--
-- Fast-forward only; the check lives in the service rather than here, because
-- "is this commit a descendant of that one" is a walk, and a walk in a trigger
-- is a walk nobody can see when it is slow.
-- ----------------------------------------------------------------------------
CREATE TABLE code_branches (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id        uuid NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    name           text NOT NULL
                       CHECK (name ~ '^[a-zA-Z0-9]([a-zA-Z0-9._/-]{0,98}[a-zA-Z0-9])?$'),
    -- NULL on a branch created before its first commit.
    head_commit_id uuid REFERENCES code_commits(id) ON DELETE RESTRICT,
    created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (repo_id, name)
);

CREATE TRIGGER trg_code_branches_updated BEFORE UPDATE ON code_branches
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ----------------------------------------------------------------------------
-- Provenance on a model version: which commit this code was published from.
--
-- Nullable, and stays nullable: every version written before repositories
-- existed has no commit to point at, and back-filling a guess would be a
-- fabricated record. `code` on the version remains the source of truth for
-- what ran - this only answers "where did it come from".
-- ----------------------------------------------------------------------------
ALTER TABLE model_versions
    ADD COLUMN source_commit_id uuid REFERENCES code_commits(id) ON DELETE RESTRICT,
    ADD COLUMN source_path text;

COMMENT ON COLUMN model_versions.source_commit_id IS
    'Commit this version was published from (db 0033). ON DELETE RESTRICT: a '
    'version whose commit vanished would be a record that changed after the fact.';

-- ----------------------------------------------------------------------------
-- RLS. Commits and branches reach their project through code_repos; blobs are
-- workspace-scoped directly.
-- ----------------------------------------------------------------------------
ALTER TABLE code_blobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY code_blob_isolation ON code_blobs
    USING (rls_can_access_workspace(workspace_id));

ALTER TABLE code_commits ENABLE ROW LEVEL SECURITY;
CREATE POLICY code_commit_isolation ON code_commits
    USING (EXISTS (SELECT 1 FROM code_repos r
                    WHERE r.id = repo_id AND rls_can_access_project(r.project_id)));

ALTER TABLE code_branches ENABLE ROW LEVEL SECURITY;
CREATE POLICY code_branch_isolation ON code_branches
    USING (EXISTS (SELECT 1 FROM code_repos r
                    WHERE r.id = repo_id AND rls_can_access_project(r.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON code_blobs TO platform_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON code_commits TO platform_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON code_branches TO platform_app;
