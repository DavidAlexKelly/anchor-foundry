"""Stack teardown (the third lifecycle operation alongside Provisioner's
provision()/update_stack()) - an operator tool, not a customer-facing
action (see STATUS.md for why: it needs AWS-account-level trust the
customer-facing app doesn't have).

Mirrors Provisioner's assume-role + poll pattern exactly, but has to reach
past CloudFormation for four resources the stack deliberately keeps out of
CFN's own deletion (spec §10 "don't let a bad deploy nuke a customer's
data"): RDS has deletionProtection=true, and the OpenSearch domain plus both
S3 buckets have removalPolicy: RETAIN (infra/cdk/src/constructs/data-stores.ts).
Order matters and is the whole reason this isn't just `cfn.delete_stack()`:

  1. Read the stack's outputs *before* deleting it - once the stack is gone
     there is nothing left to describe, and CDK auto-generates every one of
     these physical names, so this is the only reliable way to learn them
     (customer-stack.ts's DatabaseInstanceIdentifier/SearchDomainName/
     AccessLogBucketName/DataBucketName outputs exist for exactly this).
  2. Disable RDS deletion protection and wait for it to actually clear -
     CloudFormation will otherwise fail deleting the DB instance even
     moments after the ModifyDBInstance call returns.
  3. Delete the stack and poll until it's gone.
  4. Only now clean up what RETAIN left behind: empty + delete both S3
     buckets, delete the OpenSearch domain. Best-effort and logged, not
     fatal to the overall result - the expensive, ongoing-cost resources
     (RDS, ECS, NAT gateway, ALB, CloudFront) are already gone by this
     point via the stack deletion, which is the part that actually matters
     if this step needs a human to finish by hand.
"""
from __future__ import annotations

import logging
import time

from ..provisioner.provisioner import STACK_NAME, AwsGateway, TempCredentials
from ..registry.registry import StackRegistry, StackStatus

logger = logging.getLogger("control_plane.deprovisioner")

_ALREADY_TERMINAL = {StackStatus.DESTROYING, StackStatus.DESTROYED}


class Deprovisioner:
    def __init__(
        self,
        registry: StackRegistry,
        aws: AwsGateway,
        poll_interval_s: float = 15.0,
        poll_timeout_s: float = 1800.0,
        protection_wait_timeout_s: float = 120.0,
    ) -> None:
        self._registry = registry
        self._aws = aws
        self._poll_interval = poll_interval_s
        self._poll_timeout = poll_timeout_s
        self._protection_wait_timeout = protection_wait_timeout_s

    def deprovision(self, org_slug: str) -> None:
        record = self._registry.get(org_slug)
        if record.stack_status in _ALREADY_TERMINAL:
            raise ValueError(f"customer {org_slug!r} stack is already {record.stack_status.value}")
        if not record.bootstrap_role_arn or not record.aws_region:
            raise ValueError(f"customer {org_slug!r} has not connected an AWS account")

        self._registry.set_status(org_slug, StackStatus.DESTROYING)
        try:
            external_id = self._registry.external_id_for(org_slug)
            creds = self._aws.assume_bootstrap_role(
                record.bootstrap_role_arn, external_id, session_name=f"platform-teardown-{org_slug}"
            )
            del external_id
            region = record.aws_region

            # Must happen before delete_stack: nothing describable afterward.
            outputs = self._aws.stack_outputs(creds, region, STACK_NAME)

            db_id = outputs.get("DatabaseInstanceIdentifier")
            if db_id:
                self._aws.disable_deletion_protection(creds, region, db_id)
                self._wait_for_deletion_protection_off(creds, region, db_id)
            else:
                logger.warning(
                    "no DatabaseInstanceIdentifier output for %s - stack predates this output; "
                    "deletion will fail if RDS deletion protection is still on",
                    org_slug,
                )

            self._aws.delete_stack(creds, region, STACK_NAME)
            self._poll_until_deleted(creds, region)
            logger.info("stack %s for %s deleted", STACK_NAME, org_slug)

            # Best-effort from here: the expensive, ongoing-cost resources
            # are already gone via the stack deletion above. A failure here
            # is left for a human, not retried or turned into FAILED.
            for output_key in ("DataBucketName", "AccessLogBucketName"):
                bucket = outputs.get(output_key)
                if not bucket:
                    logger.warning("no %s output for %s - skipping bucket cleanup", output_key, org_slug)
                    continue
                try:
                    self._aws.empty_bucket(creds, region, bucket)
                    self._aws.delete_bucket(creds, region, bucket)
                except Exception:
                    logger.exception("failed to delete retained bucket %s for %s - needs manual cleanup", bucket, org_slug)

            domain = outputs.get("SearchDomainName")
            if not domain:
                logger.warning("no SearchDomainName output for %s - skipping OpenSearch cleanup", org_slug)
            else:
                try:
                    self._aws.delete_search_domain(creds, region, domain)
                except Exception:
                    logger.exception("failed to delete retained OpenSearch domain %s for %s - needs manual cleanup", domain, org_slug)

            self._registry.set_status(org_slug, StackStatus.DESTROYED)
            logger.info("teardown complete for %s", org_slug)
        except Exception:
            self._registry.set_status(org_slug, StackStatus.FAILED)
            logger.exception("teardown failed for %s", org_slug)
            raise

    def _wait_for_deletion_protection_off(self, creds: TempCredentials, region: str, db_instance_identifier: str) -> None:
        deadline = time.monotonic() + self._protection_wait_timeout
        while time.monotonic() < deadline:
            if not self._aws.deletion_protection_enabled(creds, region, db_instance_identifier):
                return
            time.sleep(self._poll_interval)
        raise TimeoutError(
            f"RDS deletion protection on {db_instance_identifier} did not clear "
            f"within {self._protection_wait_timeout}s"
        )

    def _poll_until_deleted(self, creds: TempCredentials, region: str) -> None:
        deadline = time.monotonic() + self._poll_timeout
        while time.monotonic() < deadline:
            status = self._aws.stack_status(creds, region, STACK_NAME)
            if status is None:  # describe_stacks 404s once deletion completes
                return
            if status == "DELETE_FAILED":
                raise RuntimeError(f"{STACK_NAME} entered DELETE_FAILED")
            time.sleep(self._poll_interval)
        raise TimeoutError(f"{STACK_NAME} did not finish deleting within {self._poll_timeout}s")
