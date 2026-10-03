-- ============================================================================
-- 0139_shared_property_type_classes.sql
-- A shared property's type classes (§723; `object-link-types` p.181, p.188).
--
--     "A shared property can be configured with a subset of regular property
--      metadata: … Type classes: Additional metadata that are interpreted by
--      user applications." (p.181)
--
--     "You can still add, delete, or edit type classes. When the property is
--      loaded, the resulting set of type classes will be a union of those
--      from the property and its associated shared property." (p.188)
--
-- **Kept apart, joined on read.** An attached property stores only its own
-- classes (db 0133's column) and this column holds the shared property's; the
-- union is taken when the property is loaded, which is p.188's word for it.
-- Storing the union instead would make a class removed from the shared
-- property stay on every object type that had ever been saved while it was
-- there.
--
-- Same shape and rules as db 0133: `kind:name`, checked in
-- `services/type_classes.py`. An empty array means none.
-- ============================================================================

ALTER TABLE shared_properties
    ADD COLUMN type_classes text[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN shared_properties.type_classes IS
    'Type classes (object-link-types p.181): kind:name labels applications '
    'interpret. An attached property loads the union of these and its own '
    '(p.188). Shape checked in services/type_classes.py.';
