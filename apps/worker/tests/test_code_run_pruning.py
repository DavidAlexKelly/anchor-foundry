"""Old code test and preview runs are deleted (§972; db 0173).

Each run stores what it ran - a repository's whole working set, or a file and
the rows it produced - and nothing deleted one, while the panels only ever
read a branch's or a file's newest ten. These hold what may go: finished, a
month old, and not among those ten; and that nothing still running, nothing
recent and nothing a panel can show goes with them.
"""
from __future__ import annotations

import json
import os
import sys

import psycopg
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.jobs import code_run_pruning  # noqa: E402
from test_code_preview_runs_job import repository, storage_root  # noqa: E402,F401 (fixtures)
from test_model_runs import ADMIN_DSN, _ctx  # noqa: E402


def a_test_run(repository: dict, *, branch: str = "main", days_old: int, finished: bool = True):
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            """INSERT INTO code_test_runs (repo_id, branch, files, requested_by, status, outcomes,
                                           queued_at, started_at, finished_at)
               VALUES (%s, %s, '{}'::jsonb, %s, %s, %s,
                       now() - make_interval(days => %s), now() - make_interval(days => %s),
                       CASE WHEN %s THEN now() - make_interval(days => %s) END)
               RETURNING id""",
            (repository["repo_id"], branch, repository["user_id"],
             "succeeded" if finished else "running", json.dumps([]) if finished else None,
             days_old, days_old, finished, days_old)).fetchone()[0]


def a_preview(repository: dict, *, path: str = "src/build.py", days_old: int):
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            """INSERT INTO code_preview_runs (repo_id, branch, path, content, output,
                                              input_datasets, requested_by, status, result,
                                              queued_at, started_at, finished_at)
               VALUES (%s, 'main', %s, 'x', 'out', '{}'::jsonb, %s, 'succeeded', '{}'::jsonb,
                       now() - make_interval(days => %s), now() - make_interval(days => %s),
                       now() - make_interval(days => %s))
               RETURNING id""",
            (repository["repo_id"], path, repository["user_id"], days_old, days_old,
             days_old)).fetchone()[0]


def left(table: str, ids: list) -> set:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return {r[0] for r in conn.execute(f"SELECT id FROM {table} WHERE id = ANY(%s)",
                                           (ids,)).fetchall()}


def test_a_branchs_newest_ten_are_kept_and_the_old_rest_go(repository) -> None:
    # Twelve old runs on main: the newest ten of them stay, the two oldest go.
    runs = [a_test_run(repository, days_old=40 + n) for n in range(12)]
    code_run_pruning.prune_code_runs(_ctx())
    assert left("code_test_runs", runs) == set(runs[:10])


def test_recent_and_unfinished_runs_stay_whatever_their_place(repository) -> None:
    recent = [a_test_run(repository, days_old=1) for _ in range(12)]
    old_running = a_test_run(repository, days_old=60, finished=False)
    code_run_pruning.prune_code_runs(_ctx())
    assert left("code_test_runs", recent + [old_running]) == set(recent + [old_running])


def test_each_branch_and_each_file_keeps_its_own_ten(repository) -> None:
    main = [a_test_run(repository, branch="main", days_old=40 + n) for n in range(11)]
    other = [a_test_run(repository, branch="feature", days_old=50) for _ in range(3)]
    one = [a_preview(repository, path="src/a.py", days_old=40 + n) for n in range(11)]
    two = [a_preview(repository, path="src/b.py", days_old=45)]
    code_run_pruning.prune_code_runs(_ctx())
    assert left("code_test_runs", main + other) == set(main[:10] + other)
    assert left("code_preview_runs", one + two) == set(one[:10] + two)


def test_it_calls_again_until_nothing_is_left(repository, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(code_run_pruning, "BATCH", 2)
    runs = [a_test_run(repository, branch="batches", days_old=40 + n) for n in range(15)]
    code_run_pruning.prune_code_runs(_ctx())
    assert left("code_test_runs", runs) == set(runs[:10])
