-- ============================================================================
-- 0148_interface_link_constraints.sql
-- Decision 0024; parity `docs/parity/ontology.md` §1.5 (Interfaces: "links on
-- an interface"); Foundry `ontology` p.60, `action-types` p.63-64 (§759).
--
-- > "Interfaces … describe the shape of an object type: its properties,
-- > links and actions" (ontology p.60, paraphrased by the Interfaces row)
-- > "Select the interface link constraint defined on the interface. If the
-- > link constraint is between two interfaces … If the link constraint is
-- > between an interface and an object type …" (action-types p.63)
--
-- A **link constraint** is an interface's promise that every implementing
-- object type links to something: to the objects of another interface, or of
-- one object type. An implementation keeps it with one or more of its own
-- link types (p.64: "multiple concrete link implementations on the object
-- type for the link constraint"), listed in `link_mapping` beside the
-- property mapping it already keeps.
-- ============================================================================

CREATE TABLE interface_link_constraints (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    interface_id           uuid NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
    -- Named like a link type (db 0003), since it stands for one.
    api_name               text NOT NULL CHECK (api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    display_name           text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    description            text NOT NULL DEFAULT '',
    -- p.63's two kinds: to an interface, or to an object type. Exactly one.
    -- Not CASCADE: deleting what a promise points at is refused by the
    -- service with a sentence, and this is the backstop. NO ACTION rather
    -- than RESTRICT, so an interface linking to itself can still be deleted:
    -- the check waits for its own constraint to cascade away.
    target_interface_id    uuid REFERENCES interfaces(id),
    target_object_type_id  uuid REFERENCES object_types(id),
    -- Whether every implementation must keep it, as `interface_properties`.
    required               boolean NOT NULL DEFAULT true,
    sort_order             integer NOT NULL DEFAULT 0,
    UNIQUE (interface_id, api_name),
    CHECK ((target_interface_id IS NULL) <> (target_object_type_id IS NULL))
);

CREATE INDEX idx_interface_link_constraints_interface
    ON interface_link_constraints (interface_id);
CREATE INDEX idx_interface_link_constraints_target_interface
    ON interface_link_constraints (target_interface_id);
CREATE INDEX idx_interface_link_constraints_target_type
    ON interface_link_constraints (target_object_type_id);

CREATE FUNCTION enforce_interface_link_constraint_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_ws uuid;
    v_target_ws uuid;
BEGIN
    SELECT workspace_id INTO v_ws FROM interfaces WHERE id = NEW.interface_id;
    IF NEW.target_interface_id IS NOT NULL THEN
        SELECT workspace_id INTO v_target_ws FROM interfaces WHERE id = NEW.target_interface_id;
    ELSE
        SELECT workspace_id INTO v_target_ws FROM object_types WHERE id = NEW.target_object_type_id;
    END IF;
    IF v_ws IS DISTINCT FROM v_target_ws THEN
        RAISE EXCEPTION 'a link constraint cannot point at another workspace (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_interface_link_constraints_workspace
    BEFORE INSERT OR UPDATE ON interface_link_constraints
    FOR EACH ROW EXECUTE FUNCTION enforce_interface_link_constraint_workspace();

-- `{constraint api_name: [link type id, …]}`, jsonb for `property_mapping`'s
-- reason (db 0065): read whole, written whole, never joined against.
ALTER TABLE object_type_interfaces
    ADD COLUMN link_mapping jsonb NOT NULL DEFAULT '{}';

-- Visible when its interface is, as `interface_properties` (db 0065).
ALTER TABLE interface_link_constraints ENABLE ROW LEVEL SECURITY;
CREATE POLICY interface_link_constraints_isolation ON interface_link_constraints
    USING (EXISTS (SELECT 1 FROM interfaces i WHERE i.id = interface_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON interface_link_constraints TO platform_app;
