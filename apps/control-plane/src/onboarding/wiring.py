"""Building the real, AWS-backed onboarding service from the environment.

Split out of `api/app.py` because two callers need the identical wiring - the
HTTP surface and the operator CLI - and two copies of "which env var means
what" is how they drift.

Every value here is read at call time, never at import: the CLI's `demo`
command builds a fake-backed service in a shell that has none of these set,
and importing this module must not explode there.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..provisioner.provisioner import Boto3Gateway, Provisioner, SubprocessCdkRunner
from ..registry.registry import KmsSecretsCodec, StackRegistry
from .service import OnboardingConfig, OnboardingService


def registry_from_env() -> StackRegistry:
    registry = StackRegistry(
        os.environ["CONTROL_PLANE_DATABASE_URL"],
        KmsSecretsCodec(
            os.environ["ONBOARDING_KMS_KEY_ID"],
            os.environ.get("AWS_REGION", "eu-west-2"),
        ),
    )
    registry.ensure_schema()
    return registry


def service_from_env(registry: StackRegistry | None = None) -> tuple[StackRegistry, OnboardingService]:
    reg = registry or registry_from_env()
    aws = Boto3Gateway()
    provisioner = Provisioner(
        reg,
        aws,
        SubprocessCdkRunner(Path(os.environ.get("CDK_DIR", "infra/cdk"))),
        os.environ["VENDOR_ECR_REGISTRY"],
    )
    config = OnboardingConfig(
        template_url=os.environ["BOOTSTRAP_TEMPLATE_URL"],
        control_plane_role_arn=os.environ["CONTROL_PLANE_ROLE_ARN"],
        image_tag=os.environ.get("PLATFORM_IMAGE_TAG", "latest"),
    )
    return reg, OnboardingService(reg, aws, provisioner, config)
