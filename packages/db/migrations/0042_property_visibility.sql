-- ============================================================================
-- 0042_property_visibility.sql
-- Property visibility (parity `docs/parity/ontology.md` §1.2; Foundry
-- `object-link-types` p.111).
--
-- > "Visibility: An indication to user applications for how prominently to
-- > display the property. A **prominent** property will lead applications to
-- > show this property first to users. A **hidden** property will not appear in
-- > user applications. By default, the start date property will have visibility
-- > `normal`."
--
-- **It is the input to standard Object Views, which is why it comes first.**
-- `object-views` p.10: the standard view "matches the object type's
-- configuration by spotlighting prominent properties … Normal properties are
-- displayed in a regular table, and hidden properties are not visible." Without
-- this column there is nothing for a generated view to be generated *from*, and
-- every object type would render the same undifferentiated table.
--
-- **`hidden` is a display hint, not a permission.** Foundry's own wording is
-- "an indication to user applications", and that is exactly how it is treated
-- here: a hidden property is still stored, still synced, still returned by the
-- API to anyone who may read the object type at all. Making it look like access
-- control would be worse than not having it - somebody would use it as one.
-- Access control is RLS, and it is somewhere else.
--
-- Default `normal`, so every existing property keeps rendering exactly as it
-- does today and no object type changes shape on upgrade.
-- ============================================================================

CREATE TYPE property_visibility AS ENUM ('normal', 'prominent', 'hidden');

ALTER TABLE object_type_properties
    ADD COLUMN visibility property_visibility NOT NULL DEFAULT 'normal';

COMMENT ON COLUMN object_type_properties.visibility IS
    'How prominently applications should show this property (Foundry '
    'object-link-types p.111). A display hint, never a permission - hidden '
    'properties are still stored and still returned by the API.';
