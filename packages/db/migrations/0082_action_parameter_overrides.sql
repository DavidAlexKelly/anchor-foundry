-- Changing a parameter under specific circumstances (§329; `action-types` p.43-46).
--
--     "Overrides are used to change a parameter's behavior and configuration
--      under specific circumstances. Using overrides, parameters and forms can
--      become more flexible, removing the need to configure separate action
--      types with only minor variations." (p.43)
--
--     "For example, let's assume that you have an action type which changes the
--      status of a support ticket object and you want to restrict action
--      submission to managers and assignees. While assignees can change the
--      status, managers will have to provide a justification. Using overrides,
--      the Justification reason parameter can be made **required and visible
--      for managers, while it is hidden and optional for the assignee**." (p.43)
--
--     "An override block presents the basis for overrides. It defines both the
--      conditions (shown in the "if" part) and the overrides (shown in the
--      "then" part)… Every parameter can contain multiple override blocks,
--      however, **if more than one is true, only the first one will be
--      executed**." (p.45)
--
--     "An override can change the configuration of the parameter's constraints,
--      visibility, requiredness, and default values." (p.45)
--
-- **This is not §328 one table along, and the difference is the whole point.**
-- A section changes what a form *looks like* and nothing else; an override
-- changes what the action *asks for*. p.43's own example makes a parameter
-- required for one person and optional for another — so `bind_parameters` has
-- to resolve these before it decides whether a submission is complete, and a
-- form that applied them for drawing only would let a manager submit without
-- the justification p.43 says they owe.
--
-- That is why this hangs off `action_parameters` rather than off a form: the
-- same resolution runs for a submission that never went near a screen.

CREATE TABLE action_parameter_overrides (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    parameter_id uuid        NOT NULL REFERENCES action_parameters(id) ON DELETE CASCADE,
    -- p.45-46: "if more than one is true, only the first one will be executed",
    -- said twice on two pages. The order is the rule, not a presentation
    -- detail, so it is stored rather than derived from anything.
    sort_order   integer     NOT NULL DEFAULT 0,
    -- p.45's "if" part: "Each block can contain one or multiple conditions."
    --
    -- **decision 0007's conditions, the same list `action_criteria` stores** —
    -- p.45 says so in as many words ("see the submission criteria
    -- documentation on conditions") and names exactly one difference, which is
    -- a refusal at save time rather than a different shape: only parameters
    -- above this one in the form may be referenced.
    --
    -- A JSON array rather than a child table: a block's conditions are read,
    -- evaluated and replaced together, and a block with none is a block that
    -- is always true — which p.45 does not offer and `replace_overrides`
    -- refuses, because "always" is what a parameter's own configuration is for.
    conditions   jsonb       NOT NULL DEFAULT '[]'::jsonb,
    -- p.45's "then" part. **NULL means "leave this alone"**, which is not the
    -- same as false: p.43's justification is made *required and visible* by one
    -- block, and a block that only hid something would otherwise silently
    -- un-require it as well. Every override is a change somebody asked for.
    set_hidden   boolean,
    set_required boolean,
    -- And the default value, where NULL is again "leave alone". p.45 lists
    -- default values among what an override may change, and the column cannot
    -- express "clear the default" for the same reason `action_parameters`
    -- cannot (0044): nothing can say JSON null and mean it. When something
    -- can, both columns need the same companion flag.
    set_default  jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_action_parameter_overrides_parameter
    ON action_parameter_overrides (parameter_id, sort_order);

CREATE TRIGGER trg_action_parameter_overrides_updated
    BEFORE UPDATE ON action_parameter_overrides
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE action_parameter_overrides ENABLE ROW LEVEL SECURITY;

-- The action type's isolation, reached through the parameter that owns it — the
-- same two-hop `action_sections` makes in one (db 0081). An override has no
-- workspace of its own and inventing one would be a second answer to who may
-- see it.
CREATE POLICY action_parameter_overrides_isolation ON action_parameter_overrides
    USING (EXISTS (SELECT 1
                     FROM action_parameters ap
                     JOIN action_types at ON at.id = ap.action_type_id
                    WHERE ap.id = action_parameter_overrides.parameter_id
                      AND at.workspace_id = ANY (rls_workspace_ids())));

GRANT SELECT, INSERT, UPDATE, DELETE ON action_parameter_overrides TO platform_app;

COMMENT ON TABLE action_parameter_overrides IS
    'p.43-46''s override blocks (db 0082). An ordered list per parameter; the '
    'first block whose conditions all hold is the only one applied (p.45). '
    'Unlike a section (db 0081) this changes what the action asks for, not '
    'how the form looks — so it is resolved before a submission is bound.';
