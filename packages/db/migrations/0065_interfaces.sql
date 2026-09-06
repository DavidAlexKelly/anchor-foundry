-- ============================================================================
-- 0065_interfaces.sql
-- Parity `docs/parity/ontology.md` §1.2 (build order item 9's fourth of four);
-- Foundry `object-link-types` p.4/p.8 and p.53, `ontology` p.60–62.
--
-- > "An interface is an Ontology type that describes the shape of an object
-- > type and its capabilities. Interfaces provide object type polymorphism,
-- > allowing for consistent modeling of and interaction with object types that
-- > share a common shape." (`object-link-types` p.4)
--
-- > "You can implement an interface on multiple object types, and interfaces
-- > may extend any number of other interfaces." (p.53)
--
-- **The `[?]` on this row was about the screens, not the concept**, and that
-- is worth stating because it decided whether this could be built at all.
-- `object-link-types` has no *reference* section for creating or editing an
-- interface — p.4 and p.8 define one and then say "Learn more about
-- interfaces", pointing at a section this PDF does not contain, and every
-- other mention is the Gaia/Gotham integration (p.51–73), which is out of
-- scope. What `ontology` p.60–62 does give is the model in full: a shared
-- shape of **properties, links and actions**; many object types implementing
-- one; interfaces extending others for "multi-level abstraction"; and a worked
-- example (`Inspectable` with `lastInspectionDate` and `inspectionStatus`,
-- implemented by Vehicle, Equipment and Facility). So the model is sourced and
-- the surface is this platform's own, which is the same split §215's Object
-- Selector was built on.
--
-- **Properties only, in this migration.** p.60 says an interface can share
-- links and actions too, and both are named as ○ on the row rather than built
-- here: a link has two ends and an action has parameters and rules, so each is
-- its own question about what "the implementing type must supply" means.
-- Properties are the half p.61's worked example is entirely about.
--
-- Why an interface is a *workspace* resource
-- ------------------------------------------
-- The same reason a shared property is (0053) and a value type is (0054): an
-- ontology is workspace-scoped here (db 0003), object types are, and an
-- interface that could be implemented across workspaces would be a read path
-- through the isolation boundary. The trigger below enforces it for the same
-- reason `enforce_object_type_series_workspace` does one table over.
-- ============================================================================

CREATE TABLE interfaces (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- **The object type's shape, not the property's.** p.60's examples are
    -- `Inspectable`, `SchedulableResource`, `MilitaryAsset`, `MedicalDevice` -
    -- type names, and an interface is a *type* (p.4 calls it "an Ontology
    -- type"). Same rule as `object_types.api_name` so the two read alike in
    -- the one place they appear side by side: an object type's implements
    -- list.
    api_name        text NOT NULL
                        CHECK (api_name ~ '^[A-Za-z][A-Za-z0-9_]{0,99}$'),
    display_name    text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    description     text NOT NULL DEFAULT '',
    -- p.253's developmental state, like every other ontology resource
    -- (0055). An interface is a promise other types make; how much anybody
    -- should rely on it is exactly the question a status answers.
    status          ontology_status NOT NULL DEFAULT 'experimental',
    deprecation     jsonb,
    created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, api_name)
);

CREATE INDEX idx_interfaces_workspace ON interfaces (workspace_id);

CREATE TRIGGER trg_interfaces_updated BEFORE UPDATE ON interfaces
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE interfaces IS
    'A shared shape several object types implement (Foundry '
    'object-link-types p.4, ontology p.60-62). Metadata only: an interface '
    'has no instances of its own, and an implementing type keeps its own '
    'properties and its own data.';

-- The shape itself. Deliberately the same columns an `object_type_properties`
-- row has for the same facts, minus everything about *storage* - no column
-- mapping, no visibility, no formatter. An interface says a type must have a
-- `lastInspectionDate` that is a date; how that type stores or shows it is the
-- type's business, and p.60's whole argument is that three types can satisfy
-- one interface while differing in everything else.
CREATE TABLE interface_properties (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    interface_id    uuid NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
    api_name        text NOT NULL
                        CHECK (api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    display_name    text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    description     text NOT NULL DEFAULT '',
    data_type       property_data_type NOT NULL,
    -- Whether an implementation must map it at all. p.60's `Inspectable` reads
    -- as though both its properties are required; making it a column rather
    -- than assuming lets an interface carry an optional part of a shape, which
    -- p.62's "design interfaces around capabilities" needs - a capability with
    -- one mandatory field and two optional ones is an ordinary thing.
    required        boolean NOT NULL DEFAULT true,
    sort_order      integer NOT NULL DEFAULT 0,
    UNIQUE (interface_id, api_name)
);

CREATE INDEX idx_interface_properties_interface
    ON interface_properties (interface_id);

-- p.53: "interfaces may extend any number of other interfaces", and p.62's
-- "extend interfaces for multi-level abstraction" with `SchedulableResource
-- extends Trackable`.
--
-- **A table rather than a column**, because "any number" is the spec's word.
-- The cycle refusal is in `services/interfaces.py` rather than here: Postgres
-- cannot express "no cycles in this graph" as a constraint, and a trigger that
-- walked the graph on every insert would be a second implementation of the
-- traversal the service already has to do to resolve inherited properties.
CREATE TABLE interface_extends (
    interface_id    uuid NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
    extends_id      uuid NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
    PRIMARY KEY (interface_id, extends_id),
    -- The one cycle a constraint *can* catch, and the one most likely to be
    -- typed by hand.
    CHECK (interface_id <> extends_id)
);

CREATE INDEX idx_interface_extends_extends ON interface_extends (extends_id);

-- p.53: "You can implement an interface on multiple object types."
CREATE TABLE object_type_interfaces (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_type_id    uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    interface_id      uuid NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
    -- `{interface property api_name: this type's property api_name}`.
    --
    -- **A mapping rather than a name match**, which is p.66's own shape - "map
    -- your ontology's Geoshape shared property type to the object type
    -- implementing the interface" - and the reason is p.60's: three types
    -- satisfy one interface *while differing in everything else*, and that has
    -- to include what they call things. A Vehicle whose column is
    -- `last_checked` can still be Inspectable.
    --
    -- jsonb rather than a row per pair for `column_mappings`' reason (db
    -- 0003): it is read whole, written whole, and never joined against.
    property_mapping  jsonb NOT NULL DEFAULT '{}',
    created_by        uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (object_type_id, interface_id)
);

CREATE INDEX idx_oti_interface ON object_type_interfaces (interface_id);

CREATE TRIGGER trg_object_type_interfaces_updated
    BEFORE UPDATE ON object_type_interfaces
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Same workspace-consistency shape as `object_type_sources` (0003) and
-- `object_type_series` (0047): an implementation may not cross the isolation
-- boundary, because the interface's properties would then be read through it.
CREATE FUNCTION enforce_object_type_interface_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_type_ws uuid;
    v_iface_ws uuid;
BEGIN
    SELECT workspace_id INTO v_type_ws FROM object_types WHERE id = NEW.object_type_id;
    SELECT workspace_id INTO v_iface_ws FROM interfaces WHERE id = NEW.interface_id;
    IF v_type_ws IS DISTINCT FROM v_iface_ws THEN
        RAISE EXCEPTION 'an object type cannot implement an interface from another workspace (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_object_type_interfaces_workspace
    BEFORE INSERT OR UPDATE ON object_type_interfaces
    FOR EACH ROW EXECUTE FUNCTION enforce_object_type_interface_workspace();

-- And the same for extension: an interface may only extend one in its own
-- workspace, for the same reason and with the same failure if it could not.
CREATE FUNCTION enforce_interface_extends_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_child_ws uuid;
    v_parent_ws uuid;
BEGIN
    SELECT workspace_id INTO v_child_ws FROM interfaces WHERE id = NEW.interface_id;
    SELECT workspace_id INTO v_parent_ws FROM interfaces WHERE id = NEW.extends_id;
    IF v_child_ws IS DISTINCT FROM v_parent_ws THEN
        RAISE EXCEPTION 'an interface cannot extend one from another workspace (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_interface_extends_workspace
    BEFORE INSERT OR UPDATE ON interface_extends
    FOR EACH ROW EXECUTE FUNCTION enforce_interface_extends_workspace();

-- Visible to whoever can see the workspace, like every other ontology
-- resource (0006's shape). The children are visible when their parent is,
-- which is what `object_type_series` and `object_type_sources` already do.
ALTER TABLE interfaces ENABLE ROW LEVEL SECURITY;
CREATE POLICY interfaces_isolation ON interfaces
    USING (rls_can_access_workspace(workspace_id));

ALTER TABLE interface_properties ENABLE ROW LEVEL SECURITY;
CREATE POLICY interface_properties_isolation ON interface_properties
    USING (EXISTS (SELECT 1 FROM interfaces i WHERE i.id = interface_id));

ALTER TABLE interface_extends ENABLE ROW LEVEL SECURITY;
CREATE POLICY interface_extends_isolation ON interface_extends
    USING (EXISTS (SELECT 1 FROM interfaces i WHERE i.id = interface_id));

ALTER TABLE object_type_interfaces ENABLE ROW LEVEL SECURITY;
CREATE POLICY object_type_interfaces_isolation ON object_type_interfaces
    USING (EXISTS (SELECT 1 FROM object_types ot WHERE ot.id = object_type_id));
