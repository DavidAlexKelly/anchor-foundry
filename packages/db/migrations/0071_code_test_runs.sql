-- 0071 — Unit test runs (§294; `code-repositories.md` §8, p.13-14, p.19)
--
-- **A test run is a job, not a request, and decision 0004 is why.** Running a
-- repository's unit tests is running customer Python, and 0004 settled where
-- that happens: "a transform runs in a process that cannot obtain the
-- platform's credentials", in the runner task, never in the API. The Problems
-- panel (§286) could be a plain POST because it parses and reads names and
-- executes nothing; this cannot. `routes/repositories.py` already refuses to
-- preview a Python transform for exactly this reason, and says so in the
-- message: "they run in an isolated task rather than in the API, which takes
-- long enough to need a job you can watch rather than a request that waits."
--
-- So this table is the thing you watch. The API writes a queued row, the
-- worker picks it up on the same poll `model_runs` uses, and the Tests panel
-- reads the row back.
--
-- **The files travel and are stored, which is the unusual part.** Every other
-- job in this schema names a resource and reads its current state. A test run
-- is over the author's *working set* — the uncommitted buffer — because the
-- question is "does what I just typed pass" (§286 made the same choice, for
-- the same reason). There is nowhere else that working set exists, so it is
-- written here. That has two consequences worth stating rather than
-- discovering: the row is large, and the row is a snapshot, so a run always
-- reports on the code it actually ran rather than on whatever the file says by
-- the time somebody reads the result.

CREATE TABLE code_test_runs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id       uuid NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,

    -- Which branch the working set was laid over, for the panel to say what it
    -- ran against. Not a foreign key: a branch is a name that can be deleted
    -- while a run's record of it stays true (0033 takes the same position).
    branch        text NOT NULL CHECK (length(branch) BETWEEN 1 AND 100),

    -- path -> content, the whole working set as it was when the run was asked
    -- for. **A snapshot, not a reference.** See the header: there is nowhere
    -- else it exists, and a run that re-read the files would report on code
    -- that is no longer the code it ran.
    files         jsonb NOT NULL,

    -- queued -> running -> succeeded | failed | errored.
    --
    -- **`failed` and `errored` are different rows on purpose**, and this is the
    -- distinction `transform_runner.py` keeps with `result.json`, arriving in
    -- the schema. `failed` means the author's tests ran and some did not pass;
    -- `errored` means the *run* did not happen — pytest could not start, the
    -- time limit was hit, the report would not parse. Only the first is an
    -- answer about their code, and a status that collapsed them would send the
    -- wrong person looking every time.
    status        text NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'errored')),

    -- What the run produced: the parsed outcomes, or NULL until there are any.
    -- Shaped by `anchor_worker.unit_test_report.TestOutcome`.
    outcomes      jsonb,

    -- Set only when `status = 'errored'`: why the run did not happen. Never
    -- carries a test's failure message — those live in `outcomes`, because a
    -- failing test is a result and not an error.
    error         text,

    requested_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    queued_at     timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    finished_at   timestamptz,

    -- Both or neither, so a row cannot claim to have finished without having
    -- started. The same shape `model_runs` uses, and it is what makes
    -- "abandoned" detectable: started long ago, never finished.
    CONSTRAINT code_test_runs_finished_after_started
        CHECK (finished_at IS NULL OR started_at IS NOT NULL),

    -- A terminal row has an answer and a running one does not. Without this a
    -- run could report 'succeeded' with no outcomes at all, which is the
    -- "suite that ran nothing looks green" failure this whole feature is
    -- written against, arriving through the database instead of the report.
    CONSTRAINT code_test_runs_terminal_has_an_answer
        CHECK (
            status IN ('queued', 'running')
            OR (status = 'errored' AND error IS NOT NULL)
            OR (status IN ('succeeded', 'failed') AND outcomes IS NOT NULL)
        )
);

-- The worker's poll, and the panel's "what happened to the run I asked for".
CREATE INDEX idx_code_test_runs_queued
    ON code_test_runs (queued_at) WHERE status = 'queued';
CREATE INDEX idx_code_test_runs_repo
    ON code_test_runs (repo_id, queued_at DESC);

-- No `updated_at` and no trigger: a run's life is three named moments, and
-- `queued_at`/`started_at`/`finished_at` say which one it is in. A fourth
-- column that moved on every write would be a second, vaguer answer to the
-- same question.

ALTER TABLE code_test_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY ctr_isolation ON code_test_runs
    USING (EXISTS (SELECT 1 FROM code_repos r
                   WHERE r.id = repo_id
                     AND rls_can_access_project(r.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON code_test_runs TO platform_app;

-- ---------------------------------------------------------------------------
-- Worker discovery. The same SECURITY DEFINER enumeration 0014 introduced: the
-- worker has no workspace context of its own, so it cannot discover work in
-- workspaces it does not know about, and this function is how it is told what
-- is waiting. It returns the workspace so the caller can open a scoped
-- connection and re-check the row before touching it.
CREATE FUNCTION list_queued_test_runs() RETURNS TABLE(run_id uuid, workspace_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT t.id, p.workspace_id
      FROM code_test_runs t
      JOIN code_repos r ON r.id = t.repo_id
      JOIN projects p ON p.id = r.project_id
     WHERE t.status = 'queued'
     ORDER BY t.queued_at
$$;

REVOKE EXECUTE ON FUNCTION list_queued_test_runs() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION list_queued_test_runs() TO platform_app;

COMMENT ON TABLE code_test_runs IS
    'One run of a repository''s unit tests over an author''s working set '
    '(db 0071). A job rather than a request because it executes customer '
    'Python, which decision 0004 confines to the runner task.';
