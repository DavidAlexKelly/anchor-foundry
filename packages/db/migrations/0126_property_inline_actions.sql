-- ============================================================================
-- 0126_property_inline_actions.sql
-- Parity `docs/parity/workshop.md` ("Property List"). `workshop` p.266,
-- `object-views` p.67, `object-link-types` p.148.
--
-- > "To enable inline editing for a property, configure an inline action for
-- >  the property in the Ontology Manager." (workshop p.266)
--
-- A property's inline action (§594): the action type an edit in place submits.
-- A column on the property, like the value type (db 0054), because it is part
-- of the property's definition and a save of the object type carries it.
-- **SET NULL when the action is deleted**: the property is still there and
-- simply not editable in place any more, which is what a property with no
-- inline action is. Whether the action still *backs* the property (it can
-- change after it is chosen) is re-read where it is used,
-- `services/property_inline_actions.py`.
-- ============================================================================

ALTER TABLE object_type_properties
    ADD COLUMN inline_action_type_id uuid REFERENCES action_types(id) ON DELETE SET NULL;

CREATE INDEX object_type_properties_inline_action_idx
    ON object_type_properties (inline_action_type_id)
    WHERE inline_action_type_id IS NOT NULL;
