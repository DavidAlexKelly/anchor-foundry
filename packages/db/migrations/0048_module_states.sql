-- ============================================================================
-- 0048_module_states.sql
-- Parity `docs/parity/workshop.md` §7; Foundry `workshop` p.200-206.
--
-- > "State saving is a powerful Workshop feature that allows module consumers
-- > to store the current state of their work within a module and then either
-- > return to that saved state or share the saved state with other users."
-- > (p.200)
--
-- **A saved state is the third consumer of an external ID**, after embedding
-- (p.163) and routing (p.198). p.203 is explicit that this is the storage key:
--
-- > "Variable values are stored within a saved state via their external ID. As
-- > a result, modifying a variable's external ID after state saving has been
-- > configured may cause previously configured states to reload
-- > unsuccessfully."
--
-- So `values` is keyed by external ID and not by variable id, and that is a
-- feature rather than an accident - p.203's own example is a module whose
-- Object Dropdown becomes an Object Selection, "and state saving will continue
-- to work as long as the output object set from those widgets uses the same
-- external ID". A state survives the module being rebuilt around it.
--
-- **Values, not a rendering.** What is stored is what the viewer had chosen;
-- everything derived is recomputed on open, by the same evaluator that
-- computes it on any other viewing (decision 0002 §3: values are never
-- persisted *by the module*). A state is the one place a value is written
-- down, and it is written down because a person asked for it by name.
--
-- **Which values are savable is decided in Python**, against the module
-- document, the same arrangement `object_type_views.subject_variable` uses:
-- the enablement lives on the variable, and variables live in a jsonb
-- document this schema deliberately does not interpret.
-- ============================================================================

CREATE TABLE module_states (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canvas_app_id  uuid NOT NULL REFERENCES canvas_apps(id) ON DELETE CASCADE,
    name           text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    -- Keyed by external ID (p.203). A variable that is renamed keeps its
    -- states; a variable whose *external ID* changes loses them, which is the
    -- documented consequence rather than a bug to paper over.
    values         jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- p.200: "optionally, the current page that a user is viewing". The
    -- author-set page ID, the same one routing writes (p.197) - not the
    -- Craft.js node id, which changes when a page is recreated and would make
    -- a state open on the wrong page for a reason nobody could see.
    page_id        text,
    created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    -- Two states of one module with the same name are two things a person
    -- would tell apart only by opening both. Scoped to the module rather than
    -- globally, because "Unresolved Zurich alerts" is a good name for a state
    -- of one module and nobody else's business.
    UNIQUE (canvas_app_id, name)
);

CREATE INDEX idx_module_states_app ON module_states (canvas_app_id);

CREATE TRIGGER trg_module_states_updated BEFORE UPDATE ON module_states
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN module_states.values IS
    'The viewer''s chosen values, keyed by variable external ID (Foundry '
    'p.203). Derived variables are absent: they are functions of their '
    'inputs and are recomputed on open.';

-- **Whoever can open the module can open its states**, which is why this
-- mirrors `canvas_apps`'s own policy rather than being project-scoped. p.200's
-- second sentence is that a state is shared "with other users", and a
-- published module is reached by a workspace member who may not be in its
-- project at all - so a project-scoped state would be invisible to exactly the
-- audience the module was published to.
--
-- The `EXISTS` looks like a no-op and is not: `canvas_apps` has its own policy,
-- and RLS applies inside subqueries too, so "a row exists in canvas_apps with
-- this id" *is* the question "can you see this module". Writing the app's
-- visibility rule out again here would be a second copy to keep in step.
ALTER TABLE module_states ENABLE ROW LEVEL SECURITY;
CREATE POLICY module_states_isolation ON module_states
    USING (EXISTS (SELECT 1 FROM canvas_apps a WHERE a.id = canvas_app_id));
