-- ============================================================================
-- 0141_link_action_type_classes.sql
-- Type classes on link types and action types (§730; `object-link-types`
-- p.235).
--
--     "Type classes can be applied to properties, link types, and action
--      types." (p.235)
--
-- db 0133 gave properties theirs. p.236-246's table names classes of each
-- kind (`hierarchy:parent` on a link type, `actions:generate_uuid` on an
-- action type), and its Description column is cut off in the corpus - so,
-- as for a property's, they are labels each reading application interprets,
-- kept as written in `kind:name` and checked for that shape only
-- (`services/type_classes.py`).
-- ============================================================================

ALTER TABLE link_types
    ADD COLUMN type_classes text[] NOT NULL DEFAULT '{}';

ALTER TABLE action_types
    ADD COLUMN type_classes text[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN link_types.type_classes IS
    'Type classes (object-link-types p.235): kind:name labels applications '
    'interpret, such as hierarchy:parent. Shape checked in '
    'services/type_classes.py.';
COMMENT ON COLUMN action_types.type_classes IS
    'Type classes (object-link-types p.235): kind:name labels applications '
    'interpret, such as actions:generate_uuid. Shape checked in '
    'services/type_classes.py.';
