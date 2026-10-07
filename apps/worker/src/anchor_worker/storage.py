"""Dataset file storage - worker's copy of apps/api's services/storage.py.
Duplicated rather than shared: api and worker are independently deployable
images (separate Dockerfiles, separate dependency sets) with no shared
Python package between them in this build, the same reason control-plane
carries its own AWS logic rather than importing api's. Keep this in sync
with api's storage.py if the key layout ever changes.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Protocol

# Kept in step with the API's copy (roadmap Objects item 4 widened it to
# cover object attachments; §358 added `runs` for a model run's log). The
# worker never reads an attachment today, but a validator that is *narrower*
# than the writer's is how a key written by one service becomes unreadable by
# the other — and §358 is that case pointed the other way, since the worker
# writes run logs and only the API reads them.
_KEY_RE = re.compile(
    r"^workspaces/[a-z0-9-]+/(datasets|attachments|runs)/[0-9a-f-]{36}/[A-Za-z0-9._/-]+$"
)


class StorageKeyError(ValueError):
    """Key failed validation. Message is user-safe."""


def validate_key(key: str) -> str:
    if ".." in key or key.startswith("/") or not _KEY_RE.match(key):
        raise StorageKeyError("invalid storage key")
    return key


class StorageGateway(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def put_file(self, key: str, path: str) -> None: ...

    def read(self, key: str) -> bytes: ...

    def local_path(self, key: str) -> str: ...

    def size(self, key: str) -> int | None: ...

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

    def put_file(self, key: str, path: str) -> None:
        """Copy a file into place without holding it in memory (§907)."""
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

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

    def size(self, key: str) -> int | None:
        path = self._path(key)
        return path.stat().st_size if path.is_file() else None

    def delete_prefix(self, prefix: str) -> None:
        if ".." in prefix or not prefix.startswith("workspaces/"):
            raise StorageKeyError("invalid storage prefix")
        target = (self._root / prefix).resolve()
        if target.is_relative_to(self._root) and target.is_dir():
            shutil.rmtree(target)


# ---- S3 objects on local disk (§869) -----------------------------------------
# `local_path` hands DuckDB a file. On S3 it downloaded the whole object to a
# new temporary file on every call and nothing ever removed one: every query,
# preview, object-set read and export left a full copy behind, and a task that
# ran long enough filled its disk and failed every read after. A copy is now
# kept by the object's key and ETag - so a repeat read costs a HEAD rather than
# a download, and an object that changed is fetched again - and the least
# recently used are deleted once the copies pass a size. Kept in step with the
# other app's copy by `test_storage_cache_parity.py`.
CACHE_DIR = os.path.join(tempfile.gettempdir(), "anchor-s3-cache")
CACHE_MAX_BYTES = int(os.environ.get("STORAGE_CACHE_MAX_BYTES", str(4 * 1024**3)))
#: Only a copy nobody has asked for this long is deleted: a caller handed a
#: path opens it within moments, and must not find it gone. So the size is a
#: target rather than a ceiling - copies all in use are kept.
CACHE_IDLE_SECONDS = 15 * 60


def cached_copy(client, bucket: str, key: str, *, cache_dir: str | None = None,
                max_bytes: int | None = None, idle_seconds: float | None = None) -> str:
    """A local file holding the object's current bytes. The settings are read
    when called, not when defined, so a test or an operator can move them."""
    cache_dir = cache_dir or CACHE_DIR
    max_bytes = CACHE_MAX_BYTES if max_bytes is None else max_bytes
    idle_seconds = CACHE_IDLE_SECONDS if idle_seconds is None else idle_seconds
    tag = str(client.head_object(Bucket=bucket, Key=key).get("ETag", "")).strip('"')
    name = hashlib.sha256(f"{key}\0{tag}".encode()).hexdigest() + Path(key).suffix
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, name)
    if os.path.exists(path):
        os.utime(path)  # used now: last in line to be deleted
        return path
    fd, partial = tempfile.mkstemp(dir=cache_dir, suffix=".partial")
    try:
        with os.fdopen(fd, "wb") as handle:
            client.download_fileobj(bucket, key, handle)
        os.replace(partial, path)  # whole or not at all: no reader sees half a file
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(partial)
        raise
    _evict(cache_dir, max_bytes, idle_seconds, keep=path)
    return path


def _evict(cache_dir: str, max_bytes: int, idle_seconds: float, *, keep: str) -> None:
    """Delete idle copies, least recently used first, until under max_bytes."""
    entries = []
    for entry in os.scandir(cache_dir):
        with contextlib.suppress(FileNotFoundError):
            stat = entry.stat()
            entries.append((stat.st_mtime, stat.st_size, entry.path))
    total = sum(size for _, size, _ in entries)
    now = time.time()
    for mtime, size, path in sorted(entries):
        if total <= max_bytes:
            break
        if path == keep or now - mtime < idle_seconds:
            continue
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
            total -= size


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

    def put_file(self, key: str, path: str) -> None:
        """Upload a file from disk in parts (§907). A dataset's output used to
        be read whole into memory and sent in one request, so a run held its
        output's size on top of DuckDB's, and a file past 5 GB, the limit
        of a single PUT, could not be stored at all. Four 8 MiB parts in flight
        bound what this holds."""
        from boto3.s3.transfer import TransferConfig  # deferred, as boto3 is

        validate_key(key)
        self._client.upload_file(
            path, self._bucket, key,
            Config=TransferConfig(multipart_chunksize=8 * 1024 * 1024, max_concurrency=4),
        )

    def read(self, key: str) -> bytes:
        validate_key(key)
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def local_path(self, key: str) -> str:
        validate_key(key)
        return cached_copy(self._client, self._bucket, key)

    def size(self, key: str) -> int | None:
        validate_key(key)
        try:
            return int(self._client.head_object(Bucket=self._bucket, Key=key)["ContentLength"])
        except Exception:
            return None

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


def run_log_key(ws_s3_prefix: str, run_id) -> str:
    """Where a model run's log lives (§358).

    **Keyed by the run, not by the dataset it produced**, and that is the
    load-bearing part: a failed run produces no dataset at all, and its log is
    the one most worth keeping — so a key derived from output would have
    nowhere to put exactly the logs somebody goes looking for.

    The `runs/` segment itself is a name rather than a mechanism, and §358's
    sweep said so: a mutant filing the same log under `datasets/` survived,
    correctly. Nothing collides either way, because a run id is not a dataset
    id, and `delete_prefix` for a dataset names that dataset's own id. What the
    grammar *does* enforce is the workspace prefix, and a mutant dropping that
    is caught — see `validate_key` and `test_storage_key_parity`.
    """
    return f"{ws_s3_prefix}runs/{run_id}/log.txt"


_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,61}[a-z0-9])?$")


def slugify(name: str) -> str:
    """Matches apps/api's services/datasets.py slugify exactly - dataset
    slugs must agree regardless of which side (API upload/sync, or worker
    model/sync run) creates the row."""
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")
    slug = re.sub(r"-{2,}", "-", slug)[:63].strip("-_")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"cannot derive a valid slug from {name!r}")
    return slug


#: The data bucket's variable: the name the stack sets (`commonEnv` in
#: infra/cdk/src/constructs/services.ts) and the API reads. This read
#: `DATA_BUCKET`, which nothing set, so every deployed worker wrote to its own
#: container's disk - syncs, model outputs and exports the API, reading S3,
#: could never see (§844).
BUCKET_ENV = "S3_DATA_BUCKET"
#: Set by the ECS agent in every task, and by nothing in development or tests.
ECS_MARKER = "ECS_CONTAINER_METADATA_URI_V4"


def gateway_from_env() -> StorageGateway:
    import os

    bucket = os.environ.get(BUCKET_ENV)
    if bucket:
        return S3StorageGateway(bucket, os.environ.get("AWS_REGION", "us-east-1"))
    if os.environ.get(ECS_MARKER):
        # Deployed and no bucket: the local fallback here is a disk nobody
        # else can read, which is the failure this replaced. Refuse instead.
        raise RuntimeError(
            f"running on ECS without {BUCKET_ENV}: refusing to store data on "
            "the worker's own disk"
        )
    return LocalStorageGateway(os.environ.get("LOCAL_STORAGE_ROOT", "/tmp/anchor-worker-storage"))
