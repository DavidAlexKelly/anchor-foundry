-- ============================================================================
-- 0066_notifications.sql
-- Parity `docs/parity/ontology.md` §5.2 (build order item 10, first half);
-- Foundry `action-types` p.87-101.
--
-- > "Side effects in action types enable you to send data out of Foundry to
-- > integrate with existing organizational processes. There are two main types
-- > of side effects: Notifications … Webhooks …" (p.87)
--
-- > "Notifications can be added to an action through the Add new rule dropdown
-- > menu. Configuring a notification requires specification of recipients and
-- > content." (p.89)
--
-- **A notification is a rule, not a new resource on the action.** p.89 puts it
-- in the same *Add new rule* menu as the five that already exist, and that is
-- the whole of why `notify` becomes a sixth `action_rule_kind` rather than an
-- `action_notifications` table: a rule is a thing an action does when it runs,
-- and one that sends a message is not a different category from one that sets
-- a property. The config's shape is checked in `services/notifications.py`,
-- like every other rule kind's (0044).
--
-- What this migration adds is the **delivered** notification, which is a
-- different thing entirely: the rule is a template, and this is what a person
-- was actually sent.
-- ============================================================================

ALTER TYPE action_rule_kind ADD VALUE IF NOT EXISTS 'notify';

-- ---------------------------------------------------------------------------
-- One notification, delivered to one person.
--
-- > "Notifications will be sent to each recipient individually. Adding users as
-- > CC (carbon copy) recipients to email notifications is not supported."
-- > (p.90)
--
-- So a row per recipient rather than a row per firing with a recipient list.
-- That is p.90's sentence, and it is also what makes "read" a property of the
-- notification rather than of a join table nobody would think to look in.
-- ---------------------------------------------------------------------------
CREATE TABLE notifications (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- **Workspace-scoped**, like every ontology-derived resource here (0003).
    -- A notification carries rendered object data, and p.96 is explicit that
    -- "users may only receive notifications containing data which they are
    -- allowed to view" - a notification readable across the isolation boundary
    -- would be that rule broken by the delivery mechanism.
    workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Which run sent it. Nullable so a notification outlives the run's
    -- retention: what somebody was told is a fact about them, and losing it
    -- because the audit trail rolled would be losing the wrong half.
    action_run_id   uuid REFERENCES action_runs(id) ON DELETE SET NULL,
    -- Who caused it. p.101's "Current User" is renderable in the content, so
    -- the actor is part of what the notification *says* as well as of why it
    -- exists.
    actor_id        uuid REFERENCES users(id) ON DELETE SET NULL,
    -- p.91's three content components. Rendered at send time, not at read
    -- time: p.92 says the content reflects "the state of the Ontology before
    -- edits of the current Action are applied", and a notification that
    -- re-rendered when somebody opened it would show a different world each
    -- time it was read.
    --
    -- Lengths are p.95's, and they are **truncation limits rather than
    -- refusals** - see `services/notifications.truncate`. The CHECKs here are
    -- the same numbers, so a bug in the truncation is a failed insert rather
    -- than a row nobody expected.
    subject         text NOT NULL CHECK (length(subject) BETWEEN 1 AND 250),
    body            text NOT NULL DEFAULT '' CHECK (length(body) <= 1000),
    -- p.91's optional link, and its button text. Both or neither: a button
    -- with no destination and a destination with no button are each half a
    -- control.
    link_url        text,
    link_text       text,
    CONSTRAINT notifications_link_is_whole
        CHECK ((link_url IS NULL) = (link_text IS NULL)),
    -- p.91: "they may still view their notifications when logged into Foundry
    -- by going to Notifications". So a notification is a stored thing with a
    -- read state, not a transient toast.
    read_at         timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- The listing every reader makes: mine, newest first.
CREATE INDEX idx_notifications_user
    ON notifications (user_id, created_at DESC);
-- And the unread count, which is the thing a header badge asks for on every
-- page load. Partial, because a read notification can never answer it.
CREATE INDEX idx_notifications_unread
    ON notifications (user_id) WHERE read_at IS NULL;

COMMENT ON TABLE notifications IS
    'One notification delivered to one person (Foundry action-types p.87-101). '
    'A row per recipient rather than per firing, which is p.90''s "sent to '
    'each recipient individually".';

-- **Reading and sending are different permissions**, and writing one policy
-- for both is the fail-closed trap this schema has fallen into three times
-- (0008, 0009, 0015). The first attempt here was a single
-- `USING (user_id = rls_current_user_id())`, which reads exactly right and
-- makes the feature impossible: the person who *sends* a notification is never
-- the person who receives it, so every insert was refused by the policy
-- protecting the recipient.
--
-- Reading is yours and nobody else''s. Unlike every other table in this schema
-- the read policy is not "can you see the workspace" - a notification is
-- addressed to a person, and a workspace admin reading other people''s
-- messages is not a feature anybody asked for.
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

CREATE POLICY notifications_read ON notifications FOR SELECT
    USING (user_id = rls_current_user_id());

-- Marking one read is a write *to your own row*, so it is the read rule again
-- rather than the send rule. `WITH CHECK` as well as `USING`, so an update
-- cannot hand a notification to somebody else on its way past.
CREATE POLICY notifications_mark ON notifications FOR UPDATE
    USING (user_id = rls_current_user_id())
    WITH CHECK (user_id = rls_current_user_id());

-- Sending is "may you act in this workspace at all", which is the same floor
-- every other write in the workspace has. It is deliberately **not** "may the
-- recipient see it" - that is p.96''s check, it is about the *content* rather
-- than about the row, and `services/notifications.deliverable` makes it before
-- the action writes anything so that p.96''s "no data will be edited" can be
-- true.
CREATE POLICY notifications_send ON notifications FOR INSERT
    WITH CHECK (rls_can_access_workspace(workspace_id));
