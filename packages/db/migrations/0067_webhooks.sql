-- 0067 — Webhooks (decision 0012; Foundry `data-connection` p.216-242,
--                  `action-types` p.105-111)
--
-- A webhook is a *request shape* held against a connection: the connection
-- owns the base URL, the auth and the secrets (`connections.secret_arn`), and
-- the webhook owns the method, relative path, query params, headers and body
-- template. `data-connection` p.220 draws the line in those words — "the
-- source is meant to contain the minimal set of secrets and connection details
-- required to establish a connection… when configuring individual webhooks
-- using this source, you will have an opportunity to add additional request
-- details, including the relative path, query parameters, headers, and body
-- content."
--
-- Decision 0012 §4 records why that split is kept rather than letting an
-- action rule carry a URL: a URL on a rule needs a second home for a bearer
-- token, skips `connectors._check_url`'s link-local guard, and leaves an
-- egress allowlist nothing to hang off.

-- ---------------------------------------------------------------------------
-- The rule kind.
--
-- `IF NOT EXISTS` for 0066's reason: `ALTER TYPE ... ADD VALUE` is not
-- transactional in older PostgreSQL and a re-run must not fail.
ALTER TYPE action_rule_kind ADD VALUE IF NOT EXISTS 'webhook';

-- ---------------------------------------------------------------------------
CREATE TABLE webhooks (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id       uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    -- **RESTRICT rather than CASCADE.** A connection deleted out from under a
    -- webhook would silently take an action's rule with it; the refusal names
    -- the webhook, which is the thing somebody has to decide about.
    connection_id    uuid NOT NULL REFERENCES connections(id) ON DELETE RESTRICT,

    api_name         text NOT NULL CHECK (api_name ~ '^[a-z][a-z0-9_]{0,62}$'),
    display_name     text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    description      text NOT NULL DEFAULT '' CHECK (length(description) <= 2000),

    -- p.233's request builder, less the parts that need a second unit.
    method           text NOT NULL CHECK (method IN ('GET','POST','PUT','PATCH','DELETE')),
    path             text NOT NULL DEFAULT '' CHECK (length(path) <= 2048),
    query            jsonb NOT NULL DEFAULT '{}'::jsonb,
    headers          jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- p.233 lists seven body types; this holds the one that matters first,
    -- `Raw JSON`, as a template with `{{{name}}}` references resolved the same
    -- way a notification's content is (§257). `NULL` is a request with no body,
    -- which is not the same as a request with an empty one.
    body             jsonb,

    -- p.228's input parameters: [{api_name, data_type, required}].
    inputs           jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- p.229's output parameters: [{api_name, data_type, path}], where `path`
    -- is the dotted JSON path `connectors._json_path` already understands.
    outputs          jsonb NOT NULL DEFAULT '[]'::jsonb,

    -- p.242: "This option may be disabled entirely for a webhook that is known
    -- to return sensitive information that should not be stored in the webhook
    -- history." On by default, because a webhook you cannot debug is worse
    -- than one whose responses are readable by the person who made the call —
    -- and that person is the only one who can read them (see `webhook_runs`).
    store_responses  boolean NOT NULL DEFAULT true,
    -- p.237's `retryable-status-codes`, "defaults to an empty list".
    retry_statuses   integer[] NOT NULL DEFAULT '{}',
    timeout_seconds  integer NOT NULL DEFAULT 20 CHECK (timeout_seconds BETWEEN 1 AND 60),

    created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),

    UNIQUE (workspace_id, api_name)
);

CREATE INDEX idx_webhooks_project ON webhooks (project_id);
CREATE INDEX idx_webhooks_connection ON webhooks (connection_id);

CREATE TRIGGER trg_webhooks_updated BEFORE UPDATE ON webhooks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- p.242's history. One row per execution, whether or not it succeeded.
CREATE TABLE webhook_runs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    webhook_id       uuid NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- Which action run fired it, when one did. NULL for a test call from the
    -- webhook's own page (p.222's "run a test request to see if your
    -- configuration is correct").
    action_run_id    uuid REFERENCES action_runs(id) ON DELETE SET NULL,
    -- **The person the history belongs to.** p.242: "inputs passed to the
    -- webhook and the full response will only be visible to the user who
    -- called the webhook". This column is what the read policy compares
    -- against, so it is NOT NULL and does not fall back to anybody.
    called_by        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- p.105: writeback runs before the object changes and can refuse the
    -- action; side effect runs after and cannot. p.106's table is the whole
    -- difference and it is a property of the *rule*, recorded here because a
    -- run read afterwards has to say which semantics applied to it.
    mode             text NOT NULL CHECK (mode IN ('writeback','side_effect','test')),

    ok               boolean NOT NULL,
    status_code      integer,
    -- p.237: "When a Webhook is executed and fails, the indication of whether
    -- the external system may have been changed is captured to enable
    -- debugging of write failures." Three-valued on purpose: a request that
    -- never left is `false`, a 4xx in `external-system-not-changed-status-codes`
    -- is `false`, and anything else that failed is NULL — unknown, which is
    -- the honest answer and the one a person debugging needs to see said out
    -- loud rather than guessed at.
    system_changed   boolean,
    error            text,
    duration_ms      integer,

    -- NULL when `store_responses` is off. Empty is a stored empty body; NULL
    -- is "deliberately not kept", and the two must not be confused by anything
    -- reading this back.
    request_body     jsonb,
    response_body    jsonb,
    outputs          jsonb NOT NULL DEFAULT '{}'::jsonb,

    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_webhook_runs_webhook ON webhook_runs (webhook_id, created_at DESC);
CREATE INDEX idx_webhook_runs_action ON webhook_runs (action_run_id)
    WHERE action_run_id IS NOT NULL;

-- ---------------------------------------------------------------------------
ALTER TABLE webhooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_runs ENABLE ROW LEVEL SECURITY;

-- A webhook is a project resource, like the connection it points at.
CREATE POLICY webhooks_isolation ON webhooks
    USING (rls_can_access_project(project_id));

-- **Two policies, not one, and 0066 is why.** A single `USING` clause governs
-- reads *and* the visibility half of writes; the read rule here is narrower
-- than the write rule, so one clause would make every insert impossible. The
-- notifications table needed exactly this split and got it the second time.
--
-- Read: p.242's "only visible to the user who called the webhook". The
-- privileged read (`webhooks:read-privileged-data`, "not granted to any users
-- by default") has no custom-role mechanism here to hang off, so it is absent
-- rather than approximated — decision 0012's own note.
CREATE POLICY webhook_runs_read ON webhook_runs FOR SELECT
    USING (called_by = rls_current_user_id());

-- Write: may you act in this workspace at all. The floor every other write in
-- a workspace has, and deliberately not the read rule — the executor inserts
-- the row as the person who ran the action, so the two agree in practice, and
-- an insert that could only happen when the read rule already passed would be
-- the same fail-closed mistake 0066 made once.
CREATE POLICY webhook_runs_record ON webhook_runs FOR INSERT
    WITH CHECK (rls_can_access_workspace(workspace_id));
