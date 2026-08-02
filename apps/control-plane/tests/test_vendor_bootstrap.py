"""The vendor's own bootstrap (`cli init`).

No AWS: the gateway is a Protocol precisely so the ordering, the idempotence
and the two IAM policies can be checked without an account. What matters here
is not that the calls happen but that running it twice is safe, that the
policies say the narrow thing they are meant to say, and that the output tells
somebody what is still theirs to do.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.bootstrap.vendor import (  # noqa: E402
    IMAGES,
    KEY_ALIAS,
    ROLE_NAME,
    VendorBootstrap,
    control_plane_policy,
    control_plane_trust_policy,
)

ACCOUNT = "999999999999"


class FakeVendorAws:
    def __init__(self) -> None:
        self.keys: dict[str, str] = {}
        self.roles: dict[str, str] = {}
        self.role_policies: dict[str, dict[str, Any]] = {}
        self.repos: dict[str, str] = {}
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], bytes] = {}
        self.calls: list[str] = []

    def account_id(self) -> str:
        return ACCOUNT

    def find_kms_alias(self, alias: str) -> str | None:
        return self.keys.get(alias)

    def create_kms_key(self, alias: str, description: str) -> str:
        self.calls.append(f"create_kms_key:{alias}")
        arn = f"arn:aws:kms:eu-west-2:{ACCOUNT}:key/abc-123"
        self.keys[alias] = arn
        return arn

    def find_role(self, name: str) -> str | None:
        return self.roles.get(name)

    def create_role(self, name: str, assume_policy: dict[str, Any], description: str) -> str:
        self.calls.append(f"create_role:{name}")
        arn = f"arn:aws:iam::{ACCOUNT}:role/{name}"
        self.roles[name] = arn
        self.role_policies[f"{name}:trust"] = assume_policy
        return arn

    def put_role_policy(self, role: str, policy_name: str, policy: dict[str, Any]) -> None:
        self.calls.append(f"put_role_policy:{role}")
        self.role_policies[f"{role}:{policy_name}"] = policy

    def find_ecr_repository(self, name: str) -> str | None:
        return self.repos.get(name)

    def create_ecr_repository(self, name: str) -> str:
        self.calls.append(f"create_ecr:{name}")
        uri = f"{ACCOUNT}.dkr.ecr.eu-west-2.amazonaws.com/{name}"
        self.repos[name] = uri
        return uri

    def find_bucket(self, name: str) -> bool:
        return name in self.buckets

    def create_bucket(self, name: str, region: str) -> None:
        self.calls.append(f"create_bucket:{name}")
        self.buckets.add(name)

    def put_public_object(self, bucket: str, key: str, body: bytes, content_type: str) -> str:
        self.calls.append(f"put_object:{bucket}/{key}")
        self.objects[(bucket, key)] = body
        return f"https://{bucket}.s3.eu-west-2.amazonaws.com/{key}"


@pytest.fixture()
def template(tmp_path: Path) -> Path:
    path = tmp_path / "customer-bootstrap.yaml"
    path.write_text("AWSTemplateFormatVersion: '2010-09-09'\n")
    return path


@pytest.fixture()
def aws() -> FakeVendorAws:
    return FakeVendorAws()


def run(aws: FakeVendorAws, template: Path, **kwargs: Any):
    return VendorBootstrap(aws, template_path=template).ensure(region="eu-west-2", **kwargs)


# ---- what it creates ---------------------------------------------------------
def test_a_first_run_creates_everything_the_control_plane_needs(
    aws: FakeVendorAws, template: Path
) -> None:
    result = run(aws, template)
    kinds = {r.kind for r in result.created}
    assert kinds == {"KMS key", "IAM role", "ECR repo", "S3 bucket", "Template"}
    assert set(aws.repos) == set(IMAGES)
    assert KEY_ALIAS in aws.keys and ROLE_NAME in aws.roles


def test_the_env_block_is_the_whole_configuration(
    aws: FakeVendorAws, template: Path
) -> None:
    """Anything missing here is something somebody has to work out by hand,
    which is the thing this command exists to stop."""
    result = run(aws, template, public_url="https://onboard.example")
    assert set(result.env) == {
        "AWS_REGION", "CONTROL_PLANE_ROLE_ARN", "ONBOARDING_KMS_KEY_ID",
        "TEARDOWN_KMS_KEY_ID", "BOOTSTRAP_TEMPLATE_URL", "VENDOR_ECR_REGISTRY",
        "CONTROL_PLANE_PUBLIC_URL",
    }
    assert result.env["CONTROL_PLANE_ROLE_ARN"].endswith(f":role/{ROLE_NAME}")
    assert result.env["VENDOR_ECR_REGISTRY"] == f"{ACCOUNT}.dkr.ecr.eu-west-2.amazonaws.com"
    assert result.env["CONTROL_PLANE_PUBLIC_URL"] == "https://onboard.example"


# ---- running it twice --------------------------------------------------------
def test_running_it_again_creates_nothing_and_still_reports_everything(
    aws: FakeVendorAws, template: Path
) -> None:
    """Idempotence is the feature: running it again is how you check an
    account somebody set up months ago."""
    run(aws, template)
    aws.calls.clear()
    second = run(aws, template)

    assert [r.kind for r in second.created] == ["Template"], "only the template is rewritten"
    assert not any(c.startswith("create_") for c in aws.calls), aws.calls
    assert len(second.resources) == len(IMAGES) + 4
    assert second.env["CONTROL_PLANE_ROLE_ARN"].endswith(f":role/{ROLE_NAME}")


def test_the_template_is_re_uploaded_every_run(aws: FakeVendorAws, template: Path) -> None:
    """A stale template is worse than a missing one: the launch link keeps
    working and hands the customer a role missing whatever permission this
    build added since."""
    run(aws, template)
    template.write_text("AWSTemplateFormatVersion: '2010-09-09'\n# newer\n")
    run(aws, template)
    stored = aws.objects[(f"anchor-onboarding-{ACCOUNT}", "customer-bootstrap.yaml")]
    assert b"# newer" in stored


def test_the_role_policy_is_rewritten_on_every_run(
    aws: FakeVendorAws, template: Path
) -> None:
    run(aws, template)
    aws.role_policies[f"{ROLE_NAME}:anchor-control-plane"] = {"stale": True}
    run(aws, template)
    policy = aws.role_policies[f"{ROLE_NAME}:anchor-control-plane"]
    assert "stale" not in policy


# ---- the two policies --------------------------------------------------------
def test_the_control_plane_can_only_assume_the_one_role_name() -> None:
    """A control plane that could assume *any* role in a customer account
    would be a much bigger promise than this product makes."""
    policy = control_plane_policy("arn:aws:kms:eu-west-2:1:key/k")
    assume = next(s for s in policy["Statement"] if s["Sid"] == "AssumeCustomerBootstrapRoles")
    assert assume["Resource"] == "arn:aws:iam::*:role/platform-bootstrap"
    assert assume["Action"] == "sts:AssumeRole"


def test_the_kms_grant_is_scoped_to_the_one_key() -> None:
    policy = control_plane_policy("arn:aws:kms:eu-west-2:1:key/k")
    kms = next(s for s in policy["Statement"] if s["Sid"] == "UnwrapExternalIds")
    assert kms["Resource"] == "arn:aws:kms:eu-west-2:1:key/k"
    assert "kms:Decrypt" in kms["Action"]


def test_trust_defaults_to_the_account_and_can_be_narrowed() -> None:
    """Account root is not "anybody" - it delegates to the account's own IAM,
    which is how you avoid naming a person who later leaves."""
    default = control_plane_trust_policy(ACCOUNT, None)
    assert default["Statement"][0]["Principal"]["AWS"] == f"arn:aws:iam::{ACCOUNT}:root"
    narrowed = control_plane_trust_policy(ACCOUNT, f"arn:aws:iam::{ACCOUNT}:user/deployer")
    assert narrowed["Statement"][0]["Principal"]["AWS"].endswith(":user/deployer")


def test_the_trust_policy_is_json_serialisable(aws: FakeVendorAws, template: Path) -> None:
    """It goes to IAM as a JSON string; a dataclass or a set in there fails at
    the API rather than here."""
    run(aws, template)
    json.dumps(aws.role_policies[f"{ROLE_NAME}:trust"])
    json.dumps(aws.role_policies[f"{ROLE_NAME}:anchor-control-plane"])


# ---- what it says it did not do ----------------------------------------------
def test_the_output_names_what_is_still_manual(aws: FakeVendorAws, template: Path) -> None:
    """A bootstrap that stops without saying so leaves somebody to discover
    the gap when the control plane will not start."""
    text = run(aws, template).render()
    assert "CONTROL_PLANE_DATABASE_URL" in text
    assert "onboarding page runs" in text
    assert "--platform=linux/amd64" in text
    for image in IMAGES:
        assert image in text
