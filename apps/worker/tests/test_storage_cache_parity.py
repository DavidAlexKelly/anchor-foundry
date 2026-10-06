"""The two apps keep S3 objects on disk the same way (§869).

The API and the worker each materialise objects for DuckDB, and each leaked a
full copy per read until both had the same cache. They share no Python on
purpose (see `test_storage_key_parity.py`), so the cache is written twice and
compared here as source: a fix to one that misses the other fails this.
"""
from __future__ import annotations

import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = os.path.join(ROOT, "api", "src", "services", "storage.py")
WORKER = os.path.join(ROOT, "worker", "src", "anchor_worker", "storage.py")
SHARED = ("CACHE_DIR", "CACHE_MAX_BYTES", "CACHE_IDLE_SECONDS", "cached_copy", "_evict")


def definitions(path: str) -> dict[str, str]:
    source = open(path).read()
    found: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            found[node.name] = ast.get_source_segment(source, node)
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = ast.get_source_segment(source, node)
    return found


def test_the_cache_is_the_same_in_both_apps() -> None:
    api, worker = definitions(API), definitions(WORKER)
    for name in SHARED:
        assert name in api and name in worker, name
        assert api[name] == worker[name], f"{name} differs between the API and the worker"


def test_both_gateways_read_through_it() -> None:
    for path in (API, WORKER):
        source = open(path).read()
        assert "return cached_copy(self._client, self._bucket, key)" in source, path
        assert "NamedTemporaryFile(delete=False" not in source, path
