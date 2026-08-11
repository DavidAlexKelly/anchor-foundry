-- ============================================================================
-- 0044_action_parameters_and_rules.sql
-- Decision `docs/decisions/0007-action-parameters-and-rules.md`; parity
-- `docs/parity/ontology.md` §5; Foundry `action-types` p.25 and p.75.
--
-- **Our action model had no word for "what the user typed."**
-- `action_types.editable_properties` was a list of property names, and
-- executing an action posted `{property: value}` with each value written to
-- the property of the same name. The input *was* the output: one list played
-- both parts, and there was nowhere to put anything that was not literally a
-- property being overwritten. Foundry separates them:
--
-- > "**Parameters** are the inputs of an action type. They are the interface
-- > between the Rules and other Foundry applications... Parameters are treated
-- > like variables that contain external values." (p.25)
--
-- > "In an action type, **rules** define the ways objects should change when
-- > the action is applied." (p.75)
--
-- Every remaining feature in `ontology.md` §5 - defaults, submission criteria,
-- creating and deleting objects and links, editing several objects at once -
-- hangs off that distinction and is unbuildable without it.
--
-- ---------------------------------------------------------------------------
-- **The conversion is total and changes nothing**, which is the property that
-- makes this migration safe to run on a live database. Each name in
-- `editable_properties` becomes exactly one parameter, named after the
-- property, of the property's own type - plus one `modify_object` rule writing
-- that parameter into that property. That is what the old column *meant*,
-- spelled out, so `{property: value}` and `{parameter: value}` are the same
-- wire shape by construction and every saved Workshop `run_action` effect
-- keeps working untouched.
--
-- Two details of the conversion are load-bearing:
--
--   * **Converted parameters are `required = false`.** The old executor
--     accepted a subset of the editable properties - submitting one of three
--     was a legal action. A conversion that marked them required would refuse
--     calls that work today, which is exactly the kind of "no behaviour change"
--     that is not one.
--
--   * **A name that is no longer a property still converts**, as a `string`
--     parameter. `editable_properties` was validated at create time and
--     nothing re-validated it afterwards, so a property renamed or deleted
--     since (§38 makes both possible) leaves a name behind. Dropping it here
--     would quietly change what an action accepts; keeping it preserves the
--     status quo, and the executor refuses the write for the same reason it
--     always did - no mapped dataset column.
--
-- ---------------------------------------------------------------------------
-- **Why a separate enum for parameter types.** `property_data_type` is the
-- vocabulary the ontology already has, and p.25 needs one word it does not
-- contain: `object`, for a parameter that takes an object rather than a scalar
-- ("the object type parameter will take the value of a selected Ticket
-- object"). Adding `object` to `property_data_type` would make it legal to
-- declare an object *property* of type object, which means nothing. So the two
-- are separate types with a deliberate overlap, and
-- `tests/test_action_parameters.py` asserts every `property_data_type` label
-- exists here - the same drift guard the mirrored connector registries carry,
-- because a property type this table cannot express would be a property no
-- action could ever write.
-- ============================================================================

CREATE TYPE action_parameter_type AS ENUM
    ('string', 'integer', 'float', 'boolean', 'date', 'timestamp',
     'geopoint', 'json', 'attachment', 'object');

CREATE TYPE action_rule_kind AS ENUM
    ('modify_object', 'create_object', 'delete_object', 'create_link', 'delete_link');

COMMENT ON TYPE action_rule_kind IS
    'Foundry p.75 "simple rules". Deliberately a closed vocabulary rather than '
    'an expression language: p.75 answers the cases simple rules cannot cover '
    'with functions, which are out of scope for this build.';

-- ---------------------------------------------------------------------------
-- Parameters - the inputs.
-- ---------------------------------------------------------------------------
CREATE TABLE action_parameters (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type_id  uuid NOT NULL REFERENCES action_types(id) ON DELETE CASCADE,
    api_name        text NOT NULL CHECK (api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    display_name    text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    data_type       action_parameter_type NOT NULL,
    required        boolean NOT NULL DEFAULT false,
    -- NULL means "no default", which is not the same as a default of JSON
    -- null. Nothing distinguishes them today because nothing can express a
    -- null default; when something can, this column needs a companion flag
    -- rather than a cleverer encoding.
    default_value   jsonb,
    -- p.25: "each parameter can be individually configured as to whether they
    -- are exposed in the form or not". Not decoration - p.25's own second
    -- example passes a *previous* value into a hidden parameter so that a rule
    -- can compare against it.
    hidden          boolean NOT NULL DEFAULT false,
    sort_order      integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (action_type_id, api_name)
);

CREATE INDEX idx_action_parameters_type ON action_parameters (action_type_id, sort_order);

CREATE TRIGGER trg_action_parameters_updated BEFORE UPDATE ON action_parameters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Rules - what the action does with them.
-- ---------------------------------------------------------------------------
CREATE TABLE action_rules (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type_id  uuid NOT NULL REFERENCES action_types(id) ON DELETE CASCADE,
    kind            action_rule_kind NOT NULL,
    -- Shape depends on `kind`, validated in services/actions.py at save time -
    -- the same arrangement workshop_events already uses for effects, and for
    -- the same reason: one place decides what a config means, and a second set
    -- of rules in the type system would be a second thing to keep in step.
    -- `modify_object` is {"property": <api_name>, "parameter": <api_name>}.
    config          jsonb NOT NULL DEFAULT '{}'::jsonb,
    sort_order      integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_action_rules_type ON action_rules (action_type_id, sort_order);

CREATE TRIGGER trg_action_rules_updated BEFORE UPDATE ON action_rules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Both follow action_runs (0013): the row is visible when its action type is.
-- `action_types`' own policy is workspace-based, so this does not hit the
-- fail-closed trap that RLS-reading-RLS has caused three times (0008, 0009,
-- 0015) - there is no case where the action type is legitimately hidden from
-- somebody who may see its parameters.
ALTER TABLE action_parameters ENABLE ROW LEVEL SECURITY;
CREATE POLICY action_parameters_isolation ON action_parameters
    USING (EXISTS (SELECT 1 FROM action_types at
                   WHERE at.id = action_type_id
                     AND rls_can_access_workspace(at.workspace_id)));

ALTER TABLE action_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY action_rules_isolation ON action_rules
    USING (EXISTS (SELECT 1 FROM action_types at
                   WHERE at.id = action_type_id
                     AND rls_can_access_workspace(at.workspace_id)));

-- ---------------------------------------------------------------------------
-- The conversion.
-- ---------------------------------------------------------------------------
-- `editable_properties` was a plain jsonb array and nothing uniqued it, so a
-- duplicate name is possible. `DISTINCT ON` keeps the first occurrence and its
-- position, which is what the old executor did with it too: a dict keyed by
-- property name collapsed the duplicate long before anything was written. Both
-- inserts read this one list so a parameter and its rule cannot disagree.
CREATE TEMP TABLE _converted_editable AS
SELECT DISTINCT ON (at.id, prop.name)
       at.id AS action_type_id,
       at.object_type_id,
       prop.name AS api_name,
       prop.ord::integer AS sort_order
  FROM action_types at
  CROSS JOIN LATERAL
       jsonb_array_elements_text(at.editable_properties) WITH ORDINALITY AS prop(name, ord)
 ORDER BY at.id, prop.name, prop.ord;

INSERT INTO action_parameters
    (action_type_id, api_name, display_name, data_type, required, sort_order)
SELECT c.action_type_id,
       c.api_name,
       COALESCE(NULLIF(p.display_name, ''), c.api_name),
       COALESCE(p.data_type::text, 'string')::action_parameter_type,
       false,
       c.sort_order
  FROM _converted_editable c
  LEFT JOIN object_type_properties p
         ON p.object_type_id = c.object_type_id AND p.api_name = c.api_name;

INSERT INTO action_rules (action_type_id, kind, config, sort_order)
SELECT c.action_type_id,
       'modify_object',
       jsonb_build_object('property', c.api_name, 'parameter', c.api_name),
       c.sort_order
  FROM _converted_editable c;

-- Dropped rather than left to `ON COMMIT DROP`: the runner applies every
-- pending migration in one session, and a temp table outliving its migration
-- is a name the next one could collide with.
DROP TABLE _converted_editable;

ALTER TABLE action_types DROP COLUMN editable_properties;
