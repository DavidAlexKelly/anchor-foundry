-- Grouping an action form's parameters (§328; `action-types` p.122-124).
--
--     "The action form can be customized with sections. These sections provide
--      a logical grouping of parameters to organize an action form. Sections
--      also support columns, descriptions, and conditional overrides." (p.122)
--
--     "In the Form tab, click Add section. This will open a detailed section
--      configuration modal where you can add a title, choose a column layout,
--      and optionally write a user-facing description. **The description is not
--      stylized and, unlike parameter descriptions, will always be shown in the
--      section itself, not in a tooltip.**" (p.123)
--
--     "Sections are also collapsible, can be hidden entirely… A section can be
--      hidden at first and only shown based on a prior parameter." (p.123)
--
--     "Parameters and sections display in the form based on their order in this
--      Form Content section." (p.124)
--
-- **A section is about the form, not about what the action does.** Nothing here
-- changes which parameters exist, what they mean, or what a rule writes with
-- them — an action with its sections deleted submits exactly the same values.
-- That is why this is a table beside `action_parameters` rather than columns on
-- it: a parameter belongs to at most one section, and a form with no sections
-- at all is the shape every action in this platform already has.

CREATE TABLE action_sections (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type_id uuid        NOT NULL REFERENCES action_types(id) ON DELETE CASCADE,
    -- p.123's title. Required, because p.124 says "the Form tab lists the
    -- sections with their parameters" — an untitled section is a box the
    -- builder cannot point at when they come back to it.
    title          text        NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    -- p.123's "optionally write a user-facing description", which is shown in
    -- the section rather than in a tooltip. Empty means none; the column is
    -- NOT NULL so a reader never has to tell "" from NULL for a string that
    -- means the same thing either way.
    description    text        NOT NULL DEFAULT '',
    -- p.123: "A section can be divided into one or two columns." Exactly two
    -- values, so the form cannot be asked to draw a layout nothing renders.
    columns        smallint    NOT NULL DEFAULT 1 CHECK (columns IN (1, 2)),
    -- p.123's "Sections are also collapsible". Whether it *may* be collapsed,
    -- not whether it is: the second is a fact about a reader in a moment, and
    -- storing it would make one person's form fold for everybody.
    collapsible    boolean     NOT NULL DEFAULT false,
    -- And whether it starts folded, which only means anything when it can be
    -- unfolded. A section collapsed with no way to open it would be p.123's
    -- "hidden entirely" wearing the wrong name.
    collapsed      boolean     NOT NULL DEFAULT false,
    -- p.123's "can be hidden entirely". Always hidden, regardless of anything
    -- else — the plain case that needs no condition.
    hidden         boolean     NOT NULL DEFAULT false,
    -- p.123's "A section can be hidden at first and only shown based on a
    -- prior parameter."
    --
    -- **The same condition shape `action_criteria` already stores**, rather
    -- than a second grammar: decision 0007's conditions are `{left, operator,
    -- right}` over parameters and the current user, and a form that evaluated
    -- its own dialect would be a second opinion about the same values. NULL
    -- means no condition, which is not the same as a condition that is always
    -- true — one is "always shown" and the other is "shown when nothing is
    -- false", and only the first survives a parameter being renamed.
    visible_when   jsonb,
    -- p.124's "order in this Form Content section". Sections and the
    -- parameters inside them are ordered separately, because p.124 describes
    -- dragging a parameter *into* a section: its position within the section is
    -- a different question from where the section sits in the form.
    sort_order     integer     NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    -- Two sections of one action cannot share a title: p.124's Form tab lists
    -- them by name, and two called "Details" is a list the builder cannot use.
    UNIQUE (action_type_id, title)
);

CREATE INDEX idx_action_sections_form
    ON action_sections (action_type_id, sort_order);

-- **A parameter belongs to at most one section**, which is why this is a
-- column here rather than a join table. p.124 offers two ways to put a
-- parameter in a section and neither is "in both".
--
-- `ON DELETE SET NULL`: deleting a section returns its parameters to the form
-- rather than taking them with it. A section is a way of arranging the form
-- (p.122's "logical grouping"), and an arrangement that could delete the thing
-- it arranges would make tidying a form a destructive act.
ALTER TABLE action_parameters
    ADD COLUMN section_id uuid REFERENCES action_sections(id) ON DELETE SET NULL;

CREATE INDEX idx_action_parameters_section
    ON action_parameters (section_id, sort_order)
    WHERE section_id IS NOT NULL;

CREATE TRIGGER trg_action_sections_updated
    BEFORE UPDATE ON action_sections
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE action_sections ENABLE ROW LEVEL SECURITY;

-- The action type's own isolation, reached through it: a section has no
-- workspace of its own and inventing one would be a second answer to who may
-- see it.
CREATE POLICY action_sections_isolation ON action_sections
    USING (EXISTS (SELECT 1 FROM action_types at
                    WHERE at.id = action_sections.action_type_id
                      AND at.workspace_id = ANY (rls_workspace_ids())));

GRANT SELECT, INSERT, UPDATE, DELETE ON action_sections TO platform_app;

COMMENT ON TABLE action_sections IS
    'p.122-124''s form sections (db 0081). A logical grouping of an action''s '
    'parameters with a title, an optional always-shown description, one or two '
    'columns, and p.123''s hiding — plain or conditional on a prior parameter. '
    'Nothing here changes what the action does.';
