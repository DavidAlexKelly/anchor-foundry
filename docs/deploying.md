# Deploying Anchor, and testing that you can

Anchor runs **inside the customer's AWS account**. The vendor runs one thing —
the control plane — which holds the customer registry, serves the onboarding
page, and drives `cdk deploy` into the customer's account through a
cross-account role.

This document is both the runbook and the test procedure, in three levels: the
whole flow with **no AWS at all**, one stack **by hand**, and the real thing
**through the onboarding page**. Do them in that order; each one rules out a
class of problem before the next one costs you fifteen minutes.

---

## Level 1 — the whole onboarding flow, no AWS account

Proves the flow, the copy, the refusals and the hand-off. Proves nothing about
AWS. Takes a minute.

```bash
cd apps/control-plane
CONTROL_PLANE_DATABASE_URL="postgresql://platform:devpass@localhost:5432/platform?sslmode=disable" \
  python -m src.cli demo --port 8400
```

In another shell, create an onboarding and open the link it prints:

```bash
curl -XPOST localhost:8400/api/onboardings \
  -H 'Authorization: Bearer demo' -H 'content-type: application/json' \
  -d '{"org_slug":"demo-co","org_name":"Demo Co","contact_email":"ops@demo.example"}'
```

The demo account starts **un-assumable**, which is what a customer who has not
yet run the template looks like. Drive it from the same shell:

```bash
curl -XPOST localhost:8400/demo/break-preflight   # no CDK bootstrap, no spare Elastic IPs
curl -XPOST localhost:8400/demo/run-template      # "they created the bootstrap stack"
curl -XPOST localhost:8400/demo/fix-preflight
```

Walk the page between each: it should refuse to connect, then connect, then
show two failing checks with the exact remedies, then pass, then deploy with
events tailing and a link to `/setup`. `--fail` scripts the deploy to fail
partway, which is the only convenient way to see the failure screen.

**Flagged: `demo` is development tooling** (`src/onboarding/demo.py`), the same
as `apps/api/dev_server.py`. The production entrypoints cannot reach it.

---

## Level 2 — one real stack, by hand

This is what proves the *infrastructure*. You need an AWS account you are
willing to spend money in, Docker running, and Node.

**1. Build and push the three service images.**

```bash
docker build --platform=linux/amd64 -t $ECR/platform-api:$TAG    apps/api
docker build --platform=linux/amd64 -t $ECR/platform-worker:$TAG apps/worker
docker build --platform=linux/amd64 -f apps/web/Dockerfile -t $ECR/platform-web:$TAG .   # from the repo root
docker push $ECR/platform-api:$TAG && docker push $ECR/platform-worker:$TAG && docker push $ECR/platform-web:$TAG
```

**`--platform=linux/amd64` on the build command is not optional and the
Dockerfile pin does not replace it.** `FROM --platform=…` only selects the base
image for that stage; the exported image still takes the host's architecture.
An arm64 image on Fargate fails before any application code runs, with empty
CloudWatch log streams and a tripped deployment circuit breaker — this build
has been bitten by it twice (`STATUS.md` §20).

**2. Bootstrap CDK in the target account and region**, once ever:

```bash
npx cdk bootstrap aws://<account-id>/<region>
```

**3. Deploy:**

```bash
cd infra/cdk && npm ci
npx cdk deploy \
  -c orgSlug=<slug> \
  -c platformUrl=https://<slug>.example.com \
  -c vendorEcrRegistry=$ECR \
  -c imageTag=$TAG \
  -c region=<region> \
  -c deletionProtection=false      # throwaway stacks only, see below
```

Docker must be running: the migration Lambda bundles `psycopg[binary]` in a
container, and there is deliberately no host-pip fallback (the fallback used to
exist and silently produced a wheel that imported at bundle time and failed at
runtime).

`deletionProtection=false` is for stacks you intend to tear down repeatedly.
With the default (`true`), a failed CREATE cannot roll back past the RDS
instance and you are into the manual teardown runbook — CloudFormation checks
the template's declared property, not the live value.

**4. First account.** A fresh stack has no organisation and no users. Open the
`PlatformDomain` output and go to `/setup`, which creates the first
organisation and its owner. Everyone else arrives by invitation.

**Known blocker:** the owner's password is currently rejected at the Cognito
hosted UI (`ROADMAP.md`, carried forward). Onboarding will hand you a working
`/setup` link and you may still not get past sign-in.

**5. Tear it down** — `python -m src.cli deprovision --org-slug <slug>` for
stacks the registry knows about. Anything deployed by hand is not in the
registry, so it needs the manual sequence: disable RDS deletion protection,
delete the DB instance directly, delete the stack, then empty and delete the
two retained buckets and the OpenSearch domain. The ongoing-cost resources are
RDS, OpenSearch, the NAT gateway and the ALB; a stack left up is not free.

---

## Level 3 — the real thing, through the onboarding page

Two accounts: the vendor's (control plane) and the customer's. This is the path
a real customer takes, and the only one that exercises the AWS calls preflight
and the progress view depend on.

**1. Stand up the vendor side — one command, in your own account:**

```bash
cd apps/control-plane
python -m src.cli init --region eu-west-2 --public-url https://onboard.example.com
```

That creates the KMS key that wraps customers' external IDs, the IAM role their
bootstrap roles will trust, the three ECR repositories, and an S3 bucket holding
`customer-bootstrap.yaml` at a public URL — then prints the exact environment
block for step 2 and the three `docker build` commands.

It is **idempotent**: run it again any time to check the state of an account, or
after pulling a change that adds a permission to the control-plane role (the
role policy and the template are rewritten on every run; nothing else is
touched). Ongoing cost is a KMS key, about a dollar a month.

It deliberately does **not** create the registry database or host the onboarding
page — both are decisions with a bill attached, and it says so rather than
leaving you to find out. Postgres on your own machine is fine for a first
customer.

**Note on credentials:** the customer's bootstrap template trusts a *role*, so
the control plane has to run as the role `init` created. Assume it (a profile
with `role_arn = arn:aws:iam::…:role/anchor-control-plane`, or
`aws sts assume-role`) before running `serve` or `provision`.

**2. Run the control plane** with the environment `init` printed, plus the two
values only you can supply:

```bash
cd apps/control-plane
export CONTROL_PLANE_DATABASE_URL=postgresql://…   # the registry
export PLATFORM_IMAGE_TAG=$TAG CDK_DIR=../../infra/cdk
# …plus the block `init` printed
python -m src.cli serve --port 8400
```

Or as a container: `docker build --platform=linux/amd64 -f apps/control-plane/Dockerfile -t control-plane .`
from the repo root (it copies `infra/cdk` in, because `cdk deploy` is a
subprocess it has to be able to run).

**3. Mint the customer's link:**

```bash
python -m src.cli onboard --org-slug acme --org-name "Acme Logistics" --email ops@acme.example
```

**4. Walk it as the customer.** Open the link in the *customer's* browser,
pick a region, paste the 12-digit account ID, click **Launch in AWS** — the
CloudFormation form arrives with the template, the stack name, the control-plane
role ARN and the external ID already filled in. Create it, come back, click
**Check for the role**.

From there the page detects the role, runs preflight, and — once every check
passes — provisions with CloudFormation's events on screen, ending at a link
to `/setup` in the new deployment.

**Or do the same thing from the operator's side**, which is useful when the
customer cannot:

```bash
python -m src.cli provision --org-slug acme --account-id 123456789012 --region eu-west-2
python -m src.cli status    --org-slug acme
```

Both paths run the same `OnboardingService`, so they preflight identically and
refuse identically.

### What level 3 exercises that levels 1 and 2 do not

Three gateway calls have only ever run against fakes, and this is where they
first meet AWS: `stack_events` (the progress view), `cdk_bootstrap_version`
(the CDK-bootstrap check), and `elastic_ip_headroom` (the NAT gateway check).
Expect the first surprise here, most likely a permission the bootstrap role
does not have. The Service Quotas read already degrades to the AWS default
limit rather than failing the check, on purpose.

---

## Reference: environment variables

| Variable | Used by | What it is |
|---|---|---|
| `CONTROL_PLANE_DATABASE_URL` | control plane | Postgres holding the customer registry. Raw `postgresql://`, **not** `postgresql+psycopg://` |
| `ONBOARDING_KMS_KEY_ID` | control plane | KMS key that wraps each customer's external ID |
| `TEARDOWN_KMS_KEY_ID` | `deprovision` | Same key; separate variable because teardown is a separate tool |
| `CONTROL_PLANE_ROLE_ARN` | onboarding | The vendor role the customer's bootstrap role trusts — created by `cli init` |
| `BOOTSTRAP_TEMPLATE_URL` | onboarding | Public URL of `customer-bootstrap.yaml` — uploaded by `cli init` |
| `CONTROL_PLANE_PUBLIC_URL` | onboarding | Where the onboarding page is reachable; used to build customer links |
| `CONTROL_PLANE_ADMIN_TOKEN` | onboarding | Operator token for `POST /api/onboardings` |
| `VENDOR_ECR_REGISTRY` | provisioning | Registry the customer's ECS tasks pull images from |
| `PLATFORM_IMAGE_TAG` | provisioning | Image tag to deploy; defaults to `latest` |
| `CDK_DIR` | provisioning | Path to `infra/cdk`; defaults to `infra/cdk` |

Local development of the platform itself (Postgres, the two venvs, the API dev
server, the web app) is a different setup — see the repository's `STATUS.md`
for the current dev-environment notes.
