-- ============================================================================
-- 0087_array_properties.sql
-- Parity `docs/parity/ontology.md` §1.1 ("Arrays of any base type").
-- `object-link-types` p.86, p.116; and db 0064's own forward reference.
--
-- > "Array — valid as title key: Yes. Valid as primary key: No. Array
-- >  properties cannot contain null elements. If the inner type of the Array
-- >  is not a valid title property, the Array property also cannot be used as
-- >  the title property." (p.86)
--
-- > "Array properties cannot be empty: Setting an array property to required
-- >  ensures the presence of at least one item." (p.116)
--
-- **An array is the first property type whose label does not name its type.**
-- Every other base type here is total: `integer` says everything there is to
-- know about what an `integer` property holds. An array holds *something
-- else*, so the declaration needs a second field — the same shape `struct`
-- needed in db 0064, and the reason that migration wrote "main fields and
-- reducers are about *arrays* of structs, which this platform has no property
-- type for; they belong with that".
--
-- **A column rather than a label per inner type.** `array_of_string`,
-- `array_of_integer` and the rest would be nine more enum labels for one
-- concept, and every list in the codebase that enumerates property types —
-- `ontology.PROPERTY_TYPES`, `instance_mapping.FIELD_TYPES`, the editor's
-- dropdown, the interface vocabulary — would have to carry all of them. One
-- label and one column keeps "is this an array" and "of what" as the two
-- separate questions they are.
--
-- **No CHECK tying the column to the label, for the reason 0064 had none.**
-- The obvious constraint — `array_of IS NOT NULL` exactly when
-- `data_type = 'array'` — cannot be written here: PostgreSQL refuses to use an
-- enum value added in the same transaction, and this file adds `'array'` a few
-- lines up. It could be spelled `data_type::text = 'array'` to dodge that, and
-- it is still not written, because the rule it would enforce is one of four
-- that `services/array_properties.py` makes together (which inner types are
-- allowed, no nesting, no time series, and the pairing) — and a database that
-- enforced the fourth alone would refuse a row with a sentence naming no field
-- while the other three arrived as sentences that do.
--
-- **Both enums, in the same breath**, which is 0047's note and 0064's: a
-- property type no action parameter can hold is a property no action could
-- ever write, and `test_every_property_type_can_be_an_action_parameter` fails
-- until both carry it. The label being *storable* is not the same as an array
-- parameter being *offered*: `_UNSUPPORTED_PARAMETER_TYPES` refuses one at
-- save time with a sentence, exactly as it refuses a struct, until p.36's
-- ObjectReference-list parameter is built.
-- ============================================================================

ALTER TYPE property_data_type ADD VALUE IF NOT EXISTS 'array';
ALTER TYPE action_parameter_type ADD VALUE IF NOT EXISTS 'array';

ALTER TABLE object_type_properties
    ADD COLUMN array_of property_data_type;

COMMENT ON COLUMN object_type_properties.array_of IS
    'The element type of an `array` property (object-link-types p.86), and '
    'NULL for every other type. Checked in services/array_properties.py: no '
    'nesting, no time series, and NULL exactly when the property is not an '
    'array.';
