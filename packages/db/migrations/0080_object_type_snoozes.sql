-- Hiding an object type from *your* cleanup queue (§325; `ontology-manager`
-- p.68-74).
--
--     "The Ontology cleanup tool is a safe way to delete object types… The tool
--      aims to help Ontology editors determine the safety of deleting an object
--      type and provides a deprecation option which informs object type users
--      of its future removal." (p.68)
--
--     "**Snooze**: Hide object types from your cleanup queue for a configurable
--      amount of time. Snoozing is an action that will affect only the user
--      that performs it." (p.71)
--
-- **This is the only thing the cleanup tool needs to store**, which is worth
-- saying because the queue looks like a feature that would need a table of its
-- own. Every flag p.73-74 lists is computed from something this platform
-- already records — the deprecation deadline on `object_types`, the sync state
-- on `object_type_sources` (§315), the description column, the display name,
-- and §320's thirty-day usage. A materialised queue would be a second copy of
-- all of it, stale the moment anything it summarises changed, and p.69's "the
-- tool may take time to find cleanup candidates" is a statement about scale
-- rather than about storage.
--
-- **Per user, and p.71 says so twice**: "will affect only the user that
-- performs it", and p.73 repeats it for the flag settings. So the row is keyed
-- by both, and one editor clearing their queue does not hide a type from the
-- colleague who would have deleted it.
--
-- **An expiry rather than a flag**, because p.71's snooze is "for a
-- configurable amount of time". A boolean would need a second mechanism to
-- ever come back, and a queue you can permanently silence one row at a time is
-- a queue that quietly stops being a queue.

CREATE TABLE object_type_snoozes (
    object_type_id uuid        NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    user_id        uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- When it comes back. Past this moment the row is ignored rather than
    -- deleted: a reader who snoozed something for a week and wants to know why
    -- it reappeared can still see that they did it.
    until          timestamptz NOT NULL,
    -- Why, when somebody said. p.71 does not ask for one and a queue is a
    -- conversation between an editor and their future self, so it is optional.
    note           text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type_id, user_id)
);

-- The queue asks "what has this person snoozed, and is it back yet" on every
-- read, which is one index rather than one per question.
CREATE INDEX idx_object_type_snoozes_mine
    ON object_type_snoozes (user_id, until DESC);

ALTER TABLE object_type_snoozes ENABLE ROW LEVEL SECURITY;

-- **Your own rows and nobody else's**, which is a stronger rule than the
-- workspace isolation everything else here uses — and it is p.71's rule rather
-- than a choice: a snooze that another editor could see would be a note about
-- how somebody manages their own work, and one they could *write* would let
-- them hide a type from the colleague about to delete it.
--
-- The workspace check is spelled out here rather than left to the join the
-- queue happens to write: a policy that protected the row only when somebody
-- remembered to join `object_types` is a policy the next writer of a SELECT
-- does not meet (§312's note on the same shape).
CREATE POLICY object_type_snoozes_own ON object_type_snoozes
    USING (user_id = rls_current_user_id()
           AND EXISTS (SELECT 1 FROM object_types ot
                        WHERE ot.id = object_type_snoozes.object_type_id
                          AND ot.workspace_id = ANY (rls_workspace_ids())))
    WITH CHECK (user_id = rls_current_user_id()
           AND EXISTS (SELECT 1 FROM object_types ot
                        WHERE ot.id = object_type_snoozes.object_type_id
                          AND ot.workspace_id = ANY (rls_workspace_ids())));

GRANT SELECT, INSERT, UPDATE, DELETE ON object_type_snoozes TO platform_app;

COMMENT ON TABLE object_type_snoozes IS
    'p.71''s snooze (db 0080). One row per person per object type, with the '
    'moment it comes back — the only thing the Ontology cleanup tool stores, '
    'since every flag p.73-74 lists is computed from what the ontology, its '
    'sources and db 0077''s usage already record.';
