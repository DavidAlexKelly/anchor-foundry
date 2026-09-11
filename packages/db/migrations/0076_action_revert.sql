-- Undoing an action (§319; `ontology.md` §5; `action-types` p.154-156).
--
--     "Action reverts in Ontology Manager allow an action to be reverted (that
--      is, undone) immediately after the action has been applied. You can
--      revert an action by selecting Undo in the success message after any
--      successful action application." (p.154)
--
--     "New actions are revertible by default." (p.154)
--
--     "Currently, actions can only be reverted by the user who applied the
--      action." (p.154)
--
-- **Seven columns, and four of them exist to refuse.** p.154-156 spend most of
-- their words on when an undo is *not* available, and every one of those
-- sentences needs state that the apply path is the only thing in a position to
-- record.
--
-- What a revert restores
-- ---------------------
-- p.156: "An action revert only reverts the edits to the object instance, but
-- it will not revert side effects, such as notifications or webhooks, nor will
-- it call them in the same way that the applied action would have."
--
-- Here the dataset is the record and the instance store is a projection of it
-- (decision 0008), so restoring only the projection would last until the next
-- sync and then silently come back. A revert therefore writes the previous
-- values **through the same path the action used** - an append to the dataset
-- and an update to the index - which is the only form of undo this storage
-- model has. The side effects stay as p.156 describes: no notification, no
-- webhook, in either direction.
--
-- Why a whole snapshot rather than the keys that changed
-- ----------------------------------------------------
-- p.156: "An action on an object cannot be reverted once any subsequent edit
-- has been made to the object, **even if the edit is on a different
-- property**."
--
-- That sentence is the whole reason `applied_properties` is the object's
-- entire property map and not a diff. A record of "this run set `status` to
-- `open`" cannot tell whether somebody has since changed `owner`, so the
-- comparison that decides whether an undo is safe has to be against everything
-- the object had when the action finished. Two maps per run is the cost, and
-- an action run is already a row carrying its submitted values.

ALTER TABLE action_types
    -- p.154: "New actions are revertible by default." The default applies to
    -- rows that already exist too, which is the more useful of the two
    -- readings: an action written before this migration is an ordinary
    -- revertible action, not one somebody has to go and enable.
    ADD COLUMN allow_revert boolean NOT NULL DEFAULT true;

ALTER TABLE action_runs
    -- The object's properties **before** this run, in full. What an undo
    -- writes back.
    ADD COLUMN previous_properties jsonb,
    -- The object's properties **after** this run, in full. What the object
    -- must still look like for an undo to be offered - see p.156 above.
    ADD COLUMN applied_properties jsonb,
    -- p.155: "An action cannot be reverted if action reverts has been toggled
    -- off after action submission, **even if action reverts have been toggled
    -- on again**."
    --
    -- That is a sentence about *this run*, not about the action type, and it
    -- is why a `allow_revert` check on its own is not enough: turning the
    -- toggle back on must not resurrect an undo that was taken away. So
    -- switching the toggle off stamps every outstanding run of that type, and
    -- the stamp is never cleared.
    ADD COLUMN revert_blocked boolean NOT NULL DEFAULT false,
    -- When this run was undone, and by whom. Also the answer to "has this
    -- already been undone" - p.155 calls the toast "your only opportunity",
    -- and an undo that could be pressed twice would apply the old values over
    -- whatever the second press found.
    ADD COLUMN reverted_at timestamptz,
    ADD COLUMN reverted_by uuid REFERENCES users(id) ON DELETE SET NULL,
    -- The run that undid this one. A revert is itself an action run - it
    -- appends to the dataset and writes the index exactly as an apply does -
    -- so it has a row, and the two point at each other rather than a revert
    -- being an invisible edit with no author and no time.
    ADD COLUMN reverted_by_run_id uuid REFERENCES action_runs(id) ON DELETE SET NULL,
    -- Set on the revert run, naming what it undid. `NULL` on an ordinary run.
    -- Both directions are stored because both questions get asked: "was this
    -- undone" on the original, and "is this an undo" on the revert.
    ADD COLUMN reverts_run_id uuid REFERENCES action_runs(id) ON DELETE SET NULL,
    -- Why this run can never be undone, written **at apply time** because the
    -- apply path is the only thing that knows.
    --
    -- An action that creates or deletes objects, or that edits objects other
    -- than its subject, is outside what this unit undoes: restoring the
    -- subject's properties would leave the created rows behind, or the deleted
    -- ones gone, and an undo that half-works is worse than one that says it
    -- cannot (§214). Recorded as a **sentence rather than a flag** because it
    -- is the text somebody reads on the screen where the Undo button is not -
    -- "this action cannot be undone" is a fact nobody can act on, and "this
    -- action also created objects" is one they can.
    ADD COLUMN revert_unsupported text;

-- Finding a type's outstanding runs when its toggle goes off, and finding the
-- runs a person may still undo. Partial, because a run that has been reverted
-- is never a candidate again and there is no reason to index the history.
CREATE INDEX idx_action_runs_revertible
    ON action_runs (action_type_id, requested_by, finished_at DESC)
    WHERE reverted_at IS NULL AND NOT revert_blocked;
