-- ============================================================================
-- 0089_saved_graphs.sql
-- Save and share a lineage graph (§360; `data-lineage` p.12).
--
-- > "You can save and share your lineage graph with other Foundry users in the
-- >  following ways: **Save / Open**: Save your Data Lineage graph and re-open
-- >  it by clicking on Open graph. **Get quick share link**: Generates a
-- >  shareable link that provides read-only access to your graph." (p.12)
--
-- **This follows db 0040 rather than inventing a second convention**, and the
-- §191 check is what found it: saved searches already answered most of these
-- questions for a different resource, and a platform where two saved things
-- behave differently is one a reader has to learn twice.
--
-- **A saved graph stores the view, never the nodes.** 0040's sentence about
-- saved searches is the same sentence here: "a saved search stores a
-- definition, never results", because the question is live and the answer is
-- different tomorrow. A graph that stored its nodes would be a screenshot with
-- a date on it, and the first person to notice would be the one who trusted
-- it. §355 settled that this platform draws the whole project anyway, so there
-- is no node list to store even if it were wanted - what a person chooses is
-- the *view*: which node is focused, which column is highlighted, which nodes
-- are selected, what was searched for.
--
-- **Project-scoped, where 0040 is workspace-scoped**, and the difference has a
-- reason rather than being a copy error: object types are workspace-wide (db
-- 0003), so a search across them is too; a lineage graph is over datasets and
-- models, which are project-scoped, so a graph saved against a workspace would
-- name resources half of it cannot see.
--
-- **Shared within its scope, not private to its author**, which is 0040's
-- decision and its reason: "one that only its author can see gets reinvented
-- slightly differently by everyone else." Read access is RLS's, exactly as it
-- is for every other project resource - which is also what p.12's "read-only
-- access" honestly translates to here. A link that *widened* access would be a
-- new sharing mechanism and a security decision, not a convenience.
--
-- **`jsonb`, not a column per parameter**, for 0040's reason, which this
-- resource has already proven: the graph's view grew three times in one
-- session - §353 added a highlighted column, §354 a selection, §356 a search
-- and a kind filter. A column apiece would have made each of those a
-- migration.
--
-- **One name per project.** 0040 again: "two searches called 'Active vessels'
-- that differ is the thing sharing them exists to prevent."
-- ============================================================================

CREATE TABLE saved_graphs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        text NOT NULL CHECK (btrim(name) <> '' AND length(name) <= 200),
    description text NOT NULL DEFAULT '',
    -- {focus, column, selected, query, kinds} - the graph's own view
    -- parameters and nothing else. No zoom or pan: where a viewport happened
    -- to be is not what somebody means by "look at this", and a recipient
    -- whose window is a different size lands somewhere else anyway, which is a
    -- control that looks like it works (§214).
    view        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

CREATE INDEX idx_saved_graphs_project ON saved_graphs (project_id, name);

CREATE TRIGGER trg_saved_graphs_updated BEFORE UPDATE ON saved_graphs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN saved_graphs.view IS
    'The graph view this reopens (db 0089): focus, column, selected, query, '
    'kinds. Never the nodes - a lineage graph is a live question, and a saved '
    'list of nodes would be a screenshot with a date on it.';

-- No foreign key from `view`'s ids to datasets or models, for db 0040's
-- reason: jsonb cannot carry one, and the fallback - a join table kept in step
-- by application code - would be a second place for the view to live. A saved
-- graph naming a dataset that has since been deleted opens with that node
-- missing, which is more useful than refusing to open it or quietly rewriting
-- what somebody saved.

ALTER TABLE saved_graphs ENABLE ROW LEVEL SECURITY;
CREATE POLICY saved_graph_isolation ON saved_graphs
    USING (rls_can_access_project(project_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON saved_graphs TO platform_app;
