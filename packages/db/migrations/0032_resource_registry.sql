-- ============================================================================
-- 0032_resource_registry.sql
-- One table that knows every resource in the platform (ROADMAP.md phase 2,
-- section 0 item 1).
--
-- Why this exists
-- ---------------
-- Foundry's unit of navigation is the *resource*: a project is a folder of
-- them, and every one opens its own full-screen application. That requires a
-- question this schema could not answer - "what is in this project?" -
-- because resources live in six unrelated tables with nothing in common but a
-- convention. `resource_counts` on the project endpoint is six separate
-- COUNT(*)s, which is the shape of a missing table.
--
-- What this is, and is not
-- ------------------------
-- A *registry*, not a rewrite. `datasets` still owns everything true of a
-- dataset and nothing else. This table owns only what is true of every
-- resource regardless of kind: identity, where it lives, what it is called,
-- and whether it still exists. The alternative - one table with a jsonb blob
-- per kind - would trade six verified schemas for one unverifiable one, and
-- the schema tests that have caught real bugs would have nothing left to
-- check.
--
-- Two kinds do not live in a project, and the registry says so
-- -----------------------------------------------------------
-- `object_types` are workspace-wide - they have no project_id column at all,
-- which is what made the first-run checklist tick a step in an empty project
-- (STATUS.md §44). `connections` are workspace-wide when scope = 'workspace'.
-- So project_id is nullable here and means what it says: NULL is a resource
-- that belongs to the workspace, not a resource whose project is unknown.
-- Forcing every kind into a project would have made the registry lie about
-- two of them on day one.
--
-- The name is mirrored, not owned
-- -------------------------------
-- Each kind table remains the source of truth for its own name; triggers copy
-- it here on insert and update. The registry needs the name sortable and
-- searchable in one indexed place - a six-way UNION would defeat the point of
-- the table - but two writable copies of a name is a guarantee of drift, so
-- there is only ever one writer.
--
-- Registration is structural, not a convention
-- --------------------------------------------
-- The BEFORE INSERT trigger creates the registry row and fills in
-- resource_id. Nothing in the API has to remember to register anything, and no
-- resource can exist unregistered by someone forgetting a step. Partial
-- adoption of a registry is worse than none: the browser would be confidently
-- incomplete.
-- ============================================================================

CREATE TYPE resource_kind AS ENUM (
    'connection',
    'dataset',
    'model',
    'object_type',
    'canvas_app',
    'code_repo'
);

-- 'canvas_app' rather than 'workshop_module' on purpose: the kind names the
-- table that exists today. Renaming it belongs to the format migration that
-- changes what a canvas app *is* (ROADMAP.md section 1 item 8), not to a
-- change about identity.

CREATE TABLE resources (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- NULL = a workspace-level resource (object types, workspace-scoped
    -- connections). See the header.
    project_id    uuid REFERENCES projects(id) ON DELETE CASCADE,
    kind          resource_kind NOT NULL,
    -- Mirrored from the kind table by trigger. Never written directly.
    name          text NOT NULL DEFAULT '',
    description   text NOT NULL DEFAULT '',
    created_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    -- Reserved for the trash/restore flow. Nothing sets it yet; the browser
    -- filters on it from the start so adding that flow later is not also a
    -- change to every query that lists resources.
    trashed_at    timestamptz
);

CREATE INDEX idx_resources_workspace ON resources (workspace_id);
CREATE INDEX idx_resources_kind ON resources (workspace_id, kind);
-- The browser's default sort, and the query that runs on every project open.
-- Partial so trashed rows do not sit in the middle of the index.
CREATE INDEX idx_resources_recent ON resources (project_id, updated_at DESC)
    WHERE trashed_at IS NULL;
-- Case-insensitive search on name.
CREATE INDEX idx_resources_name ON resources (workspace_id, lower(name));

CREATE TRIGGER trg_resources_updated BEFORE UPDATE ON resources
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ----------------------------------------------------------------------------
-- Registration triggers.
--
-- One function for all six kinds. It reads the row generically through
-- to_jsonb rather than naming columns, because the six tables disagree about
-- which columns they have - object_types calls its name `display_name`,
-- connections has no description, models have no workspace_id - and six
-- near-identical functions would drift the moment one kind gained a column.
-- ----------------------------------------------------------------------------
CREATE FUNCTION register_resource() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_row      jsonb := to_jsonb(NEW);
    v_kind     resource_kind := TG_ARGV[0]::resource_kind;
    v_name     text;
    v_desc     text;
    v_project  uuid;
    v_ws       uuid;
    v_id       uuid;
BEGIN
    v_name := COALESCE(v_row->>'name', v_row->>'display_name', '');
    v_desc := COALESCE(v_row->>'description', '');
    v_project := NULLIF(v_row->>'project_id', '')::uuid;
    v_ws := NULLIF(v_row->>'workspace_id', '')::uuid;

    -- models, canvas_apps and code_repos carry only a project; derive their
    -- workspace the way the rest of the schema does.
    IF v_ws IS NULL AND v_project IS NOT NULL THEN
        SELECT workspace_id INTO v_ws FROM projects WHERE id = v_project;
    END IF;
    IF v_ws IS NULL THEN
        RAISE EXCEPTION 'cannot register a % without a workspace', v_kind;
    END IF;

    IF TG_OP = 'INSERT' THEN
        INSERT INTO resources (workspace_id, project_id, kind, name, description, created_by)
        VALUES (v_ws, v_project, v_kind, v_name, v_desc,
                NULLIF(v_row->>'created_by', '')::uuid)
        RETURNING id INTO v_id;
        NEW.resource_id := v_id;
        RETURN NEW;
    END IF;

    -- UPDATE: keep the mirror honest, including a move between projects. The
    -- IS DISTINCT FROM guard means an unrelated column change does not churn
    -- the registry's updated_at, which the browser sorts on.
    UPDATE resources
       SET name = v_name, description = v_desc,
           project_id = v_project, workspace_id = v_ws
     WHERE id = NEW.resource_id
       AND (name, description, project_id, workspace_id)
           IS DISTINCT FROM (v_name, v_desc, v_project, v_ws);
    RETURN NEW;
END;
$$;

-- Deleting the kind row retires the registry row. The FK added below covers
-- the other direction (deleting the resource cascades to the kind row), so the
-- two can never disagree about whether something exists.
CREATE FUNCTION unregister_resource() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM resources WHERE id = OLD.resource_id;
    RETURN OLD;
END;
$$;

-- ----------------------------------------------------------------------------
-- Wire up the six kinds.
--
-- The backfill is in this migration rather than in a follow-up script because
-- a half-registered database is the one state that must not exist. Each kind
-- gets the same four steps, written out rather than looped: the id is
-- generated on the *source* side first, so correlating the registry row back
-- to the row it describes is a plain column comparison instead of a clever
-- one that has to be trusted.
-- ----------------------------------------------------------------------------

-- connections. Workspace-scoped rows keep project_id NULL - the distinction
-- the nullable column exists for. No description column on this table.
ALTER TABLE connections ADD COLUMN resource_id uuid;
UPDATE connections SET resource_id = gen_random_uuid();
INSERT INTO resources (id, workspace_id, project_id, kind, name, description,
                       created_by, created_at, updated_at)
SELECT resource_id, workspace_id, project_id, 'connection', name, '',
       created_by, created_at, updated_at
  FROM connections;

-- datasets
ALTER TABLE datasets ADD COLUMN resource_id uuid;
UPDATE datasets SET resource_id = gen_random_uuid();
INSERT INTO resources (id, workspace_id, project_id, kind, name, description,
                       created_by, created_at, updated_at)
SELECT resource_id, workspace_id, project_id, 'dataset', name, description,
       created_by, created_at, updated_at
  FROM datasets;

-- models (project only; workspace derived)
ALTER TABLE models ADD COLUMN resource_id uuid;
UPDATE models SET resource_id = gen_random_uuid();
INSERT INTO resources (id, workspace_id, project_id, kind, name, description,
                       created_by, created_at, updated_at)
SELECT m.resource_id, p.workspace_id, m.project_id, 'model', m.name, m.description,
       m.created_by, m.created_at, m.updated_at
  FROM models m JOIN projects p ON p.id = m.project_id;

-- object_types (workspace only; project_id stays NULL, and its name column is
-- display_name)
ALTER TABLE object_types ADD COLUMN resource_id uuid;
UPDATE object_types SET resource_id = gen_random_uuid();
INSERT INTO resources (id, workspace_id, project_id, kind, name, description,
                       created_by, created_at, updated_at)
SELECT resource_id, workspace_id, NULL, 'object_type', display_name, description,
       created_by, created_at, updated_at
  FROM object_types;

-- canvas_apps
ALTER TABLE canvas_apps ADD COLUMN resource_id uuid;
UPDATE canvas_apps SET resource_id = gen_random_uuid();
INSERT INTO resources (id, workspace_id, project_id, kind, name, description,
                       created_by, created_at, updated_at)
SELECT c.resource_id, p.workspace_id, c.project_id, 'canvas_app', c.name, c.description,
       c.created_by, c.created_at, c.updated_at
  FROM canvas_apps c JOIN projects p ON p.id = c.project_id;

-- code_repos. Empty in every deployment - the Code pillar's system of record
-- is model_versions (docs/decisions/0001-where-code-lives.md) - but registered
-- anyway, because ROADMAP.md section 2 gives this table a writer and a kind
-- added later is a second migration for no reason.
ALTER TABLE code_repos ADD COLUMN resource_id uuid;
UPDATE code_repos SET resource_id = gen_random_uuid();
INSERT INTO resources (id, workspace_id, project_id, kind, name, description,
                       created_by, created_at, updated_at)
SELECT c.resource_id, p.workspace_id, c.project_id, 'code_repo', c.name, c.description,
       c.created_by, c.created_at, c.updated_at
  FROM code_repos c JOIN projects p ON p.id = c.project_id;

-- Constraints and triggers, once every row is registered. NOT NULL is what
-- makes the invariant real: after this, a kind row without a registry row
-- cannot be written at all.
DO $$
DECLARE
    v_table text;
    v_kind  text;
BEGIN
    FOR v_table, v_kind IN
        SELECT * FROM (VALUES
            ('connections',  'connection'),
            ('datasets',     'dataset'),
            ('models',       'model'),
            ('object_types', 'object_type'),
            ('canvas_apps',  'canvas_app'),
            ('code_repos',   'code_repo')
        ) AS t(tbl, kind)
    LOOP
        EXECUTE format('ALTER TABLE %I ALTER COLUMN resource_id SET NOT NULL', v_table);
        EXECUTE format(
            'ALTER TABLE %I ADD CONSTRAINT %I UNIQUE (resource_id)',
            v_table, v_table || '_resource_id_key');
        EXECUTE format(
            'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (resource_id) '
            'REFERENCES resources(id) ON DELETE CASCADE',
            v_table, v_table || '_resource_id_fkey');
        EXECUTE format(
            'CREATE TRIGGER trg_%s_register BEFORE INSERT ON %I '
            'FOR EACH ROW EXECUTE FUNCTION register_resource(%L)',
            v_table, v_table, v_kind);
        EXECUTE format(
            'CREATE TRIGGER trg_%s_reregister AFTER UPDATE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION register_resource(%L)',
            v_table, v_table, v_kind);
        EXECUTE format(
            'CREATE TRIGGER trg_%s_unregister AFTER DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION unregister_resource()',
            v_table, v_table);
    END LOOP;
END
$$;

-- ----------------------------------------------------------------------------
-- RLS. The registry holds resource *names* across every project in a
-- workspace, which is precisely the metadata a project boundary is supposed to
-- keep private - so this policy matters more than most, not less. It mirrors
-- the connections policy, because the nullable project_id has the same meaning
-- in both places.
-- ----------------------------------------------------------------------------
ALTER TABLE resources ENABLE ROW LEVEL SECURITY;
CREATE POLICY resource_isolation ON resources
    USING (
        CASE
            WHEN project_id IS NULL THEN rls_can_access_workspace(workspace_id)
            ELSE rls_can_access_project(project_id)
        END
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON resources TO platform_app;
