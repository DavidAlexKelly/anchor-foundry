-- ============================================================================
-- 0120_struct_field_constraints.sql
-- Parity `docs/parity/ontology.md` §4 ("Actions on structs"). `action-types`
-- p.71-72.
--
--     "Constraints can be configured individually for struct parameter
--      fields, as with regular parameters. For example, a string length
--      constraint can be defined on struct parameter fields of string types
--      to only allow string value that are between 10 and 500 characters
--      long." (p.71)
--
--     "A struct parameter value is only valid if all fields meet the defined
--      constraint." (p.72)
--
-- `{field api_name: constraint}`, each in db 0119's shape (a value type's,
-- p.233), and `{}` for a parameter with none - which is every parameter that
-- is not a struct. **Keyed by the field's api_name, not typed here**: a
-- struct parameter's fields are the property's its rule writes (§450), so the
-- field's type is read from the ontology at save and at submit rather than
-- copied beside the constraint, where it would be free to disagree.
-- ============================================================================

ALTER TABLE action_parameters
    ADD COLUMN field_constraints jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN action_parameters.field_constraints IS
    'action-types p.71-72: a struct parameter''s per-field constraints, '
    '{field: constraint} in value_constraints'' shape. Checked in '
    'services/action_constraints against the fields of the property the '
    'parameter writes.';
