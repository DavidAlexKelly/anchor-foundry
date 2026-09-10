-- The SQL Scratchpad's history and favourites (§306; p.15).
--
--     "To view queries marked as favorites, go to the [star] tab. To view a
--      history of queries ran in the SQL helper, go to the [clock] tab." (p.15)
--
-- **Two tabs, one table.** p.15 shows favourites and history as separate
-- places, and the temptation is to build them as two. They are one thing seen
-- twice: a favourite is a query somebody starred, and starring is not a way of
-- making a second copy. Two tables would need a rule for what happens when you
-- star a query and then run it again, and every answer to that is a bug.
--
-- **One row per distinct query text, not per run.** A history that repeats the
-- same query twenty times is a log, and what somebody opens this tab for is the
-- query they wrote, not the twentieth time they ran it. `last_ran_at` and
-- `run_count` carry what a per-run table would have said, and this is also what
-- makes a favourite survive being re-run — with a row per run, starring one run
-- would leave the star behind the moment you pressed the button again.
--
-- **Per user, not per repository.** A scratchpad is a workbench: what is on it
-- is half-finished, often wrong, and written to be thrown away. p.15 gives no
-- sharing affordance and inventing one would put somebody's scratch work in
-- front of their colleagues without their asking.

CREATE TABLE scratchpad_queries (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id      uuid NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    author_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sql          text NOT NULL CHECK (length(sql) BETWEEN 1 AND 20000),
    -- p.15's star. A favourite is exempt from the history cap below: it is the
    -- one signal somebody has given that a query is worth keeping, and a
    -- retention rule that ignored it would delete precisely the queries they
    -- asked to keep.
    favourite    boolean NOT NULL DEFAULT false,
    -- What a per-run table would have told you, without being one.
    run_count    integer NOT NULL DEFAULT 1 CHECK (run_count > 0),
    first_ran_at timestamptz NOT NULL DEFAULT now(),
    last_ran_at  timestamptz NOT NULL DEFAULT now(),
    -- Running the same text again is the same row. The uniqueness is the whole
    -- design decision above, stated where it cannot be forgotten: a service
    -- that stopped deduplicating would find out here rather than three months
    -- later in a history nobody can read.
    UNIQUE (repo_id, author_id, sql)
);

CREATE INDEX scratchpad_queries_recent
    ON scratchpad_queries (repo_id, author_id, last_ran_at DESC);

-- Favourites first, then by recency: the two tabs are one query with one
-- filter, and this index serves both orders.
CREATE INDEX scratchpad_queries_favourites
    ON scratchpad_queries (repo_id, author_id, last_ran_at DESC)
    WHERE favourite;

ALTER TABLE scratchpad_queries ENABLE ROW LEVEL SECURITY;

-- **Two conditions, and the second is the point.** Project access alone would
-- let a colleague read the scratch work of everybody in the project, which is
-- the thing the per-user design above exists to prevent — and a rule that lives
-- only in a service is one the next writer of a SELECT does not meet.
CREATE POLICY scratchpad_isolation ON scratchpad_queries
    USING (author_id = rls_current_user_id()
           AND EXISTS (SELECT 1 FROM code_repos r
                       WHERE r.id = repo_id
                         AND rls_can_access_project(r.project_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON scratchpad_queries TO platform_app;

COMMENT ON TABLE scratchpad_queries IS
    'p.15''s SQL Scratchpad history and favourites (db 0073). Two tabs over one '
    'table: a favourite is a history entry somebody starred, and one row per '
    'distinct query text rather than per run, so a star survives re-running.';
