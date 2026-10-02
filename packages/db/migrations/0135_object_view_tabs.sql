-- ============================================================================
-- 0135 — tabs on a configured full Object View (§695; `object-views` p.34-35)
-- ============================================================================
--
-- > "Each Object View tab is backed by a Workshop module … In the object title
-- > bar, you can manage tabs by selecting the gear icon. Each tab corresponds
-- > to a single workshop module. If only one tab is configured, the tab title
-- > will be hidden when viewing the Object View … Selecting the gear icon
-- > opens a dialog that allows you to add, reorder, rename, and delete Object
-- > View tabs." (p.35)
--
-- **The view's own module is its first tab**, so every view that exists is a
-- view of one tab and needs no backfill: `object_type_views` keeps the first
-- tab's module and subject variable, and gains the first tab's title. The
-- further tabs are rows here, in order from position 1.
--
-- A tab is the same pointer a view is (0046): a module, and the single-object
-- variable that receives the object. So it gets 0046's two guards: the module
-- must be in the view's workspace (a trigger, since a view is a
-- workspace-visible read path), and rows are visible to whoever can see that
-- workspace. ON DELETE CASCADE from the module, for 0046's reason: a tab
-- pointing at a module that is gone renders nothing.
-- ============================================================================

ALTER TABLE object_type_views
    ADD COLUMN title text NOT NULL DEFAULT '' CHECK (length(title) <= 100);

COMMENT ON COLUMN object_type_views.title IS
    'The first tab''s title (§695). Empty means the module''s name.';

CREATE TABLE object_view_tabs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    view_id          uuid NOT NULL REFERENCES object_type_views(id) ON DELETE CASCADE,
    position         integer NOT NULL CHECK (position BETWEEN 1 AND 19),
    title            text NOT NULL CHECK (length(title) BETWEEN 1 AND 100),
    canvas_app_id    uuid NOT NULL REFERENCES canvas_apps(id) ON DELETE CASCADE,
    subject_variable text NOT NULL CHECK (length(subject_variable) BETWEEN 1 AND 200),
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (view_id, position)
);

CREATE INDEX object_view_tabs_view ON object_view_tabs (view_id, position);

CREATE FUNCTION enforce_object_view_tab_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_view_ws uuid;
    v_app_ws uuid;
BEGIN
    SELECT workspace_id INTO v_view_ws FROM object_type_views WHERE id = NEW.view_id;
    SELECT rls_project_workspace_id(project_id) INTO v_app_ws
      FROM canvas_apps WHERE id = NEW.canvas_app_id;
    IF v_app_ws IS DISTINCT FROM v_view_ws THEN
        RAISE EXCEPTION 'object views cannot cross workspace boundaries (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_object_view_tabs_workspace BEFORE INSERT OR UPDATE ON object_view_tabs
    FOR EACH ROW EXECUTE FUNCTION enforce_object_view_tab_workspace();

ALTER TABLE object_view_tabs ENABLE ROW LEVEL SECURITY;
CREATE POLICY object_view_tabs_isolation ON object_view_tabs
    USING (EXISTS (SELECT 1 FROM object_type_views v
                    WHERE v.id = view_id AND rls_can_access_workspace(v.workspace_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON object_view_tabs TO platform_app;
