-- ============================================================================
-- 0103_interface_reference_parameter.sql
-- p.62's interface reference parameter (§454).
--
--     "An 'interface reference' parameter will be generated, constrained to
--      the selected interface. The 'interface reference' parameter is similar
--      to the 'object reference' parameter, with the exception that the
--      'interface reference' parameter shows objects of any type that
--      implements the interface. If using a form or a table, the user could
--      then pick an object from a list." (`action-types` p.62)
--
-- **A column beside db 0083's, not a second parameter type**, and p.62's own
-- sentence is the argument: the two are *similar*, and they differ only in what
-- the list shows. The value is the same thing either way — one object's id —
-- so the rules that read it (`modify_object`'s `object`, `delete_object`'s)
-- do not care which kind of constraint produced it, and a second `data_type`
-- would make every one of them ask.
--
-- What the constraint decides is two things and only two: **which objects the
-- dropdown offers**, and **what p.34's check validates the submitted id
-- against**. Both are already keyed off db 0083's column, so both gain a
-- branch rather than a parallel implementation.
--
-- **At most one, and neither is also legal.** db 0101's CHECK says *exactly*
-- one subject because an action with no subject acts on nothing; here an
-- object parameter with neither constraint is the shape every object parameter
-- had before §330 — a text box and no p.34 check, which `action_choices.type_of`
-- documents as the deliberate behaviour for an untyped one. So the rule is
-- "not both", and the difference from 0101 is worth stating rather than
-- looking like an oversight.
--
-- `ON DELETE RESTRICT`, matching `object_type_id`: an interface a parameter is
-- constrained to is one the action depends on, and deleting it out from under
-- the action would leave a dropdown with nothing to offer and a check with
-- nothing to check.
-- ============================================================================

ALTER TABLE action_parameters
    ADD COLUMN interface_id uuid REFERENCES interfaces(id) ON DELETE RESTRICT;

ALTER TABLE action_parameters
    ADD CONSTRAINT action_parameters_one_constraint
        CHECK (NOT (object_type_id IS NOT NULL AND interface_id IS NOT NULL));

CREATE INDEX idx_action_parameters_interface
    ON action_parameters (interface_id)
    WHERE interface_id IS NOT NULL;

COMMENT ON COLUMN action_parameters.interface_id IS
    'p.62''s interface reference: the interface an `object` parameter''s value '
    'must implement (db 0103). Mutually exclusive with object_type_id, and '
    'both NULL is an untyped object parameter — a text box with no p.34 check, '
    'which is what every object parameter was before db 0083.';
