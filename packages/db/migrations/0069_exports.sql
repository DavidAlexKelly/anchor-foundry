-- 0069 — Exports (decision 0014; `data-connection` p.17, p.192-206)
--
-- The reverse direction. p.17 pairs each export type with the sync it
-- reverses:
--
--   "File exports are the opposite of file batch syncs... Table exports are
--    the opposite of table batch syncs." (p.17)
--
-- Two tables: the configured export, and one row per run. The same split
-- `sync_configs` and `sync_runs` already use, for the same reason — a
-- configuration is edited and a run is appended, and a table that did both
-- would have a history nobody could read.

-- ---------------------------------------------------------------------------
-- **Exports are off until somebody turns them on** (p.202).
--
--   "To export data, you must enable exports in the Connection settings
--    section of the source to which you are exporting... A Foundry user with
--    the Information Security Officer role should navigate to this tab and
--    toggle on the option to Enable exports to this source." (p.202)
--
-- A column on `connections` rather than a row somewhere, because the absence
-- of a row is how *unrestricted* is spelled one migration back (0068), and
-- this is the opposite default: absent means **no**. A boolean that starts
-- false says that in one place and cannot be misread as "not configured yet".
--
-- Foundry's gate is the enrollment-level `Information Security Officer` role.
-- This platform has no such role; the nearest is workspace admin, which is a
-- genuine narrowing (per-workspace, not per-enrollment) and decision 0014 §4
-- records it as one. The route is what enforces that; this column only holds
-- the answer.
ALTER TABLE connections
    ADD COLUMN exports_enabled boolean NOT NULL DEFAULT false;

-- p.193's two types, minus streaming. There is no stream in this platform to
-- reverse, so p.194's replay-behaviour setting has nothing to be about.
CREATE TYPE export_kind AS ENUM ('table', 'file');

-- p.195-196 lists six table export modes. **Four of them are defined over a
-- transaction log this platform does not keep** — every one of them says
-- "unexported *transactions* from the current view", or names a `SNAPSHOT` /
-- `APPEND` / `UPDATE` / `DELETE` transaction type — and `dataset_versions` is,
-- in 0003's own words, a "snapshot per sync/upload": every version is a
-- complete view and there is no transaction type on it.
--
-- So two, and they are the two whose definitions never mention a transaction:
--
--   'mirror'  = p.195's "Full dataset with truncation" - "truncate (drop) the
--               target table, and then export a snapshot of the full current
--               dataset view... the external table always mirroring the
--               Foundry dataset".
--   'full'    = p.195's "Full dataset without truncation" - "Note: This option
--               will almost always result in duplicates in the external table.
--               This option can be useful when external systems consume and
--               remove rows after each run."
--
-- Decision 0014 §2 carries the table of which four are absent and why. The
-- gap is in `dataset_versions`, not here: adding transaction types would
-- unlock four modes and change every writer in the platform, which is a
-- decision of its own rather than something to smuggle in behind a dropdown.
CREATE TYPE export_mode AS ENUM ('mirror', 'full');

CREATE TABLE exports (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- **`project_id` alone, with no denormalised `workspace_id`.** Several
    -- tables here carry both, each with a trigger keeping them in step; every
    -- one of those is a table something reads by workspace. Nothing reads
    -- exports that way — the RLS rule is `rls_can_access_project`, the routes
    -- are project-scoped, and the connection and dataset each carry their own
    -- workspace. `models` is the precedent: project-scoped, one column, no
    -- trigger. A denormalised column nothing reads is a second source of truth
    -- maintained for nobody.
    project_id     uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- p.203: an export is created from "the Overview page of the source to
    -- which you want to export", so it belongs to a connection the way a
    -- webhook does (0067).
    --
    -- **RESTRICT, not CASCADE.** Deleting a source that something exports to
    -- should say so rather than silently removing the export - the same
    -- treatment 0067 gives a webhook, and §259 had to learn to turn the
    -- resulting constraint error into a sentence.
    connection_id  uuid NOT NULL REFERENCES connections(id) ON DELETE RESTRICT,

    -- What is exported. CASCADE here and RESTRICT above, deliberately: a
    -- dataset is the *content* and the source is the *destination*, and an
    -- export whose content is gone has nothing left to mean, while an export
    -- whose destination is gone is a configuration somebody should be told
    -- about before it disappears.
    dataset_id     uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,

    name           text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    kind           export_kind NOT NULL,

    -- Only meaningful for a table export; a file export has no mode because
    -- p.193 gives it only one behaviour ("raw files from a dataset are copied
    -- on a schedule and written to the target system"). Held as NULL rather
    -- than defaulted, so the two kinds cannot quietly share a column that
    -- means something for one of them.
    mode           export_mode,

    -- The destination, in whichever shape the kind needs: a table export names
    -- a schema and table (p.197: "ensure that DATABASE, SCHEMA, and TABLE
    -- fields are filled out if required by your source"), a file export names
    -- a path. One jsonb rather than four nullable columns, because the set of
    -- fields is per-connector and 0067 already made that choice for webhooks.
    destination    jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- **The last dataset version successfully written**, and the whole of
    -- p.192's June 2025 behaviour change:
    --
    --   "Prior to June 2025, exports have been marked as failed if there are
    --    no new files or rows to be exported during a build. From June 2025
    --    onward, exports with no new files or rows to be exported will be
    --    marked as success." (p.192)
    --
    -- NULL means never exported. A run finding this equal to the dataset's
    -- current version has nothing new - for a file export (p.193: "only files
    -- that were modified since the last successfully exported transaction...
    -- will be written") and for 'mirror', whose end state is already correct.
    --
    -- **'full' does not consult it**, and that is not an exception to p.192 but
    -- a consequence of it: p.195 says that mode is for "external systems [that]
    -- consume and remove rows after each run", so there is always something new
    -- to export. A 'full' export that skipped would be a queue that stopped
    -- being fed.
    last_version   integer CHECK (last_version IS NULL OR last_version > 0),

    created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),

    -- A mode belongs to a table export and nowhere else. Written as a CHECK
    -- rather than left to the service because it is the kind of invariant a
    -- second write path would forget - and this schema has learned that a
    -- column meaning different things per row is how two features end up
    -- sharing a bug.
    CONSTRAINT exports_mode_matches_kind CHECK (
        (kind = 'table' AND mode IS NOT NULL)
        OR (kind = 'file' AND mode IS NULL)
    ),

    UNIQUE (project_id, name)
);

CREATE INDEX idx_exports_connection ON exports (connection_id);
CREATE INDEX idx_exports_dataset ON exports (dataset_id);
CREATE INDEX idx_exports_project ON exports (project_id);

CREATE TRIGGER trg_exports_updated BEFORE UPDATE ON exports
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- **The dataset and the destination must be in the same project as the
-- export**, and that is not covered by the RLS rule above. RLS decides what a
-- *caller* may see; it says nothing about whether the three ids on one row
-- belong together, and a caller with access to two projects could otherwise
-- write an export in one that reads a dataset from the other. A
-- workspace-scoped connection is the deliberate exception — 0061 exists so a
-- source can be shared across a workspace's projects, and refusing one here
-- would break the feature the scope column was added for.
CREATE FUNCTION enforce_export_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_dataset_project uuid;
    v_scope           connection_scope;
    v_conn_project    uuid;
    v_conn_workspace  uuid;
    v_export_workspace uuid;
BEGIN
    SELECT project_id INTO v_dataset_project FROM datasets WHERE id = NEW.dataset_id;
    IF v_dataset_project IS DISTINCT FROM NEW.project_id THEN
        RAISE EXCEPTION 'an export must read a dataset in its own project';
    END IF;

    SELECT scope, project_id, workspace_id
      INTO v_scope, v_conn_project, v_conn_workspace
      FROM connections WHERE id = NEW.connection_id;
    SELECT workspace_id INTO v_export_workspace FROM projects WHERE id = NEW.project_id;

    IF v_scope = 'workspace'::connection_scope THEN
        IF v_conn_workspace IS DISTINCT FROM v_export_workspace THEN
            RAISE EXCEPTION 'an export must write to a source in its own workspace';
        END IF;
    ELSIF v_conn_project IS DISTINCT FROM NEW.project_id THEN
        RAISE EXCEPTION 'an export must write to a source in its own project';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_exports_scope BEFORE INSERT OR UPDATE ON exports
    FOR EACH ROW EXECUTE FUNCTION enforce_export_scope();

-- ---------------------------------------------------------------------------
-- p.206: "the History view of an export shows the history of the jobs
-- associated with it." One row per run, whether it wrote anything or not —
-- a run that skipped is a run somebody needs to see, because "nothing
-- happened" and "nothing ran" are the two answers a schedule makes people
-- guess between.
CREATE TABLE export_runs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    export_id      uuid NOT NULL REFERENCES exports(id) ON DELETE CASCADE,

    -- 'succeeded' covers p.192's nothing-to-do case; `rows_written = 0` with
    -- `skipped = true` is what distinguishes it, rather than a third status.
    -- A status enum that grew a 'skipped' member would make every existing
    -- reader of this column wrong by omission.
    status         text NOT NULL CHECK (status IN ('succeeded', 'failed')),
    skipped        boolean NOT NULL DEFAULT false,

    -- Which version this run wrote (or would have). Recorded even on a
    -- failure, because "it failed trying to export v7" is the first thing
    -- anybody asks.
    dataset_version integer CHECK (dataset_version IS NULL OR dataset_version > 0),
    rows_written   bigint NOT NULL DEFAULT 0 CHECK (rows_written >= 0),
    error          text,

    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    -- Who pressed run. NULL once scheduling exists (p.205) and nobody did.
    run_by         uuid REFERENCES users(id) ON DELETE SET NULL,

    -- A failed run without a reason is a row that tells nobody anything, and a
    -- succeeded run with one reads as a contradiction.
    CONSTRAINT export_runs_error_matches_status CHECK (
        (status = 'failed' AND error IS NOT NULL)
        OR (status = 'succeeded' AND error IS NULL)
    ),
    -- A skipped run wrote nothing, by definition. Without this the two could
    -- disagree and the history would be unreadable.
    CONSTRAINT export_runs_skipped_wrote_nothing CHECK (
        NOT skipped OR rows_written = 0
    )
);

CREATE INDEX idx_export_runs_export ON export_runs (export_id, started_at DESC);

-- ---------------------------------------------------------------------------
-- RLS. An export is project-scoped like a dataset, and its runs follow it —
-- the same shape as `sync_runs` and, one migration back, `egress_policies`:
-- the child restates the parent's rule through a helper rather than relying on
-- RLS applying inside a subquery.
ALTER TABLE exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE export_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY exports_isolation ON exports
    USING (rls_can_access_project(project_id));

CREATE POLICY export_runs_isolation ON export_runs
    USING (EXISTS (
        SELECT 1 FROM exports e
         WHERE e.id = export_runs.export_id
           AND rls_can_access_project(e.project_id)
    ));

GRANT SELECT, INSERT, UPDATE, DELETE ON exports TO platform_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON export_runs TO platform_app;
