-- ============================================================================
-- 0040_saved_searches.sql
-- Saved searches for the Object Explorer (ROADMAP phase 2, item 4.1).
--
-- The explorer itself has existed since `STATUS.md` §32 and needs no schema.
-- The one thing item 4.1 names that does not exist is saving a search, and it
-- needs a table because the alternative - keeping it in the URL and asking
-- people to bookmark it - is not sharing, it is filing.
--
-- **A saved search stores a definition, never results.** That is the whole
-- point of saving one: "vessels flagged NO" is a question, and the answer is
-- different tomorrow. Storing rows would turn a live question into a stale
-- report, and the first person to notice would be the one who trusted it.
--
-- **Workspace-scoped, and shared within it.** Object types are workspace-wide
-- (db 0003), so a search across them is too - one scoped to a project would
-- search an ontology it could only half see. Shared rather than private for
-- the reason Foundry shares them: a saved search is usually a *definition of a
-- cohort* that a team argues about, and one that only its author can see gets
-- reinvented slightly differently by everyone else.
--
-- **The definition is validated when it is saved**, by the same function the
-- explorer route uses (`services/object_searches.parse`). A search that cannot
-- run is refused at save time rather than at open time - otherwise the person
-- who finds out is not the person who made the mistake.
-- ============================================================================

CREATE TABLE object_searches (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         text NOT NULL CHECK (btrim(name) <> '' AND length(name) <= 200),
    description  text NOT NULL DEFAULT '',
    -- {q, type_ids, property, value} - the explorer's own parameters, and
    -- nothing else. jsonb rather than columns because the explorer's parameter
    -- set is application knowledge that has already grown once (property/value
    -- arrived with Canvas item 3) and would grow again; a column per parameter
    -- makes every such addition a migration.
    definition   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by   uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    -- One name per workspace: two searches called "Active vessels" that differ
    -- is the thing sharing them exists to prevent.
    UNIQUE (workspace_id, name)
);

CREATE INDEX idx_object_searches_workspace ON object_searches (workspace_id, name);

CREATE TRIGGER trg_object_searches_updated BEFORE UPDATE ON object_searches
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN object_searches.definition IS
    'The explorer parameters this search runs (db 0040): q, type_ids, '
    'property, value. Never results - a saved search is a question, and the '
    'answer is different tomorrow.';

-- No foreign key from `definition`'s type_ids to object_types, and that is a
-- decision rather than an omission: jsonb cannot carry one, and the fallback -
-- a join table kept in step by application code - would be a second place for
-- the definition to live. A search naming a type that has since been deleted
-- is reported as such when it is read, which is more useful than either
-- cascading it away or refusing to open it.

ALTER TABLE object_searches ENABLE ROW LEVEL SECURITY;
CREATE POLICY object_search_isolation ON object_searches
    USING (rls_can_access_workspace(workspace_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON object_searches TO platform_app;
