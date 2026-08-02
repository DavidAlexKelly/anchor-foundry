"""A fake AWS account, for walking through onboarding without one.

**Flagged for review: development tooling only; never wired in production.**
Same shape and same warning as `apps/api/dev_server.py` - the production
entrypoint (`create_production_app`, `service_from_env`) cannot reach any of
this, and the CLI only builds it under an explicitly named `demo` command.

It exists because the onboarding flow is five steps of *waiting for AWS*, and
the only way to see whether those five steps make sense to a human is to walk
them. Scripting the account's state - not assumable, then assumable, then a
region with no CDK bootstrap - is how you see the failure screens without
breaking a real account to get them.
"""
from __future__ import annotations

from typing import Any

from ..provisioner.provisioner import TempCredentials
from ..registry.registry import StackRegistry, StackStatus


class DemoAws:
    """Every gateway call onboarding makes, answered from memory."""

    def __init__(self) -> None:
        # Starts unassumable: the customer has not run the template yet, which
        # is the first thing anybody walking the flow should see.
        self.assumable = False
        self.cdk_version: str | None = "18"
        self.eips: tuple[int, int] = (1, 5)
        self.existing_stack: str | None = None
        self.events: list[dict[str, str]] = []

    def assume_bootstrap_role(
        self, role_arn: str, external_id: str, session_name: str
    ) -> TempCredentials:
        if not self.assumable:
            raise RuntimeError("AccessDenied: not authorized to perform sts:AssumeRole")
        return TempCredentials("AKIA_DEMO", "secret", "token")

    def cdk_bootstrap_version(self, creds: TempCredentials, region: str) -> str | None:
        return self.cdk_version

    def elastic_ip_headroom(self, creds: TempCredentials, region: str) -> tuple[int, int]:
        return self.eips

    def stack_status(self, creds: TempCredentials, region: str, stack_name: str) -> str | None:
        return self.existing_stack

    def stack_events(
        self, creds: TempCredentials, region: str, stack_name: str, limit: int = 25
    ) -> list[dict[str, str]]:
        return self.events[:limit]

    def ensure_opensearch_service_linked_role(self, creds: TempCredentials) -> None:
        pass


class DemoProvisioner:
    """Deploys nothing, in about four seconds, writing the events a real
    fifteen-minute deploy would have written."""

    _SCRIPT = [
        ("Vpc", "AWS::EC2::VPC", "CREATE_COMPLETE"),
        ("Postgres", "AWS::RDS::DBInstance", "CREATE_IN_PROGRESS"),
        ("Search", "AWS::OpenSearchService::Domain", "CREATE_IN_PROGRESS"),
        ("Migration", "AWS::CloudFormation::CustomResource", "CREATE_COMPLETE"),
        ("ApiService", "AWS::ECS::Service", "CREATE_COMPLETE"),
        ("PlatformStack", "AWS::CloudFormation::Stack", "CREATE_COMPLETE"),
    ]

    def __init__(self, registry: StackRegistry, aws: DemoAws, *, fail: bool = False) -> None:
        self._registry = registry
        self._aws = aws
        self.fail = fail

    def provision(self, org_slug: str, image_tag: str) -> dict[str, str]:
        import time

        self._registry.set_status(org_slug, StackStatus.PROVISIONING)
        for i, (logical, kind, status) in enumerate(self._SCRIPT):
            if self.fail and logical == "Search":
                self._aws.events.insert(0, {
                    "timestamp": f"2026-01-01T10:00:{i:02d}",
                    "logical_id": logical, "resource_type": kind,
                    "status": "CREATE_FAILED",
                    "reason": "Resource creation cancelled",
                })
                self._registry.set_status(org_slug, StackStatus.FAILED)
                raise RuntimeError("CREATE_FAILED: Search (Resource creation cancelled)")
            self._aws.events.insert(0, {
                "timestamp": f"2026-01-01T10:00:{i:02d}",
                "logical_id": logical, "resource_type": kind,
                "status": status, "reason": "",
            })
            time.sleep(0.6)
        outputs = {"PlatformDomain": "d3xample.cloudfront.net", "UserPoolId": "eu-west-2_demo"}
        self._registry.set_status(
            org_slug, StackStatus.READY,
            platform_url="https://d3xample.cloudfront.net", outputs=outputs,
        )
        return outputs


def demo_service(registry: StackRegistry, **kwargs: Any):
    """Build an OnboardingService over the fakes above."""
    from .service import OnboardingConfig, OnboardingService

    aws = DemoAws()
    provisioner = DemoProvisioner(registry, aws, fail=bool(kwargs.get("fail")))
    config = OnboardingConfig(
        template_url="https://example.invalid/anchor-bootstrap.yaml",
        control_plane_role_arn="arn:aws:iam::999999999999:role/anchor-control-plane",
    )
    return aws, OnboardingService(registry, aws, provisioner, config)  # type: ignore[arg-type]
