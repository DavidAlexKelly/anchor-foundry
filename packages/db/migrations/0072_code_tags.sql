-- 0072 — Tags (§299; `code-repositories.md` §3, p.17)
--
--   "The branches tab also lets you access a list of tags, which are like
--    immutable branches. A tag can be used to mark a significant version of
--    the code for future reference by giving it a version number or name. To
--    create a new tag, navigate to the tags section of the branches tab and
--    click the 'New Tag' button. A tag can be created from the current version
--    of a branch, or from any arbitrary commit." (p.17)
--
-- **"Like immutable branches" is the whole design, and the word that matters is
-- *immutable*.** A branch is a name whose commit moves; a tag is a name whose
-- commit does not. That is the entire difference, and it is enforced here
-- rather than in a service, because a rule that lives only in a service is a
-- rule the next writer of an UPDATE does not meet.
--
-- So there is no `head_commit_id` that a `SET` could move. `commit_id` is
-- written once and the trigger below refuses to change it. Deleting a tag is
-- allowed - a mistyped name has to be removable, and Foundry's own advice about
-- branches ("you should not delete any branches that you did not create") is
-- about lost work, which a tag cannot cause: it holds no work of its own.

CREATE TABLE code_tags (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id     uuid NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,

    -- p.17: "giving it a version number or name". The shape rules are the
    -- repository's own (`repoSettings.json`'s `tagNameValidation`, read at
    -- creation time); this is only the floor no repository may go below,
    -- because a name is part of a URL and part of a filesystem-shaped path.
    name        text NOT NULL CHECK (
                    length(name) BETWEEN 1 AND 100
                    AND name ~ '^[A-Za-z0-9][A-Za-z0-9._+-]*$'
                ),

    -- **ON DELETE RESTRICT, and this is what "immutable" costs.** A tag marks a
    -- significant version *for future reference*, so a commit somebody tagged
    -- cannot quietly go: the tag would then name nothing, which is worse than
    -- refusing the delete because it fails later and somewhere else.
    -- `code_commits.parent_id` and `code_proposals.source_commit_id` take the
    -- same position (0033, 0039).
    commit_id   uuid NOT NULL REFERENCES code_commits(id) ON DELETE RESTRICT,

    -- p.17 does not mention a message and Foundry's own tag dialog has none.
    -- Kept anyway, and nullable: "1.4.0" says what it is and not why, and the
    -- one moment somebody knows why is the moment they type it.
    message     text CHECK (message IS NULL OR length(message) <= 1000),

    created_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),

    -- One name per repository. Two tags called `1.4.0` pointing at different
    -- commits is the state that makes a tag worthless: whoever reads one has no
    -- way to know which they got.
    UNIQUE (repo_id, name)
);

CREATE INDEX idx_code_tags_repo ON code_tags (repo_id, created_at DESC);
CREATE INDEX idx_code_tags_commit ON code_tags (commit_id);

-- **Immutability, enforced where an UPDATE has to pass.**
--
-- Not a rule in a service: `services/repositories.py` could refuse to move a
-- tag and the next person to write an UPDATE - a migration, a repair script, a
-- feature nobody has thought of - would not meet that refusal. A tag whose
-- commit moved would be a lie told to whoever tagged it, discovered whenever
-- they next resolved it, which may be a year later.
--
-- The name is fixed too: renaming a tag and creating a new one are the same act
-- from every reader's point of view, except that renaming silently breaks the
-- references that already exist. `message` may be corrected, because a sentence
-- about why is not what anything resolves.
CREATE FUNCTION code_tags_are_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.commit_id IS DISTINCT FROM OLD.commit_id THEN
        RAISE EXCEPTION
            'a tag is immutable: % points at %, and moving it would break every '
            'reference already taken. Delete it and make a new one if that is '
            'what you mean.', OLD.name, OLD.commit_id;
    END IF;
    IF NEW.name IS DISTINCT FROM OLD.name THEN
        RAISE EXCEPTION
            'a tag cannot be renamed: % is how it is referred to. Delete it and '
            'make a new one.', OLD.name;
    END IF;
    IF NEW.repo_id IS DISTINCT FROM OLD.repo_id THEN
        RAISE EXCEPTION 'a tag belongs to the repository it was made in';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_code_tags_immutable BEFORE UPDATE ON code_tags
    FOR EACH ROW EXECUTE FUNCTION code_tags_are_immutable();

ALTER TABLE code_tags ENABLE ROW LEVEL SECURITY;
CREATE POLICY ctag_isolation ON code_tags
    USING (EXISTS (SELECT 1 FROM code_repos r
                   WHERE r.id = repo_id
                     AND rls_can_access_project(r.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON code_tags TO platform_app;

COMMENT ON TABLE code_tags IS
    'A name pinned to a commit that never moves (db 0072; p.17 "like immutable '
    'branches"). The immutability is a trigger rather than a service rule, '
    'because a rule in a service is one the next writer of an UPDATE does not '
    'meet.';
