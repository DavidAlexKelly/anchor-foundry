-- ============================================================================
-- 0057_object_type_visibility.sql
-- An object type's visibility (parity `docs/parity/ontology.md` §1.3; Foundry
-- `object-link-types` p.255).
--
-- > "Visibility: Setting an object type's status to `promoted` will
-- > automatically set its visibility to `prominent`, increasing its
-- > discoverability across the platform." (p.255)
--
-- §170 read p.255 for its `promoted`-scope sentence and stopped there; this is
-- the sentence beside it. The rule needs somewhere to put the answer, and an
-- object type had no visibility of its own - `property_visibility` has existed
-- since 0003 but only ever on `object_type_properties`.
--
-- Reusing the property enum rather than declaring a second one
-- -----------------------------------------------------------
-- The values are the same three, and two enums holding the same values would
-- be two spellings of one idea - the redundancy §170 deleted a `CONTAGIOUS`
-- list for. A visibility means the same thing here as it does on a property:
-- how prominently an application should show the thing. What differs is only
-- what is being shown.
--
-- `hidden` is legal here because the enum has it, and is deliberately not
-- offered by the API: p.111's hidden is a statement about a column an
-- application should not draw, and nothing in `object-link-types` describes
-- hiding a whole object type. A value the schema can hold and the service
-- refuses is the safer direction - the reverse would need a migration the day
-- somebody found a use for it.
-- ============================================================================

ALTER TABLE object_types
    ADD COLUMN visibility property_visibility NOT NULL DEFAULT 'normal';

COMMENT ON COLUMN object_types.visibility IS
    'How prominently applications should surface this object type (Foundry '
    'object-link-types p.255). Set to `prominent` automatically when the '
    'status becomes `promoted`, and never lowered by a later demotion - see '
    'services/ontology_status.visibility_for.';
