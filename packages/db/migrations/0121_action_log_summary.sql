-- ============================================================================
-- 0121_action_log_summary.sql
-- Parity `docs/parity/ontology.md` §4 ("Action log"). `action-types` p.168.
--
--     "[Optional] Summary: A customizable string to describe the action
--      [Optional] Property values of object reference parameters (this is not
--      supported for object reference parameters if allow multiple values is
--      enabled)" (p.168)
--
-- Two settings on the action type the log belongs to (db 0116), because they
-- decide what each submission writes:
--
-- * `log_summary`: the template, in p.92's triple handlebars, rendered from the
--   objects as they were before the action's edits. NULL writes no summary.
-- * `log_reference_properties`: `{object parameter: [property]}` whose values
--   each submission keeps, one log column per pair, fixed when the log is made.
--
-- Checked in `services/action_log`, with sentences.
-- ============================================================================

ALTER TABLE action_types
    ADD COLUMN log_summary text,
    ADD COLUMN log_reference_properties jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN action_types.log_summary IS
    'action-types p.168: the action log''s Summary template (triple '
    'handlebars, p.92). NULL writes none.';
COMMENT ON COLUMN action_types.log_reference_properties IS
    'action-types p.168: {object parameter: [property]} whose pre-edit values '
    'each action log entry keeps.';
