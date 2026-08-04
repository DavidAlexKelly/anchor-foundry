-- ============================================================================
-- 0038_repository_authored_models.sql
-- A model can be authored in a repository (ROADMAP phase 2, item 2.5).
--
-- Migration 0033 built repositories and said what they were for:
--
--   "Repositories are where code is *authored*; publishing creates a
--    `model_versions` row that copies the source in. The copy is the point - a
--    record of what ran must not change when a branch does."
--
-- It added `model_versions.source_commit_id` and `source_path` to record that,
-- and then nothing wrote them, because there was no publish. This is the
-- publish, and it needs one thing 0033 did not give it: a *stable identity* for
-- "the model this file publishes to".
--
-- **Identity is (repository, path), not the model's name.** A file renamed
-- would otherwise publish to a second model and leave the first one running
-- forever; a model renamed would be silently adopted by whatever file next
-- claimed the name. Neither is recoverable by looking at the data afterwards.
--
-- **A model authored in a repository cannot be edited directly**, and the
-- refusal is in `models.update` rather than here, beside the review gate, for
-- the reason written there: that is the function which makes a definition live,
-- and the Models editor and the Code surface are two doors into it. The
-- alternative is worse than it first looks - a direct edit is not merely
-- overwritten by the next publish, it makes the repository *lie* about what
-- runs until that publish happens, and lineage read from the repository would
-- describe a pipeline that is not the one executing.
--
-- Both columns stay NULL for every model authored the way models have always
-- been authored. Nothing is migrated, because there is nothing to migrate: no
-- model has ever come from a repository.
-- ============================================================================

ALTER TABLE models
    ADD COLUMN source_repo_id uuid REFERENCES code_repos(id) ON DELETE SET NULL,
    ADD COLUMN source_path text;

-- Both or neither. A path with no repository cannot be resolved, and a
-- repository with no path does not say which file.
ALTER TABLE models
    ADD CONSTRAINT models_source_is_whole
        CHECK ((source_repo_id IS NULL) = (source_path IS NULL));

-- One file publishes to one model. Partial, so the unlimited number of models
-- with no repository at all are unaffected.
CREATE UNIQUE INDEX idx_models_source_file
    ON models (source_repo_id, source_path)
 WHERE source_repo_id IS NOT NULL;

COMMENT ON COLUMN models.source_repo_id IS
    'The repository this transform is authored in (db 0038). NULL means it is '
    'authored directly, the way every model was before repositories. A model '
    'with a source repository refuses direct edits: an edit that the next '
    'publish overwrites is bad, and one it does not is worse - the repository '
    'would describe a pipeline that is not the one running.';

COMMENT ON COLUMN models.source_path IS
    'Repository-relative path of the file this transform is published from '
    '(db 0038). Identity is (repo, path) rather than the model name, so a '
    'rename on either side cannot silently adopt or abandon a definition.';
