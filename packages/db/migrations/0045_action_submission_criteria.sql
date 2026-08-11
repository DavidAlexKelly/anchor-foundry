-- ============================================================================
-- 0045_action_submission_criteria.sql
-- Decision `docs/decisions/0007-action-parameters-and-rules.md`; parity
-- `docs/parity/ontology.md` §5; Foundry `action-types` p.49-56 and p.140.
--
-- > "Submission criteria (formerly known as validations) are the conditions
-- > that determine whether an action can be submitted... Actions can only be
-- > submitted if **all** the submission criteria are met." (p.49, p.50)
--
-- The first thing that needed parameters (0044) and could not exist without
-- them: a criterion is a condition over *inputs*, and until inputs had a name
-- there was nothing to write one about.
--
-- **A criterion is one condition, and every row must pass.** p.50 describes
-- conditions combined by logical operators (all / any / none, nestable); this
-- table stores the root level only, and the list is an implicit ALL - which is
-- p.50's own default and the only combination our executor evaluates. Nesting
-- is a `config` shape away and deliberately not invented before something asks
-- for it.
--
-- **`message` is Foundry's failure message** (p.56): "Every condition and
-- logical operator on the root level has its own failure message... The failure
-- message informs the user about why they are blocked from submitting an
-- Action." NOT NULL and non-empty, because a criterion that refuses without
-- saying why is the greyed-out button with no explanation that p.56 exists to
-- prevent.
--
-- **`config` is the condition**, validated in Python at save time, same
-- arrangement as `action_rules.config` and `workshop_events`:
--
--   {"left":     {"kind": "parameter", "parameter": "status"}
--             |  {"kind": "current_user", "attribute": "id" | "group_ids"},
--    "operator": "is" | "is_not" | "matches" | "is_less_than"
--             |  "is_greater_than_or_equals" | "includes" | "is_included_in",
--    "right":    {"kind": "value", "value": <json>}
--             |  {"kind": "parameter", "parameter": "reason"}
--             |  {"kind": "none"}}
--
-- The operator names are p.54's and p.55's, unchanged, because a builder
-- reading Foundry's table should find the same words here. `{"kind": "none"}`
-- is p.55's "no value", which "checks whether the first value is empty (or
-- null)".
--
-- **`current_user` is not decoration.** p.140: "Action submission criteria
-- allow for fine-grained control over who can run an action. Simple submission
-- criteria can require a specific user ID or group ID and can be combined with
-- information from parameters." It is the mechanism Foundry uses for per-action
-- permissions, and we already know the submitting user and their groups.
--
-- **Not built here, and named rather than assumed:** nesting (any / none),
-- multipass attributes beyond id and group membership, and criteria over
-- linked or shared objects (p.138). The first is a config shape; the second
-- needs attributes we do not have; the third needs the object-set half of an
-- action, which is §5's later work.
-- ============================================================================

CREATE TABLE action_criteria (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type_id  uuid NOT NULL REFERENCES action_types(id) ON DELETE CASCADE,
    message         text NOT NULL CHECK (length(message) BETWEEN 1 AND 500),
    config          jsonb NOT NULL,
    sort_order      integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_action_criteria_type ON action_criteria (action_type_id, sort_order);

CREATE TRIGGER trg_action_criteria_updated BEFORE UPDATE ON action_criteria
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN action_criteria.message IS
    'Foundry p.56 failure message: what the user is told when this criterion '
    'blocks submission. Required - a refusal with no reason is the problem, '
    'not the feature.';

-- Same shape as action_parameters and action_rules (0044): visible when the
-- action type is.
ALTER TABLE action_criteria ENABLE ROW LEVEL SECURITY;
CREATE POLICY action_criteria_isolation ON action_criteria
    USING (EXISTS (SELECT 1 FROM action_types at
                   WHERE at.id = action_type_id
                     AND rls_can_access_workspace(at.workspace_id)));
