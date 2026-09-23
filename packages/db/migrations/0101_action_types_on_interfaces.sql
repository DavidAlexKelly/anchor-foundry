-- ============================================================================
-- 0101_action_types_on_interfaces.sql
-- An action type whose subject is an *interface* (§451).
--
--     "You can use interface action rules whenever the edits can apply to all
--      the object types that implement the interface. In other words, you can
--      use interface action rules only to modify the interface shared
--      properties or to delete objects." (`action-types` p.59)
--
-- **One table, not a second one**, and p.64 is the reason rather than economy:
-- "actions created with interface action rules can be applied to objects whose
-- object type implements the interface, **just like any object-specific action
-- type**. For a given object, all object-type-specific and interface-based
-- actions that can be applied to that object will appear in the action
-- dropdown." A separate `interface_action_types` would mean two services, two
-- listings, two executors and a dropdown that merges them — four places for
-- one idea to drift (§292), and a merge is exactly what p.64 says must not be
-- visible to the person using it.
--
-- **The subject is one of two things and never both**, which is db 0087's rule
-- about a declaration that says only half of itself, applied to a foreign key:
-- an action type with neither has no subject at all, and one with both has two
-- answers to "what does this act on". The CHECK says it once, here, rather
-- than in each of the routes that can write the row.
--
-- **`object_type_id` becomes nullable and that is the migration's whole risk.**
-- Every reader of the column was written when it could not be null. The ones
-- that matter are named in `services/actions.py`, and the shape they take is
-- `subject_type_of`: the concrete type an execution is against, which for an
-- interface action is the *instance's* type and is not known until submission.
-- A reader that still assumes a type will now see `None` rather than a wrong
-- id, which is the failure worth having (§210).
--
-- **The uniqueness rule splits in two.** `UNIQUE (object_type_id, api_name)`
-- is no rule at all once the column is nullable — Postgres treats every NULL
-- as distinct, so two interface actions could share a name. Two partial unique
-- indexes say what was meant: a name is unique within its subject, whichever
-- kind of subject that is.
--
-- **No `interface_action_control` column** (p.65's "disable interface actions
-- for specific object types … in the Interface action control section"). It is
-- a real part of the page and it is a *permission* — p.65 says so in the same
-- breath ("the ability to apply more granular permission controls to interface
-- actions is under active development"). A column here would be the storage
-- for a check nothing performs, which is §214's control that looks like it
-- works. It is a named ○ on the row instead.
-- ============================================================================

ALTER TABLE action_types
    ALTER COLUMN object_type_id DROP NOT NULL,
    ADD COLUMN interface_id uuid REFERENCES interfaces(id) ON DELETE CASCADE;

ALTER TABLE action_types
    ADD CONSTRAINT action_types_one_subject
        CHECK ((object_type_id IS NULL) <> (interface_id IS NULL));

-- The old constraint could not survive a nullable column; see above.
ALTER TABLE action_types DROP CONSTRAINT action_types_object_type_id_api_name_key;

CREATE UNIQUE INDEX uq_action_types_object_type_api_name
    ON action_types (object_type_id, api_name)
    WHERE object_type_id IS NOT NULL;

CREATE UNIQUE INDEX uq_action_types_interface_api_name
    ON action_types (interface_id, api_name)
    WHERE interface_id IS NOT NULL;

CREATE INDEX idx_action_types_interface
    ON action_types (interface_id)
    WHERE interface_id IS NOT NULL;

COMMENT ON COLUMN action_types.interface_id IS
    'The interface this action acts on (`action-types` p.59; db 0101). '
    'Exactly one of interface_id and object_type_id is set. An interface '
    'action''s rules name *interface* properties, and the concrete property '
    'each one writes is found through object_type_interfaces.property_mapping '
    'at submission, once the subject''s own type is known.';

-- The workspace trigger checked the object type and would now pass an
-- interface action unexamined - a subject from another workspace, admitted by
-- a guard that looks like it is still doing its job (§214). Both branches,
-- one function.
CREATE OR REPLACE FUNCTION enforce_action_type_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_ws uuid;
BEGIN
    IF NEW.object_type_id IS NOT NULL THEN
        SELECT workspace_id INTO v_ws FROM object_types WHERE id = NEW.object_type_id;
    ELSE
        SELECT workspace_id INTO v_ws FROM interfaces WHERE id = NEW.interface_id;
    END IF;
    IF v_ws IS DISTINCT FROM NEW.workspace_id THEN
        RAISE EXCEPTION 'action types cannot cross workspace boundaries (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;
