-- ============================================================================
-- 0147_outbound_grants.sql
-- Decision 0022; parity `docs/parity/data-connection.md` §2 (Credential-free
-- auth, Webhooks); Foundry `data-connection` p.39-40, p.243 (§752).
--
-- > "When a source is configured with an outbound application, authentication
-- > is delegated to an external OAuth 2.0 provider on behalf of the calling
-- > user. The user must complete the interactive authorization flow at least
-- > once before the source can be used from non-interactive contexts." (p.39)
--
-- A **grant** is one person's authorization of one source: the tokens the
-- provider issued them, kept in the secrets gateway under the source's own
-- secret (`secret_arn`), and what this table says about them - for whom,
-- since when, with what scope and until when. The tokens are never here.
--
-- An **oauth state** is one authorization in flight: the state the provider
-- echoes back and the PKCE verifier (RFC 7636) only the platform knows, kept
-- for the ten minutes a person may take at the provider. Both tables are the
-- person's own: nobody can read another's, which is what makes "the calling
-- user" mean the caller.
-- ============================================================================

CREATE TABLE outbound_grants (
    connection_id uuid NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    secret_arn    text NOT NULL,
    scope         text,
    expires_at    timestamptz,
    granted_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (connection_id, user_id)
);

ALTER TABLE outbound_grants ENABLE ROW LEVEL SECURITY;
CREATE POLICY outbound_grants_own ON outbound_grants
    USING (user_id = rls_current_user_id()
           AND EXISTS (SELECT 1 FROM connections c
                        WHERE c.id = outbound_grants.connection_id
                          AND rls_can_access_connection(c.scope, c.workspace_id, c.project_id)));
GRANT SELECT, INSERT, UPDATE, DELETE ON outbound_grants TO platform_app;

CREATE TABLE oauth_states (
    state         text PRIMARY KEY CHECK (length(state) BETWEEN 32 AND 200),
    connection_id uuid NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_verifier text NOT NULL,
    return_to     text NOT NULL CHECK (return_to LIKE '/%' AND return_to NOT LIKE '//%'),
    created_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE oauth_states ENABLE ROW LEVEL SECURITY;
CREATE POLICY oauth_states_own ON oauth_states
    USING (user_id = rls_current_user_id());
GRANT SELECT, INSERT, DELETE ON oauth_states TO platform_app;
