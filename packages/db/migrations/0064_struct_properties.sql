-- ============================================================================
-- 0064_struct_properties.sql
-- Parity `docs/parity/ontology.md` §1.1 (build order item 7, "Struct property
-- type, then Workshop struct variables"); Foundry `object-link-types`
-- p.149-150, and the modelling argument in `ontology` p.58-59.
--
-- > "A struct is an Ontology property base type that allows users to create
-- > schema-based properties with multiple fields." (`object-link-types` p.149)
--
-- The point of the type, from `ontology` p.58: a property that is naturally
-- multi-field - an address with street, city, state and postal code - should
-- be one property with fields rather than five properties sharing a naming
-- convention. "Semantic grouping" is the benefit p.59 names first, and it is
-- the one this platform can honour: `json` already accepts the same *value*,
-- and what it cannot do is say what the value is supposed to contain.
--
-- **A struct is a schema, so the schema is the migration.** Everything else
-- here follows from p.149's four constraints, which are stated as CHECKs and
-- in `services/ontology.py` rather than left to the writer:
--
--   * depth of one, structs cannot be nested;
--   * at least one field;
--   * fields have a name and a declared type;
--   * the field types are a fixed list, and it is *narrower* than the
--     property types this platform has.
--
-- Why the fields are a jsonb column and not a child table
-- ------------------------------------------------------
-- This is the one decision here that could reasonably have gone the other
-- way, and 0028 settles it: **property ids do not survive an edit.**
-- `update_type` deletes every row in `object_type_properties` for the type and
-- re-inserts the list it was given, which is why 0028's version snapshot keeps
-- the title property by `api_name` rather than by id. A child table keyed on
-- `object_type_properties(id)` would therefore be cascade-deleted by any
-- unrelated edit to any other property on the type - a struct's schema
-- silently emptied by renaming a neighbouring column - and keying it on
-- `(object_type_id, property_api_name)` instead would be a second identity for
-- a property, which is exactly what `object_type_series.property_api_name`'s
-- comment declines to introduce.
--
-- So the fields travel *with the property row*, the way `value_format` (0049),
-- `conditional_format` (0050) and `derivation` already do: written by
-- `_write_property_rows` from the payload, snapshotted by 0028 along with the
-- rest of the definition, and gone when the property is.
--
-- The counter-precedent is 0044, which split action parameters *out* of a JSON
-- column into their own table, and it does not apply: an action parameter is
-- named from three other places (rules, criteria, and saved Workshop modules -
-- see `actions.parameter_usages`), so it needs an identity other rows can
-- point at. Nothing points at a struct field.
--
-- What this migration deliberately does not do
-- --------------------------------------------
--   * **No per-field column mapping.** p.149's primary sentence is that
--     "struct properties are created from struct type dataset columns" - one
--     column holding the whole struct - and that is what `column_mappings`
--     already expresses. p.155's step 7 maps a datasource column per field,
--     with p.160's Automap on top; that is a mapping feature, and building it
--     here would mean a second way for a struct property to get its value
--     before there is any way to read the first.
--   * **No field-level index.** A struct is mapped `object` with
--     `enabled: false` in `instance_mapping`, alongside `json` and
--     `attachment`, so nothing filters or sorts on a field. That is Foundry's
--     own position rather than a shortcut: p.150 lists Object Explorer as
--     supporting structs with "struct field search is under development", and
--     warns in the same breath that array-of-struct queries match fields
--     independently rather than within one entry. A mapping written now would
--     have to pick a side of a question the source has not answered.
--   * **No main fields and no reducers.** `ontology` p.59 describes both -
--     a designated main field so a struct "behaves like a simple property",
--     and reducers that surface one value from a multi-valued struct. Both
--     are about *arrays* of structs, which this platform has no property type
--     for; they belong with that, not with the scalar type.
-- ============================================================================

ALTER TYPE property_data_type ADD VALUE IF NOT EXISTS 'struct';

-- **And the parameter enum, in the same breath**, which is 0047's note and
-- the reason `test_every_property_type_can_be_an_action_parameter` exists: a
-- property type no parameter can hold is a property no action could ever
-- write, and p.150 lists Actions among the applications that "use actions to
-- create and modify struct property values".
ALTER TYPE action_parameter_type ADD VALUE IF NOT EXISTS 'struct';

ALTER TABLE object_type_properties
    ADD COLUMN struct_fields jsonb;

COMMENT ON COLUMN object_type_properties.struct_fields IS
    'The declared fields of a struct property, as an ordered array of '
    '{api_name, display_name, description, data_type} (Foundry '
    '`object-link-types` p.149). NULL for every other data type, and required '
    'to be a non-empty array for `struct` - p.149 says a struct "must have at '
    'least 1 field", and a struct with no fields is a `json` property with a '
    'more specific name. Validated in `services/ontology.py`, which also '
    'holds p.149''s narrower list of field types and its refusal to nest.';
