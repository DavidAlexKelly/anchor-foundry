-- ============================================================================
-- 0150_interface_action_control.sql
-- Parity `docs/parity/ontology.md` §5 (Actions on interfaces: "○ still:
-- p.65's Interface action control"); Foundry `action-types` p.65 (§763).
--
-- > "To restrict access, disable interface actions for specific object types
-- > in Ontology Manager by selecting its Interfaces tab and establishing
-- > control over actions inherited from an interface in the Interface action
-- > control section." (p.65)
--
-- A row is one interface action an object type has switched off for its own
-- objects: not offered among its actions, and refused if submitted against
-- one. No row is the default, which is p.64's: an interface action applies to
-- every implementing type.
-- ============================================================================

CREATE TABLE interface_action_controls (
    object_type_id  uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    action_type_id  uuid NOT NULL REFERENCES action_types(id) ON DELETE CASCADE,
    created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type_id, action_type_id)
);

CREATE INDEX idx_interface_action_controls_action
    ON interface_action_controls (action_type_id);

-- Visible when the object type is, as its implementations are (db 0065).
ALTER TABLE interface_action_controls ENABLE ROW LEVEL SECURITY;
CREATE POLICY interface_action_controls_isolation ON interface_action_controls
    USING (EXISTS (SELECT 1 FROM object_types ot WHERE ot.id = object_type_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON interface_action_controls TO platform_app;
