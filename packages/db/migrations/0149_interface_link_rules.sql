-- ============================================================================
-- 0149_interface_link_rules.sql
-- Decision 0024 §3; parity `docs/parity/ontology.md` §5 (Actions on
-- interfaces); Foundry `action-types` p.63-64 (§761).
--
-- > "'Create interface link' rules allow you to create links using an
-- > interface link constraint defined on an interface." (p.63)
-- > "'Delete interface link' rules allow you to delete links using an
-- > interface link constraint defined on an interface." (p.64)
--
-- Two rule kinds an action on an interface may carry. At submission each is
-- renamed into `create_link` / `delete_link` rules on the concrete link types
-- the object's own type keeps the constraint with (db 0148), so the executor
-- that writes links is the one there already was.
-- ============================================================================

ALTER TYPE action_rule_kind ADD VALUE IF NOT EXISTS 'create_interface_link';
ALTER TYPE action_rule_kind ADD VALUE IF NOT EXISTS 'delete_interface_link';
