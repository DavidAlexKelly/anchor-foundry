"""The platform makes its own OpenID Connect key on a deployed stack (§871).

CloudFormation can generate a password but not an RSA key, so a stack had
neither OIDC setting and every source configured for OIDC was refused (§599).
Given OIDC_SIGNING_KEY_SECRET, the first API task to need a key makes one and
stores it; every other task, and the worker, signs with the stored one. Against
moto's Secrets Manager.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys

import boto3
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from moto import mock_aws

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import oidc  # noqa: E402

NAME = "anchor/connections/_platform/oidc-signing-key"
WORKER_OIDC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "worker",
                           "src", "anchor_worker", "oidc.py")


def worker_oidc():
    spec = importlib.util.spec_from_file_location("worker_oidc_under_test", WORKER_OIDC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def aws(monkeypatch):
    for k, v in {"AWS_DEFAULT_REGION": "eu-west-2", "AWS_ACCESS_KEY_ID": "testing",
                 "AWS_SECRET_ACCESS_KEY": "testing"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("OIDC_SIGNING_KEY", raising=False)
    monkeypatch.setenv("OIDC_ISSUER", "https://d1.cloudfront.net/api/oidc")
    monkeypatch.setenv("OIDC_SIGNING_KEY_SECRET", NAME)
    monkeypatch.setattr(oidc, "_stored", None)
    with mock_aws():
        yield boto3.client("secretsmanager", region_name="eu-west-2")


def kid() -> str:
    return oidc.jwks()["keys"][0]["kid"]


def test_the_first_task_makes_the_key_and_every_other_signs_with_it(aws, monkeypatch) -> None:
    assert oidc.available()
    first = kid()
    stored = json.loads(aws.get_secret_value(SecretId=NAME)["SecretString"])["pem"]
    assert stored.startswith("-----BEGIN PRIVATE KEY-----")
    # Another task, starting cold, reads the same key rather than making one.
    monkeypatch.setattr(oidc, "_stored", None)
    assert kid() == first
    assert len(aws.list_secrets()["SecretList"]) == 1


def test_a_key_another_task_already_stored_is_the_one_used(aws) -> None:
    theirs = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = theirs.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode()
    aws.create_secret(Name=NAME, SecretString=json.dumps({"pem": pem}))
    assert oidc._public_jwk(theirs)["kid"] == kid()


def test_the_worker_signs_with_the_key_the_api_publishes(aws) -> None:
    published = oidc.jwks()["keys"][0]
    worker = worker_oidc()
    token = worker.mint("connection.r1", "sts.amazonaws.com")
    header, claims, signature = token.split(".")
    pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    assert json.loads(pad(header))["kid"] == published["kid"]
    numbers = rsa.RSAPublicNumbers(int.from_bytes(pad(published["e"]), "big"),
                                   int.from_bytes(pad(published["n"]), "big"))
    numbers.public_key().verify(pad(signature), f"{header}.{claims}".encode(),
                                padding.PKCS1v15(), hashes.SHA256())


def test_the_worker_never_makes_one(aws) -> None:
    worker = worker_oidc()
    assert worker._private_key() is None
    assert aws.list_secrets()["SecretList"] == []


def test_a_key_given_directly_is_used_without_asking(aws, monkeypatch) -> None:
    mine = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("OIDC_SIGNING_KEY", mine.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode())
    assert kid() == oidc._public_jwk(mine)["kid"]
    assert aws.list_secrets()["SecretList"] == []


def test_unreachable_is_not_kept(monkeypatch) -> None:
    monkeypatch.setattr(oidc, "_stored", None)
    monkeypatch.setenv("OIDC_SIGNING_KEY_SECRET", NAME)
    monkeypatch.setenv("OIDC_ISSUER", "https://d1.cloudfront.net/api/oidc")
    monkeypatch.delenv("OIDC_SIGNING_KEY", raising=False)
    monkeypatch.setattr(oidc, "_load_or_create", lambda name: (_ for _ in ()).throw(OSError("down")))
    assert not oidc.available()
    monkeypatch.setattr(oidc, "_load_or_create", lambda name: "kept")
    assert oidc._stored_pem() == "kept"
