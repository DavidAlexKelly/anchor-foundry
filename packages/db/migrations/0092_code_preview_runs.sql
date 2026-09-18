-- 0092 — Python transform previews (§390; `code-repositories.md` §2.2 and
-- §2.4, `code-repositories` p.13-14)
--
-- **The gap 0071 named, closed by the shape 0071 built.** That migration's
-- own header quotes the refusal this one removes: `routes/repositories.py`
-- "already refuses to preview a Python transform for exactly this reason, and
-- says so in the message: 'they run in an isolated task rather than in the
-- API, which takes long enough to need a job you can watch rather than a
-- request that waits.'" So the pattern was written down with this case in
-- mind, and this table is that sentence's answer.
--
-- p.13 is the button — "run the Transform on a sample of the input datasets…
-- a quick way to preview your code changes on real data" — and p.14 is the
-- panel that shows what came back. §389 recorded that they are one feature.
--
-- **One file, not a working set**, and that is the difference from 0071. A
-- test run is over everything the author has open because pytest collects
-- across the repository; a preview runs *this* transform, whose declaration
-- names its own inputs. So `path` and `content` rather than `files`. Still a
-- snapshot, for 0071's reason: the buffer exists nowhere else, and a run must
-- report on the code it actually ran.
--
-- **The rows are stored here rather than in a file**, which is the decision
-- worth stating. `dataset_engine.PREVIEW_ROWS` caps a preview at 100 rows, so
-- the result is small by construction — small enough to be a column. The
-- alternative is a parquet somewhere with a lifetime nobody owns, and a
-- preview that leaves files behind is a leak that nothing on the screen would
-- ever show.

CREATE TABLE code_preview_runs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id       uuid NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,

    -- Which branch the buffer was laid over, for the panel to say what it ran
    -- against. Not a foreign key, for 0071's reason: a branch is a name that
    -- can be deleted while a run's record of it stays true.
    branch        text NOT NULL CHECK (length(branch) BETWEEN 1 AND 100),

    path          text NOT NULL CHECK (length(path) BETWEEN 1 AND 1000),
    content       text NOT NULL,

    -- `{alias: dataset_id}`, **resolved by the API when the run is queued**
    -- rather than by the worker when it starts. The declaration that names
    -- these inputs is parsed by `transform_declarations`, which lives in the
    -- API because that is where every other caller of it is; teaching the
    -- worker to parse one too would be a second reader of a syntax with one
    -- writer (§292). It also means a file naming a dataset the project does
    -- not have is refused *at the button*, with the name in the message,
    -- instead of becoming a queued row that fails a minute later.
    input_datasets jsonb NOT NULL,

    -- queued -> running -> succeeded | failed | errored.
    --
    -- **`failed` and `errored` are different rows here for 0071's reason**,
    -- read one step along: `failed` means the author's transform ran and
    -- raised — an answer about their code, on their data — and `errored`
    -- means the run did not happen, because the runner was unavailable or the
    -- task could not start. Only the first sends the author to their own
    -- code, and a status that collapsed them would send the wrong person
    -- looking every time.
    status        text NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'errored')),

    -- What the preview produced: `{columns: [...], rows: [[...]]}`, capped at
    -- `PREVIEW_ROWS`. NULL until there is an answer.
    result        jsonb,

    -- Per input, once it has run: `alias`, `rows_available`, `rows_used`.
    -- **The answer to `input_datasets`' question**, and a different column
    -- because they are different facts: one is which datasets were asked for,
    -- the other is how much of each the preview actually read. **Kept beside the
    -- rows rather than derived from them**, because it is the half that says
    -- the answer is not the answer: a join or a `group by` over a sample finds
    -- fewer matches and smaller groups than the real run will, and
    -- `PreviewedInput.sampled` is how a reader is told. A preview that showed
    -- a row count without it would be confidently wrong.
    inputs        jsonb,

    -- Set only when `status = 'errored'`: why the run did not happen. Never
    -- carries the author's traceback — that is a result, and it lives in
    -- `result` beside the rows it failed to produce.
    error         text,

    requested_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    queued_at     timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    finished_at   timestamptz,

    CONSTRAINT code_preview_runs_finished_after_started
        CHECK (finished_at IS NULL OR started_at IS NOT NULL),

    -- A terminal row has an answer and a running one does not — 0071's
    -- constraint, and the same failure behind it: a run reporting 'succeeded'
    -- with nothing in `result` is an empty table that looks like a transform
    -- producing no rows.
    CONSTRAINT code_preview_runs_terminal_has_an_answer
        CHECK (
            status IN ('queued', 'running')
            OR (status = 'errored' AND error IS NOT NULL)
            OR (status IN ('succeeded', 'failed') AND result IS NOT NULL)
        )
);

CREATE INDEX idx_code_preview_runs_queued
    ON code_preview_runs (queued_at) WHERE status = 'queued';
CREATE INDEX idx_code_preview_runs_repo
    ON code_preview_runs (repo_id, queued_at DESC);

ALTER TABLE code_preview_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY cpr_isolation ON code_preview_runs
    USING (EXISTS (SELECT 1 FROM code_repos r
                   WHERE r.id = repo_id
                     AND rls_can_access_project(r.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON code_preview_runs TO platform_app;


-- The worker's poll. SECURITY DEFINER for 0071's reason: workspace-blind
-- enumeration across every workspace, with the worker re-verifying and acting
-- through a workspace-scoped connection.
CREATE FUNCTION list_queued_preview_runs() RETURNS TABLE(run_id uuid, workspace_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT t.id, p.workspace_id
      FROM code_preview_runs t
      JOIN code_repos r ON r.id = t.repo_id
      JOIN projects p ON p.id = r.project_id
     WHERE t.status = 'queued'
     ORDER BY t.queued_at
$$;

REVOKE EXECUTE ON FUNCTION list_queued_preview_runs() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION list_queued_preview_runs() TO platform_app;

COMMENT ON TABLE code_preview_runs IS
    'One preview of a Python transform over a sample of its inputs (db 0092). '
    'A job rather than a request because it executes customer Python, which '
    'decision 0004 confines to the runner task — the refusal db 0071''s '
    'header quotes.';
