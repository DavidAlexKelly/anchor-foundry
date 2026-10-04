-- ============================================================================
-- 0152_promotion_requests.sql
-- Parity `docs/parity/ontology.md` §1.3 (Status: "Missing: p.255's second
-- sentence, a proposal others may submit for an owner's approval"); Foundry
-- `object-link-types` p.255 (§767).
--
-- > "Only users with the `Ontology Owner` role on the ontology level can
-- > directly apply the `promoted` status. Other users must submit a proposal
-- > for review and approval by an `Ontology Owner`." (p.255)
--
-- A row is one such proposal: an object type somebody without the role asked
-- to have promoted, and what became of it. The owner here is a workspace
-- admin (`ontology_status.PROMOTION_ROLE`). Approving applies the status
-- through the same path an admin's own edit takes, so every rule p.255-258
-- attaches to `promoted` still runs.
--
-- At most one pending per object type: a second would be the same question
-- asked twice, with two answers possible.
-- ============================================================================

CREATE TABLE promotion_requests (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    uuid        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    object_type_id  uuid        NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    requested_by    uuid        REFERENCES users(id) ON DELETE SET NULL,
    reason          text        NOT NULL DEFAULT '',
    state           text        NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending', 'approved', 'rejected', 'withdrawn')),
    decided_by      uuid        REFERENCES users(id) ON DELETE SET NULL,
    decision_note   text        NOT NULL DEFAULT '',
    decided_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_promotion_requests_one_pending
    ON promotion_requests (object_type_id) WHERE state = 'pending';
CREATE INDEX idx_promotion_requests_workspace
    ON promotion_requests (workspace_id, created_at DESC);

ALTER TABLE promotion_requests ENABLE ROW LEVEL SECURITY;
CREATE POLICY promotion_requests_isolation ON promotion_requests
    USING (workspace_id = ANY (rls_workspace_ids()))
    WITH CHECK (workspace_id = ANY (rls_workspace_ids()));

GRANT SELECT, INSERT, UPDATE ON promotion_requests TO platform_app;
