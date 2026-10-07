"""§913: what the API writes to a dataset is stored from its file.

The API's own dataset writers - a sync, a model run, an action's edit, a file
sync, a listener archive, the action log's columns and a fork - each wrote
their parquet to a temp file, then read it whole into memory to store it. A
200 MB sync, or an object type's backing dataset rewritten by one edit, sat in
the API's memory on top of DuckDB's share of the task, beside every other
request on it. `put_file` copies, or uploads in parts, from the file itself:
the worker's §907, for the API.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services import datasets as ds_service  # noqa: E402
from src.services.storage import (  # noqa: E402
    LocalStorageGateway,
    S3StorageGateway,
    StorageKeyError,
)

KEY = "workspaces/ws/datasets/0b5c7f1e-6f1d-4d8e-9a43-2a9c4e5f6a7b/v1/data.parquet"
SRC = Path(__file__).resolve().parent.parent / "src"


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
    moto = pytest.importorskip("moto")
    with moto.mock_aws():
        import boto3

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="data")
        gateway = S3StorageGateway("data", "us-east-1")
        src = _file(tmp_path, 9 * 1024 * 1024)
        gateway.put_file(KEY, str(src))
        stored = gateway._client.get_object(Bucket="data", Key=KEY)
        assert stored["Body"].read() == src.read_bytes()
        # A multipart upload's ETag records its parts: "<md5>-<n>".
        assert stored["ETag"].strip('"').endswith("-2")
        with pytest.raises(StorageKeyError):
            gateway.put_file("../escape", str(src))


@pytest.mark.parametrize("given", [{}, {"parquet_bytes": b"x", "parquet_path": "/x"}])
def test_a_version_is_written_from_bytes_or_a_path_not_both(given: dict) -> None:
    with pytest.raises(ValueError, match="one of them"):
        asyncio.run(ds_service.stage_version(
            None, None, dataset_id=uuid4(), workspace_id=uuid4(), schema=[], row_count=0,
            produced_by_kind="upload", produced_by_id=None, created_by=uuid4(),
            transaction_type="SNAPSHOT", **given))


def _enclosing(tree: ast.AST) -> dict[ast.AST, str]:
    owner: dict[ast.AST, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Outer functions are walked first, so a nested one's name wins.
            for node in ast.walk(fn):
                owner[node] = fn.name
    return owner


def _sites(predicate) -> list[tuple[str, str]]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        owner = _enclosing(tree)
        for node in ast.walk(tree):
            if predicate(node):
                found.append((str(path.relative_to(SRC)), owner.get(node, "<module>")))
    return sorted(found)


def test_bytes_go_to_storage_only_where_they_are_small_or_already_in_hand() -> None:
    """Every `.put` of bytes left in the API is a file a person sent, which
    the request already holds and the body limit caps, or `stage_version`'s
    bytes branch. A new one is either one of those or an output that should
    go through `put_file`."""
    def is_put(node: ast.AST) -> bool:
        if not (isinstance(node, ast.Attribute) and node.attr == "put"):
            return False
        value = node.value
        if isinstance(value, ast.Name):
            return value.id in {"storage", "_storage"}
        return isinstance(value, ast.Call) and "storage" in ast.unparse(value.func)

    assert _sites(is_put) == [
        ("routes/datasets.py", "ingest"),            # the upload's original file
        ("routes/datasets.py", "upload_file_into"),  # one more file of it
        ("routes/objects.py", "upload_attachment"),
        ("services/action_functions.py", "store_attachments"),
        ("services/datasets.py", "stage_version"),   # the bytes branch
    ]


def test_versions_come_from_bytes_only_where_the_bytes_are_small() -> None:
    """`parquet_bytes=` is for an output small by construction. The two in
    routes/datasets.py combine an upload dataset's files, whose originals are
    already read into memory, one each at most 50 MB."""
    def is_bytes_version(node: ast.AST) -> bool:
        return (isinstance(node, ast.keyword) and node.arg == "parquet_bytes"
                and not (isinstance(node.value, ast.Name) and node.value.id == "parquet_bytes"))

    assert _sites(is_bytes_version) == [
        ("routes/datasets.py", "parse_again"),
        ("routes/datasets.py", "upload_file_into"),
        ("services/datasets.py", "create_empty"),    # an empty dataset's file
    ]
