"""Self-service onboarding (ROADMAP section 7 item 2).

Standing this platform up in a customer's AWS account used to be a runbook
with a Python REPL in the middle of it: register the customer by hand, mail
them a YAML and an external ID, wait for them to mail back a role ARN, call
`Provisioner.provision()` from a shell, then tell them a URL. This module is
the same lifecycle with the humans taken out of the middle.

Three decisions shape it:

* **The customer pastes a 12-digit account ID, and nothing else.** The
  bootstrap template hardcodes `RoleName: platform-bootstrap`, so the role ARN
  is derivable - asking somebody to copy an ARN is asking them to make a typo
  that fails at assume-role time with a message about trust policies.
* **Detection is a probe, not a form field.** "Have they run the template
  yet?" is answerable by trying to assume the role, which is exactly what
  provisioning will do a minute later. A form field that asks the customer to
  confirm they did it can be wrong; an assume-role that succeeds cannot.
* **Preflight fails in plain English before it fails in CloudFormation.** The
  checks here are the specific ways the deploys in `STATUS.md` §17/§20
  actually broke: no CDK bootstrap in the region, no Elastic IP headroom for
  the NAT gateway, a stack already there. Ten minutes into a `CREATE_FAILED`
  is the worst possible time to learn any of them.

The onboarding token authorises exactly one customer's onboarding and nothing
else. It has to exist because this is the one flow with no user account behind
it - the platform the customer would log into does not exist yet.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import threading
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

from ..provisioner.provisioner import AwsGateway, Provisioner
from ..registry.registry import CustomerRecord, StackRegistry, StackStatus

STACK_NAME = "PlatformStack"
BOOTSTRAP_ROLE_NAME = "platform-bootstrap"
BOOTSTRAP_STACK_NAME = "anchor-platform-bootstrap"

_ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
_REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]$")


def mint_token() -> tuple[str, str]:
    """(token, sha256 hash). Only the hash is stored - see the registry."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def bootstrap_role_arn(account_id: str) -> str:
    """Derived, never typed. The template fixes the role name, so the account
    ID is the only unknown."""
    return f"arn:aws:iam::{account_id}:role/{BOOTSTRAP_ROLE_NAME}"


def launch_url(
    *, template_url: str, control_plane_role_arn: str, external_id: str, region: str
) -> str:
    """A CloudFormation console URL with the parameters already filled in.

    The customer's whole job becomes: click, tick the IAM acknowledgement,
    Create. Every character they would otherwise have copied by hand - the
    external ID especially, which is 43 characters of base64 - is in the link.
    """
    return (
        f"https://{region}.console.aws.amazon.com/cloudformation/home"
        f"?region={region}#/stacks/create/review"
        f"?templateURL={quote(template_url, safe='')}"
        f"&stackName={BOOTSTRAP_STACK_NAME}"
        f"&param_ControlPlaneRoleArn={quote(control_plane_role_arn, safe='')}"
        f"&param_ExternalId={quote(external_id, safe='')}"
    )


@dataclass(frozen=True)
class Check:
    """One preflight result. `ok=False` always carries a `remedy`: a check
    that reports a problem without saying what to do about it has moved the
    confusion rather than removed it."""
    name: str
    ok: bool
    detail: str
    remedy: str = ""


@dataclass
class OnboardingConfig:
    template_url: str
    control_plane_role_arn: str
    image_tag: str = "latest"
    platform_url_template: str = "https://{org_slug}.anchor.example"
    # Regions this build has been deployed to and expects to work in. Not a
    # guess at AWS's own availability: a region nobody has ever run the stack
    # in is not one to discover problems in during somebody's onboarding.
    supported_regions: tuple[str, ...] = ("eu-west-1", "eu-west-2", "us-east-1", "us-west-2")


@dataclass
class _Job:
    """A provisioning run in flight. Kept in memory deliberately: the durable
    answer to "what happened" is the registry status plus CloudFormation's own
    events, and duplicating that into a job table would create a third place
    to disagree. All this adds is the exception text, which neither of those
    two records."""
    error: str | None = None
    done: bool = False


class OnboardingService:
    def __init__(
        self,
        registry: StackRegistry,
        aws: AwsGateway,
        provisioner: Provisioner,
        config: OnboardingConfig,
        *,
        runner: Callable[[Callable[[], None]], Any] | None = None,
    ) -> None:
        self._registry = registry
        self._aws = aws
        self._provisioner = provisioner
        self._config = config
        # Injectable so tests run provisioning synchronously rather than
        # racing a thread; production spawns one.
        self._runner = runner or self._spawn
        self._jobs: dict[str, _Job] = {}

    # ---- step 1: the vendor creates the onboarding -------------------------
    def start(self, org_slug: str, org_name: str, contact_email: str) -> dict[str, str]:
        record, external_id = self._registry.register_customer(org_slug)
        token, token_hash = mint_token()
        self._registry.set_onboarding(
            org_slug, org_name=org_name, contact_email=contact_email, token_hash=token_hash
        )
        # The external ID is deliberately *not* returned. It used to be, on
        # the assumption the vendor would paste it into a link by hand -
        # `launch_url_for` mints that link server-side, so nothing needs the
        # plaintext outside this process, and a secret with no caller should
        # not be handed out on the chance somebody wants it later.
        del external_id
        return {"org_slug": record.org_slug, "onboarding_token": token}

    def launch_url_for(self, record: CustomerRecord, region: str) -> str:
        return launch_url(
            template_url=self._config.template_url,
            control_plane_role_arn=self._config.control_plane_role_arn,
            external_id=self._registry.external_id_for(record.org_slug),
            region=region,
        )

    # ---- step 2: detect that the bootstrap stack landed --------------------
    def detect_account(self, org_slug: str, account_id: str, region: str) -> dict[str, Any]:
        """Try to assume the derived role. Success *is* the detection - and it
        also proves the external ID matched, which is the other half of what
        could have gone wrong."""
        if not _ACCOUNT_RE.match(account_id):
            raise ValueError("that does not look like a 12-digit AWS account ID")
        if not _REGION_RE.match(region):
            raise ValueError(f"invalid AWS region: {region!r}")
        if region not in self._config.supported_regions:
            raise ValueError(
                f"{region} is not a region this platform has been deployed to yet "
                f"(supported: {', '.join(self._config.supported_regions)})"
            )
        arn = bootstrap_role_arn(account_id)
        external_id = self._registry.external_id_for(org_slug)
        try:
            self._aws.assume_bootstrap_role(arn, external_id, session_name=f"detect-{org_slug}")
        except Exception as exc:  # boto3 raises a ClientError subclass
            return {
                "connected": False,
                "detail": (
                    "Couldn't assume the bootstrap role yet. If you have just created the "
                    "stack, give it a few seconds. If it has finished, check that it was "
                    "created in this account and that the parameters were left as the "
                    "link filled them in."
                ),
                "error": str(exc)[:300],
            }
        self._registry.connect_aws(org_slug, account_id, region, arn)
        return {"connected": True, "detail": "Connected to AWS account " + account_id}

    # ---- step 3: preflight --------------------------------------------------
    def preflight(self, org_slug: str) -> list[Check]:
        record = self._registry.get(org_slug)
        if not (record.aws_account_id and record.aws_region and record.bootstrap_role_arn):
            return [Check("AWS account", False, "No AWS account connected yet.",
                          "Finish the previous step first.")]
        region = record.aws_region
        checks: list[Check] = []
        try:
            creds = self._aws.assume_bootstrap_role(
                record.bootstrap_role_arn,
                self._registry.external_id_for(org_slug),
                session_name=f"preflight-{org_slug}",
            )
        except Exception as exc:
            return [Check("Bootstrap role", False, str(exc)[:300],
                          "Re-run the bootstrap stack; the role could not be assumed.")]
        checks.append(Check("Bootstrap role", True, f"Assumed {record.bootstrap_role_arn}"))

        checks.append(
            Check("Region", True, f"{region} is supported")
            if region in self._config.supported_regions
            else Check("Region", False, f"{region} has not been deployed to before",
                       "Pick one of: " + ", ".join(self._config.supported_regions))
        )

        version = self._aws.cdk_bootstrap_version(creds, region)
        checks.append(
            Check("CDK bootstrap", True, f"version {version} in {region}")
            if version
            else Check(
                "CDK bootstrap", False, f"{region} has never been CDK-bootstrapped",
                f"Run `npx cdk bootstrap aws://{record.aws_account_id}/{region}` in that "
                "account, or let us do it for you.",
            )
        )

        used, limit = self._aws.elastic_ip_headroom(creds, region)
        checks.append(
            Check("Elastic IPs", True, f"{used} of {limit} in use; the stack needs 1")
            if used < limit
            else Check(
                "Elastic IPs", False, f"all {limit} Elastic IPs in {region} are in use",
                "Release one, or ask AWS to raise the quota - the NAT gateway needs one.",
            )
        )

        existing = self._aws.stack_status(creds, region, STACK_NAME)
        checks.append(
            Check("Existing stack", True, "No platform stack in this account yet")
            if existing is None
            else Check(
                "Existing stack", existing.endswith("_COMPLETE"),
                f"A stack named {STACK_NAME} is already here ({existing})",
                "" if existing.endswith("_COMPLETE")
                else "It is mid-operation or failed; finish or delete it before provisioning.",
            )
        )
        return checks

    # ---- step 4: provision --------------------------------------------------
    def provision(self, org_slug: str) -> dict[str, Any]:
        """Kick off provisioning. Refuses while a failing preflight check
        stands: the customer would otherwise wait ten minutes to be told
        something this already knows."""
        record = self._registry.get(org_slug)
        if record.stack_status in (StackStatus.PROVISIONING, StackStatus.UPDATING):
            return {"started": False, "detail": "Already provisioning."}
        if record.stack_status is StackStatus.READY:
            return {"started": False, "detail": "This deployment is already provisioned."}
        failed = [c for c in self.preflight(org_slug) if not c.ok]
        if failed:
            raise ValueError("; ".join(f"{c.name}: {c.detail}" for c in failed))

        def run() -> None:
            job = self._jobs[org_slug]
            try:
                self._provisioner.provision(org_slug, self._config.image_tag)
            except Exception as exc:
                job.error = str(exc)[:500]
            finally:
                job.done = True

        self._jobs[org_slug] = _Job()
        self._runner(run)
        return {"started": True, "detail": "Provisioning started. This takes about 15 minutes."}

    def _spawn(self, run: Callable[[], None]) -> None:
        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    # ---- failure, in words (ROADMAP section 7 item 4) -----------------------
    # Each entry is a failure this build has actually hit, and the one action
    # that resolves it. A wall of CloudFormation events is not an explanation:
    # somebody reading `CREATE_FAILED  Search  Resource creation cancelled` for
    # the first time has no way to know that the *previous* failure is what
    # cancelled it, or that a stuck OpenSearch domain has to be deleted by hand
    # before a retry can work (`STATUS.md` §17, §20).
    _HINTS: tuple[tuple[str, str], ...] = (
        ("Resource creation cancelled",
         "This one was cancelled because something else failed first - look for the "
         "earliest CREATE_FAILED above, which is the real cause."),
        ("no pq wrapper available",
         "The migration Lambda was bundled for the wrong architecture. Rebuild with "
         "Docker running and try again."),
        ("exec format error",
         "An image was built for the wrong architecture. Rebuild all three with "
         "`docker build --platform=linux/amd64` on the build command itself - the "
         "Dockerfile pin alone is not enough."),
        ("AddressLimitExceeded",
         "The account is out of Elastic IPs in this region. Release one or raise the "
         "quota; the NAT gateway needs exactly one."),
        ("has a dependent object",
         "Something CloudFormation could not delete is holding a security group or "
         "subnet - usually an RDS instance skipped by deletion protection, or an "
         "OpenSearch domain that was never told to delete. Both have to go by hand "
         "before a retry."),
        ("is not authorized to perform",
         "The bootstrap role is missing a permission. Re-run the bootstrap template - "
         "it may predate the permission this deploy needs."),
    )

    def failures(self, events: list[dict[str, str]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for event in events:
            if "FAILED" not in event.get("status", ""):
                continue
            reason = event.get("reason", "")
            hint = next((h for needle, h in self._HINTS if needle in reason), "")
            out.append({
                "logical_id": event.get("logical_id", ""),
                "status": event["status"],
                "reason": reason,
                "hint": hint,
            })
        return out

    # ---- status, throughout -------------------------------------------------
    def status(self, org_slug: str, *, with_events: bool = True) -> dict[str, Any]:
        record = self._registry.get(org_slug)
        job = self._jobs.get(org_slug)
        events: list[dict[str, str]] = []
        if with_events and record.bootstrap_role_arn and record.aws_region:
            try:
                creds = self._aws.assume_bootstrap_role(
                    record.bootstrap_role_arn,
                    self._registry.external_id_for(org_slug),
                    session_name=f"status-{org_slug}",
                )
                events = self._aws.stack_events(creds, record.aws_region, STACK_NAME)
            except Exception:
                # Progress is a nicety; never let it break the status page the
                # customer is watching to find out whether things are broken.
                events = []
        return {
            "org_slug": record.org_slug,
            "org_name": record.org_name,
            "aws_account_id": record.aws_account_id,
            "aws_region": record.aws_region,
            "connected": bool(record.bootstrap_role_arn),
            "stack_status": record.stack_status.value,
            "platform_url": record.platform_url,
            "outputs": record.outputs,
            "error": job.error if job else None,
            "events": events,
            # Only the failures, in plain English, so the page does not ask
            # somebody to read a stack trace to find out what to do next.
            "failures": self.failures(events),
            # A failed deploy is retryable: `provision` refuses while one is
            # running or already ready, and FAILED is neither.
            "retryable": record.stack_status is StackStatus.FAILED,
        }
