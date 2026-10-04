-- §826: an app knows its workspace, so a workspace's apps are found by index.
--
-- `canvas_apps` has no workspace of its own: the workspace-wide reads (the
-- published-apps gallery, an action type's usages in modules, the related
-- artifacts of an object type) found theirs with
-- `rls_project_workspace_id(project_id) = :wid`. That is a function call, and
-- not a leakproof one, so Postgres must run the row policy first - on every
-- app in the database, every tenant's, before it can ask which workspace each
-- is in. On a copy of the development database the gallery checked 12,473
-- apps' policies to return 11: 607 ms. A `uuid` equality is leakproof, so
-- with a column and an index the planner reads the 11 and checks those.
--
-- **Set by the database, never by a caller**, as 0158 did for objects: a
-- trigger copies the project's workspace on insert and on any change of
-- project, overwriting whatever a caller passed. It reads the project through
-- `rls_project_workspace_id`, which sees past the caller's row policy, so the
-- value is right even for a project the caller cannot see - and the row
-- policy, which runs after BEFORE triggers, refuses that write exactly as it
-- did before.
--
-- **A project cannot change workspace**, now enforced: the copied value is
-- only as good as that.

ALTER TABLE canvas_apps ADD COLUMN workspace_id uuid;

UPDATE canvas_apps a
   SET workspace_id = p.workspace_id
  FROM projects p
 WHERE p.id = a.project_id;

ALTER TABLE canvas_apps ALTER COLUMN workspace_id SET NOT NULL;

CREATE FUNCTION canvas_apps_set_workspace() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.workspace_id := rls_project_workspace_id(NEW.project_id);
    RETURN NEW;
END
$$;

-- **Named to fire first.** Triggers on one event fire in name order, and
-- `register_resource` (trg_canvas_apps_register, _reregister) takes a row's
-- `workspace_id` when it has one, which from now on it does. Fired after
-- them, this would correct the app while the resources registry kept
-- whatever workspace the caller had written.
CREATE TRIGGER trg_canvas_apps_a_workspace
    BEFORE INSERT OR UPDATE OF project_id, workspace_id ON canvas_apps
    FOR EACH ROW EXECUTE FUNCTION canvas_apps_set_workspace();

CREATE FUNCTION projects_keep_workspace() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id THEN
        RAISE EXCEPTION 'a project cannot move to another workspace'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER trg_projects_keep_workspace
    BEFORE UPDATE OF workspace_id ON projects
    FOR EACH ROW EXECUTE FUNCTION projects_keep_workspace();

CREATE INDEX idx_canvas_apps_workspace ON canvas_apps (workspace_id);

-- The policy's workspace disjunct reads the column too: the same answer,
-- without a lookup per row.
DROP POLICY app_isolation ON canvas_apps;
CREATE POLICY app_isolation ON canvas_apps
    USING (rls_can_access_project(project_id)
           OR (publish_scope = 'workspace'
               AND workspace_id = ANY ((SELECT rls_workspace_ids())::uuid[]))
           OR (publish_scope = 'groups' AND rls_app_shared_with_user(id)));
