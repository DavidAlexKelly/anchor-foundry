-- ============================================================================
-- 0104_object_edit_history.sql
-- Per-object edit history (§470; `workshop` p.402–403).
--
--     "The Edit History widget displays the list of user edits made to an
--      object's properties after Track user edit history has been enabled for
--      the object type within Ontology Manager. Edits completed prior to
--      enabling Edit History, edits completed by a pipeline, or edits
--      completed while on Object Storage v1 will not be reflected." (p.402)
--
--     "The Edit History widget provides an immutable audit trail of all
--      changes made to ontology objects. Changelog records are designed for
--      auditing purposes and cannot be deleted or modified by end users, even
--      if the corresponding ontology edits are reverted or deleted." (p.402)
--
-- **A row per property changed, written by the action paths and nothing
-- else.** p.402's "user edits" are what an action makes; "edits completed by a
-- pipeline" - a sync, here - are left out by where the writes happen rather
-- than by a flag, because the sync path never calls the recorder. An object
-- created or deleted by an action gets one row with no property, so its
-- history begins and ends where its life does.
--
-- **Immutable by grant, not by convention.** The application role may insert
-- and read, and nothing else: no UPDATE, no DELETE, and no policy that would
-- allow either. An undo is a new edit on top, which is p.402's "even if the
-- corresponding ontology edits are reverted" - the record of the edit that was
-- undone stays, and so does the record of the undo.
--
-- **The toggle is a time, not a flag.** p.402's "edits completed prior to
-- enabling Edit History … will not be reflected" is a statement about *when*,
-- and switching tracking off and on again must not make the gap between look
-- tracked. So an enable stamps `edit_history_since` and a disable clears it;
-- edits are recorded while it is set, and the widget reads what was recorded.
-- ============================================================================

ALTER TABLE object_types
    ADD COLUMN edit_history_since timestamptz;

CREATE TABLE object_edits (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The order edits were written in. One run's rows share `edited_at` - it
    -- is the transaction's `now()` - so without this, two properties changed
    -- together would list in whatever order their random ids fell.
    seq             bigint GENERATED ALWAYS AS IDENTITY,
    workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- No cascade from the type or the instance: p.402's trail outlives the
    -- edit it records, and a deleted object's history is the one most likely
    -- to be asked about.
    object_type_id  uuid NOT NULL,
    primary_key     text NOT NULL,
    action_run_id   uuid REFERENCES action_runs(id) ON DELETE SET NULL,
    edited_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    edited_at       timestamptz NOT NULL DEFAULT now(),
    -- `modify` carries a property and both values; `create` and `delete` carry
    -- the whole object on the side that has one and no property.
    kind            text NOT NULL CHECK (kind IN ('modify', 'create', 'delete')),
    property        text,
    before_value    jsonb,
    after_value     jsonb,
    CHECK ((kind = 'modify') = (property IS NOT NULL))
);

CREATE INDEX idx_object_edits_object
    ON object_edits (object_type_id, primary_key, edited_at, seq);

ALTER TABLE object_edits ENABLE ROW LEVEL SECURITY;
CREATE POLICY object_edits_read ON object_edits FOR SELECT
    USING (rls_can_access_workspace(workspace_id));
CREATE POLICY object_edits_write ON object_edits FOR INSERT
    WITH CHECK (rls_can_access_workspace(workspace_id));

REVOKE UPDATE, DELETE ON object_edits FROM platform_app;
