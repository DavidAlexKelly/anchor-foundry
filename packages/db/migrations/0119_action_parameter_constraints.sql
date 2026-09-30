-- ============================================================================
-- 0119_action_parameter_constraints.sql
-- Parity `docs/parity/ontology.md` §4 ("Parameter configuration overrides"
-- and "Constrain a parameter's values"). `action-types` p.8, p.45, p.71.
--
--     "Select the Priority parameter to limit the values it can take on.
--      Change the constraints from User input to Multiple choice… Add P0, P1
--      and P2 as options." (p.8)
--
--     "Constraints can be configured individually for struct parameter
--      fields, as with regular parameters. For example, a string length
--      constraint…" (p.71)
--
--     "An override can change the configuration of the parameter's
--      constraints, visibility, requiredness, and default values." (p.45)
--
-- **A parameter's constraint is a value type's constraint** (db 0053,
-- `object-link-types` p.233): one of a fixed list, within a range (a string's
-- *length*, as p.71's example has it), matching a pattern, or a UUID. The
-- shape and the checks are `services/value_constraints.py`'s, so a parameter
-- and a value type cannot mean two different things by "between 10 and 500".
--
-- NULL is p.8's **User input**: whatever is typed. No CHECK here, for db
-- 0053's reason: which kinds a type may carry is a rule with sentences, in
-- `services/action_constraints.py`.
--
-- And p.45's fourth overridable thing, which db 0082 named as absent because
-- the thing it would override was: `set_constraint`, NULL for "leave alone".
-- An override cannot *remove* a constraint, for the reason db 0082 gives about
-- `set_default` - nothing can say JSON null and mean it.
-- ============================================================================

ALTER TABLE action_parameters
    ADD COLUMN value_constraint jsonb;

ALTER TABLE action_parameter_overrides
    ADD COLUMN set_constraint jsonb;

COMMENT ON COLUMN action_parameters.value_constraint IS
    'action-types p.8 and p.71: what values this parameter accepts, in '
    'value_constraints'' shape (enum, range, regex, uuid). NULL is p.8''s '
    '"User input". Checked in services/action_constraints.';

COMMENT ON COLUMN action_parameter_overrides.set_constraint IS
    'p.45: the constraint this block puts in place of the parameter''s own. '
    'NULL leaves it alone.';
