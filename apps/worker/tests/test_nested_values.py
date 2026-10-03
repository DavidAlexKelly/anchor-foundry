"""A scheduled sync reads struct and list columns as values (§735).

`json_safe` writes a dict or a list as Python's repr, which no struct or array
property can read, so the sync reads with `json_value`. The API's interactive
sync is tested on the same file shape in `apps/api/tests/test_struct_automap.py`;
this is the worker's copy, and the two functions are compared as source below
for `test_storage_key_parity`'s reason - two packages on purpose, so neither
imports the other.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.dataset_engine import extract_instance_rows, json_value  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_struct_and_list_columns_read_as_values(tmp_path) -> None:
    import duckdb

    path = str(tmp_path / "nested.parquet")
    duckdb.connect().execute(
        "COPY (SELECT 'A1' AS code, {'street': '1 Main St', 'since': DATE '2024-01-02'} AS address, "
        "['north', 'big'] AS tags, [{'n': 1.5::DECIMAL(3,1)}] AS visits) "
        f"TO '{path}' (FORMAT parquet)"
    )
    [(key, values)] = extract_instance_rows(
        path, "code", {"address": "address", "tags": "tags", "visits": "visits"})
    assert key == "A1"
    assert values == {
        "address": {"street": "1 Main St", "since": "2024-01-02"},
        "tags": ["north", "big"],
        "visits": [{"n": "1.5"}],
    }


def test_json_value_recurses_and_leaves_scalars_to_json_safe() -> None:
    assert json_value((1, {"a": None})) == [1, {"a": None}]
    assert json_value({1: "x"}) == {"1": "x"}
    assert json_value("text") == "text"


def _function(path: str, name: str) -> str:
    with open(path) as handle:
        text = handle.read()
    start = text.index(f"def {name}(")
    end = text.find("\n\n\n", start)
    body = text[start:end]
    # The docstring may differ (the API's `json_safe` has none); the code may
    # not.
    if '"""' in body:
        first = body.index('"""')
        body = body[:first] + body[body.index('"""', first + 3) + 3:]
    return "\n".join(line for line in body.splitlines() if line.strip())


def test_the_two_copies_are_the_same_code() -> None:
    api = os.path.join(ROOT, "api", "src", "services", "dataset_engine.py")
    worker = os.path.join(ROOT, "worker", "src", "anchor_worker", "dataset_engine.py")
    # `merge_transaction` (§747) types an incremental sync the same in both.
    for name in ("json_safe", "json_value", "merge_transaction"):
        assert _function(api, name) == _function(worker, name), name
