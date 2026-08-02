"""Standing up the *vendor's* side of the control plane, in one command.

The customer's path has been one page since `STATUS.md` §48: pick a region,
type twelve digits, click a prefilled CloudFormation link, come back. The
vendor's path to *make that page exist* was still a runbook - create a KMS
key, create a role with the right trust policy, create three ECR
repositories, put the bootstrap template somewhere CloudFormation can read
it, then work out which environment variable wants which ARN. Five manual
steps and a paragraph of copying, every one of them a chance to wire a trust
policy to the wrong principal.

`ensure()` does all five, **idempotently**: it is safe to run repeatedly, it
reports what already existed rather than failing on it, and it ends by
printing the exact environment block the control plane needs. Running it
twice is how you check the state of an account you set up months ago.

**What it deliberately does not do**, because both are decisions with a bill
attached and neither belongs to a bootstrap command:

* **Provision a database.** The registry needs Postgres. For a first customer
  that can be anything, including one on the operator's own machine; for a
  real fleet it wants RDS with backups and a retention policy nobody should
  pick on somebody's behalf.
* **Host the onboarding app.** Where the customer-facing page runs - Fargate,
  App Runner, a VM - is an availability decision, and the answer for a
  business with one customer is not the answer for one with fifty.

Both are named in the output rather than silently missing, which is the whole
difference between a tool that finished and a tool that stopped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# The three service images a customer stack pulls. Names are structural: the
# CDK stack builds `{vendorEcrRegistry}/platform-{name}:{tag}`.
IMAGES = ("platform-api", "platform-worker", "platform-web")
ROLE_NAME = "anchor-control-plane"
KEY_ALIAS = "alias/anchor-external-ids"
TEMPLATE_KEY = "customer-bootstrap.yaml"


class VendorGateway(Protocol):
    """Every AWS call the vendor bootstrap makes. A Protocol for the same
    reason the provisioner has one: the orchestration above is worth testing
    without an AWS account, and the tests are the only place the ordering and
    the idempotence get checked."""

    def account_id(self) -> str: ...

    def find_kms_alias(self, alias: str) -> str | None: ...
    def create_kms_key(self, alias: str, description: str) -> str: ...

    def find_role(self, name: str) -> str | None: ...
    def create_role(self, name: str, assume_policy: dict[str, Any], description: str) -> str: ...
    def put_role_policy(self, role: str, policy_name: str, policy: dict[str, Any]) -> None: ...

    def find_ecr_repository(self, name: str) -> str | None: ...
    def create_ecr_repository(self, name: str) -> str: ...

    def find_bucket(self, name: str) -> bool: ...
    def create_bucket(self, name: str, region: str) -> None: ...
    def put_public_object(self, bucket: str, key: str, body: bytes, content_type: str) -> str: ...


@dataclass
class Resource:
    kind: str
    name: str
    created: bool
    value: str = ""


@dataclass
class BootstrapResult:
    account_id: str
    region: str
    resources: list[Resource] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @property
    def created(self) -> list[Resource]:
        return [r for r in self.resources if r.created]

    def render(self) -> str:
        """What to do next, in the order you have to do it. A bootstrap that
        leaves somebody wondering what it just did has not saved them
        anything."""
        lines = [f"account {self.account_id} in {self.region}", ""]
        for r in self.resources:
            lines.append(f"  {'created' if r.created else 'exists '}  {r.kind:<14}{r.name}")
        lines += ["", "Environment for the control plane:", ""]
        for key, value in self.env.items():
            lines.append(f"  export {key}={value}")
        lines += [
            "",
            "Still yours to decide (deliberately not automated):",
            "  * CONTROL_PLANE_DATABASE_URL - the registry's Postgres. Local is fine for",
            "    a first customer; a fleet wants RDS with a backup policy you choose.",
            "  * Where the onboarding page runs. `python -m src.cli serve` on any host",
            "    that customers can reach; CONTROL_PLANE_PUBLIC_URL is that address.",
            "",
            "Then push the three images (Docker must be running):",
        ]
        registry = self.env.get("VENDOR_ECR_REGISTRY", "<registry>")
        for image in IMAGES:
            src = {"platform-api": "apps/api", "platform-worker": "apps/worker"}.get(image, ".")
            dockerfile = "" if src != "." else "-f apps/web/Dockerfile "
            lines.append(
                f"  docker build --platform=linux/amd64 {dockerfile}"
                f"-t {registry}/{image}:$TAG {src}"
            )
        lines.append(
            "\n  (--platform on the build command is not optional: the Dockerfile pin\n"
            "   only picks the base image, and an arm64 image fails on Fargate before\n"
            "   any application code runs.)"
        )
        return "\n".join(lines)


def control_plane_trust_policy(account_id: str, principal: str | None) -> dict[str, Any]:
    """Who may become the control plane.

    Defaults to the account root, which does *not* mean "anybody" - it means
    the account's own IAM policies decide, which is the standard way to
    delegate without naming a person who will later leave. Pass an explicit
    principal ARN to narrow it.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": principal or f"arn:aws:iam::{account_id}:root"},
            "Action": "sts:AssumeRole",
        }],
    }


def control_plane_policy(key_arn: str) -> dict[str, Any]:
    """What the control plane may do, which is deliberately almost nothing.

    It assumes customer bootstrap roles and it unwraps external IDs. It has no
    permissions in any customer account of its own - everything it does there
    is done with credentials the customer's own role handed it, which is the
    entire point of the external-ID handshake.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeCustomerBootstrapRoles",
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                # Only the fixed role name the customer template creates, in
                # any account: a control plane that could assume *any* role in
                # a customer account would be a much bigger promise than the
                # one this product makes.
                "Resource": "arn:aws:iam::*:role/platform-bootstrap",
            },
            {
                "Sid": "UnwrapExternalIds",
                "Effect": "Allow",
                "Action": ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"],
                "Resource": key_arn,
            },
        ],
    }


class VendorBootstrap:
    def __init__(self, aws: VendorGateway, *, template_path: Path) -> None:
        self._aws = aws
        self._template_path = template_path

    def ensure(
        self,
        *,
        region: str,
        bucket: str | None = None,
        trust_principal: str | None = None,
        public_url: str = "",
    ) -> BootstrapResult:
        account = self._aws.account_id()
        result = BootstrapResult(account_id=account, region=region)

        # 1. The key that wraps every customer's external ID.
        key_arn = self._aws.find_kms_alias(KEY_ALIAS)
        created = key_arn is None
        if key_arn is None:
            key_arn = self._aws.create_kms_key(KEY_ALIAS, "Anchor customer external IDs")
        result.resources.append(Resource("KMS key", KEY_ALIAS, created, key_arn))

        # 2. The role customers' bootstrap roles will trust. Its policy is
        #    rewritten on every run, so a permission added to this file
        #    reaches an account somebody bootstrapped a year ago.
        role_arn = self._aws.find_role(ROLE_NAME)
        created = role_arn is None
        if role_arn is None:
            role_arn = self._aws.create_role(
                ROLE_NAME,
                control_plane_trust_policy(account, trust_principal),
                "Anchor control plane - assumes customer bootstrap roles",
            )
        self._aws.put_role_policy(ROLE_NAME, "anchor-control-plane", control_plane_policy(key_arn))
        result.resources.append(Resource("IAM role", ROLE_NAME, created, role_arn))

        # 3. Somewhere for the customer stacks to pull images from.
        for image in IMAGES:
            uri = self._aws.find_ecr_repository(image)
            created = uri is None
            if uri is None:
                uri = self._aws.create_ecr_repository(image)
            result.resources.append(Resource("ECR repo", image, created, uri))

        # 4. The bootstrap template, somewhere CloudFormation can read it -
        #    the launch link is a URL, so the template has to be one.
        bucket_name = bucket or f"anchor-onboarding-{account}"
        exists = self._aws.find_bucket(bucket_name)
        if not exists:
            self._aws.create_bucket(bucket_name, region)
        result.resources.append(Resource("S3 bucket", bucket_name, not exists))
        template_url = self._aws.put_public_object(
            bucket_name,
            TEMPLATE_KEY,
            self._template_path.read_bytes(),
            "text/yaml",
        )
        # Always re-uploaded: a stale template is worse than a missing one,
        # because the launch link keeps working and hands the customer a role
        # that lacks whatever permission this build added since.
        result.resources.append(Resource("Template", TEMPLATE_KEY, True, template_url))

        registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
        result.env = {
            "AWS_REGION": region,
            "CONTROL_PLANE_ROLE_ARN": role_arn,
            "ONBOARDING_KMS_KEY_ID": key_arn,
            "TEARDOWN_KMS_KEY_ID": key_arn,
            "BOOTSTRAP_TEMPLATE_URL": template_url,
            "VENDOR_ECR_REGISTRY": registry,
            "CONTROL_PLANE_PUBLIC_URL": public_url or "http://localhost:8400",
        }
        return result


class Boto3VendorGateway:
    """Production gateway. boto3 is imported lazily, as everywhere else in
    this package, so the orchestration can be tested without it."""

    def __init__(self, region: str) -> None:
        self._region = region

    def _client(self, service: str):
        import boto3

        return boto3.client(service, region_name=self._region)

    def account_id(self) -> str:
        return self._client("sts").get_caller_identity()["Account"]

    def find_kms_alias(self, alias: str) -> str | None:
        kms = self._client("kms")
        paginator = kms.get_paginator("list_aliases")
        for page in paginator.paginate():
            for entry in page["Aliases"]:
                if entry["AliasName"] == alias and entry.get("TargetKeyId"):
                    return kms.describe_key(KeyId=entry["TargetKeyId"])["KeyMetadata"]["Arn"]
        return None

    def create_kms_key(self, alias: str, description: str) -> str:
        kms = self._client("kms")
        key = kms.create_key(Description=description, KeyUsage="ENCRYPT_DECRYPT")
        arn = key["KeyMetadata"]["Arn"]
        kms.create_alias(AliasName=alias, TargetKeyId=key["KeyMetadata"]["KeyId"])
        return arn

    def find_role(self, name: str) -> str | None:
        iam = self._client("iam")
        try:
            return iam.get_role(RoleName=name)["Role"]["Arn"]
        except iam.exceptions.NoSuchEntityException:
            return None

    def create_role(self, name: str, assume_policy: dict[str, Any], description: str) -> str:
        iam = self._client("iam")
        return iam.create_role(
            RoleName=name,
            AssumeRolePolicyDocument=json.dumps(assume_policy),
            Description=description,
            MaxSessionDuration=3600,
        )["Role"]["Arn"]

    def put_role_policy(self, role: str, policy_name: str, policy: dict[str, Any]) -> None:
        self._client("iam").put_role_policy(
            RoleName=role, PolicyName=policy_name, PolicyDocument=json.dumps(policy)
        )

    def find_ecr_repository(self, name: str) -> str | None:
        ecr = self._client("ecr")
        try:
            return ecr.describe_repositories(repositoryNames=[name])["repositories"][0][
                "repositoryUri"
            ]
        except ecr.exceptions.RepositoryNotFoundException:
            return None

    def create_ecr_repository(self, name: str) -> str:
        ecr = self._client("ecr")
        return ecr.create_repository(
            repositoryName=name,
            imageScanningConfiguration={"scanOnPush": True},
            # Immutable tags: a customer stack pinned to a tag must keep
            # meaning the same image, or "which version are they on" has no
            # answer (STATUS.md §20's deploy-hardening note).
            imageTagMutability="IMMUTABLE",
        )["repository"]["repositoryUri"]

    def find_bucket(self, name: str) -> bool:
        s3 = self._client("s3")
        try:
            s3.head_bucket(Bucket=name)
            return True
        except Exception:
            return False

    def create_bucket(self, name: str, region: str) -> None:
        s3 = self._client("s3")
        kwargs: dict[str, Any] = {"Bucket": name}
        if region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**kwargs)
        # The template must be publicly readable - CloudFormation fetches it
        # as the customer, from their account, with no credentials of ours.
        # It is a template, not data: it contains no secret, and the external
        # ID travels in the launch URL rather than in the file.
        s3.put_public_access_block(
            Bucket=name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        s3.put_bucket_policy(
            Bucket=name,
            Policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Sid": "PublicReadTemplate",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    # Scoped to the one object, not the bucket: a bucket that
                    # is publicly readable in general is a bucket somebody
                    # will eventually put something else in.
                    "Resource": f"arn:aws:s3:::{name}/{TEMPLATE_KEY}",
                }],
            }),
        )

    def put_public_object(self, bucket: str, key: str, body: bytes, content_type: str) -> str:
        self._client("s3").put_object(
            Bucket=bucket, Key=key, Body=body, ContentType=content_type
        )
        return f"https://{bucket}.s3.{self._region}.amazonaws.com/{key}"
