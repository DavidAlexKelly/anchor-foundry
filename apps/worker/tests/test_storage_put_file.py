"""§907: dataset output is stored from its file, not from memory.

Model runs, syncs and listener archives each wrote their parquet to a temp
file and then read it whole into memory to store it. A run therefore held its
output's size on top of DuckDB's, and on S3 an output past 5 GB, the limit
of a single PUT, could not be stored at all. `put_file` copies or uploads in
parts from the file itself.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from anchor_worker.storage import (  # noqa: E402
    LocalStorageGateway,
    S3StorageGateway,
    StorageKeyError,
)

KEY = "workspaces/ws/datasets/0b5c7f1e-6f1d-4d8e-9a43-2a9c4e5f6a7b/v1/data.parquet"
JOBS = Path(__file__).resolve().parent.parent / "src" / "anchor_worker" / "jobs"


def _file(tmp_path: Path, size: int) -> Path:
    path = tmp_path / "out.parquet"
    path.write_bytes(os.urandom(size))
    return path


def test_the_local_gateway_stores_a_file(tmp_path: Path) -> None:
    gateway = LocalStorageGateway(str(tmp_path / "root"))
    src = _file(tmp_path, 1024)
    gateway.put_file(KEY, str(src))
    assert gateway.read(KEY) == src.read_bytes()
    with pytest.raises(StorageKeyError):
        gateway.put_file("../escape", str(src))


def test_the_s3_gateway_uploads_a_file_in_parts(tmp_path: Path) -> None:
    """A file larger than one part goes up as a multipart upload, which is
    how a file past the single-PUT limit is stored at all."""
    moto = pytest.importorskip("moto")
    with moto.mock_aws():
        import boto3

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="data")
        gateway = S3StorageGateway("data", "us-east-1")
        src = _file(tmp_path, 9 * 1024 * 1024)
        gateway.put_file(KEY, str(src))
        stored = gateway._client.get_object(Bucket="data", Key=KEY)
        assert stored["Body"].read() == src.read_bytes()
        # Parts are what an ETag of a multipart upload records: "<md5>-<n>".
        assert stored["ETag"].strip('"').endswith("-2")
        with pytest.raises(StorageKeyError):
            gateway.put_file("../escape", str(src))


def test_no_job_stores_bytes_it_read_back_from_a_file() -> None:
    """The jobs' only `storage.put` with bytes in hand is a model run's log,
    which is text it captured. Anything else is an output that should go
    through `put_file`."""
    puts = []
    for path in sorted(JOBS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "put"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "storage"):
                puts.append((path.name, ast.unparse(node.args[0])))
    assert puts == [("model_runs.py", "log_key")], puts
