"""Control plane operator CLI. Not customer-facing (see deprovisioner.py's
module docstring for why teardown lives here and not in the product's own
UI) - this is a tool run by whoever operates the control plane.

    python -m src.cli deprovision --org-slug <slug>

Permanently deletes that customer's platform stack, including their
database, in one fully-automated run (no confirmation prompt - the caller
is expected to already mean it; this is an operator tool, not a self-service
one). Reads CONTROL_PLANE_DATABASE_URL and TEARDOWN_KMS_KEY_ID from the
environment; everything else about the target customer (bootstrap role ARN,
AWS region, external ID) comes from the registry, keyed by --org-slug.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .deprovisioner.deprovisioner import Deprovisioner
from .provisioner.provisioner import Boto3Gateway
from .registry.registry import KmsSecretsCodec, StackRegistry

logger = logging.getLogger("control_plane.cli")


def _registry() -> StackRegistry:
    dsn = os.environ["CONTROL_PLANE_DATABASE_URL"]
    key_id = os.environ["TEARDOWN_KMS_KEY_ID"]
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")
    return StackRegistry(dsn, KmsSecretsCodec(key_id, region))


def _cmd_deprovision(args: argparse.Namespace) -> int:
    registry = _registry()
    deprovisioner = Deprovisioner(registry, Boto3Gateway())
    logger.info("tearing down stack for %r - this deletes real infrastructure and data", args.org_slug)
    deprovisioner.deprovision(args.org_slug)
    logger.info("%r: torn down", args.org_slug)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    deprovision = subparsers.add_parser(
        "deprovision", help="Permanently delete a customer's platform stack and all its data."
    )
    deprovision.add_argument("--org-slug", required=True)
    deprovision.set_defaults(func=_cmd_deprovision)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
