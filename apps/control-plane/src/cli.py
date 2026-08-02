"""Control plane operator CLI. Not customer-facing (see deprovisioner.py's
module docstring for why teardown lives here and not in the product's own
UI) - this is a tool run by whoever operates the control plane.

    python -m src.cli onboard    --org-slug acme --org-name "Acme" --email ops@acme.com
    python -m src.cli provision  --org-slug acme --account-id 123456789012 --region eu-west-2
    python -m src.cli status     --org-slug acme
    python -m src.cli serve      --port 8400
    python -m src.cli demo       --port 8400
    python -m src.cli deprovision --org-slug acme

`onboard` mints the customer's link and stops - the customer drives the rest
from the page (`ROADMAP.md` section 7 item 2). `provision` is the same
lifecycle for an operator who would rather not, or for a customer who cannot:
it detects, preflights and deploys with CloudFormation's events on stdout.

Everything the customer-facing flow can do, this can do, because both are the
same `OnboardingService` - a CLI that drifted from the page would eventually
provision something the page would have refused.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from .deprovisioner.deprovisioner import Deprovisioner
from .registry.registry import KmsSecretsCodec, StackRegistry, StackStatus

logger = logging.getLogger("control_plane.cli")


def _registry() -> StackRegistry:
    dsn = os.environ["CONTROL_PLANE_DATABASE_URL"]
    key_id = os.environ["TEARDOWN_KMS_KEY_ID"]
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")
    return StackRegistry(dsn, KmsSecretsCodec(key_id, region))


def _cmd_deprovision(args: argparse.Namespace) -> int:
    from .provisioner.provisioner import Boto3Gateway

    registry = _registry()
    deprovisioner = Deprovisioner(registry, Boto3Gateway())
    logger.info("tearing down stack for %r - this deletes real infrastructure and data", args.org_slug)
    deprovisioner.deprovision(args.org_slug)
    logger.info("%r: torn down", args.org_slug)
    return 0


# ---- onboarding (ROADMAP section 7 item 1) ----------------------------------
def _cmd_onboard(args: argparse.Namespace) -> int:
    from .onboarding.wiring import service_from_env

    _, service = service_from_env()
    started = service.start(args.org_slug, args.org_name, args.email)
    base = os.environ.get("CONTROL_PLANE_PUBLIC_URL", "")
    print(f"customer:  {started['org_slug']}")
    print(f"send them: {base}/onboarding?token={started['onboarding_token']}")
    print("\nThat link carries the CloudFormation launch URL with both parameters "
          "prefilled;\nthe only thing they type is their 12-digit account ID.")
    return 0


def _print_checks(checks: list) -> bool:
    for check in checks:
        print(f"  {'PASS' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
        if not check.ok and check.remedy:
            print(f"        -> {check.remedy}")
    return all(c.ok for c in checks)


def _cmd_provision(args: argparse.Namespace) -> int:
    """Detect, preflight, deploy - the operator's path through exactly the
    steps the customer's page walks, with the same refusals."""
    from .onboarding.wiring import service_from_env

    registry, service = service_from_env()
    if args.account_id and args.region:
        print(f"connecting {args.account_id} in {args.region}…")
        result = service.detect_account(args.org_slug, args.account_id, args.region)
        print(f"  {result['detail']}")
        if not result["connected"]:
            return 1

    print("preflight:")
    if not _print_checks(service.preflight(args.org_slug)):
        print("\nrefusing to provision while a check is failing - "
              "ten minutes into a CREATE_FAILED is the wrong time to learn any of this.")
        return 1

    started = service.provision(args.org_slug)
    print(f"\n{started['detail']}")
    if not started["started"]:
        return 1
    return _follow(service, registry, args.org_slug)


def _follow(service, registry: StackRegistry, org_slug: str) -> int:
    """Tail the deploy. The events are the only honest answer to "what is it
    doing?" during the fifteen minutes, and they were previously visible to
    nobody."""
    seen: set[str] = set()
    while True:
        state = service.status(org_slug)
        for event in reversed(state["events"]):
            key = f"{event['timestamp']}{event['logical_id']}{event['status']}"
            if key in seen:
                continue
            seen.add(key)
            reason = f"  {event['reason']}" if event["reason"] else ""
            print(f"  {event['timestamp'][11:19]}  {event['status']:<22}{event['logical_id']}{reason}")
        status = state["stack_status"]
        if status == StackStatus.READY.value:
            print(f"\nready: {state['platform_url']}")
            print(f"first account: {state['platform_url']}/setup")
            return 0
        if status == StackStatus.FAILED.value:
            print(f"\nfailed: {state['error'] or 'see the events above'}")
            return 1
        time.sleep(5)


def _cmd_status(args: argparse.Namespace) -> int:
    from .onboarding.wiring import service_from_env

    _, service = service_from_env()
    state = service.status(args.org_slug)
    print(f"{state['org_slug']}: {state['stack_status']}")
    print(f"  account:  {state['aws_account_id'] or '-'} ({state['aws_region'] or '-'})")
    print(f"  url:      {state['platform_url'] or '-'}")
    if state["error"]:
        print(f"  error:    {state['error']}")
    for event in state["events"][:10]:
        print(f"  {event['timestamp'][11:19]}  {event['status']:<22}{event['logical_id']}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api.app import create_production_app

    uvicorn.run(create_production_app(), host=args.host, port=args.port)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    """Walk the onboarding flow with no AWS account at all.

    Development tooling, flagged as such in `onboarding/demo.py`: it wires a
    fake gateway that starts un-assumable, so the whole sequence - including
    the screens people only see when something is wrong - can be walked before
    anybody spends a real fifteen minutes on it.
    """
    import uvicorn

    from .api.app import create_app
    from .onboarding.demo import demo_service

    registry = StackRegistry(
        os.environ["CONTROL_PLANE_DATABASE_URL"], _DemoCodec()
    )
    registry.ensure_schema()
    aws, service = demo_service(registry, fail=args.fail)
    app = create_app(
        service, registry, admin_token="demo",
        base_url=f"http://localhost:{args.port}",
    )

    @app.post("/demo/run-template")
    def run_template() -> dict[str, bool]:
        """Stands in for the customer creating the bootstrap stack."""
        aws.assumable = True
        return {"assumable": True}

    @app.post("/demo/break-preflight")
    def break_preflight() -> dict[str, bool]:
        aws.cdk_version = None
        aws.eips = (5, 5)
        return {"broken": True}

    @app.post("/demo/fix-preflight")
    def fix_preflight() -> dict[str, bool]:
        aws.cdk_version = "18"
        aws.eips = (1, 5)
        return {"fixed": True}

    print(f"demo onboarding on http://localhost:{args.port}")
    print("create one:  curl -XPOST localhost:%d/api/onboardings -H 'Authorization: Bearer demo' \\" % args.port)
    print("               -H 'content-type: application/json' \\")
    print("               -d '{\"org_slug\":\"demo-co\",\"org_name\":\"Demo Co\","
          "\"contact_email\":\"ops@demo.example\"}'")
    print("then:        curl -XPOST localhost:%d/demo/run-template   # 'they ran the template'" % args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


class _DemoCodec:
    """Reversible, not secret - the demo has no real external ID to protect.
    Flagged for review: never used outside `demo`."""

    def encrypt(self, plaintext: str) -> bytes:
        return bytes(b ^ 0x42 for b in plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        return bytes(b ^ 0x42 for b in ciphertext).decode()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    onboard = subparsers.add_parser(
        "onboard", help="Register a customer and mint their onboarding link."
    )
    onboard.add_argument("--org-slug", required=True)
    onboard.add_argument("--org-name", required=True)
    onboard.add_argument("--email", required=True)
    onboard.set_defaults(func=_cmd_onboard)

    provision = subparsers.add_parser(
        "provision", help="Detect, preflight and deploy a customer's stack, streaming events."
    )
    provision.add_argument("--org-slug", required=True)
    provision.add_argument("--account-id", help="12-digit AWS account ID; the role ARN is derived")
    provision.add_argument("--region")
    provision.set_defaults(func=_cmd_provision)

    status = subparsers.add_parser("status", help="Registry state and recent stack events.")
    status.add_argument("--org-slug", required=True)
    status.set_defaults(func=_cmd_status)

    serve = subparsers.add_parser("serve", help="Run the customer-facing onboarding app.")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8400)
    serve.set_defaults(func=_cmd_serve)

    demo = subparsers.add_parser(
        "demo", help="Walk the onboarding flow against a fake AWS account (development only)."
    )
    demo.add_argument("--port", type=int, default=8400)
    demo.add_argument("--fail", action="store_true", help="Script the deploy to fail partway.")
    demo.set_defaults(func=_cmd_demo)

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
