-- ============================================================================
-- 0003_resources.sql
-- Resource tables (spec §16 "Resource Tables"):
--   connections, datasets, dataset_versions, models, model_inputs,
--   model_runs, object_types, object_type_properties, link_types,
--   object_type_sources, canvas_apps, canvas_app_versions, code_repos
-- ============================================================================

-- ---- Enum types --------------------------------------------------------------
CREATE TYPE connection_scope   AS ENUM ('project', 'workspace');       -- spec §16
CREATE TYPE sync_mode          AS ENUM ('federated', 'full', 'incremental'); -- spec §5
CREATE TYPE connection_status  AS ENUM ('unconfigured', 'ok', 'error', 'testing');
CREATE TYPE dataset_origin     AS ENUM ('upload', 'sync', 'model_output');
CREATE TYPE model_language     AS ENUM ('sql', 'python');
CREATE TYPE model_trigger      AS ENUM ('manual', 'cron', 'upstream');
CREATE TYPE run_status         AS ENUM ('queued', 'running', 'succeeded', 'failed', 'cancelled');
CREATE TYPE link_cardinality   AS ENUM ('one_to_one', 'one_to_many', 'many_to_many');
CREATE TYPE property_data_type AS ENUM
    ('string', 'integer', 'float', 'boolean', 'date', 'timestamp', 'geopoint', 'json');
CREATE TYPE app_publish_scope  AS ENUM ('private', 'workspace', 'groups');
CREATE TYPE object_sync_status AS ENUM ('never_synced', 'syncing', 'ok', 'error');

-- ----------------------------------------------------------------------------
-- connections — data source configurations. Either project-scoped or
-- workspace-shared (spec §16). Config here, credentials in Secrets Manager:
-- we store only the secret ARN, never a secret value. (spec §5, §10)
-- ----------------------------------------------------------------------------
CREATE TABLE connections (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- NULL when scope = 'workspace' (shared across the workspace's projects).
    project_id       uuid REFERENCES projects(id) ON DELETE CASCADE,
    scope            connection_scope NOT NULL DEFAULT 'project',
    name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    -- e.g. 'postgresql', 'mysql', 's3', 'rest', 'salesforce', ...
    source_type      text NOT NULL,
    -- Non-secret configuration only (host, port, database name, options).
    -- The API layer must never write credentials into this column.
    config           jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- ARN of the AWS Secrets Manager secret holding the credentials.
    secret_arn       text,
    sync_mode        sync_mode NOT NULL DEFAULT 'federated',
    sync_schedule    text,                 -- cron expression, NULL = on demand
    status           connection_status NOT NULL DEFAULT 'unconfigured',
    last_tested_at   timestamptz,
    last_synced_at   timestamptz,
    last_error       text,
    created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK ((scope = 'project' AND project_id IS NOT NULL)
        OR (scope = 'workspace' AND project_id IS NULL))
);

CREATE INDEX idx_connections_workspace ON connections (workspace_id);
CREATE INDEX idx_connections_project ON connections (project_id) WHERE project_id IS NOT NULL;
CREATE TRIGGER trg_connections_updated BEFORE UPDATE ON connections
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ----------------------------------------------------------------------------
-- datasets — tables of data. S3 location, schema, row count, versioned (§16).
-- Every dataset lives in a project (spec §4: "Every resource lives at the
-- project level"). workspace_id is denormalised for isolation enforcement and
-- kept consistent by trigger.
-- ----------------------------------------------------------------------------
CREATE TABLE datasets (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    slug             text NOT NULL
                         CHECK (slug ~ '^[a-z0-9]([a-z0-9_-]{0,61}[a-z0-9])?$'),
    description      text NOT NULL DEFAULT '',
    origin           dataset_origin NOT NULL,
    connection_id    uuid REFERENCES connections(id) ON DELETE SET NULL,
    -- S3/Iceberg root for this dataset, under the workspace s3_prefix (§8).
    s3_location      text NOT NULL,
    -- Column schema: [{"name": ..., "type": ..., "nullable": ...}, ...]
    table_schema     jsonb NOT NULL DEFAULT '[]'::jsonb,
    row_count        bigint NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    current_version  integer NOT NULL DEFAULT 0 CHECK (current_version >= 0),
    created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, slug)
);

CREATE INDEX idx_datasets_project ON datasets (project_id);
CREATE INDEX idx_datasets_workspace ON datasets (workspace_id);
CREATE TRIGGER trg_datasets_updated BEFORE UPDATE ON datasets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Keep the denormalised workspace_id honest: it must always equal the
-- project's workspace, and cross-workspace references are impossible.
CREATE FUNCTION enforce_dataset_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_ws uuid;
BEGIN
    SELECT workspace_id INTO v_ws FROM projects WHERE id = NEW.project_id;
    IF v_ws IS NULL THEN
        RAISE EXCEPTION 'project % not found', NEW.project_id;
    END IF;
    IF NEW.workspace_id IS DISTINCT FROM v_ws THEN
        RAISE EXCEPTION 'dataset workspace_id must match its project''s workspace (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_datasets_workspace BEFORE INSERT OR UPDATE ON datasets
    FOR EACH ROW EXECUTE FUNCTION enforce_dataset_workspace();

-- ----------------------------------------------------------------------------
-- dataset_versions — snapshot per sync/upload; enables time travel and
-- rollback (spec §16). Iceberg holds the data-level snapshot; this table is
-- the platform-level index of those snapshots.
-- ----------------------------------------------------------------------------
CREATE TABLE dataset_versions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id          uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    version_number      integer NOT NULL CHECK (version_number > 0),
    iceberg_snapshot_id bigint,
    s3_manifest_key     text,
    table_schema        jsonb NOT NULL DEFAULT '[]'::jsonb,
    row_count           bigint NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    -- What produced this version (upload id, model_run id, sync job id).
    produced_by_kind    text,
    produced_by_id      uuid,
    created_by          uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, version_number)
);

CREATE INDEX idx_dataset_versions_dataset ON dataset_versions (dataset_id);

-- ----------------------------------------------------------------------------
-- models — SQL or Python transforms. Links to input datasets (via
-- model_inputs) and one output dataset (spec §16).
-- ----------------------------------------------------------------------------
CREATE TABLE models (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id         uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name               text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    description        text NOT NULL DEFAULT '',
    language           model_language NOT NULL,
    code               text NOT NULL DEFAULT '',
    output_dataset_id  uuid REFERENCES datasets(id) ON DELETE SET NULL,
    trigger_mode       model_trigger NOT NULL DEFAULT 'manual',
    cron_schedule      text,   -- required when trigger_mode = 'cron'
    created_by         uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name),
    CHECK (trigger_mode <> 'cron' OR cron_schedule IS NOT NULL)
);

CREATE INDEX idx_models_project ON models (project_id);
CREATE TRIGGER trg_models_updated BEFORE UPDATE ON models
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- model_inputs — many-to-many between models and their input datasets (§16).
-- This is the lineage edge set: dataset -> model -> output dataset.
CREATE TABLE model_inputs (
    model_id     uuid NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    dataset_id   uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    -- Alias by which the transform refers to this input (e.g. FROM orders).
    input_alias  text NOT NULL DEFAULT '',
    PRIMARY KEY (model_id, dataset_id)
);

CREATE INDEX idx_model_inputs_dataset ON model_inputs (dataset_id);

-- model_runs — execution history per model (spec §16, §5: retained 90 days;
-- retention is enforced by a scheduled worker job, not the schema).
CREATE TABLE model_runs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id       uuid NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    status         run_status NOT NULL DEFAULT 'queued',
    triggered_by   uuid REFERENCES users(id) ON DELETE SET NULL,
    trigger_kind   model_trigger NOT NULL DEFAULT 'manual',
    queued_at      timestamptz NOT NULL DEFAULT now(),
    started_at     timestamptz,
    finished_at    timestamptz,
    rows_produced  bigint CHECK (rows_produced IS NULL OR rows_produced >= 0),
    error_message  text,
    log_s3_key     text,
    -- Version of the output dataset this run produced, if it succeeded.
    output_version uuid REFERENCES dataset_versions(id) ON DELETE SET NULL
);

CREATE INDEX idx_model_runs_model ON model_runs (model_id, queued_at DESC);
CREATE INDEX idx_model_runs_status ON model_runs (status) WHERE status IN ('queued', 'running');

-- ----------------------------------------------------------------------------
-- object_types — defined at workspace level; the semantic entity definitions
-- (spec §5, §16). Available to all projects in the workspace.
-- ----------------------------------------------------------------------------
CREATE TABLE object_types (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id      uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- Stable machine name used by the GraphQL API and exports.
    api_name          text NOT NULL
                          CHECK (api_name ~ '^[A-Za-z][A-Za-z0-9_]{0,99}$'),
    display_name      text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    description       text NOT NULL DEFAULT '',
    icon              text NOT NULL DEFAULT 'cube',
    colour            text NOT NULL DEFAULT '#4f46e5'
                          CHECK (colour ~ '^#[0-9a-fA-F]{6}$'),
    -- Set after properties exist (spec §15 Phase 3: "set title property").
    title_property_id uuid,
    created_by        uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, api_name)
);

CREATE INDEX idx_object_types_workspace ON object_types (workspace_id);
CREATE TRIGGER trg_object_types_updated BEFORE UPDATE ON object_types
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- object_type_properties — typed properties on object types (spec §16).
CREATE TABLE object_type_properties (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_type_id  uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    api_name        text NOT NULL
                        CHECK (api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    display_name    text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    data_type       property_data_type NOT NULL,
    required        boolean NOT NULL DEFAULT false,
    description     text NOT NULL DEFAULT '',
    sort_order      integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (object_type_id, api_name)
);

ALTER TABLE object_types
    ADD CONSTRAINT fk_object_types_title_property
    FOREIGN KEY (title_property_id) REFERENCES object_type_properties(id)
    ON DELETE SET NULL;

-- link_types — typed relationships between object types (spec §5, §16).
-- Both ends must be in the same workspace: links may not cross the hard
-- isolation boundary. Enforced by trigger below.
CREATE TABLE link_types (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    api_name             text NOT NULL
                             CHECK (api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    display_name         text NOT NULL,
    from_object_type_id  uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    to_object_type_id    uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    cardinality          link_cardinality NOT NULL,
    created_by           uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, api_name)
);

CREATE FUNCTION enforce_link_type_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_from uuid;
    v_to   uuid;
BEGIN
    SELECT workspace_id INTO v_from FROM object_types WHERE id = NEW.from_object_type_id;
    SELECT workspace_id INTO v_to   FROM object_types WHERE id = NEW.to_object_type_id;
    IF v_from IS DISTINCT FROM NEW.workspace_id OR v_to IS DISTINCT FROM NEW.workspace_id THEN
        RAISE EXCEPTION 'link types cannot cross workspace boundaries (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_link_types_workspace BEFORE INSERT OR UPDATE ON link_types
    FOR EACH ROW EXECUTE FUNCTION enforce_link_type_workspace();

-- ----------------------------------------------------------------------------
-- object_type_sources — maps a dataset (in a project) to a workspace object
-- type with column mappings (spec §16). Multiple projects can contribute
-- data to the same object type (spec §5).
-- ----------------------------------------------------------------------------
CREATE TABLE object_type_sources (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_type_id      uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    dataset_id          uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    -- Column in the dataset that uniquely identifies each object instance.
    primary_key_column  text NOT NULL,
    -- {"dataset_column": "property_api_name", ...}
    column_mappings     jsonb NOT NULL DEFAULT '{}'::jsonb,
    sync_status         object_sync_status NOT NULL DEFAULT 'never_synced',
    last_synced_at      timestamptz,
    last_error          text,
    created_by          uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (object_type_id, dataset_id)
);

CREATE TRIGGER trg_object_type_sources_updated BEFORE UPDATE ON object_type_sources
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The dataset must live in the same workspace as the object type — datasets
-- in one workspace can never feed another workspace's ontology.
CREATE FUNCTION enforce_object_source_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_ot_ws uuid;
    v_ds_ws uuid;
BEGIN
    SELECT workspace_id INTO v_ot_ws FROM object_types WHERE id = NEW.object_type_id;
    SELECT workspace_id INTO v_ds_ws FROM datasets WHERE id = NEW.dataset_id;
    IF v_ot_ws IS DISTINCT FROM v_ds_ws THEN
        RAISE EXCEPTION 'object type sources cannot cross workspace boundaries (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_object_type_sources_workspace
    BEFORE INSERT OR UPDATE ON object_type_sources
    FOR EACH ROW EXECUTE FUNCTION enforce_object_source_workspace();

-- ----------------------------------------------------------------------------
-- canvas_apps — app definitions stored as JSON, versioned (spec §16).
-- ----------------------------------------------------------------------------
CREATE TABLE canvas_apps (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    slug             text NOT NULL
                         CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'),
    description      text NOT NULL DEFAULT '',
    -- Craft.js serialised definition. Human-readable JSON per spec §11.
    definition       jsonb NOT NULL DEFAULT '{}'::jsonb,
    current_version  integer NOT NULL DEFAULT 0 CHECK (current_version >= 0),
    publish_scope    app_publish_scope NOT NULL DEFAULT 'private',
    published_at     timestamptz,
    created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, slug)
);

CREATE INDEX idx_canvas_apps_project ON canvas_apps (project_id);
CREATE TRIGGER trg_canvas_apps_updated BEFORE UPDATE ON canvas_apps
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- canvas_app_versions — snapshot per save (spec §16).
CREATE TABLE canvas_app_versions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canvas_app_id   uuid NOT NULL REFERENCES canvas_apps(id) ON DELETE CASCADE,
    version_number  integer NOT NULL CHECK (version_number > 0),
    definition      jsonb NOT NULL,
    created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (canvas_app_id, version_number)
);

-- canvas_app_shares — publish target groups when publish_scope = 'groups'.
-- NOTE (flagged for review): §16 does not list this table, but §5 "Publishing"
-- requires apps publishable "to specific groups". A join table is the most
-- conservative way to model that; without it the requirement is unmeetable.
CREATE TABLE canvas_app_shares (
    canvas_app_id  uuid NOT NULL REFERENCES canvas_apps(id) ON DELETE CASCADE,
    group_id       uuid NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    added_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    added_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (canvas_app_id, group_id)
);

-- ----------------------------------------------------------------------------
-- code_repos — git-backed code repositories stored in S3 (spec §16).
-- ----------------------------------------------------------------------------
CREATE TABLE code_repos (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    slug            text NOT NULL
                        CHECK (slug ~ '^[a-z0-9]([a-z0-9_-]{0,61}[a-z0-9])?$'),
    description     text NOT NULL DEFAULT '',
    -- S3 prefix (under the workspace prefix) where the bare git repo lives.
    s3_prefix       text NOT NULL UNIQUE,
    default_branch  text NOT NULL DEFAULT 'main',
    created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, slug)
);

CREATE TRIGGER trg_code_repos_updated BEFORE UPDATE ON code_repos
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
