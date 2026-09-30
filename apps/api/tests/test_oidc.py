"""The platform as an OpenID Connect identity provider, and an S3 source
that authenticates with it (§599; `data-connection` p.11, p.359, p.391).

> "When using OIDC, you do not need to configure credentials for a source
>  system in Foundry... Foundry acts as the OIDC identity provider; every time
>  a workflow in Foundry is required to authenticate with the source system
>  (for example, a Data Connection sync), Foundry will issue an OIDC token
>  with claims that identify the Data Connection source being used. The
>  source system is able to validate those claims and provide a short-lived
>  access token" (p.391)

The source system is a real `moto.server`, whose STS answers
AssumeRoleWithWebIdentity as an S3-compatible store's would. It does not
check the token, so what the token says is asserted here against the key set
this platform publishes, as a source system would check it.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("moto", reason="moto not installed")
import boto3  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, rsa  # noqa: E402

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_s3_connector import REGION, s3_endpoint  # noqa: E402,F401
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.services import connectors as connectors_service  # noqa: E402
from src.services import oidc  # noqa: E402
from src.services.connectors import ConnectorConfigError, S3Connector  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402

ISSUER = "https://platform.example.test/api/oidc"
ROLE = "arn:aws:iam::123456789012:role/anchor-reader"
BUCKET = "oidc-source-bucket"


def pem(key) -> str:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def provider(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER + "/")
    monkeypatch.setenv("OIDC_SIGNING_KEY", pem(KEY))


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def gateway() -> InMemorySecretsGateway:
    return InMemorySecretsGateway()


@pytest.fixture(scope="module")
def client(gateway) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(gateway)
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def cbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections"


def verified(token: str, audience: str) -> dict:
    """What a source system would do with the token: fetch our key set and
    check it."""
    [jwk] = oidc.jwks()["keys"]
    assert jwt.get_unverified_header(token)["kid"] == jwk["kid"]
    return jwt.decode(token, jwt.algorithms.RSAAlgorithm.from_jwk(jwk), algorithms=["RS256"],
                      audience=audience, issuer=ISSUER)


# ---- the identity provider -----------------------------------------------------
def test_p391_a_token_names_the_source_and_lasts_an_hour(provider) -> None:
    before = int(time.time())
    claims = verified(oidc.mint("connection.abc", "sts.amazonaws.com"), "sts.amazonaws.com")
    assert (claims["iss"], claims["sub"], claims["aud"]) == (
        ISSUER, "connection.abc", "sts.amazonaws.com")
    assert claims["iat"] == claims["nbf"] >= before
    assert claims["exp"] - claims["iat"] == 3600
    assert claims["jti"] != verified(oidc.mint("connection.abc", "a"), "a")["jti"]
    with pytest.raises(jwt.InvalidAudienceError):
        verified(oidc.mint("connection.abc", "somebody-else"), "sts.amazonaws.com")


def test_the_discovery_document_and_key_set_are_public(client, provider) -> None:
    r = client.get("/api/oidc/.well-known/openid-configuration")
    assert r.status_code == 200, r.text
    document = r.json()
    assert (document["issuer"], document["jwks_uri"]) == (ISSUER, f"{ISSUER}/jwks")
    assert document["id_token_signing_alg_values_supported"] == ["RS256"]
    keys = client.get("/api/oidc/jwks").json()["keys"]
    assert keys == oidc.jwks()["keys"]
    assert {"n", "e", "kid"} <= set(keys[0]) and "d" not in keys[0]


def test_without_the_deployment_s_settings_nothing_is_issued(client, monkeypatch) -> None:
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.setenv("OIDC_SIGNING_KEY", pem(KEY))
    assert client.get("/api/oidc/jwks").status_code == 404
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    for bad in ("", "not a key", pem(ec.generate_private_key(ec.SECP256R1()))):
        monkeypatch.setenv("OIDC_SIGNING_KEY", bad)
        r = client.get("/api/oidc/.well-known/openid-configuration")
        assert r.status_code == 404 and "OIDC_SIGNING_KEY" in r.json()["detail"], bad
        with pytest.raises(oidc.OidcUnavailable):
            oidc.mint("connection.abc", "a")


# ---- an S3 source configured for it --------------------------------------------
def test_an_s3_source_names_the_role_and_takes_amazon_s_audience() -> None:
    c = S3Connector()
    cleaned = c.validate_config({"bucket": "abc", "oidc_role_arn": ROLE})
    assert (cleaned["oidc_role_arn"], cleaned["oidc_audience"]) == (ROLE, "sts.amazonaws.com")
    assert c.validate_config({"bucket": "abc", "oidc_role_arn": ROLE,
                              "oidc_audience": "minio"})["oidc_audience"] == "minio"
    assert connectors_service.oidc_audience(c.validate_config({"bucket": "abc"})) is None
    for bad, said in (({"oidc_role_arn": "role/anchor"}, "an IAM role ARN"),
                      ({"oidc_role_arn": "arn:aws:iam::12:role/x"}, "an IAM role ARN"),
                      ({"oidc_audience": "minio"}, "needs the role")):
        with pytest.raises(ConnectorConfigError, match=said):
            c.validate_config({"bucket": "abc", **bad})


def create(client, fx, config: dict, secret: dict | None = None):
    return client.post(cbase(fx), headers=hdr(fx.editor_sub), json={
        "name": f"OIDC bucket {uuid.uuid4().hex[:6]}", "source_type": "s3",
        "config": config, **({"secret": secret} if secret else {})})


def test_an_oidc_source_stores_no_credentials(client, fx, provider) -> None:
    r = create(client, fx, {"bucket": BUCKET, "oidc_role_arn": ROLE},
               {"access_key_id": "AKIA", "secret_access_key": "x"})
    assert r.status_code == 422 and "stores no credentials" in r.json()["detail"], r.text


def test_an_oidc_source_is_refused_where_nothing_can_be_issued(client, fx, monkeypatch) -> None:
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    r = create(client, fx, {"bucket": BUCKET, "oidc_role_arn": ROLE})
    assert r.status_code == 422 and "OIDC_ISSUER" in r.json()["detail"], r.text


def test_the_source_says_what_its_trust_policy_names(client, fx, provider) -> None:
    import psycopg
    from test_api import ADMIN_DSN

    r = create(client, fx, {"bucket": BUCKET, "oidc_role_arn": ROLE})
    assert r.status_code == 201, r.text
    made = r.json()
    with psycopg.connect(ADMIN_DSN) as db:
        resource = db.execute("SELECT resource_id FROM connections WHERE id = %s",
                              (made["id"],)).fetchone()[0]
    assert made["oidc"] == {"issuer": ISSUER, "audience": "sts.amazonaws.com",
                            "subject": f"connection.{resource}"}
    keyed = create(client, fx, {"bucket": BUCKET},
                   {"access_key_id": "AKIA", "secret_access_key": "x"}).json()
    assert keyed["oidc"] is None


def test_a_keyed_source_moved_to_oidc_forgets_its_key(client, fx, provider) -> None:
    import psycopg
    from test_api import ADMIN_DSN

    keyed = create(client, fx, {"bucket": BUCKET},
                   {"access_key_id": "AKIA", "secret_access_key": "x"}).json()
    r = client.patch(f"{cbase(fx)}/{keyed['id']}", headers=hdr(fx.editor_sub),
                     json={"config": {"bucket": BUCKET, "oidc_role_arn": ROLE}})
    assert r.status_code == 200, r.text
    with psycopg.connect(ADMIN_DSN) as db:
        assert db.execute("SELECT secret_arn FROM connections WHERE id = %s",
                          (keyed["id"],)).fetchone()[0] is None


@pytest.fixture()
def bucket(s3_endpoint):
    s3 = boto3.client("s3", endpoint_url=s3_endpoint, region_name=REGION,
                      aws_access_key_id="AKIAIOSFODNN7EXAMPLE", aws_secret_access_key="x")
    try:
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass
    s3.put_object(Bucket=BUCKET, Key="in/orders.csv", Body=b"id,total\n1,5\n")
    return s3_endpoint


def test_p391_the_source_trades_its_token_for_access(client, fx, provider, bucket,
                                                    monkeypatch) -> None:
    """The whole exchange, against a store whose STS answers it: the source
    is tested and browsed with no credential stored anywhere."""
    traded: list[dict] = []
    real_client = boto3.client

    def spying_client(service, **kwargs):
        made = real_client(service, **kwargs)
        if service == "sts":
            original = made.assume_role_with_web_identity

            def assume(**call):
                traded.append(call)
                return original(**call)
            made.assume_role_with_web_identity = assume
        return made
    monkeypatch.setattr(boto3, "client", spying_client)

    r = create(client, fx, {"bucket": BUCKET, "prefix": "in", "region": REGION,
                            "endpoint_url": bucket, "oidc_role_arn": ROLE})
    assert r.status_code == 201, r.text
    made = r.json()
    r = client.post(f"{cbase(fx)}/{made['id']}/test", headers=hdr(fx.editor_sub))
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    r = client.post(f"{cbase(fx)}/{made['id']}/discover", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert "orders.csv" in r.text
    assert traded and traded[0]["RoleArn"] == ROLE
    claims = verified(traded[0]["WebIdentityToken"], "sts.amazonaws.com")
    assert claims["sub"] == made["oidc"]["subject"]


def test_a_refused_token_says_what_to_check(client, fx, provider, bucket, monkeypatch) -> None:
    from botocore.exceptions import ClientError

    real_client = boto3.client

    def refusing_client(service, **kwargs):
        made = real_client(service, **kwargs)
        if service == "sts":
            def assume(**_):
                raise ClientError({"Error": {"Code": "InvalidIdentityToken"}},
                                  "AssumeRoleWithWebIdentity")
            made.assume_role_with_web_identity = assume
        return made
    monkeypatch.setattr(boto3, "client", refusing_client)
    made = create(client, fx, {"bucket": BUCKET, "region": REGION, "endpoint_url": bucket,
                               "oidc_role_arn": ROLE}).json()
    r = client.post(f"{cbase(fx)}/{made['id']}/test", headers=hdr(fx.editor_sub))
    assert r.json()["ok"] is False
    assert "refused this platform's OpenID Connect token (InvalidIdentityToken)" in \
        r.json()["error"]


def test_the_worker_signs_with_the_same_code() -> None:
    """The worker's `oidc.py` holds these functions verbatim: a scheduled sync
    and an interactive one must issue the same token."""
    import ast

    here = os.path.dirname(os.path.abspath(__file__))
    api_path = os.path.join(here, "..", "src", "services", "oidc.py")
    worker_path = os.path.join(here, "..", "..", "worker", "src", "anchor_worker", "oidc.py")

    def definitions(path: str) -> dict[str, str]:
        source = open(path).read()
        out = {}
        for node in ast.parse(source).body:
            name = getattr(node, "name", None)
            if isinstance(node, ast.Assign):
                name = node.targets[0].id
            if name:
                out[name] = ast.get_source_segment(source, node)
        return out
    api, worker = definitions(api_path), definitions(worker_path)
    shared = ("LIFETIME_SECONDS", "ALGORITHM", "OidcUnavailable", "_b64", "issuer",
              "_private_key", "_require", "_public_jwk", "subject_for", "mint")
    for name in shared:
        assert worker.get(name) == api[name], f"the worker's {name} differs from the API's"


def test_an_export_to_the_source_is_told_who_it_is(client, fx, gateway, provider) -> None:
    """An export writes through the same connector, so the row its reader
    hands over has to name the source as the others do."""
    import asyncio

    import psycopg
    from test_api import ADMIN_DSN
    from src.lib.db import user_connection
    from src.services import connections as conn_service
    from src.services import export_store

    made = create(client, fx, {"bucket": BUCKET, "oidc_role_arn": ROLE}).json()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        db.execute("UPDATE connections SET exports_enabled = true WHERE id = %s", (made["id"],))

    async def read():
        async with user_connection(fx.editor) as conn:
            return await export_store.connection_for(conn, fx.project, uuid.UUID(made["id"]))
    row = asyncio.run(read())
    assert conn_service.secret_values_for(gateway, row) == {"oidc_subject": made["oidc"]["subject"]}
