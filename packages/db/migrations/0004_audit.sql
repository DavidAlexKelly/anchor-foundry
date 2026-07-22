-- ============================================================================
-- 0004_audit.sql
-- audit_log — append-only log of every action. Protected by SQL rules that
-- prevent update or delete (spec §16, verbatim requirement).
-- ============================================================================

CREATE TABLE audit_log (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organisation_id  uuid NOT NULL REFERENCES organisations(id) ON DELETE RESTRICT,
    -- NULL for system-initiated actions (scheduled syncs, control-plane updates).
    user_id          uuid REFERENCES users(id) ON DELETE SET NULL,
    -- dotted verb, e.g. 'workspace.create', 'project.permissions.update',
    -- 'auth.login', 'dataset.export'
    action           text NOT NULL CHECK (length(action) BETWEEN 1 AND 200),
    resource_type    text NOT NULL DEFAULT '',
    resource_id      uuid,
    workspace_id     uuid,   -- deliberately NOT an FK: audit rows must survive
    project_id       uuid,   -- deletion of the resources they describe.
    -- Structured context. The API layer must never log credentials or secret
    -- values here (spec §10: "never logged").
    metadata         jsonb NOT NULL DEFAULT '{}'::jsonb,
    ip_address       inet,
    user_agent       text,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_org_time ON audit_log (organisation_id, created_at DESC);
CREATE INDEX idx_audit_user ON audit_log (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_audit_action ON audit_log (action);
CREATE INDEX idx_audit_workspace ON audit_log (workspace_id) WHERE workspace_id IS NOT NULL;

-- Spec §16: "Protected by SQL rules that prevent update or delete."
-- Rules rewrite the statement to a no-op at the parser level, so even the
-- table owner cannot UPDATE or DELETE without first dropping the rule —
-- which is itself visible in DDL audit (CloudTrail / pgaudit).
CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;

-- Belt and braces: TRUNCATE is not covered by rules, so block it with a
-- trigger. (Conservative addition beyond the spec's explicit requirement.)
CREATE FUNCTION forbid_audit_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only; TRUNCATE is forbidden';
END;
$$;

CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_audit_truncate();
