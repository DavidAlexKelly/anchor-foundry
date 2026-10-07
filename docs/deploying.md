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

## Python

3.12 or 3.13, and **name the version explicitly when you create the venv**:

```bash
python3.13 -m venv .venv-cp && .venv-cp/bin/pip install -r apps/control-plane/requirements-dev.txt
```

`python3` on macOS is CommandLineTools 3.9, which this codebase does not
support. It does not say so: the venv is created happily and the first failure
is `pip` reporting "no matching distribution" for a pinned wheel — an error
about a *package version*, for a problem with the *interpreter*. If you see a
"from versions:" list that skips the pinned version, check
`.venv-*/bin/python --version` before touching the pin (`STATUS.md` §51).

The service images build on 3.12. The pins sit at the lowest version each
native package publishes wheels for across both supported interpreters, on
linux **and** Apple Silicon. Anything older than 3.12 is untested.

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

**Base images are pinned by digest (§818)**, as `tag@sha256:…`, so two builds
of one commit start from the same base. To take upstream updates, run
`scripts/pin-images.sh`, then build, test and commit. `--check` reports pins
that are behind their tag without changing anything.

**2. Bootstrap CDK in the target account and region**, once ever:

```bash
npx cdk bootstrap aws://<account-id>/<region>
```

**3. Deploy:**

```bash
cd infra/cdk && npm ci
npx cdk deploy \
  -c orgSlug=<slug> \
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

**Invitations, past the first fifty a day.** A stack's user pool sends
invitation and password-reset emails through Cognito's own email unless told
otherwise, and AWS limits that to 50 messages a day per account. The 51st
invitation of a day is refused, and the platform says so and why (§866).
`-c inviteFromEmail=platform@<your domain>` sends them through SES instead.
The address must be verified in SES in the stack's region first, and an SES
account still in the sandbox can only send to verified recipients, so
request production access for a real organisation.

`-c platformUrl=https://<host>` is optional: a further address, beside the
distribution's own, that sign-in may send a viewer back to. Pass it only for a
domain you have pointed at the distribution yourself; the stack does not set
one up (decision 0025, option C).

**4. First account.** A fresh stack has no organisation and no users. Open the
`PlatformUrl` output and go to `/setup`, which creates the first
organisation and its owner. Everyone else arrives by invitation.

**Known blocker, possibly resolved:** the owner's password was rejected at the
Cognito hosted UI (`ROADMAP.md`, carried forward), and the cause was never
confirmed. §849 found one that would do it. The hosted UI sends a viewer back
only to an address on the app client's list. The web app asks for its own
origin, the distribution's address, but the list held only `platformUrl`: on
a control-plane deploy a placeholder, `https://<slug>.platform.example.com`.
The list now holds the distribution's address. If sign-in still fails, the
callback page shows Cognito's own reason (§816).

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

## Moving objects to OpenSearch (§813)

A stack starts with its objects in Postgres. Moving them to the OpenSearch
domain is **backfill, flip, backfill again**. Each step can be run again
safely, because every document's id is derived from its source and key, so
copying an object twice rewrites one document.

1. **Backfill.** Run a one-off task from the API image with the owner role's
   `DATABASE_URL`, plus `OPENSEARCH_ENDPOINT` and `OPENSEARCH_SECRET_ARN`.
   Set those two on this task only:
   `python -m src.services.instance_cutover [--workspace <uuid>]`. It copies
   every workspace's objects, a page at a time, and moves each action run's
   `instance_id` to the copied object's id. It commits one workspace at a
   time and prints JSON counts. It refuses to start without both variables.
2. **Flip.** Redeploy the stack with `-c objectStore=opensearch` (§814).
   The API and the worker get the domain's master secret, and the domain's
   policy lets their basic auth through to fine-grained access control.
   From then on, both read and write the index. Without the flag a stack
   stays on Postgres, so no deploy can switch a stack before its objects
   are copied.
3. **Backfill again**, with the same command, to copy anything written
   between step 1 and the flip.
4. Run `python -m src.services.restore_check` with the same variables. A
   non-empty `stale_index` names the sources to re-sync.

## Taking the load balancer off the internet (decision 0025, §909)

Every stack deployed so far has an internet-facing load balancer with an HTTP
listener open to `0.0.0.0/0`. CloudFront reaches it in plain HTTP, and so can
anyone who learns its name, skipping CloudFront altogether. Decision 0025's
option B moves it behind a CloudFront VPC origin:

```
cdk deploy -c originAccess=vpc ...
```

- The load balancer becomes **internal**, in the private subnets, and its
  listener admits only the VPC's own range. CloudFront's VPC origin reaches it
  from network interfaces inside the VPC.
- The distribution's origin becomes that VPC origin.
- `LISTENER_PROXY_HOPS` goes from 1 to 2. A listener's allowlist then sees the
  sender's own address, the one CloudFront writes, instead of the CloudFront
  edge's (§850).

Without the flag a stack synthesizes exactly as before. The construct check
compares the two (`src/checks/stack-check.ts`). **This has not been deployed
yet.** `internetFacing` cannot change in place, so the first deploy replaces
the load balancer, and the distribution moves to the new one in the same
deployment. Try it on a stack that can be visited before and after:

1. Before: note the load balancer's DNS name (`aws elbv2
   describe-load-balancers`), and that `curl http://<that name>/api/health`
   answers from the internet.
2. Deploy with `-c originAccess=vpc` and wait for CloudFront's deployment to
   finish.
3. After: `https://<distribution>/api/health` answers, and a sign-in completes.
   The old name no longer resolves, and the new load balancer's name resolves
   only to private addresses, so the same `curl` cannot connect.
4. A listener with an allowlist admits a sender listed by its own address.

To roll back, deploy again without the flag. That replaces the load balancer
once more.

## A migration the running version survives (§927)

An update migrates the database first, then replaces the services' tasks a
few at a time, and every old task keeps serving until its replacement is
healthy. For those minutes the previous API and worker run against the new
schema. A migration therefore adds before it removes: a new column is
nullable or defaulted, or filled by a trigger, and a column, table, view or
function the previous version reads is dropped or renamed a release after
the code stopped reading it. `apps/api/tests/test_migration_deploy_safety.py`
refuses, from 0169 on, a drop, a rename, a type change or a `SET NOT NULL`
that has no `-- deploy-safe: <why>` comment just above it.

## Backup and restore (§803)

The stack's three stores are backed up three ways, and a restore is finished
only when they agree again.

| Store | Backed up by | Restored by |
|---|---|---|
| Postgres (RDS) | Automated backups, 14 days (`data-stores.ts`) | Point-in-time restore to a new instance |
| Data bucket (S3) | Versioning on every object; a deleted or replaced file's previous version is kept 30 days (§852) | Nothing, usually - see below |
| OpenSearch | Not backed up: a projection of the datasets (decision 0008) | Re-syncing the object type sources |

**Why the bucket usually needs nothing.** A dataset version is written to its
own key (`.../v{n}/data.parquet`) and never over another, so a database
restored to an earlier point names files the bucket still holds. The exception
is a file deleted since; the bucket's previous version of that key is the
repair. Deleting a workspace or a dataset, a project's included, removes its
files at the next nightly cleanup (§864). Previous versions last 30 days, so a restore to the oldest backup (14
days) leaves two weeks to repair from them. Past that, a deleted file is gone:
that is what deleting it means.

1. Restore the RDS instance to the chosen point in time, as a new instance.
2. Point the stack's `DATABASE_HOST` at it and redeploy the API and worker.
3. From an API task, run the check with the owner role's `DATABASE_URL`:
   `python -m src.services.restore_check [--workspace <uuid>]`. It prints JSON
   and exits 1 when anything needs repairing:
   - `missing_current_files` / `missing_version_files` - restore each key's
     previous S3 version;
   - `index_unchecked` - types whose file is missing: repair the file, then run
     the check again;
   - `stale_index` - each entry names the sources to re-sync.
4. Run the check again until it says `"ok": true`.

**Rehearsed.** `scripts/rehearse-restore.sh` does the database half against
any Postgres it can reach: it dumps it, restores the dump into a new database
beside it, and runs the same check against the copy. Against the development
database (731 MB, 11,017 workspaces, 66,281 datasets) the dump and restore took
about 40 seconds. The check over the whole database took about a minute, and
over its largest workspace (8,460 datasets) about 5 seconds. In that workspace
it found three datasets whose files had been deleted, which it reported as
missing files.



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
| `S3_DATA_BUCKET` | platform API and worker | The data bucket. A stack sets it in every service's environment. Unset, both fall back to development storage (local disk, and on the API in-memory connection secrets); on ECS, where that fallback would be a disk nothing else reads, both now refuse to start (§844). The worker read `DATA_BUCKET` until §844, which nothing set |
| `COGNITO_DOMAIN` | platform API | The hosted UI's address, which the API hands to the sign-in page at `GET /api/auth/config` along with `COGNITO_CLIENT_ID` (§851). A stack sets both. The web image is the same for every stack, so it cannot carry them: `NEXT_PUBLIC_COGNITO_*` are written into a build, and remain only for development against a real pool. Unset, the sign-in page says sign-in is not configured. The API also renews a session at it, with the refresh token, when the fifteen-minute access token runs out (§859); unset, a session ends with its access token |
| `STORAGE_CACHE_MAX_BYTES` | platform API and worker | How much of a task's disk the local copies of S3 objects may hold before the least recently used idle ones are deleted; default 4 GiB of Fargate's 20 (§869). Copies in use in the last fifteen minutes are kept regardless |
| `DUCKDB_MEMORY_LIMIT`, `DUCKDB_THREADS` | platform API and worker | What one DuckDB connection may hold, as DuckDB writes it (`512MiB`), and how many threads it may use; past the limit it spills to the task's temporary directory (§875). A stack sets 512 MiB and two threads on both, and sizes each task for two such operations at once (`infra/cdk/src/constructs/services.ts`). Unset, as in development, DuckDB keeps its own defaults: 80% of the memory it can see, and a thread per core |
| `DUCKDB_SLOTS` | platform API | How many DuckDB operations one API process runs at once (§911). A stack sets 2, what the task's memory is sized for; one past it waits up to `DUCKDB_SLOT_WAIT` seconds (60) for a slot, then gets a 503 with `Retry-After`. Unset, as in development, nothing is limited |
| `BOOTSTRAP_TOKEN_SHA256` | platform API | SHA-256, in hex, of the token the control plane creates the first owner with (§886). Set, `POST /api/bootstrap/first-owner` refuses anyone without that token, so a new stack cannot be claimed by whoever finds its address first. A stack sets it from the `bootstrapTokenHash` context the provisioner passes on every deploy. Unset, as in development, the setup page creates the first owner as before |
| `PLATFORM_PUBLIC_URL` | platform API | The platform's public address, for an outbound application's OAuth callback (§752) and a listener's endpoint (§849). A stack sets it to its distribution's address, `https://<id>.cloudfront.net` (§849). Unset, as in development, a source using the authorization-code grant is refused with a sentence naming it, and a listener's endpoint uses the request's own address: behind the load balancer that is plain HTTP |
| `OIDC_ISSUER`, `OIDC_SIGNING_KEY`, `OIDC_SIGNING_KEY_SECRET` | platform API and worker | The platform as an OIDC identity provider for source systems (§599): the issuer URL (`https://<host>/api/oidc`), and the signing key, the same for every task. A stack sets the issuer to its distribution's address and `OIDC_SIGNING_KEY_SECRET` to a secret under `anchor/connections/` (§871). The first API task to need a key makes an RSA key and stores it there, and every other task and the worker sign with that one. `OIDC_SIGNING_KEY`, an RSA private key in PEM, takes precedence when given. With neither, a source configured for OIDC is refused with a sentence naming them |
| `LOG_LEVEL` | platform API | Level for the API's structured `anchor.*` log lines; defaults to `INFO` (§802) |
| `OPENSEARCH_ENDPOINT`, `OPENSEARCH_SECRET_ARN` | platform API and worker | Both set: objects are read and written in OpenSearch, the secret holding `{"username", "password"}`. Either unset: Postgres. The two services read the pair the same way, so they cannot disagree about where objects live (§811). A stack sets the endpoint always, and the secret only when deployed with `-c objectStore=opensearch` (§814) |
| `STATEMENT_TIMEOUT_MS` | platform API | The longest one SQL statement may run before Postgres cancels it and the request gets a 503; defaults to `30000`, CloudFront's origin timeout, and `0` turns it off. The operator commands (`instance_cutover`, `restore_check`) default it to `0` themselves (§833) |
| `UVICORN_TIMEOUT_KEEP_ALIVE`, `KEEP_ALIVE_TIMEOUT` | platform API, web | How long the API (seconds) and the web server (milliseconds) keep an idle connection: 90 s on a stack, past the load balancer's 75, which is past CloudFront's 60-second wait for an answer (§918; `stack-check.ts` holds the order). Their default of 5 s let the load balancer send a request down a connection the server had just closed, a 502 for nothing |
| `LISTENER_EVENT_RETENTION_DAYS` | worker | How long a listener's event stays in the database once it is archived into the listener's dataset (§915; db 0168). 7 by default; at least 1. An event not yet archived is kept however old it is |
| `METRICS_TOKEN` | platform API | When set, `/api/metrics` requires `Authorization: Bearer <token>`. Unset, it is open in development like `/api/health` (§802), and on a stack it is a 404 (§884): through CloudFront it was anyone's to read, and nothing on a stack scrapes it, since its alarms count log lines (§815) |

**What the API emits (§802).** Every response carries `X-Request-ID` (the
caller's own when it is a safe id, otherwise a new one). Each request writes one
JSON line to stderr on `anchor.access` with the request id, method, **route
template** (never the raw path or query), status and duration. An unhandled
error writes its traceback on `anchor.error` under the same id, and its 500 body
quotes the id. `/api/metrics` serves Prometheus text: requests by method, route
and status class, a latency histogram per route, and a count of unhandled
errors. The counters live in the process, and the image runs one process per
task, so scrape each task.

**What a stack alarms on (§815).** The containers' lines already go to the
stack's CloudWatch log group. Metric filters there count the API's
`anchor.access` and `anchor.error` lines into the `Anchor/Platform`
namespace, so no scraper is needed. Thirteen alarms report, when they fire
and when they clear, to one SNS topic (the `AlarmTopicArn` stack output);
`infra/cdk/src/checks/monitoring-check.ts` counts them:

- API 5xx over 5% of requests for ten minutes, once there are 20 requests;
- any unhandled error;
- API p95 latency over two seconds for fifteen minutes;
- the API, the worker or the web server with no running task for three
  minutes (the web server's since §925);
- three or more of the worker's scheduled runs failing in five minutes (§889);
- an API or a web target failing the load balancer's health check for three
  minutes;
- five or more pages failing in people's browsers in five minutes, each a
  line on `anchor.client_error` with its path, error and who saw it (§926);
- database storage under 2 GiB, database CPU over 80% for fifteen minutes,
  or more than four in five of its connections held for ten (§925).

The worker has no load balancer in front of it; ECS itself replaces a worker
whose Dagster daemon stops beating (§924), and `WorkerNotRunning` fires if
none comes back.

Deploy with `-c alarmEmail=ops@example.com` to subscribe an address; the
subscription waits for its confirmation email. Without it, attach whatever
pages people to the topic.

Local development of the platform itself (Postgres, the two venvs, the API dev
server, the web app) is a different setup — see the repository's `STATUS.md`
for the current dev-environment notes.
