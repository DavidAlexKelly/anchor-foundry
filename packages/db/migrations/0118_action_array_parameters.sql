-- ============================================================================
-- 0118_action_array_parameters.sql
-- Parity `docs/parity/ontology.md` §1.1 ("Arrays of any base type") and §4
-- ("Upload attachments through an action"). `object-link-types` p.86, p.116;
-- `action-types` p.127.
--
-- **An array parameter says what it is an array of**, for db 0087's reason:
-- `array` is the one label that does not name a type. 0087 made the label
-- storable on a parameter and `_UNSUPPORTED_PARAMETER_TYPES` refused it at
-- save, because a parameter had nowhere to say *of what* and the form had no
-- control that collects several values. This is the first of those two; the
-- form's list control is the second (§580).
--
-- The element types are 0087's `array_properties.INNER_TYPES`, checked in
-- `actions._validate_definition` with sentences, and NULL exactly when the
-- parameter is not an array. No CHECK, for 0087's reason: the pairing is one
-- of several rules that module makes together.
-- ============================================================================

ALTER TABLE action_parameters
    ADD COLUMN array_of action_parameter_type;

COMMENT ON COLUMN action_parameters.array_of IS
    'The element type of an `array` parameter (db 0087, object-link-types '
    'p.86), and NULL for every other type. Checked in '
    'services/actions._validate_definition.';
