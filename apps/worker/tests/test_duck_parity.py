"""The two apps open DuckDB the same way (§875).

Both read `DUCKDB_MEMORY_LIMIT` and `DUCKDB_THREADS` from the task and spill
to the same place. They share no Python on purpose (see
`test_storage_key_parity.py`), so `duck.py` is written twice: the files may
differ only in the sentence naming each other.
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = os.path.join(ROOT, "api", "src", "lib", "duck.py")
WORKER = os.path.join(ROOT, "worker", "src", "anchor_worker", "duck.py")


def _without_the_pointer(path: str) -> list[str]:
    return [line for line in open(path).read().splitlines() if "is the same file for the" not in line]


def test_the_api_and_the_worker_open_duckdb_the_same_way() -> None:
    assert _without_the_pointer(API) == _without_the_pointer(WORKER)


def test_nothing_opens_duckdb_around_it() -> None:
    """A bare `duckdb.connect()` takes 80% of the task again. The sandboxed
    Python and the transform runner are their own processes and keep theirs;
    parsing a statement allocates nothing."""
    allowed = {"duck.py", "python_sandbox.py", "transform_runner.py"}
    for top in (os.path.join(ROOT, "api", "src"), os.path.join(ROOT, "worker", "src")):
        for folder, _, files in os.walk(top):
            for name in files:
                if not name.endswith(".py") or name in allowed:
                    continue
                for line in open(os.path.join(folder, name)).read().splitlines():
                    if "duckdb.connect(" in line and ".extract_statements(" not in line:
                        raise AssertionError(f"{name}: {line.strip()}")
