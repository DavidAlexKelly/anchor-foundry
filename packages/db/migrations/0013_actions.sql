-- ============================================================================
-- 0013_actions.sql
-- Actions — write-back (spec: "Canvas buttons/forms writing back to object
-- instances → source datasets"). An action_type names a set of an object
-- type's properties as writable; executing one (services/actions.py) updates
-- a specific object instance and versions the mapped dataset it came from.
--
-- Flagged for review — scope: write-back targets this platform's own
-- Parquet-backed copy of the mapped dataset, not the customer's original
-- external system. Connectors in this build only support test/discover, not
-- write, so true write-through to a live external source is out of scope;
-- see services/actions.py for the full reasoning.
-- ============================================================================

CREATE TABLE action_types (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    object_type_id       uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    api_name             text NOT NULL CHECK (api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    display_name         text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    description          text NOT NULL DEFAULT '',
    -- Property api_names (from object_type_properties) this action may
    -- write. Validated against the type's real properties in Python, same
    -- convention as object_type_sources.column_mappings.
    editable_properties  jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_by           uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (object_type_id, api_name)
);

CREATE TRIGGER trg_action_types_updated BEFORE UPDATE ON action_types
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Same workspace-consistency shape as link_types (0003): the object type
-- must belong to the action type's own workspace.
CREATE FUNCTION enforce_action_type_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_ot_ws uuid;
BEGIN
    SELECT workspace_id INTO v_ot_ws FROM object_types WHERE id = NEW.object_type_id;
    IF v_ot_ws IS DISTINCT FROM NEW.workspace_id THEN
        RAISE EXCEPTION 'action types cannot cross workspace boundaries (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_action_types_workspace BEFORE INSERT OR UPDATE ON action_types
    FOR EACH ROW EXECUTE FUNCTION enforce_action_type_workspace();

ALTER TABLE action_types ENABLE ROW LEVEL SECURITY;
CREATE POLICY action_types_isolation ON action_types
    USING (rls_can_access_workspace(workspace_id));

-- action_runs — history, one row per execution (spec §17 pattern already
-- used by sync_runs/model_runs: every mutating operation is auditable).
CREATE TABLE action_runs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type_id    uuid NOT NULL REFERENCES action_types(id) ON DELETE CASCADE,
    instance_id       uuid REFERENCES object_instances(id) ON DELETE SET NULL,
    dataset_id        uuid REFERENCES datasets(id) ON DELETE SET NULL,
    dataset_version   integer,
    requested_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    submitted_values  jsonb NOT NULL DEFAULT '{}'::jsonb,
    status            text NOT NULL DEFAULT 'running'
                          CHECK (status IN ('running', 'succeeded', 'failed')),
    error             text,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz
);

CREATE INDEX idx_action_runs_type ON action_runs (action_type_id, started_at DESC);

ALTER TABLE action_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY action_runs_isolation ON action_runs
    USING (EXISTS (SELECT 1 FROM action_types at
                   WHERE at.id = action_type_id
                     AND rls_can_access_workspace(at.workspace_id)));
