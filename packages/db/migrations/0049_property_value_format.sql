-- ============================================================================
-- 0049_property_value_format.sql
-- Value formatting (parity `docs/parity/ontology.md` §1.2; Foundry
-- `object-link-types` p.94-101).
--
-- > "Value formatting refers to applying a special formatter to the value of a
-- > property, transforming the raw value to a more readable version. In the
-- > image below, the left-hand side (Before) shows the weight and value columns
-- > without any formatting. The right-hand side (After) has a unit ("kg")
-- > applied to the weight column and the value column is displayed in a more
-- > compact form with a currency sign ("$100K")." (p.94)
--
-- **A presentation rule, stored beside the property and applied at render.**
-- The raw value is untouched: filters, actions, aggregations and exports go on
-- reading the number 100000, and only what a person looks at says "$100K".
-- Storing the formatted string instead would be the same mistake as storing a
-- rendered date - it makes every consumer that is not a screen wrong, and it
-- cannot be undone once a sync has written it.
--
-- **One nullable jsonb column rather than fifteen typed ones.** p.97-99 list
-- around a dozen options across two families that share almost nothing:
-- `currency` means nothing to a timestamp and `timezone` means nothing to a
-- number. Fifteen columns, all NULL for every property that formats the other
-- way, would encode "these do not apply" as an absence rather than as a shape.
-- The shape is validated in `services/value_format.py`, which is where the
-- base-type rules live too - a CHECK constraint cannot see `data_type`'s
-- family without repeating the classification in SQL, and a second copy of it
-- is a second thing to keep in step.
--
-- NULL means unformatted, which is what every property is today - so nothing
-- renders differently until somebody asks for it.
-- ============================================================================

ALTER TABLE object_type_properties
    ADD COLUMN value_format jsonb;

COMMENT ON COLUMN object_type_properties.value_format IS
    'How applications should render this property''s value (Foundry '
    'object-link-types p.94-101). A presentation rule applied at render - the '
    'stored value stays raw, so filters and actions are unaffected. NULL means '
    'no formatting. Shape validated in services/value_format.py, which also '
    'enforces that the formatter matches the property''s base type.';
