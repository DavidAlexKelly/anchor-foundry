-- ============================================================================
-- 0116_action_log.sql
-- The action log: every submission of an action type, as an object (§554;
-- `action-types` p.167-168).
--
--     "The action log models all action submissions as object types to be
--      analyzed and displayed in object-aware Foundry tooling." (p.167)
--
--     "Action log object types map one-to-one with action types. Submitting an
--      action generates a single new object of the corresponding action log
--      object type. This newly-created object is automatically linked to all
--      edited objects." (p.167)
--
-- The log is an ordinary object type over an ordinary dataset, which is p.167's
-- whole point: once a submission is an object it can be filtered, charted and
-- linked like any other, and nothing that reads objects needs to know it is a
-- log. So this stores only which object type and link type an action type logs
-- into; the columns, the source and the join table are made by the service
-- that turns the log on, from the same calls a person would make.
--
-- `version` is p.168's "Action type version: Version number that
-- auto-increments each time an action type is updated" - bumped with the
-- definition, which is what an action *does*.
--
-- Deleting the log's object type turns the log off rather than failing the
-- next submission: SET NULL, and the action goes on without one.
-- ============================================================================

ALTER TABLE action_types
    ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    ADD COLUMN log_object_type_id uuid REFERENCES object_types(id) ON DELETE SET NULL,
    ADD COLUMN log_link_type_id uuid REFERENCES link_types(id) ON DELETE SET NULL;

ALTER TYPE dataset_origin ADD VALUE IF NOT EXISTS 'action_log';
