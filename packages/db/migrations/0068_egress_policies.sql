-- 0068 — Egress policies (decision 0013; `data-connection` p.12, p.22, p.49, p.103)
--
-- A per-source allowlist of destinations.
--
--   "For Foundry worker sources, networking is configured via egress policies.
--    They define at a granular level how each target system can be reached from
--    Foundry, and which egress destinations are permitted." (p.12)
--
-- **Empty means unrestricted**, which decision 0013 §2 argues at length and
-- this table cannot express on its own: there is no row that says "no
-- restriction", only the absence of rows. That is deliberate — the alternative
-- is a nullable flag on `connections` that has to be kept in step with a count
-- of rows in another table, and two places that can disagree about whether a
-- source is scoped is worse than one place that has to be read as a set.

CREATE TABLE egress_policies (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- **The connection, not the project.** p.12 attaches policies to a source
    -- and a source is a connection here; a workspace-scoped connection carries
    -- its policies into every project that uses it, which is what "assigned to
    -- the same source" means.
    connection_id  uuid NOT NULL REFERENCES connections(id) ON DELETE CASCADE,

    -- p.103's own advice is to name a destination rather than address it:
    -- "use this ad-hoc domain instead of 10.0.0.1 in your source and egress
    -- policy configuration". A literal address is still allowed, because "this
    -- one host" is a legitimate thing to say — what is not allowed is a CIDR
    -- range (decision 0013's last exclusion), because a range is what somebody
    -- writes when they do not know the names, and it invites the allowlist to
    -- be widened until it means nothing.
    --
    -- Stored lowercase because a hostname is case-insensitive and a policy for
    -- `API.example.com` that missed `api.example.com` would be a guard with a
    -- one-keystroke bypass. The CHECK enforces the shape rather than the case;
    -- the service lowercases on the way in.
    host           text NOT NULL CHECK (
        host = lower(host)
        AND length(host) BETWEEN 1 AND 253
        AND host ~ '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$'
    ),

    -- **Inferred, and decision 0013 says so.** The document never mentions a
    -- port. NULL is "any port on this host", which is what a policy written
    -- without one should mean — a person who names a host and no port has said
    -- nothing about ports, and reading that as "port 0 only" would be reading
    -- silence as a restriction.
    port           integer CHECK (port IS NULL OR port BETWEEN 1 AND 65535),

    -- What this policy is for, in the words of whoever wrote it. Carried into
    -- the refusal message: decision 0013 §4 wants a refused call to name the
    -- policy, and "its egress policies allow api.example.com:443" is more use
    -- with a purpose attached to it.
    description    text NOT NULL DEFAULT '' CHECK (length(description) <= 500),

    created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),

    -- One policy per destination. A duplicate is not harmful — the check is a
    -- membership test — but it is a list somebody has to read, and two rows
    -- saying the same thing make it longer without making it stronger.
    -- `NULLS NOT DISTINCT` so a second any-port row for one host is refused
    -- too; without it NULL never equals NULL and the constraint would allow
    -- exactly the duplicate most likely to be created twice.
    UNIQUE NULLS NOT DISTINCT (connection_id, host, port)
);

CREATE INDEX idx_egress_policies_connection ON egress_policies (connection_id);

-- ---------------------------------------------------------------------------
-- **One definition of "may this caller see this connection", not two.**
--
-- Every other child table in this schema restates its parent's rule through an
-- `rls_*` helper — `otp_isolation` and `dsv_isolation` both do — rather than
-- relying on RLS applying inside a subquery. That is the better habit: it says
-- what it checks instead of depending on a composition rule a reader has to
-- know.
--
-- A connection's rule is not a helper call though; it is a `CASE` on `scope`,
-- written out in 0061. Copying it here would be §191's mirror — two copies free
-- to be identically wrong, with nothing comparing either to the thing it
-- describes.
--
-- **The function takes the columns, not the id**, and that is the whole design
-- of it. The obvious signature — `rls_can_access_connection(uuid)`, looking the
-- row up itself — cannot serve `conn_isolation`: a `USING` clause with no
-- `WITH CHECK` is also the check for an INSERT, an INSERT's check runs against
-- the *new* row, and a row from the current command is not visible to a
-- `SELECT` inside a function (PostgreSQL command-id visibility). Every insert
-- would fail its own policy. `services/workspaces.create` already carries a
-- comment about this exact trap and it was walked into anyway.
--
-- Taking the columns means the parent evaluates the rule against the row in
-- hand, with no subquery to be blind, and the child does the lookup itself —
-- which is what the sibling policies above already do.
CREATE FUNCTION rls_can_access_connection(
    p_scope connection_scope, p_workspace_id uuid, p_project_id uuid
) RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT CASE p_scope
             WHEN 'workspace'::connection_scope THEN rls_can_access_workspace(p_workspace_id)
             ELSE rls_can_access_project(p_project_id)
           END
$$;

DROP POLICY conn_isolation ON connections;
CREATE POLICY conn_isolation ON connections
    USING (rls_can_access_connection(scope, workspace_id, project_id));

ALTER TABLE egress_policies ENABLE ROW LEVEL SECURITY;

-- A policy is not a separate thing to be permissioned: seeing a source's
-- destinations is seeing the source, and editing them is editing the source.
CREATE POLICY egress_policies_isolation ON egress_policies
    USING (EXISTS (
        SELECT 1 FROM connections c
         WHERE c.id = egress_policies.connection_id
           AND rls_can_access_connection(c.scope, c.workspace_id, c.project_id)
    ));
