-- ============================================================================
-- 0052_derived_properties.sql
-- Derived properties (parity `docs/parity/ontology.md` §1.2; Foundry
-- `object-link-types` p.143-148).
--
-- > "Derived properties are properties that are calculated at runtime based on
-- > values from linked objects. Instead of storing data directly, a derived
-- > property pulls information from objects connected through link types,
-- > optionally applying aggregations like averaging, counting, or collecting
-- > values into lists." (p.143)
--
-- **Nothing is stored under a derived property, and that is the point.** It is
-- a *question* about linked objects, answered when somebody reads the object -
-- so this column holds the question, and `object_instances.properties` never
-- gains a key for it. A materialised copy would be a second answer free to
-- disagree with the first the moment a linked object changed, which is exactly
-- what "calculated at runtime" rules out.
--
-- The shape is a link chain (p.147: up to three hops), an aggregation
-- (p.145's nine), and the property at the far end (p.146). One jsonb column
-- for `value_format`'s reason: the fields are per-aggregation - a collection
-- limit means nothing to a `count` - so typed columns would encode "does not
-- apply" as an absence rather than as a shape.
--
-- **It is the third `NULL means no` column on this table**, beside
-- `value_format` and `conditional_format`, and deliberately not folded in with
-- them: those two say how a value is *shown*, this says where the value comes
-- from at all. Clearing a formatter and deleting a property's source are not
-- the same edit and must not be the same field.
-- ============================================================================

ALTER TABLE object_type_properties
    ADD COLUMN derivation jsonb;

COMMENT ON COLUMN object_type_properties.derivation IS
    'Where a derived property gets its value (Foundry object-link-types '
    'p.143-148): a chain of up to three link types, an aggregation, and the '
    'property at the far end. Evaluated at read time and never stored on the '
    'instance. NULL means an ordinary property backed by a dataset column. '
    'Shape validated in services/derived_properties.py.';
