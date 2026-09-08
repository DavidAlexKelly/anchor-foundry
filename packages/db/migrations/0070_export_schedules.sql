-- 0070 — Export schedules (decision 0016; `data-connection` p.205)
--
-- The one piece of decision 0014 that 0069 left owed:
--
--   "Exports should be scheduled to run regularly, exporting recent data to
--    the external destination." (p.205)
--
-- **p.205's scheduling is not an export feature in Foundry.** It says to
-- "select Add schedule to open the export in Data Lineage… and configure as
-- you would for any other job" — the platform's build scheduler, pointed at an
-- export the way it is pointed at anything else. This platform has no general
-- job scheduler; it has a cron column per schedulable resource, and 0014
-- established the shape for two of them. This is the third instance of that
-- shape rather than the first use of a general one, and decision 0016 §1
-- records what that costs: Foundry's schedules can fire on an upstream event
-- and a cron cannot, so the destination is stale for up to one interval.
--
-- What makes the gap small is p.192, which 0069 already implemented: an export
-- with nothing new is a *success* that writes nothing. So an hourly cron
-- against a daily dataset is twenty-three cheap skips and one export, and
-- `export_runs` says so.

ALTER TABLE exports
    -- A standard five-field cron expression, or NULL for "manual only".
    --
    -- NULL rather than a separate `schedule_enabled` boolean: an export with
    -- no schedule and an export whose schedule is switched off are the same
    -- state, and two columns able to disagree about it is how a row ends up
    -- meaning something nobody can read. 0014 made the same choice with
    -- `connections.sync_schedule`.
    ADD COLUMN schedule    text CHECK (schedule IS NULL OR length(schedule) BETWEEN 9 AND 200),

    -- When the worker should next consider it. Computed by the API from the
    -- cron at write time and recomputed by the worker after every firing —
    -- the arrangement 0014 documents, which keeps cron parsing to exactly two
    -- trusted call sites.
    --
    -- NULL with a schedule set means "never fired yet", and the discovery
    -- function below treats that as due. 0014 flagged that this makes a
    -- freshly-scheduled job fire once immediately; the same is true here and
    -- is if anything more clearly right for an export, because the first run
    -- is what makes the destination current.
    ADD COLUMN next_run_at timestamptz;

CREATE INDEX idx_exports_due ON exports (next_run_at) WHERE schedule IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Worker discovery. Same SECURITY DEFINER enumeration 0014 introduced: no
-- RLS-scoped query can find work across every workspace without already
-- knowing which workspace to look in, and the worker re-verifies and acts
-- through the normal scoped path — the bypass is read-only enumeration and
-- never the mutation.
--
-- **The join to `connections` is the part that is not decoration.** p.202
-- makes exporting to a source something an admin turns on, and 0069 holds
-- that in `connections.exports_enabled`. The route checks it when an export
-- is created; a schedule set while it was on must not keep firing after
-- somebody turns it off. That is decision 0013 §3's send-time-versus-save-time
-- argument, which existed because two of its four original paths had been
-- reasoned about the same way and were wrong. So the switch is re-read here,
-- every time, and turning it off stops the schedule without touching it.
CREATE FUNCTION list_due_exports() RETURNS TABLE(export_id uuid, workspace_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT e.id, p.workspace_id
      FROM exports e
      JOIN projects p ON p.id = e.project_id
      JOIN connections c ON c.id = e.connection_id
     WHERE e.schedule IS NOT NULL
       AND c.exports_enabled
       AND (e.next_run_at IS NULL OR e.next_run_at <= now())
     ORDER BY e.next_run_at NULLS FIRST
$$;

REVOKE EXECUTE ON FUNCTION list_due_exports() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION list_due_exports() TO platform_app;
