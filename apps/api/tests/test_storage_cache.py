"""S3 objects on local disk are kept, reused, and evicted (§869).

`local_path` downloaded the whole object to a new temporary file on every
call, and nothing removed one: a long-running task filled its disk. Against
moto's S3, which answers HEAD with an ETag as S3 does.
"""
from __future__ import annotations

import os
import sys
import time

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import storage  # noqa: E402

BUCKET = "data"
KEY = "workspaces/w-cache/datasets/00000000-0000-0000-0000-000000000001/v1/data.parquet"


@pytest.fixture
def s3(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-2")
        client.create_bucket(Bucket=BUCKET,
                             CreateBucketConfiguration={"LocationConstraint": "eu-west-2"})
        gateway = storage.S3StorageGateway.__new__(storage.S3StorageGateway)
        gateway._client, gateway._bucket = client, BUCKET
        monkeypatch.setattr(storage, "CACHE_DIR", str(tmp_path / "cache"))
        yield client, gateway, tmp_path / "cache"


def downloads(client, monkeypatch) -> list[str]:
    seen: list[str] = []
    real = client.download_fileobj
    monkeypatch.setattr(client, "download_fileobj",
                        lambda bucket, key, handle: (seen.append(key), real(bucket, key, handle))[1])
    return seen


def test_a_repeat_read_reuses_the_copy(s3, monkeypatch) -> None:
    client, gateway, cache = s3
    client.put_object(Bucket=BUCKET, Key=KEY, Body=b"v1 bytes")
    seen = downloads(client, monkeypatch)
    first = gateway.local_path(KEY)
    assert gateway.local_path(KEY) == first
    assert seen == [KEY]
    assert open(first, "rb").read() == b"v1 bytes"
    assert first.endswith(".parquet") and os.path.dirname(first) == str(cache)


def test_a_changed_object_is_fetched_again(s3) -> None:
    client, gateway, _ = s3
    client.put_object(Bucket=BUCKET, Key=KEY, Body=b"before")
    before = gateway.local_path(KEY)
    client.put_object(Bucket=BUCKET, Key=KEY, Body=b"after")
    after = gateway.local_path(KEY)
    assert after != before and open(after, "rb").read() == b"after"


def test_idle_copies_go_first_once_past_the_size(s3) -> None:
    client, _, cache = s3
    keys = [KEY.replace("v1", f"v{n}") for n in range(1, 4)]
    for key in keys:
        client.put_object(Bucket=BUCKET, Key=key, Body=b"x" * 100)
    first, second = (storage.cached_copy(client, BUCKET, k, cache_dir=str(cache),
                                         max_bytes=10_000) for k in keys[:2])
    past = time.time() - 3600
    os.utime(first, (past, past))
    # Over a 150-byte target: the idle copy goes, the recent one and the new one stay.
    third = storage.cached_copy(client, BUCKET, keys[2], cache_dir=str(cache),
                                max_bytes=150, idle_seconds=60)
    assert not os.path.exists(first)
    assert os.path.exists(second) and os.path.exists(third)


def test_copies_in_use_are_kept_even_past_the_size(s3) -> None:
    client, _, cache = s3
    keys = [KEY.replace("v1", f"v{n}") for n in range(1, 4)]
    for key in keys:
        client.put_object(Bucket=BUCKET, Key=key, Body=b"x" * 100)
    paths = [storage.cached_copy(client, BUCKET, k, cache_dir=str(cache), max_bytes=1,
                                 idle_seconds=600) for k in keys]
    assert all(os.path.exists(p) for p in paths)


def test_a_failed_download_leaves_nothing(s3, monkeypatch) -> None:
    client, gateway, cache = s3
    client.put_object(Bucket=BUCKET, Key=KEY, Body=b"bytes")

    def broken(bucket, key, handle):
        handle.write(b"half")
        raise ConnectionError("reset")

    monkeypatch.setattr(client, "download_fileobj", broken)
    with pytest.raises(ConnectionError):
        gateway.local_path(KEY)
    assert list(cache.iterdir()) == []
