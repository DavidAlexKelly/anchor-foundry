-- ============================================================================
-- 0133_property_type_classes.sql
-- A property's type classes (§671; `object-link-types` p.91, `workshop`
-- p.222).
--
--     "Type classes: Apply type classes as additional metadata that can be
--      interpreted by applications." (object-link-types p.91)
--
--     "If your object has a property that stores a URL to an image, you can
--      add the type class hubble:icon to display the image instead of the
--      icon that was selected when setting up the object type." (workshop
--      p.222)
--
-- **Labels, not settings**: a type class says nothing to the platform that
-- stores it, and is read by whichever application knows it. So they are kept
-- as the builder wrote them, `kind:name`, and only their shape is checked
-- (`services/type_classes.py`) - which names mean anything is each reader's
-- business, and a list here of the ones that do would go stale the day an
-- application learned a new one.
--
-- An empty array means none, which is what every property has today.
-- ============================================================================

ALTER TABLE object_type_properties
    ADD COLUMN type_classes text[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN object_type_properties.type_classes IS
    'Type classes (object-link-types p.91): kind:name labels applications '
    'interpret, such as hubble:icon (workshop p.222). Shape checked in '
    'services/type_classes.py.';
