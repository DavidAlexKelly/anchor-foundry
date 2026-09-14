-- ============================================================================
-- 0088_property_reducers.sql
-- Parity `docs/parity/ontology.md` §1 ("Property reducers").
-- `object-link-types` p.131-133; db 0064's and db 0087's forward references.
--
-- > "A property reducer enables you to transform an array property into a
-- >  single value in the array for display and interface implementation
-- >  purposes. **Reduction does not change the underlying property type or
-- >  property data stored**; instead, it provides access to the reduced value
-- >  in the array when reading the property value." (p.131)
--
-- > "You can also configure **multiple reducers** using different struct fields
-- >  to handle tie-breaking scenarios." (p.133)
--
-- **The whole feature is marked [Beta] upstream** (p.131). It is built anyway
-- because it is the sentence db 0064 promised and db 0087 unblocked, but a
-- future divergence from this file should read as the specification moving
-- rather than as this platform having got it wrong.
--
-- **A declaration, not a value, and that is the reason this is a column on the
-- property rather than anything on the instance.** p.131's second sentence is
-- the whole design: nothing is written, nothing is migrated, and no stored
-- array changes shape. A reducer is a question asked at read time, which is
-- `derivation`'s shape exactly (db 0057) — and for `derivation`'s reason: a
-- materialised answer would be a second copy free to disagree with the array
-- the moment a sync rewrote it.
--
-- **jsonb holding an ordered list, not one operation and one field.** p.133
-- makes several reducers a first-class case: the first picks the extreme, and
-- the ones after it break the ties. Two scalar columns could hold the common
-- declaration and not the one p.133 names, and a `property_reducers` side
-- table would be a second place to forget about in every copy, snapshot,
-- export and version the property already travels through — which is the
-- argument db 0064 made for `struct_fields` and db 0087 for `array_of`, one
-- property-shaped declaration per column.
--
-- **No CHECK tying this to `data_type = 'array'`,** for db 0087's reason and
-- one of its own. The pairing is one of several rules
-- `services/property_reducers.py` makes together — which element types can be
-- reduced at all (p.132's two tables), which operations belong to which base
-- type, that a struct array reduces *by a field* and only by a declared one
-- (p.133), and that a tie-break that cannot break a tie is not stored — and a
-- database enforcing only the pairing would refuse one of those as a
-- constraint violation naming no field while the rest arrived as sentences.
-- ============================================================================

ALTER TABLE object_type_properties
    ADD COLUMN reducers jsonb;

COMMENT ON COLUMN object_type_properties.reducers IS
    'Ordered property reducers for an `array` property (object-link-types '
    'p.131-133), and NULL for every other type. Each entry is '
    '{operation, field}: `field` names a struct field for an array of structs '
    'and is absent otherwise. Read-time only - reduction never changes the '
    'stored value. Checked in services/property_reducers.py.';
