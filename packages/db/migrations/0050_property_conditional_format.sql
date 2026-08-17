-- ============================================================================
-- 0050_property_conditional_format.sql
-- Conditional formatting (parity `docs/parity/ontology.md` §1.2; Foundry
-- `object-link-types` p.102-109).
--
-- > "Conditional formatting enables the configuration of rules for any
-- > property and dictates how that property's values will be rendered (e.g.
-- > coloring, alignment, etc.) in user facing applications. When you configure
-- > conditional formatting in the Ontology Manager, the formatting rules will
-- > apply in Object Explorer, Object Views, Quiver, and Workshop." (p.102)
--
-- **The sibling of 0049, and deliberately a separate column.** Value
-- formatting decides what a value *says*; a conditional rule decides how it
-- *looks*. p.102's own example has both on one property - a number shown
-- compactly and coloured red below a threshold - so one column holding both
-- would make "clear the formatter" and "clear the colours" the same edit.
--
-- **An ordered list, and the order is the semantics.** p.105 describes an
-- "Always true" rule used "as a fallback in case your other rules don't
-- match", which only means anything if rules are tried in sequence and the
-- first match wins. A `jsonb` array keeps that order; a table of rules with no
-- explicit rank would not, and a rank column is an ordering nobody can see
-- while editing.
--
-- **A rule's logic can read a different property than the one it paints**
-- (p.105-106: "this dropdown allows you to choose to apply the rule based on
-- the value of another property … the color would still show on Type"). So a
-- rule carries a property name, and whether that name exists is checked in
-- `services/conditional_format.py` against the type being saved - which is why
-- the check is not a constraint here: SQL cannot see the sibling rows of the
-- object type in the middle of the same statement that writes them.
--
-- NULL means no rules, which is every property today.
-- ============================================================================

ALTER TABLE object_type_properties
    ADD COLUMN conditional_format jsonb;

COMMENT ON COLUMN object_type_properties.conditional_format IS
    'Ordered conditional formatting rules; first match wins (Foundry '
    'object-link-types p.102-109). Presentation only - the rules are evaluated '
    'in the browser against the *raw* property value, never against the text '
    'value formatting produced. NULL means no rules. Shape and cross-property '
    'references validated in services/conditional_format.py.';
