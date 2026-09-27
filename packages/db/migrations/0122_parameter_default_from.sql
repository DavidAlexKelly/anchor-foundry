-- ============================================================================
-- 0122_parameter_default_from.sql
-- Parity `docs/parity/ontology.md` §4 ("Parameter default values", "Actions on
-- structs"). `action-types` p.27, p.29, p.69-70.
--
--     "Parameters can be set to default values to display either a fixed value
--      or a property of the selected object." (p.27)
--
--     "Only object reference parameters that are placed above the parameter
--      in the input list are available to be used as a default value." (p.29)
--
-- `default_value` (db 0044) is the fixed kind; this is the other: `{parameter,
-- property}` naming an object reference parameter above this one and a
-- property of its object, plus `fields` mapping a struct parameter's fields to
-- that struct property's (p.69-70). NULL for none. Checked in
-- `services/action_defaults`, with sentences, and never set beside a fixed
-- default.
-- ============================================================================

ALTER TABLE action_parameters
    ADD COLUMN default_from jsonb;

COMMENT ON COLUMN action_parameters.default_from IS
    'action-types p.27, p.29, p.69-70: the parameter''s default read from an '
    'object reference parameter''s object, {parameter, property, fields?}.';
