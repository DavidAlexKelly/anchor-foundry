"""Delete old code test and preview runs (§972; db 0173).

A test run stores a repository's whole working set and a preview its file and
the rows it produced, one row a press, and nothing deleted either: the
database grew by every press for good while the panels only ever read the
newest ten. Which runs may go is the database's to say (`prune_code_runs`):
finished, a month old, and not among the newest ten of their branch or file.
"""

from dagster import OpExecutionContext, job, op

from ..resources import PlatformDatabase

#: Rows a table one call deletes, as the function's default; the op calls
#: again until a call deletes fewer, so no one statement is long.
BATCH = 5000


@op
def prune_code_runs(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    pruned = 0
    while True:
        with platform_db.connect() as conn:
            n = int(conn.execute("SELECT prune_code_runs(p_batch => %s)", (BATCH,)).fetchone()[0])
        pruned += n
        if n < BATCH:
            break
    context.log.info(f"deleted {pruned} old code test and preview run(s)")
    return pruned


@job
def code_run_pruning():
    prune_code_runs()
