-- ============================================================================
-- 0134_kiosk_mode.sql
-- Kiosk mode (§684; Foundry `workshop` p.610-612).
--
-- > "Kiosk mode gives builders the ability to enable long-lived, restricted
-- > sessions for Workshop applications, allowing them to be safely displayed
-- > for extended periods of time. Kiosk mode sessions are read-only… and have
-- > scoped down permissions limiting the content viewable within a session."
-- > (p.610)
--
-- Three things:
--
--   * `kiosk_modules` - p.610's "Kiosk mode settings can be configured and
--     managed per Organization from Control Panel. Once a module has been
--     added to the kiosk mode setting's allowlist…"
--   * `kiosk_sessions` - a launched session: which module, which published
--     version, what it may see, and the hash of the credential it runs on.
--     p.611's "Session Launch History table", and the row an administrator
--     ends a session by.
--   * `rls_kiosk_allows` and the RESTRICTIVE policies that call it - p.611's
--     "Permissions will be scoped down for a module in kiosk mode to limit the
--     content that is viewable in an active session."
--
-- **The scope is enforced by the database, not by the browser.** A kiosk
-- screen is left unattended in a public place; a session that only *looked*
-- scoped would be a control that looks like it works on the one screen where
-- that is worst. A request made on a kiosk credential runs with the session's
-- scope in transaction-local settings (`app.kiosk`, `app.kiosk_object_types`
-- …), and RESTRICTIVE policies - ANDed with every permissive one - hide
-- whatever the module does not reference. Outside a kiosk request `app.kiosk`
-- is unset and the policies pass everything, so no other query changes.
--
-- **Only the credential's hash is stored**, as `organisations.licence_key_hash`
-- (0001) does for the same reason: a table of live kiosk tokens would make the
-- database a credential store.
-- ============================================================================

CREATE TABLE kiosk_modules (
    organisation_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    app_id          uuid NOT NULL REFERENCES canvas_apps(id) ON DELETE CASCADE,
    added_by        uuid REFERENCES users(id) ON DELETE SET NULL,
    added_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organisation_id, app_id)
);

CREATE TABLE kiosk_sessions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    app_id          uuid NOT NULL REFERENCES canvas_apps(id) ON DELETE CASCADE,
    -- p.610: "the currently published version of the module". The session is
    -- of that version; a later publish does not widen a running session.
    version_number  integer NOT NULL,
    launched_by     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    -- {"object_types": [...], "link_types": [...], "action_types": [...],
    --  "apps": [...]}: ids, as `module_access.referenced` found them.
    scope           jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    ended_at        timestamptz,
    ended_by        uuid REFERENCES users(id) ON DELETE SET NULL,
    CHECK (expires_at > created_at)
);

CREATE INDEX idx_kiosk_sessions_org ON kiosk_sessions (organisation_id, created_at DESC);

-- Both are organisation-wide settings and history: readable by the
-- organisation, written through the API, which checks who may.
ALTER TABLE kiosk_modules ENABLE ROW LEVEL SECURITY;
CREATE POLICY kiosk_modules_isolation ON kiosk_modules
    USING (organisation_id = (SELECT u.organisation_id FROM users u
                              WHERE u.id = rls_current_user_id()));

ALTER TABLE kiosk_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY kiosk_sessions_isolation ON kiosk_sessions
    USING (organisation_id = (SELECT u.organisation_id FROM users u
                              WHERE u.id = rls_current_user_id()));

GRANT SELECT, INSERT, UPDATE, DELETE ON kiosk_modules TO platform_app;
GRANT SELECT, INSERT, UPDATE ON kiosk_sessions TO platform_app;

-- p.611's scope, asked of one row. `kind` names the setting holding that
-- kind's ids ('object_types', 'link_types', 'action_types', 'apps'). An empty
-- or missing list inside a kiosk request allows nothing of that kind.
CREATE FUNCTION rls_kiosk_allows(kind text, rid uuid)
RETURNS boolean
LANGUAGE sql STABLE
AS $$
    SELECT CASE
        WHEN coalesce(current_setting('app.kiosk', true), '') = '' THEN true
        ELSE coalesce(
            rid = ANY (CAST(nullif(current_setting('app.kiosk_' || kind, true), '') AS uuid[])),
            false)
    END
$$;

CREATE POLICY ot_kiosk ON object_types AS RESTRICTIVE
    USING (rls_kiosk_allows('object_types', id));
CREATE POLICY lt_kiosk ON link_types AS RESTRICTIVE
    USING (rls_kiosk_allows('link_types', id));
CREATE POLICY action_types_kiosk ON action_types AS RESTRICTIVE
    USING (rls_kiosk_allows('action_types', id));
CREATE POLICY oi_kiosk ON object_instances AS RESTRICTIVE
    USING (rls_kiosk_allows('object_types', object_type_id));
CREATE POLICY app_kiosk ON canvas_apps AS RESTRICTIVE
    USING (rls_kiosk_allows('apps', id));
CREATE POLICY appv_kiosk ON canvas_app_versions AS RESTRICTIVE
    USING (rls_kiosk_allows('apps', canvas_app_id));

-- The credential, resolved before there is anybody to run as - so as the
-- owner, and returning only what authentication needs: the session and the
-- person who launched it (p.610: a session is launched by a builder and runs
-- with their access, narrowed).
CREATE FUNCTION kiosk_session_for_token(p_hash text)
RETURNS TABLE(session_id uuid, workspace_id uuid, project_id uuid, app_id uuid,
              scope jsonb, live boolean, user_id uuid, organisation_id uuid,
              email text, display_name text, org_role text, status text,
              cognito_sub text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT s.id, s.workspace_id, s.project_id, s.app_id, s.scope,
           (s.ended_at IS NULL AND s.expires_at > now()),
           u.id, u.organisation_id, u.email::text, u.display_name, u.org_role::text,
           u.status::text, u.cognito_sub
      FROM kiosk_sessions s
      JOIN users u ON u.id = s.launched_by
     WHERE s.token_hash = p_hash
$$;

REVOKE EXECUTE ON FUNCTION kiosk_session_for_token(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION kiosk_session_for_token(text) TO platform_app;
