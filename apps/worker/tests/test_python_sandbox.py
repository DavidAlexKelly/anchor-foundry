"""Python transform sandbox tests — no database needed, just the subprocess
executor against real Parquet files."""
from __future__ import annotations

import os
import sys
import tempfile

import duckdb
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.dataset_engine import DatasetEngineError  # noqa: E402
from anchor_worker.python_sandbox import run_python_transform  # noqa: E402


@pytest.fixture()
def input_parquet(tmp_path) -> str:
    path = str(tmp_path / "in.parquet")
    con = duckdb.connect()
    con.execute(f"COPY (SELECT * FROM (VALUES (1,'a'),(2,'b')) t(id,name)) TO '{path}' (FORMAT parquet)")
    return path


def test_transform_produces_output(input_parquet: str, tmp_path) -> None:
    dest = str(tmp_path / "out.parquet")
    schema, rows = run_python_transform(
        {"t": input_parquet}, "output = t.copy()\noutput['upper_name'] = output['name'].str.upper()",
        dest,
    )
    assert rows == 2
    names = {c.name for c in schema}
    assert {"id", "name", "upper_name"} <= names
    result = duckdb.connect().execute(f"SELECT * FROM read_parquet('{dest}') ORDER BY id").fetchall()
    assert result == [(1, "a", "A"), (2, "b", "B")]


def test_exception_in_user_code_is_reported(input_parquet: str, tmp_path) -> None:
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError, match="ZeroDivisionError"):
        run_python_transform({"t": input_parquet}, "output = 1 / 0", dest)


def test_missing_output_variable_is_reported(input_parquet: str, tmp_path) -> None:
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError, match="output"):
        run_python_transform({"t": input_parquet}, "x = 1", dest)


def test_timeout_is_enforced(input_parquet: str, tmp_path) -> None:
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError, match="time limit"):
        run_python_transform(
            {"t": input_parquet}, "import time\ntime.sleep(5)\noutput = t", dest, timeout_s=1,
        )


def test_row_count_cap_is_enforced(input_parquet: str, tmp_path, monkeypatch) -> None:
    import anchor_worker.python_sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module, "MAX_OUTPUT_ROWS", 1)
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError, match="row limit"):
        run_python_transform({"t": input_parquet}, "output = t", dest)


def test_sandbox_cannot_read_arbitrary_files(input_parquet: str, tmp_path) -> None:
    """Not a claim of a hard security boundary (see the module's docstring)
    — just confirms the subprocess's cwd/HOME are the scratch dir, not the
    caller's, so a script reading a relative path can't see unrelated data."""
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError):
        run_python_transform(
            {"t": input_parquet},
            "output = t\nopen('does_not_exist_here.txt').read()",
            dest,
        )
