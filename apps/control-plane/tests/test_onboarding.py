"""Self-service onboarding (ROADMAP section 7 item 2).

AWS and CDK are faked; the registry runs against the real local Postgres, and
the HTTP surface is exercised through FastAPI's TestClient. What these tests
protect is the part of onboarding that is a *security* boundary rather than a
convenience: one customer's link must reach exactly one customer's onboarding,
the operator route must not be open, and the external ID must never come back
out of a token-authenticated read.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.api.app import create_app  # noqa: E402
from src.onboarding.service import (  # noqa: E402
    OnboardingConfig,
    OnboardingService,
    bootstrap_role_arn,
    launch_url,
)
from src.provisioner.provisioner import TempCredentials  # noqa: E402
from src.registry.registry import StackRegistry, StackStatus  # noqa: E402

DSN = os.environ["CONTROL_PLANE_DATABASE_URL"]
ADMIN = "operator-token-for-tests"


class XorCodec:
    def encrypt(self, plaintext: str) -> bytes:
        return bytes(b ^ 0x42 for b in plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        return bytes(b ^ 0x42 for b in ciphertext).decode()


class FakeAws:
    """Enough gateway to drive onboarding. `assumable` is the switch the
    detection step turns on when the customer runs the template."""

    def __init__(self) -> None:
        self.assumable = False
        self.cdk_version: str | None = "18"
        self.eips = (1, 5)
        self.existing_stack: str | None = None
        self.events = [
            {"timestamp": "2026-01-01T10:00:01", "logical_id": "Vpc",
             "resource_type": "AWS::EC2::VPC", "status": "CREATE_COMPLETE", "reason": ""},
        ]

    def assume_bootstrap_role(self, role_arn: str, external_id: str, session_name: str):
        if not self.assumable:
            raise RuntimeError("AccessDenied: not authorized to perform sts:AssumeRole")
        return TempCredentials("AKIA_FAKE", "secret", "token")

    def cdk_bootstrap_version(self, creds, region):
        return self.cdk_version

    def elastic_ip_headroom(self, creds, region):
        return self.eips

    def stack_status(self, creds, region, stack_name):
        return self.existing_stack

    def stack_events(self, creds, region, stack_name, limit=25):
        return self.events


class FakeProvisioner:
    def __init__(self, registry: StackRegistry) -> None:
        self._registry = registry
        self.calls: list[tuple[str, str]] = []
        self.explode = False

    def provision(self, org_slug: str, image_tag: str) -> dict[str, str]:
        self.calls.append((org_slug, image_tag))
        if self.explode:
            self._registry.set_status(org_slug, StackStatus.FAILED)
            raise RuntimeError("CREATE_FAILED: OpenSearch domain never came up")
        self._registry.set_status(
            org_slug, StackStatus.READY, platform_url="https://d123.cloudfront.net",
            outputs={"PlatformDomain": "d123.cloudfront.net"},
        )
        return {"PlatformDomain": "d123.cloudfront.net"}


@pytest.fixture()
def registry() -> StackRegistry:
    reg = StackRegistry(DSN, XorCodec())
    reg.ensure_schema()
    return reg


@pytest.fixture()
def aws() -> FakeAws:
    return FakeAws()


@pytest.fixture()
def provisioner(registry: StackRegistry) -> FakeProvisioner:
    return FakeProvisioner(registry)


@pytest.fixture()
def client(registry: StackRegistry, aws: FakeAws, provisioner: FakeProvisioner) -> TestClient:
    service = OnboardingService(
        registry, aws, provisioner,  # type: ignore[arg-type]
        OnboardingConfig(
            template_url="https://vendor.example/bootstrap.yaml",
            control_plane_role_arn="arn:aws:iam::999999999999:role/control-plane",
        ),
        # Synchronous: a test that raced a daemon thread would be a test that
        # fails on a slow machine and nowhere else.
        runner=lambda run: run(),
    )
    app = create_app(service, registry, admin_token=ADMIN, base_url="https://onboard.example")
    return TestClient(app)


def slug() -> str:
    return f"cust-{uuid.uuid4().hex[:10]}"


def start(client: TestClient) -> dict:
    r = client.post(
        "/api/onboardings", headers={"Authorization": f"Bearer {ADMIN}"},
        json={"org_slug": slug(), "org_name": "Acme Logistics", "contact_email": "ops@acme-logistics.example"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---- the link the customer gets ---------------------------------------------
def test_the_launch_url_carries_both_parameters(client: TestClient, aws: FakeAws) -> None:
    """The whole point: the customer clicks, ticks the IAM box and creates.
    Every character they would otherwise copy by hand is in the link."""
    started = start(client)
    r = client.post(
        "/api/onboarding/launch-url",
        headers={"Authorization": f"Bearer {started['onboarding_token']}"},
        json={"aws_region": "eu-west-2"},
    )
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert "console.aws.amazon.com/cloudformation" in url
    assert "param_ExternalId=" in url and "param_ControlPlaneRoleArn=" in url
    assert "templateURL=https%3A%2F%2Fvendor.example%2Fbootstrap.yaml" in url


def test_the_role_arn_is_derived_not_typed() -> None:
    """The template hardcodes the role name, so a 12-digit account ID is the
    only unknown - and an ARN nobody types is an ARN nobody mistypes."""
    assert bootstrap_role_arn("123456789012") == (
        "arn:aws:iam::123456789012:role/platform-bootstrap"
    )


def test_the_external_id_is_url_encoded_into_the_link() -> None:
    url = launch_url(
        template_url="https://v/t.yaml", control_plane_role_arn="arn:aws:iam::1:role/cp",
        external_id="abc/def+ghi=", region="eu-west-2",
    )
    assert "param_ExternalId=abc%2Fdef%2Bghi%3D" in url


# ---- the token boundary ------------------------------------------------------
def test_one_link_reaches_exactly_one_onboarding(client: TestClient) -> None:
    a, b = start(client), start(client)
    r = client.get("/api/onboarding", headers={"Authorization": f"Bearer {a['onboarding_token']}"})
    assert r.status_code == 200
    assert r.json()["org_slug"] == a["org_slug"]
    assert r.json()["org_slug"] != b["org_slug"]


def test_an_unknown_token_is_a_flat_404(client: TestClient) -> None:
    """Same answer as an expired or revoked link: distinguishing them tells a
    stranger that a token existed."""
    assert client.get("/api/onboarding?token=nonsense").status_code == 404
    assert client.get("/api/onboarding").status_code == 401


def test_the_operator_route_is_not_open(client: TestClient) -> None:
    r = client.post("/api/onboardings",
                    json={"org_slug": slug(), "org_name": "X", "contact_email": "ops@acme-logistics.example"})
    assert r.status_code == 401
    r = client.post("/api/onboardings", headers={"Authorization": "Bearer wrong"},
                    json={"org_slug": slug(), "org_name": "X", "contact_email": "ops@acme-logistics.example"})
    assert r.status_code == 401


def test_a_token_read_never_returns_the_external_id(
    client: TestClient, registry: StackRegistry
) -> None:
    """It is the secret the whole trust relationship rests on. The vendor sees
    it once at creation; nothing the customer's own token can call returns
    it."""
    started = start(client)
    external_id = registry.external_id_for(started["org_slug"])
    headers = {"Authorization": f"Bearer {started['onboarding_token']}"}
    for path in ("/api/onboarding", "/api/onboarding/preflight"):
        assert external_id not in client.get(path, headers=headers).text
    # Not even the route that creates the onboarding hands it back - the
    # launch link is minted server-side, so nothing outside the control plane
    # ever needs the plaintext.
    assert "external_id" not in started


# ---- detection ----------------------------------------------------------------
def test_detection_is_a_probe_not_a_form_field(
    client: TestClient, aws: FakeAws, registry: StackRegistry
) -> None:
    """Before the customer runs the template the role cannot be assumed, and
    the answer says so in words rather than reporting success and failing ten
    minutes later."""
    started = start(client)
    headers = {"Authorization": f"Bearer {started['onboarding_token']}"}
    body = {"aws_account_id": "123456789012", "aws_region": "eu-west-2"}

    first = client.post("/api/onboarding/connect", headers=headers, json=body).json()
    assert first["connected"] is False
    assert "created" in first["detail"] or "assume" in first["detail"]

    aws.assumable = True  # they ran the template
    second = client.post("/api/onboarding/connect", headers=headers, json=body).json()
    assert second["connected"] is True
    record = registry.get(started["org_slug"])
    assert record.bootstrap_role_arn == bootstrap_role_arn("123456789012")
    assert record.aws_region == "eu-west-2"


def test_a_bad_account_id_or_region_is_refused_before_aws_sees_it(client: TestClient) -> None:
    started = start(client)
    headers = {"Authorization": f"Bearer {started['onboarding_token']}"}
    assert client.post("/api/onboarding/connect", headers=headers,
                       json={"aws_account_id": "12345", "aws_region": "eu-west-2"}
                       ).status_code == 422
    assert client.post("/api/onboarding/connect", headers=headers,
                       json={"aws_account_id": "123456789012", "aws_region": "moon-base-1"}
                       ).status_code == 422


def test_an_unsupported_region_is_refused_with_the_list(client: TestClient, aws: FakeAws) -> None:
    aws.assumable = True
    started = start(client)
    r = client.post("/api/onboarding/connect",
                    headers={"Authorization": f"Bearer {started['onboarding_token']}"},
                    json={"aws_account_id": "123456789012", "aws_region": "ap-south-1"})
    assert r.status_code == 422
    assert "eu-west-2" in r.json()["detail"]


# ---- preflight ----------------------------------------------------------------
def connected(client: TestClient, aws: FakeAws) -> dict[str, str]:
    aws.assumable = True
    started = start(client)
    headers = {"Authorization": f"Bearer {started['onboarding_token']}"}
    client.post("/api/onboarding/connect", headers=headers,
                json={"aws_account_id": "123456789012", "aws_region": "eu-west-2"})
    return {**started, "headers": headers}  # type: ignore[dict-item]


def test_preflight_passes_on_a_clean_account(client: TestClient, aws: FakeAws) -> None:
    session = connected(client, aws)
    r = client.get("/api/onboarding/preflight", headers=session["headers"])  # type: ignore[arg-type]
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert {c["name"] for c in r.json()["checks"]} == {
        "Bootstrap role", "Region", "CDK bootstrap", "Elastic IPs", "Existing stack"
    }


def test_every_failing_check_carries_a_remedy(client: TestClient, aws: FakeAws) -> None:
    """A check that reports a problem without saying what to do about it has
    moved the confusion rather than removed it."""
    aws.cdk_version = None
    aws.eips = (5, 5)
    session = connected(client, aws)
    body = client.get("/api/onboarding/preflight", headers=session["headers"]).json()  # type: ignore[arg-type]
    assert body["ok"] is False
    failed = [c for c in body["checks"] if not c["ok"]]
    assert {c["name"] for c in failed} == {"CDK bootstrap", "Elastic IPs"}
    assert all(c["remedy"] for c in failed)
    assert any("cdk bootstrap" in c["remedy"] for c in failed)


def test_preflight_notices_a_stack_that_is_already_there(
    client: TestClient, aws: FakeAws
) -> None:
    aws.existing_stack = "CREATE_FAILED"
    session = connected(client, aws)
    body = client.get("/api/onboarding/preflight", headers=session["headers"]).json()  # type: ignore[arg-type]
    existing = next(c for c in body["checks"] if c["name"] == "Existing stack")
    assert existing["ok"] is False and existing["remedy"]


# ---- provisioning --------------------------------------------------------------
def test_provisioning_is_refused_while_a_check_is_failing(
    client: TestClient, aws: FakeAws, provisioner: FakeProvisioner
) -> None:
    """Otherwise the customer waits ten minutes to be told something the
    preflight already knew."""
    aws.cdk_version = None
    session = connected(client, aws)
    r = client.post("/api/onboarding/provision", headers=session["headers"])  # type: ignore[arg-type]
    assert r.status_code == 422
    assert "CDK bootstrap" in r.json()["detail"]
    assert provisioner.calls == []


def test_provisioning_runs_and_hands_off_a_url(
    client: TestClient, aws: FakeAws, provisioner: FakeProvisioner
) -> None:
    session = connected(client, aws)
    r = client.post("/api/onboarding/provision", headers=session["headers"])  # type: ignore[arg-type]
    assert r.status_code == 200 and r.json()["started"] is True
    assert provisioner.calls == [(session["org_slug"], "latest")]

    status = client.get("/api/onboarding", headers=session["headers"]).json()  # type: ignore[arg-type]
    assert status["stack_status"] == "ready"
    assert status["platform_url"] == "https://d123.cloudfront.net"


def test_a_failed_provision_reports_the_reason_rather_than_hanging(
    client: TestClient, aws: FakeAws, provisioner: FakeProvisioner
) -> None:
    provisioner.explode = True
    session = connected(client, aws)
    client.post("/api/onboarding/provision", headers=session["headers"])  # type: ignore[arg-type]
    status = client.get("/api/onboarding", headers=session["headers"]).json()  # type: ignore[arg-type]
    assert status["stack_status"] == "failed"
    assert "CREATE_FAILED" in status["error"]


def test_provisioning_twice_is_refused(
    client: TestClient, aws: FakeAws, provisioner: FakeProvisioner
) -> None:
    session = connected(client, aws)
    client.post("/api/onboarding/provision", headers=session["headers"])  # type: ignore[arg-type]
    again = client.post("/api/onboarding/provision", headers=session["headers"])  # type: ignore[arg-type]
    assert again.json()["started"] is False
    assert len(provisioner.calls) == 1


def test_status_carries_stack_events_for_the_progress_view(
    client: TestClient, aws: FakeAws
) -> None:
    """The fifteen minutes are only silent because nothing surfaced what
    CloudFormation already knows."""
    session = connected(client, aws)
    status = client.get("/api/onboarding", headers=session["headers"]).json()  # type: ignore[arg-type]
    assert status["events"][0]["logical_id"] == "Vpc"


# ---- the page -------------------------------------------------------------------
def test_the_page_renders_for_a_valid_link_and_not_otherwise(client: TestClient) -> None:
    started = start(client)
    ok = client.get(f"/onboarding?token={started['onboarding_token']}")
    assert ok.status_code == 200
    assert "Acme Logistics" in ok.text
    assert "Launch in AWS" in ok.text
    assert client.get("/onboarding?token=nope").status_code == 404
