"""Unit tests for the control plane: registry, external-ID handling,
provisioning orchestration, and update pinning. AWS + CDK are faked; the
registry runs against the real local Postgres."""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.provisioner.provisioner import Provisioner, TempCredentials  # noqa: E402
from src.registry.registry import StackRegistry, StackStatus, generate_external_id  # noqa: E402
from src.updater.updater import Updater  # noqa: E402

DSN = os.environ["CONTROL_PLANE_DATABASE_URL"]


class XorCodec:
    """Deterministic stand-in for KMS envelope encryption in tests."""

    def encrypt(self, plaintext: str) -> bytes:
        return bytes(b ^ 0x42 for b in plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        return bytes(b ^ 0x42 for b in ciphertext).decode()


@pytest.fixture()
def registry() -> StackRegistry:
    reg = StackRegistry(DSN, XorCodec())
    reg.ensure_schema()
    return reg


def slug() -> str:
    return f"cust-{uuid.uuid4().hex[:10]}"


def test_external_id_entropy_and_length() -> None:
    a, b = generate_external_id(), generate_external_id()
    assert a != b
    assert len(a) >= 32  # bootstrap template MinLength


def test_register_and_roundtrip_external_id(registry: StackRegistry) -> None:
    s = slug()
    record, external_id = registry.register_customer(s)
    assert record.stack_status is StackStatus.PENDING
    assert registry.external_id_for(s) == external_id
    # External ID never appears in the readable record.
    assert external_id not in repr(record)


def test_register_duplicate_rejected(registry: StackRegistry) -> None:
    s = slug()
    registry.register_customer(s)
    with pytest.raises(ValueError):
        registry.register_customer(s)


def test_connect_aws_validates_inputs(registry: StackRegistry) -> None:
    s = slug()
    registry.register_customer(s)
    with pytest.raises(ValueError):
        registry.connect_aws(s, "12345", "eu-west-2", "arn:aws:iam::123456789012:role/x")
    with pytest.raises(ValueError):
        registry.connect_aws(s, "123456789012", "moon-base-1", "arn:aws:iam::123456789012:role/x")
    with pytest.raises(ValueError):
        # role ARN must belong to the connected account
        registry.connect_aws(s, "123456789012", "eu-west-2", "arn:aws:iam::999999999999:role/x")
    rec = registry.connect_aws(
        s, "123456789012", "eu-west-2", "arn:aws:iam::123456789012:role/platform-bootstrap"
    )
    assert rec.aws_region == "eu-west-2"


class FakeAws:
    def __init__(self) -> None:
        self.assume_calls: list[tuple[str, str]] = []
        self.status_sequence = ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]

    def assume_bootstrap_role(self, role_arn: str, external_id: str, session_name: str) -> TempCredentials:
        self.assume_calls.append((role_arn, external_id))
        return TempCredentials("AKIA_FAKE", "secret", "token")

    def stack_status(self, creds: TempCredentials, region: str, stack_name: str) -> str | None:
        return self.status_sequence.pop(0) if self.status_sequence else "CREATE_COMPLETE"

    def stack_outputs(self, creds: TempCredentials, region: str, stack_name: str) -> dict[str, str]:
        return {"PlatformDomain": "dxxx.cloudfront.net", "UserPoolId": "eu-west-2_abc"}


class FakeCdk:
    def __init__(self) -> None:
        self.deploys: list[dict[str, str]] = []

    def deploy(self, creds: TempCredentials, region: str, context: dict[str, str]) -> None:
        self.deploys.append(context)


def test_provision_happy_path(registry: StackRegistry) -> None:
    s = slug()
    _, external_id = registry.register_customer(s)
    registry.connect_aws(s, "123456789012", "eu-west-2", "arn:aws:iam::123456789012:role/platform-bootstrap")
    aws, cdk = FakeAws(), FakeCdk()
    prov = Provisioner(registry, aws, cdk, "111111111111.dkr.ecr.eu-west-2.amazonaws.com",
                       poll_interval_s=0.0)
    outputs = prov.provision(s, image_tag="v1.0.0")
    # External ID was used for the assume-role call (confused deputy defence).
    assert aws.assume_calls == [("arn:aws:iam::123456789012:role/platform-bootstrap", external_id)]
    assert cdk.deploys[0]["orgSlug"] == s and cdk.deploys[0]["imageTag"] == "v1.0.0"
    assert outputs["UserPoolId"] == "eu-west-2_abc"
    rec = registry.get(s)
    assert rec.stack_status is StackStatus.READY and rec.stack_version == "v1.0.0"
    assert rec.outputs["PlatformDomain"] == "dxxx.cloudfront.net"


def test_provision_without_aws_connection_fails_closed(registry: StackRegistry) -> None:
    s = slug()
    registry.register_customer(s)
    prov = Provisioner(registry, FakeAws(), FakeCdk(), "r")
    with pytest.raises(ValueError):
        prov.provision(s, "v1")


def test_provision_marks_failed_on_stack_failure(registry: StackRegistry) -> None:
    s = slug()
    registry.register_customer(s)
    registry.connect_aws(s, "123456789012", "eu-west-2", "arn:aws:iam::123456789012:role/platform-bootstrap")
    aws = FakeAws()
    aws.status_sequence = ["ROLLBACK_COMPLETE"]
    prov = Provisioner(registry, aws, FakeCdk(), "r", poll_interval_s=0.0)
    with pytest.raises(RuntimeError):
        prov.provision(s, "v1")
    assert registry.get(s).stack_status is StackStatus.FAILED


def test_updater_respects_version_pinning(registry: StackRegistry) -> None:
    s = slug()
    registry.register_customer(s)
    registry.connect_aws(s, "123456789012", "eu-west-2", "arn:aws:iam::123456789012:role/platform-bootstrap")
    prov = Provisioner(registry, FakeAws(), FakeCdk(), "r", poll_interval_s=0.0)
    prov.provision(s, "v1.0.0")
    upd = Updater(registry, prov)
    # Fleet rollout skips pinned customers (§6 enterprise pinning).
    res = upd.update_customer(s, "v1.1.0", pinned_version="v1.0.0")
    assert not res.updated and "pinned" in res.reason
    # Customer-requested update proceeds despite pin.
    res = upd.update_customer(s, "v1.1.0", pinned_version="v1.0.0", requested_by_customer=True)
    assert res.updated
    assert registry.get(s).stack_version == "v1.1.0"
    # No-op when already at target.
    res = upd.update_customer(s, "v1.1.0")
    assert not res.updated and res.reason == "already at target version"
