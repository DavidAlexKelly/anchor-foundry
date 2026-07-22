"""Dataset file storage (spec §8 "S3 as the foundation").

All dataset bytes live under the owning workspace's s3_prefix — the same
isolation anchor IAM policies are scoped to — so storage isolation holds by
construction. The gateway hides where that prefix physically lives: the
customer's S3 bucket in production, a directory in local development.

Keys are validated against a strict shape before any filesystem/S3 call:
they must start with a known workspace prefix pattern and contain no path
traversal. Both gateways enforce this so a bug elsewhere cannot escape the
storage root.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Protocol

_KEY_RE = re.compile(r"^workspaces/[a-z0-9-]+/datasets/[0-9a-f-]{36}/[A-Za-z0-9._/-]+$")


class StorageKeyError(ValueError):
    """Key failed validation. Message is user-safe."""


def validate_key(key: str) -> str:
    if ".." in key or key.startswith("/") or not _KEY_RE.match(key):
        raise StorageKeyError("invalid storage key")
    return key


class StorageGateway(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def read(self, key: str) -> bytes: ...

    def local_path(self, key: str) -> str:
        """A filesystem path DuckDB can read. The S3 gateway materialises the
        object to a temp file; callers treat the path as read-only and
        short-lived."""
        ...

    def delete_prefix(self, prefix: str) -> None:
        """Remove every object under prefix (dataset deletion)."""
        ...


class LocalStorageGateway:
    """Development gateway: keys map to files under a root directory."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):  # belt over the regex braces
            raise StorageKeyError("invalid storage key")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def local_path(self, key: str) -> str:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return str(path)

    def delete_prefix(self, prefix: str) -> None:
        # Prefix ends at the dataset directory: workspaces/<ws>/datasets/<id>/
        if ".." in prefix or not prefix.startswith("workspaces/"):
            raise StorageKeyError("invalid storage prefix")
        target = (self._root / prefix).resolve()
        if target.is_relative_to(self._root) and target.is_dir():
            shutil.rmtree(target)


class S3StorageGateway:
    """Production gateway. The API/worker task roles are scoped to the data
    bucket's workspaces/* prefix (CDK services construct)."""

    def __init__(self, bucket: str, region: str) -> None:
        import boto3  # deferred: not installed in local dev

        self._bucket = bucket
        self._client = boto3.client("s3", region_name=region)

    def put(self, key: str, data: bytes) -> None:
        validate_key(key)
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def read(self, key: str) -> bytes:
        validate_key(key)
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def local_path(self, key: str) -> str:
        import tempfile

        validate_key(key)
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=Path(key).suffix)
        self._client.download_fileobj(self._bucket, key, handle)
        handle.close()
        return handle.name

    def delete_prefix(self, prefix: str) -> None:
        if ".." in prefix or not prefix.startswith("workspaces/"):
            raise StorageKeyError("invalid storage prefix")
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})
