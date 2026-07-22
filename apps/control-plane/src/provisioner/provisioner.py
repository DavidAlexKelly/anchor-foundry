"""Provisioner (spec §6 "Automatic provisioning" and "Updates").

Flow:
  1. Assume the customer's bootstrap role via STS with their external ID
     (confused-deputy protection — the assume call fails without it).
  2. Run `cdk deploy` for the customer stack with the temporary credentials.
  3. Poll CloudFormation until CREATE_COMPLETE / UPDATE_COMPLETE.
  4. Record stack outputs in the registry and mark the customer READY.

Updates (spec §6): push new image tags to ECR happens in CI; this module's
`update_stack` re-deploys with the new imageTag context, which produces a
rolling ECS deployment (minHealthyPercent=100 in the CDK stack → zero
downtime), then runs the migration one-off task.

AWS interactions go through the `AwsGateway` protocol so the orchestration
logic is unit-testable without AWS.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..registry.registry import StackRegistry, StackStatus

logger = logging.getLogger("control_plane.provisioner")

STACK_NAME = "PlatformStack"
_TERMINAL_OK = {"CREATE_COMPLETE", "UPDATE_COMPLETE"}
_TERMINAL_FAIL = {
    "CREATE_FAILED",
    "ROLLBACK_COMPLETE",
    "ROLLBACK_FAILED",
    "UPDATE_ROLLBACK_COMPLETE",
    "UPDATE_ROLLBACK_FAILED",
    "DELETE_FAILED",
}


@dataclass(frozen=True)
class TempCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str


class AwsGateway(Protocol):
    def assume_bootstrap_role(
        self, role_arn: str, external_id: str, session_name: str
    ) -> TempCredentials: ...

    def stack_status(self, creds: TempCredentials, region: str, stack_name: str) -> str | None: ...

    def stack_outputs(
        self, creds: TempCredentials, region: str, stack_name: str
    ) -> dict[str, str]: ...


class Boto3Gateway:
    """Production gateway. Import of boto3 is deferred so unit tests of the
    orchestration logic don't require it installed."""

    def assume_bootstrap_role(
        self, role_arn: str, external_id: str, session_name: str
    ) -> TempCredentials:
        import boto3  # type: ignore[import-untyped]

        sts = boto3.client("sts")
        resp = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            ExternalId=external_id,  # confused-deputy protection (spec §6)
            DurationSeconds=3600,
        )
        c = resp["Credentials"]
        return TempCredentials(c["AccessKeyId"], c["SecretAccessKey"], c["SessionToken"])

    def stack_status(self, creds: TempCredentials, region: str, stack_name: str) -> str | None:
        import boto3
        import botocore.exceptions  # type: ignore[import-untyped]

        cfn = boto3.client(
            "cloudformation",
            region_name=region,
            aws_access_key_id=creds.access_key_id,
            aws_secret_access_key=creds.secret_access_key,
            aws_session_token=creds.session_token,
        )
        try:
            stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
        except botocore.exceptions.ClientError as exc:
            if "does not exist" in str(exc):
                return None
            raise
        return str(stacks[0]["StackStatus"]) if stacks else None

    def stack_outputs(self, creds: TempCredentials, region: str, stack_name: str) -> dict[str, str]:
        import boto3

        cfn = boto3.client(
            "cloudformation",
            region_name=region,
            aws_access_key_id=creds.access_key_id,
            aws_secret_access_key=creds.secret_access_key,
            aws_session_token=creds.session_token,
        )
        stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
        return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


class CdkRunner(Protocol):
    def deploy(self, creds: TempCredentials, region: str, context: dict[str, str]) -> None: ...


class SubprocessCdkRunner:
    """Runs `cdk deploy` from infra/cdk with the assumed-role credentials
    injected via environment — the control plane's own credentials are never
    exposed to the child process."""

    def __init__(self, cdk_dir: Path) -> None:
        self._cdk_dir = cdk_dir

    def deploy(self, creds: TempCredentials, region: str, context: dict[str, str]) -> None:
        env = {
            # Deliberately minimal env: no inherited AWS_* from the parent.
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/tmp"),
            "AWS_ACCESS_KEY_ID": creds.access_key_id,
            "AWS_SECRET_ACCESS_KEY": creds.secret_access_key,
            "AWS_SESSION_TOKEN": creds.session_token,
            "AWS_REGION": region,
            "AWS_DEFAULT_REGION": region,
        }
        args = ["npx", "cdk", "deploy", STACK_NAME, "--require-approval", "never"]
        for key, value in context.items():
            args += ["-c", f"{key}={value}"]
        logger.info("running cdk deploy for context orgSlug=%s", context.get("orgSlug"))
        result = subprocess.run(
            args, cwd=self._cdk_dir, env=env, capture_output=True, text=True, timeout=3600
        )
        if result.returncode != 0:
            # stderr may reference resources but never credentials; safe to log.
            logger.error("cdk deploy failed: %s", result.stderr[-4000:])
            raise RuntimeError(f"cdk deploy exited with {result.returncode}")


class Provisioner:
    def __init__(
        self,
        registry: StackRegistry,
        aws: AwsGateway,
        cdk: CdkRunner,
        vendor_ecr_registry: str,
        poll_interval_s: float = 15.0,
        poll_timeout_s: float = 1800.0,
    ) -> None:
        self._registry = registry
        self._aws = aws
        self._cdk = cdk
        self._vendor_ecr = vendor_ecr_registry
        self._poll_interval = poll_interval_s
        self._poll_timeout = poll_timeout_s

    # -------------------------------------------------------------------------
    def provision(self, org_slug: str, image_tag: str) -> dict[str, str]:
        """Full first-time provisioning (spec §6 Step 3, ~15 minutes)."""
        return self._deploy(org_slug, image_tag, first_time=True)

    def update_stack(self, org_slug: str, image_tag: str) -> dict[str, str]:
        """Version update: rolling ECS service update, zero downtime (§6)."""
        return self._deploy(org_slug, image_tag, first_time=False)

    def _deploy(self, org_slug: str, image_tag: str, first_time: bool) -> dict[str, str]:
        record = self._registry.get(org_slug)
        if not record.bootstrap_role_arn or not record.aws_region or not record.aws_account_id:
            raise ValueError(f"customer {org_slug!r} has not connected an AWS account yet")

        status = StackStatus.PROVISIONING if first_time else StackStatus.UPDATING
        self._registry.set_status(org_slug, status)
        try:
            external_id = self._registry.external_id_for(org_slug)
            creds = self._aws.assume_bootstrap_role(
                record.bootstrap_role_arn, external_id, session_name=f"platform-{org_slug}"
            )
            # The external ID's job is done; drop the reference immediately.
            del external_id

            platform_url = record.platform_url or f"https://{org_slug}.platform.example.com"
            self._cdk.deploy(
                creds,
                record.aws_region,
                context={
                    "orgSlug": org_slug,
                    "platformUrl": platform_url,
                    "vendorEcrRegistry": self._vendor_ecr,
                    "imageTag": image_tag,
                    "region": record.aws_region,
                },
            )
            self._poll_until_stable(creds, record.aws_region)
            outputs = self._aws.stack_outputs(creds, record.aws_region, STACK_NAME)
            self._registry.set_status(
                org_slug,
                StackStatus.READY,
                version=image_tag,
                platform_url=outputs.get("PlatformDomain", platform_url),
                outputs=outputs,
            )
            logger.info("stack %s for %s is READY at version %s", STACK_NAME, org_slug, image_tag)
            return outputs
        except Exception:
            self._registry.set_status(org_slug, StackStatus.FAILED)
            logger.exception("deployment failed for %s", org_slug)
            raise

    def _poll_until_stable(self, creds: TempCredentials, region: str) -> None:
        """Poll CloudFormation until a terminal state (spec §6: 'polls for
        completion'). cdk deploy usually blocks until done itself; polling
        guards against the subprocess returning early or being resumed."""
        deadline = time.monotonic() + self._poll_timeout
        while time.monotonic() < deadline:
            status = self._aws.stack_status(creds, region, STACK_NAME)
            if status in _TERMINAL_OK:
                return
            if status in _TERMINAL_FAIL:
                raise RuntimeError(f"stack entered failure state {status}")
            time.sleep(self._poll_interval)
        raise TimeoutError(f"stack did not stabilise within {self._poll_timeout}s")
