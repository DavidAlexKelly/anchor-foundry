"""Dataset file storage — worker's copy of apps/api's services/storage.py.
Duplicated rather than shared: api and worker are independently deployable
images (separate Dockerfiles, separate dependency sets) with no shared
Python package between them in this build, the same reason control-plane
carries its own AWS logic rather than importing api's. Keep this in sync
with api's storage.py if the key layout ever changes.
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

    def local_path(self, key: str) -> str: ...

    def delete_prefix(self, prefix: str) -> None: ...


class LocalStorageGateway:
    """Development gateway: keys map to files under a root directory."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
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
        if ".." in prefix or not prefix.startswith("workspaces/"):
            raise StorageKeyError("invalid storage prefix")
        target = (self._root / prefix).resolve()
        if target.is_relative_to(self._root) and target.is_dir():
            shutil.rmtree(target)


class S3StorageGateway:
    """Production gateway. The worker task role is scoped to the data
    bucket's workspaces/* prefix, same as the API's."""

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


def storage_prefix(ws_s3_prefix: str, dataset_id) -> str:
    return f"{ws_s3_prefix}datasets/{dataset_id}/"


_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,61}[a-z0-9])?$")


def slugify(name: str) -> str:
    """Matches apps/api's services/datasets.py slugify exactly — dataset
    slugs must agree regardless of which side (API upload/sync, or worker
    model/sync run) creates the row."""
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")
    slug = re.sub(r"-{2,}", "-", slug)[:63].strip("-_")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"cannot derive a valid slug from {name!r}")
    return slug


def gateway_from_env() -> StorageGateway:
    import os

    bucket = os.environ.get("DATA_BUCKET")
    if bucket:
        return S3StorageGateway(bucket, os.environ.get("AWS_REGION", "us-east-1"))
    return LocalStorageGateway(os.environ.get("LOCAL_STORAGE_ROOT", "/tmp/anchor-worker-storage"))
