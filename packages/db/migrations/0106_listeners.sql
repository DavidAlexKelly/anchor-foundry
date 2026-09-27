-- ============================================================================
-- 0106_listeners.sql
-- HTTPS listeners: inbound events from systems that cannot call the API
-- (§516; `data-connection` p.249-266).
--
--     "Listeners enable the Palantir platform to receive events from other
--      systems that do not support OAuth 2.0 authentication directly or cannot
--      provide a configurable payload compatible with standard Foundry API
--      endpoints. To accept inbound connections from these systems, data
--      connection listeners provision a URL endpoint, implement the specific
--      message signing or other verification schemes for specific external
--      systems" (p.249)
--
--     "HTTPS listeners receive inbound webhook requests from external systems
--      through HTTPS endpoints. Events are written to a stream" (p.261)
--
-- **Three tables.** A listener is the configuration; an endpoint is a URL it
-- answers on; an event is a request it accepted.
--
-- **Endpoints are separate from the listener** because p.258 rotates them:
-- "you can only have a maximum of two endpoints at a time, and a maximum of
-- one active endpoint. An active endpoint is an endpoint without a set
-- expiration date." The partial unique index is that last sentence.
--
-- **`listener_events` is this platform's stream.** There is no streaming
-- dataset here, so p.261's "Events are written to a stream" is a table,
-- ordered by an identity, which the listener's screen reads newest first.
--
-- **The request path has no user**, so it cannot use RLS the way every other
-- route does. Two SECURITY DEFINER functions are the whole of what an
-- unauthenticated request can do: find the listener an endpoint token names,
-- and append one event to it. Nothing else is reachable without a user.
-- ============================================================================

CREATE TABLE listeners (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id           uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    display_name         text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 200),
    -- p.265's "implement the security protocols laid out by those external
    -- systems". The generic ones; named systems' schemes arrive with their
    -- listener types.
    verification         text NOT NULL DEFAULT 'none'
        CHECK (verification IN ('none', 'basic', 'header_secret', 'hmac_sha256')),
    -- The header a header secret or signature arrives in.
    verification_header  text CHECK (verification_header IS NULL
                                     OR verification_header ~ '^[A-Za-z0-9-]{1,100}$'),
    -- Where the secret is kept (`services/secrets.py`); never the secret.
    secret_arn           text,
    -- Stopped until somebody starts it: a listener that accepted events from
    -- the moment it was created would take traffic before it was configured.
    running              boolean NOT NULL DEFAULT false,
    created_by           uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CHECK ((verification IN ('header_secret', 'hmac_sha256')) = (verification_header IS NOT NULL)),
    CHECK ((verification = 'none') = (secret_arn IS NULL))
);

CREATE INDEX idx_listeners_project ON listeners (project_id);
CREATE TRIGGER trg_listeners_updated BEFORE UPDATE ON listeners
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE listener_endpoints (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    listener_id  uuid NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
    -- The path segment a sender posts to. Random, and the only thing that
    -- names the listener from outside.
    token        text NOT NULL UNIQUE CHECK (length(token) >= 32),
    -- NULL is active (p.258). Set, it stops answering at that time.
    expires_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_listener_endpoints_active
    ON listener_endpoints (listener_id) WHERE expires_at IS NULL;

CREATE TABLE listener_events (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listener_id   uuid NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
    endpoint_id   uuid REFERENCES listener_endpoints(id) ON DELETE SET NULL,
    received_at   timestamptz NOT NULL DEFAULT now(),
    content_type  text,
    -- p.262: "Individual event and request payloads are limited to 1 MB".
    size_bytes    integer NOT NULL CHECK (size_bytes BETWEEN 0 AND 1048576),
    body          bytea NOT NULL,
    -- Request headers, with credentials removed before they are stored.
    headers       jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_listener_events_listener ON listener_events (listener_id, id DESC);

ALTER TABLE listeners ENABLE ROW LEVEL SECURITY;
CREATE POLICY listener_isolation ON listeners
    USING (rls_can_access_project(project_id))
    WITH CHECK (rls_can_access_project(project_id));

ALTER TABLE listener_endpoints ENABLE ROW LEVEL SECURITY;
CREATE POLICY listener_endpoint_isolation ON listener_endpoints
    USING (EXISTS (SELECT 1 FROM listeners l WHERE l.id = listener_id))
    WITH CHECK (EXISTS (SELECT 1 FROM listeners l WHERE l.id = listener_id));

ALTER TABLE listener_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY listener_event_isolation ON listener_events
    USING (EXISTS (SELECT 1 FROM listeners l WHERE l.id = listener_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON listeners TO platform_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON listener_endpoints TO platform_app;
-- Events are appended by the request path's function and read by the
-- listener's screen; nobody edits one.
GRANT SELECT, DELETE ON listener_events TO platform_app;

-- ---- the request path (no user) --------------------------------------------
-- What a token names, and whether it may be used now. Returns nothing for a
-- token that names nothing, which the route answers with the same 404 as any
-- other path.
CREATE FUNCTION listener_for_token(p_token text)
RETURNS TABLE(listener_id uuid, endpoint_id uuid, running boolean, verification text,
              verification_header text, secret_arn text, expired boolean)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT l.id, e.id, l.running, l.verification, l.verification_header, l.secret_arn,
           (e.expires_at IS NOT NULL AND e.expires_at <= now())
      FROM listener_endpoints e
      JOIN listeners l ON l.id = e.listener_id
     WHERE e.token = p_token
$$;

-- One event, appended. The route has already checked the token, the running
-- switch, the size and the verification; this only writes.
CREATE FUNCTION record_listener_event(p_listener uuid, p_endpoint uuid, p_content_type text,
                                      p_body bytea, p_headers jsonb)
RETURNS bigint
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public
AS $$
    INSERT INTO listener_events (listener_id, endpoint_id, content_type, size_bytes, body, headers)
    VALUES (p_listener, p_endpoint, p_content_type, octet_length(p_body), p_body, p_headers)
    RETURNING id
$$;

REVOKE EXECUTE ON FUNCTION listener_for_token(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION listener_for_token(text) TO platform_app;
REVOKE EXECUTE ON FUNCTION record_listener_event(uuid, uuid, text, bytea, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION record_listener_event(uuid, uuid, text, bytea, jsonb) TO platform_app;
