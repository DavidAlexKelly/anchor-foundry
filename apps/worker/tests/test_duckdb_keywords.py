"""A scheduled SQL model naming a column DuckDB 1.4 made a keyword says
which word (§952): this is where saved SQL meets the upgrade unattended."""
from __future__ import annotations

import os
import sys

import duckdb
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import dataset_engine  # noqa: E402


def test_a_scheduled_model_says_which_word(tmp_path) -> None:
    path = str(tmp_path / "in.parquet")
    duckdb.sql(f"""COPY (SELECT 1 AS "by", 2 AS b) TO '{path}' (FORMAT parquet)""")
    with pytest.raises(dataset_engine.DatasetEngineError, match='"by" is a keyword'):
        dataset_engine.run_sql_transform({"t": path}, "SELECT by FROM t",
                                         str(tmp_path / "out.parquet"))
    schema, rows = dataset_engine.run_sql_transform(
        {"t": path}, 'SELECT "by" FROM t ORDER BY b', str(tmp_path / "out.parquet"))
    assert rows == 1
