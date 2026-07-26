"""Unit tests for the control plane: registry, external-ID handling,
provisioning orchestration, and update pinning. AWS + CDK are faked; the
registry runs against the real local Postgres."""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.deprovisioner.deprovisioner import Deprovisioner  # noqa: E402
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
        self.service_linked_role_calls = 0
        self.status_sequence = ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]
        self.outputs: dict[str, str] = {"PlatformDomain": "dxxx.cloudfront.net", "UserPoolId": "eu-west-2_abc"}
        self.disable_deletion_protection_calls: list[str] = []
        self.deletion_protection_state = False
        self.delete_stack_calls: list[str] = []
        self.empty_bucket_calls: list[str] = []
        self.delete_bucket_calls: list[str] = []
        self.delete_search_domain_calls: list[str] = []

    def assume_bootstrap_role(self, role_arn: str, external_id: str, session_name: str) -> TempCredentials:
        self.assume_calls.append((role_arn, external_id))
        return TempCredentials("AKIA_FAKE", "secret", "token")

    def ensure_opensearch_service_linked_role(self, creds: TempCredentials) -> None:
        self.service_linked_role_calls += 1

    def stack_status(self, creds: TempCredentials, region: str, stack_name: str) -> str | None:
        return self.status_sequence.pop(0) if self.status_sequence else "CREATE_COMPLETE"

    def stack_outputs(self, creds: TempCredentials, region: str, stack_name: str) -> dict[str, str]:
        return self.outputs

    # ---- teardown -------------------------------------------------------
    def disable_deletion_protection(self, creds: TempCredentials, region: str, db_instance_identifier: str) -> None:
        self.disable_deletion_protection_calls.append(db_instance_identifier)

    def deletion_protection_enabled(self, creds: TempCredentials, region: str, db_instance_identifier: str) -> bool:
        return self.deletion_protection_state

    def delete_stack(self, creds: TempCredentials, region: str, stack_name: str) -> None:
        self.delete_stack_calls.append(stack_name)

    def empty_bucket(self, creds: TempCredentials, region: str, bucket_name: str) -> None:
        self.empty_bucket_calls.append(bucket_name)

    def delete_bucket(self, creds: TempCredentials, region: str, bucket_name: str) -> None:
        self.delete_bucket_calls.append(bucket_name)

    def delete_search_domain(self, creds: TempCredentials, region: str, domain_name: str) -> None:
        self.delete_search_domain_calls.append(domain_name)


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
    # First-time provisioning ensures the OpenSearch service-linked role
    # exists — a real account-level prerequisite VPC-joined domains need.
    assert aws.service_linked_role_calls == 1
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


def test_update_stack_skips_service_linked_role(registry: StackRegistry) -> None:
    s = slug()
    registry.register_customer(s)
    registry.connect_aws(s, "123456789012", "eu-west-2", "arn:aws:iam::123456789012:role/platform-bootstrap")
    aws, cdk = FakeAws(), FakeCdk()
    prov = Provisioner(registry, aws, cdk, "r", poll_interval_s=0.0)
    prov.provision(s, "v1.0.0")
    assert aws.service_linked_role_calls == 1
    prov.update_stack(s, "v1.1.0")
    # Account-wide prerequisite: only ensured on first-time provisioning,
    # not re-checked on every version update.
    assert aws.service_linked_role_calls == 1


def test_deprovision_happy_path(registry: StackRegistry) -> None:
    s = slug()
    _, external_id = registry.register_customer(s)
    registry.connect_aws(s, "123456789012", "eu-west-2", "arn:aws:iam::123456789012:role/platform-bootstrap")
    aws = FakeAws()
    aws.outputs = {
        "DatabaseInstanceIdentifier": "platformstack-data",
        "DataBucketName": "platformstack-data-bucket",
        "AccessLogBucketName": "platformstack-access-logs",
        "SearchDomainName": "platformstack-search",
    }
    aws.status_sequence = ["DELETE_IN_PROGRESS", None]
    deprov = Deprovisioner(registry, aws, poll_interval_s=0.0)
    deprov.deprovision(s)
    assert aws.assume_calls == [("arn:aws:iam::123456789012:role/platform-bootstrap", external_id)]
    # RDS deletion protection cleared before the stack delete was requested.
    assert aws.disable_deletion_protection_calls == ["platformstack-data"]
    assert aws.delete_stack_calls == ["PlatformStack"]
    # RETAIN'd resources cleaned up only after the stack itself is gone.
    assert aws.empty_bucket_calls == ["platformstack-data-bucket", "platformstack-access-logs"]
    assert aws.delete_bucket_calls == ["platformstack-data-bucket", "platformstack-access-logs"]
    assert aws.delete_search_domain_calls == ["platformstack-search"]
    assert registry.get(s).stack_status is StackStatus.DESTROYED


def test_deprovision_without_teardown_outputs_still_deletes_stack(registry: StackRegistry) -> None:
    """An older stack deployed before customer-stack.ts gained these
    outputs: the core (expensive) deletion must still happen, with best-
    effort cleanup steps skipped rather than the whole run failing."""
    s = slug()
    registry.register_customer(s)
    registry.connect_aws(s, "123456789012", "eu-west-2", "arn:aws:iam::123456789012:role/platform-bootstrap")
    aws = FakeAws()
    aws.outputs = {"PlatformDomain": "dxxx.cloudfront.net"}
    aws.status_sequence = [None]
    deprov = Deprovisioner(registry, aws, poll_interval_s=0.0)
    deprov.deprovision(s)
    assert aws.disable_deletion_protection_calls == []
    assert aws.delete_stack_calls == ["PlatformStack"]
    assert aws.empty_bucket_calls == []
    assert aws.delete_search_domain_calls == []
    assert registry.get(s).stack_status is StackStatus.DESTROYED


def test_deprovision_marks_failed_on_delete_failed(registry: StackRegistry) -> None:
    s = slug()
    registry.register_customer(s)
    registry.connect_aws(s, "123456789012", "eu-west-2", "arn:aws:iam::123456789012:role/platform-bootstrap")
    aws = FakeAws()
    aws.status_sequence = ["DELETE_FAILED"]
    deprov = Deprovisioner(registry, aws, poll_interval_s=0.0)
    with pytest.raises(RuntimeError):
        deprov.deprovision(s)
    assert registry.get(s).stack_status is StackStatus.FAILED


def test_deprovision_refuses_when_already_torn_down(registry: StackRegistry) -> None:
    s = slug()
    registry.register_customer(s)
    registry.connect_aws(s, "123456789012", "eu-west-2", "arn:aws:iam::123456789012:role/platform-bootstrap")
    aws = FakeAws()
    aws.status_sequence = [None]
    deprov = Deprovisioner(registry, aws, poll_interval_s=0.0)
    deprov.deprovision(s)
    with pytest.raises(ValueError):
        deprov.deprovision(s)


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
