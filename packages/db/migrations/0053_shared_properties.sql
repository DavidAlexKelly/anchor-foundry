-- ============================================================================
-- 0053_shared_properties.sql
-- Shared properties (parity `docs/parity/ontology.md` §1.2; Foundry
-- `object-link-types` p.178-191).
--
-- > "A shared property is a property that can be used on multiple object types
-- > in your ontology. Shared properties allow for consistent data modeling
-- > across object types and centralized management of property metadata.
-- > **While property metadata is shared across objects, the underlying object
-- > data is not.**" (p.178)
--
-- That last sentence is the whole schema. This table holds *metadata* and
-- never a value: an object type attaches to it by reference, and the
-- instances keep living where they always did, keyed by the object type's own
-- api_name. Nothing about a shared property reaches `object_instances`.
--
-- Why a reference and not a copy
-- ------------------------------
-- p.178's example is `start date` on `Employee` and `Contractor`, so that you
-- can "update start date metadata in one place instead of on each object
-- type". A copy taken at attach time would satisfy the first half of that
-- sentence and silently break the second. So the attached property carries a
-- foreign key, and the inherited fields are resolved when the type is read.
--
-- The property's own columns are still written, and that is not redundancy:
-- 0028 snapshots a type's whole definition into `object_type_versions`, and a
-- version that recorded "see elsewhere" would change meaning when the shared
-- property was later edited. The row is the last known state; the join is the
-- current one; and the next save of the object type makes them agree again.
--
-- ON DELETE SET NULL is p.185, spelled in SQL
-- ------------------------------------------
-- > "When a shared property is deleted, all object types using this shared
-- > property will revert to regular properties." (p.185)
--
-- Not cascade. Deleting a *definition* that several object types happen to
-- share must not delete their properties - which would take the instances'
-- values out of every application that reads them, as a side effect of tidying
-- up an ontology. The row loses its reference and keeps everything else, which
-- is exactly what "revert to a regular property" means.
--
-- Workspace-scoped, like `object_types`
-- ------------------------------------
-- p.192 notes that links "between object types across different Ontologies is
-- not supported"; a shared property is the same kind of thing - a contract
-- between object types - so it lives at the boundary those object types share.
-- A workspace is this platform's ontology (0003), so the uniqueness of an
-- api_name and the reach of the reference are both workspace-wide.
-- ============================================================================

CREATE TABLE shared_properties (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- Same shape as `object_type_properties.api_name` (0003), because an
    -- attached property keeps its own api_name (p.188) and the two names sit
    -- side by side in every listing - one that could hold a shape the other
    -- could not would be a difference with no meaning behind it.
    api_name        text NOT NULL
                        CHECK (api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    display_name    text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    description     text NOT NULL DEFAULT '',
    -- p.181: "Base types … must match the column type in order to be applied
    -- on an object type." Attaching a property of a different type is refused
    -- in `services/shared_properties.py` rather than coerced here, because the
    -- refusal has to name both types to be worth reading.
    data_type       property_data_type NOT NULL,
    visibility      property_visibility NOT NULL DEFAULT 'normal',
    -- p.181 lists value formatting among the shared metadata. Same jsonb shape
    -- as `object_type_properties.value_format` (0049) and validated by the
    -- same module, so a formatter cannot mean one thing shared and another
    -- thing local.
    value_format    jsonb,
    created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, api_name)
);

CREATE INDEX idx_shared_properties_workspace ON shared_properties (workspace_id);

CREATE TRIGGER trg_shared_properties_updated BEFORE UPDATE ON shared_properties
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE shared_properties IS
    'One property definition used by several object types (Foundry '
    'object-link-types p.178-191). Metadata only: the values stay on the '
    'instances of each object type that attaches to it.';

ALTER TABLE object_type_properties
    ADD COLUMN shared_property_id uuid
        REFERENCES shared_properties(id) ON DELETE SET NULL;

CREATE INDEX idx_otp_shared_property
    ON object_type_properties (shared_property_id)
    WHERE shared_property_id IS NOT NULL;

COMMENT ON COLUMN object_type_properties.shared_property_id IS
    'The shared property this one inherits its metadata from (Foundry '
    'p.187-188), or NULL for an ordinary property. The property keeps its own '
    'id and api_name either way (p.188). ON DELETE SET NULL is p.185: '
    'deleting the shared property reverts every user to a regular property.';

-- The same shape as `otp_isolation` (0006) one table over: a shared property
-- is visible to whoever can see the workspace it belongs to. Modification is
-- restricted to editors by the API, as it is for object types.
ALTER TABLE shared_properties ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_properties_isolation ON shared_properties
    USING (rls_can_access_workspace(workspace_id));
