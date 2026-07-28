# Anchor — Roadmap

_Companion to `STATUS.md` (what's built, in detail) — this document is about what's next, and why, ordered by what actually blocks the next thing. Written after §20: the first fully green real AWS deploy. Re-read `STATUS.md` before treating anything here as stale; update this file in the same session as any STATUS.md entry that closes or reshapes an item below._

## How to use this document

Each phase assumes the ones before it are done. Within a phase, items aren't strictly ordered unless a dependency is called out. "Why" is included deliberately — the point of this document is to make the *reasoning* durable, the same way STATUS.md makes bug root-causes durable, not just a checklist that rots the moment priorities shift.

---

## Phase 0 — Close out this session's deploy (immediate)

The dry-run stack is green for the first time, but the loop isn't actually closed yet.

1. **Diagnose and fix the first-login failure.** §20 ends with the owner's password being rejected at login, root cause unconfirmed. Reproduce with the actual Cognito error surfaced (today the frontend swallows the specific reason — fix that regardless, see Phase 1). Likely candidates: the 12-char/upper/lower/digit/symbol policy (`auth.ts`), or Cognito's requirement that a first login after `AdminCreateUser` set a genuinely new password, not reuse the temporary one.
2. **Walk the full golden path once, end to end, on the real deployed stack**: `/setup` → first owner login → create workspace → create project → add a PostgreSQL connection → sync a table → build a model → define an object type → sync instances → create an action → build a Canvas app → publish it. Every one of these has been verified against local dev Postgres; none has been verified against a real deployed stack behind real ALB/CloudFront/Cognito. This is the actual point of doing a real deploy — finish it.
3. **Clean up the 21 orphaned Cognito User Pools** (§20) left behind by failed dry-run attempts. One-off manual cleanup now; Phase 1 below prevents recurrence.
4. **Decide what happens to this dry-run stack.** Either keep it as a standing integration environment (in which case it should be re-provisioned *through* `Provisioner`/the registry, not by hand — see Phase 1, item 4) or tear it down with the `Deprovisioner` CLI once golden-path verification is done, to stop paying for NAT/RDS/OpenSearch/ALB.

---

## Phase 1 — Make the deploy pipeline trustworthy

This is the highest-priority phase after Phase 0, ahead of any new product feature. The last two sessions' entire cost — nine bugs in §17, three more corrections in §18/§19, two more in §20 — came from the fact that **nothing about deploying this platform is automated or repeatable today**. Every image build, every `cdk deploy`, every teardown was a human typing commands by hand, and several of the bugs found (mutable `:latest` tags, a missing `--platform` flag on a build command, images that predate a Dockerfile fix) are exactly the class of mistake automation exists to make structurally impossible. Building product features on top of an unreliable deploy path just means the next feature inherits the same fragility.

1. **CI: automated image build + push.** GitHub Actions (or CodeBuild) that builds `apps/api`, `apps/worker`, `apps/web` on every merge to `main`, always with `--platform=linux/amd64` baked into the *build step itself* (not left to whoever runs the command by hand — §20's tenth bug happened precisely because a human-run command silently lacked a flag), tags images with the commit SHA (never `:latest` — see item 2), and pushes to ECR.
2. **Stop using mutable tags anywhere in the deploy path.** Both bugs in §20's "eleventh bug" and the recurring service-image architecture bugs trace back to something resolving differently on a later day than it did before, with no code change. Service images should be tagged and referenced by commit SHA (`services.ts`'s `imageTag` prop already exists for exactly this — audit that it's actually wired to something other than `latest` end-to-end). The migration bundling Dockerfile's base image is now pinned to a digest (§20) — audit every other `DockerImage.fromBuild`/`fromRegistry` reference in `infra/cdk` for the same class of risk.
3. **Automate custom-domain + ACM certificate attachment.** `services.ts` already anticipates this ("the control plane attaches the ACM certificate + HTTPS listener once the customer subdomain is issued, spec §7") but nothing does it yet — today's HTTP-only listener and the CloudFront-domain workaround (§20) are placeholders, not the intended real path. This blocks every real customer's actual production URL from ever being HTTPS-native through their own domain rather than a raw CloudFront hostname.
4. **Retire "deploy by hand with personal credentials" for anything but throwaway local testing.** Every dry-run stack this build has ever deployed (§17 through §20) went through direct `cdk deploy` with a personal AWS profile, never through `Provisioner`/`StackRegistry`. That means the actual production code path — the one real customers will go through — has *never once been exercised against a live account*. The `Deprovisioner` built in §19 has never torn down a stack it didn't provision either. Before onboarding a real customer, run at least one full provision → verify → deprovision cycle through the actual control-plane code, not a human's `cdk deploy` invocation.
5. **Add missing CDK outputs**: `UserPoolDomain` (deterministic today from `orgSlug`, but forcing an AWS CLI round-trip to confirm it and get the client ID is exactly the kind of manual step this phase exists to remove).
6. **Observability**: CloudWatch dashboards and alarms for the things that actually paged someone at a real company — RDS storage/CPU/connection count, ECS task health and restart count, ALB 5xx rate and target health, OpenSearch cluster status. Structured logging aggregation (today: three independent `LogGroup`s with no cross-service correlation ID). An error-tracking integration (Sentry or equivalent) for the API and worker.
7. **Backup/DR policy.** RDS automated backups exist by default at some retention, but there's no documented restore drill, no cross-region snapshot policy, and no answer yet to "a customer's RDS instance is gone, what do we actually do." Write the runbook before it's needed live.
8. **Secrets rotation.** RDS master and `platform_app` passwords, Cognito — none have a rotation policy today; `Boto3Gateway`'s secrets are generated once at provision time and never revisited.

---

## Phase 2 — Close the explicit day-one gaps (`STATUS.md`'s "What's not started")

These are gaps already identified and flagged in-code, not new discoveries — this phase is about actually doing them, roughly in the order they unblock the most:

1. **Wire the OpenSearch instance store in.** §14 built a complete, real `OpenSearchInstanceStore` (index-per-workspace, matching the existing `search_prefix` isolation anchor) but `routes/objects.py`/`services/instances.py` still call the Postgres-backed functions directly. This is arguably the single most important item in this phase: a Foundry-style Ontology's core promise is fast, flexible search/filter across potentially millions of object instances, and a Postgres table (however RLS-correct) is not that at scale. Cutting over is flagged as "a real service-layer change deserving its own review," not a one-line swap — budget for it as such.
2. **"Code" — the repo browser.** Listed as "not started" with no further detail in STATUS.md; this is the third pillar of the original three-pillar vision this build has consistently tracked (Data → Ontology → Code — with Canvas as the applied/BI layer on top of Ontology). Foundry's own "Code Repositories" is git-backed, versioned, and tightly integrated with the pipeline/transform layer (today's SQL/Python models). Scope this deliberately narrow for a first cut: a git-backed store for model/transform definitions with real version history, not a general-purpose IDE.
3. **Canvas: chart/BI widgets.** The palette today is Container/Text/Dataset table/Action form — explicitly "no chart/visualization widget yet (spec's 'BI' half of 'app/BI builder')." This is a natural next widget given the resolver/widget pattern already exists; needs a charting library decision and a data-binding contract (likely reusing the same dataset-preview endpoint the table widget already uses, aggregated client-side or via a new endpoint for larger datasets).
4. **Canvas: cross-widget interactivity + drag-reorder.** No widget can filter another yet (e.g., a table row selection driving a chart), and placed widgets can't be reordered without removing/re-adding. Both are "straightforward additions to the same resolver/widget pattern, just not built yet" per STATUS.md — real scope, not a rewrite.
5. **Published Canvas apps navigation.** The read API (`GET .../published-canvas-apps`) exists and is tested; no page lists it. A workspace member today can only reach a published app via a direct URL. Needs a nav entry + list page.
6. **Upstream model trigger mode.** `trigger_mode` accepts `upstream` at the schema level but nothing fires a model when its input dataset changes — only `manual` and `cron` actually run something. This is a core "pipeline" feature (a DAG that actually propagates), not just a nice-to-have; likely the same discover-then-verify worker pattern already used for cron/sync discovery, triggered off `dataset_versions` inserts instead of a schedule.
7. **Write-through to external connection sources.** Actions write back to this platform's own dataset copy only; connectors don't support write operations. Real bidirectional sync (writing a value back to the customer's actual source Postgres table, say) is a materially bigger scope than the read-only connectors today — needs its own design pass on conflict resolution, permissions, and failure semantics before implementation starts.

---

## Phase 3 — Broaden data connectivity

Today exactly one connector type is fully implemented: PostgreSQL (test + schema discovery + sync). A platform whose entire value proposition is "connect your data" needs more than one source type before it's credible to a real prospect.

1. **Additional read connectors**, roughly in likely-customer-demand order: MySQL (near-identical shape to the existing Postgres connector — good first addition to prove the connector abstraction generalizes), flat files on S3/object storage (CSV/Parquet already supported for upload — extending to "point at an S3 prefix" is a smaller lift than a new database driver), a cloud warehouse (Snowflake or BigQuery — whichever matches actual pipeline conversations first), and a generic REST API connector (auth handling varies enough per API that this is likely worth deferring until a concrete need names the specific API).
2. **Streaming sources** (Kafka/Kinesis) — likely out of scope until there's a concrete customer need; full-snapshot and cursor-incremental sync cover the batch case well today, and streaming is a different architecture, not an extension of the existing sync worker.
3. **The large-dataset path referenced in code comments doesn't exist yet.** Upload/sync/model size caps (50 MB / 200 MB / 5M rows) are flagged in comments as "the point where the Athena/worker path takes over" — `workerTaskRole` already has `athena:StartQueryExecution` IAM permissions provisioned (`services.ts`), but nothing in `apps/worker` or `apps/api` actually calls Athena anywhere today. Either build the Athena path for real before a customer's dataset actually hits the cap and gets an opaque rejection, or remove the IAM grant and the comment until it's real — don't leave a promise in a comment with no code behind it.
4. **Write-back connectors** — tracked here for connectivity breadth, same underlying work as Phase 2 item 7.

---

## Phase 4 — Access control & governance maturity

Today's model is Postgres RLS at the org/workspace/project boundary, plus role floors (viewer/editor/admin/owner). That's solid and already caught real bugs (§0008/0009/0015's RLS-reads-RLS-table class). What's missing before this is credible to an enterprise buyer — which anyone building a literal Foundry competitor should assume as the eventual customer profile:

1. **SSO/SAML federation into Cognito.** Enterprise customers standardize on an IdP (Okta, Azure AD, etc.); Cognito supports SAML/OIDC federation natively, but nothing in `auth.ts` sets it up today — self-signup is already disabled and invite-only, which is the right starting posture, but real enterprises will ask for IdP federation before rolling this out past initial pilots.
2. **Audit log surface.** An audit trail is written to the database throughout (per §5, "full audit trail"), but there's no UI to read it — grepping the frontend for "audit" turns up one unrelated logout comment, nothing else. A real audit log viewer (who did what, when, filterable by org/workspace/project) is table stakes for any enterprise data platform, and the data's apparently already there.
3. **Finer-grained classification/markings.** Foundry's actual enterprise differentiator includes data classification tags that gate access below the project level. This build's RLS boundary stops at project; whether finer-grained markings are actually needed should be validated against a real prospect's requirements before building it speculatively — flagged here as a known gap, not a committed scope.

---

## Phase 5 — Collaboration & platform polish

1. **Global search.** No cross-entity search exists today (confirmed: no "global search"/"search bar" pattern anywhere in the frontend) — finding a workspace, project, dataset, or object type means already knowing where to look. This becomes increasingly necessary as any single organisation's usage grows past a handful of workspaces.
2. **Notifications/comments.** Nothing in this build today notifies a user of anything (an invite, a sync failure, a shared Canvas app) beyond what's visible if they happen to load the right page. Even a minimal in-app notification feed (sync failed, action executed, invited to a workspace) would close a real gap.
3. **A real internal operator console.** The control plane is CLI-only (`python -m src.cli deprovision ...`, plus whatever `Provisioner` entrypoint exists). Once more than a couple of real customer stacks exist, an internal dashboard (fleet health, per-customer version, provision/deprovision history, that 21-orphaned-pool problem visible at a glance instead of discovered by `list-user-pools`) becomes necessary operational infrastructure, not a nice-to-have.

---

## Phase 6 — Scale & enterprise readiness

Longer-horizon, sequenced last because none of it matters until Phases 0–1 make the platform reliably deployable and Phases 2–4 make it feature-complete enough to run a real pilot:

1. **Multi-region support**, once a real customer actually needs data residency outside `eu-north-1`/whatever region a given deploy lands in.
2. **Usage-based billing/metering**, once there's a pricing model to meter against.
3. **Formal compliance readiness** (SOC 2 or equivalent) — audit logging completeness (ties to Phase 4 item 2), a documented access-review process, encryption-at-rest/in-transit review (mostly already true by default via RDS/S3/Secrets Manager, but never formally reviewed as a compliance artifact).
4. **Load/performance testing** against realistic data volumes — every layer of this build has been correctness-tested (382+ passing tests across API/worker/control-plane as of §19) but never load-tested; the OpenSearch cutover in Phase 2 item 1 is the first place this will actually matter.

---

## What this roadmap deliberately leaves out

Anything not listed above and not already in STATUS.md's "What's not started" is out of scope for this document, not forgotten — this is a living document; add to it deliberately when a real gap is found, the same way STATUS.md's corrections are written in rather than silently fixed. If Phase 0 or Phase 1 turns up a new structural bug (as every real deploy so far has), record it in STATUS.md first, then reassess whether it changes this roadmap's ordering.
