-- ============================================================================
-- 0046_configured_object_views.sql
-- Parity `docs/parity/ontology.md` §4.2; Foundry `object-views` p.2-4.
--
-- > "Configured Object Views are fully customizable representations of an
-- > object built using Workshop." (p.2)
--
-- **This table is a pointer, not a document.** The view *is* a Workshop
-- module: it has a layout, variables, events, versions, publishing and a
-- changelog already, and every one of those would have to be reinvented if a
-- configured view were its own kind of thing. So all this stores is which
-- module stands in for which object type, and how the object reaches it.
--
-- **`subject_variable` is the whole binding.** A standard view is generated
-- from the object type and needs no input; a configured one is a module, and a
-- module receives things through its variables (§116's interface mechanism).
-- This names the `single_object` variable that holds the object being viewed.
-- Foundry does not have to say this because its object views are authored in a
-- context that already knows; ours are ordinary modules, so the binding is
-- explicit rather than conventional - and validated in Python at save time
-- against the module's own document, the same arrangement `action_rules.config`
-- uses.
--
-- **One view per (type, form factor).** p.3-4 documents two: **Full**, "a
-- comprehensive view", and **Panel**, "for embedding in other applications,
-- focused on critical data". The enum carries both so the second is a row
-- rather than a migration; only Full is rendered today, because the panel
-- exists to be embedded and there is nothing here to embed it in yet.
--
-- **Nothing here makes the standard view go away.** p.2: standard views
-- "remain accessible even after a configured Object View is built". That is a
-- rule about the *reader*, not about storage, and it is why this table has no
-- "replace" flag - a configured view is the default, never the only one.
-- ============================================================================

CREATE TYPE object_view_form_factor AS ENUM ('full', 'panel');

CREATE TABLE object_type_views (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    object_type_id   uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    -- ON DELETE CASCADE, not SET NULL: a view pointing at a module that no
    -- longer exists is a configured view that renders nothing, and the
    -- standard view it was standing in front of is the better answer.
    canvas_app_id    uuid NOT NULL REFERENCES canvas_apps(id) ON DELETE CASCADE,
    form_factor      object_view_form_factor NOT NULL DEFAULT 'full',
    subject_variable text NOT NULL CHECK (length(subject_variable) BETWEEN 1 AND 200),
    created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (object_type_id, form_factor)
);

CREATE TRIGGER trg_object_type_views_updated BEFORE UPDATE ON object_type_views
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN object_type_views.subject_variable IS
    'The id of the module variable that receives the object being viewed. '
    'Checked in Python against the module document at save time; a module '
    'whose variables change afterwards is caught when the view is next saved, '
    'not silently repaired.';

-- Same workspace-consistency shape as link_types (0003) and action_types
-- (0013): the object type must belong to this view''s own workspace, and so
-- must the module - a view is a workspace-visible read path, and one pointing
-- across a workspace boundary would be a way through it.
CREATE FUNCTION enforce_object_type_view_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_ot_ws uuid;
    v_app_ws uuid;
BEGIN
    SELECT workspace_id INTO v_ot_ws FROM object_types WHERE id = NEW.object_type_id;
    IF v_ot_ws IS DISTINCT FROM NEW.workspace_id THEN
        RAISE EXCEPTION 'object views cannot cross workspace boundaries (hard isolation, spec §4)';
    END IF;
    SELECT rls_project_workspace_id(project_id) INTO v_app_ws
      FROM canvas_apps WHERE id = NEW.canvas_app_id;
    IF v_app_ws IS DISTINCT FROM NEW.workspace_id THEN
        RAISE EXCEPTION 'object views cannot cross workspace boundaries (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_object_type_views_workspace BEFORE INSERT OR UPDATE ON object_type_views
    FOR EACH ROW EXECUTE FUNCTION enforce_object_type_view_workspace();

ALTER TABLE object_type_views ENABLE ROW LEVEL SECURITY;
CREATE POLICY object_type_views_isolation ON object_type_views
    USING (rls_can_access_workspace(workspace_id));
