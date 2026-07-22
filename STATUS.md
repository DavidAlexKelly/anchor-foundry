# Anchor — Build Status Summary

_A Palantir Foundry competitor that deploys into the customer's own AWS account. Built from the spec at `foundry_competitor.md`, layer by layer, each layer fully tested before the next began._

**Last updated:** end of this session. Test counts below are from the last full regression run.

---

## How to read this repo

```
platform/
├── apps/
│   ├── api/            FastAPI backend — the vast majority of the logic lives here
│   ├── control-plane/  Provisions/updates customer AWS stacks (registry, CDK runner)
│   ├── worker/         Dagster background jobs (currently: orphaned-schema cleanup)
│   └── web/             Next.js 14 frontend shell
├── infra/cdk/          AWS CDK app — synths the full customer stack (87 resources)
├── packages/
│   ├── db/              SQL migrations (0001–0011) + migration runner
│   └── types/           Shared TypeScript types (API contract, hand-kept in sync)
```

Everything is real, tested, and runnable locally against a live Postgres instance — nothing here is a stub or mock. Every layer below was verified two ways: an automated pytest suite, and a live end-to-end smoke test through the actual HTTP stack (API + Next.js proxy + real bearer tokens).

---

## What's done

### 1. Database schema (migrations 0001–0011)
Full hierarchy (Organisation → Workspace → Project → resources), RLS on every table, audit log, permissions views. Three RLS policy recursion bugs were found and fixed via SECURITY DEFINER helper functions (0008, 0009) — a real, subtle Postgres gotcha (a policy that subselects its own table, or two tables whose policies subselect each other, causes "infinite recursion detected in policy" at runtime, not at migration time).

### 2. Control plane (`apps/control-plane`) — 8/8 tests
Registers customer AWS accounts, assumes roles via external ID, runs CDK deploys, polls CloudFormation to terminal state, supports version pinning for fleet rollouts.

### 3. Infrastructure (`infra/cdk`) — synths clean, 87 resources
VPC, RDS (encrypted, deletion-protected), ElastiCache, OpenSearch, S3, Cognito (spec-exact: MFA optional TOTP-only, 15 min access tokens, no self-signup), 3 ECS services behind an ALB, CloudFront, WAF, GuardDuty, CloudTrail, KMS, 6 scoped IAM roles.

### 4. Auth (Cognito JWT middleware, built into the API)
Full JWT validation pipeline (JWKS caching → exp/aud/iss → sub → DB lookup → context), 401 on any invalid/expired/tampered/wrong-audience token, disabled users locked out immediately (identity cache invalidation).

### 5. Hierarchy API — 25/25 tests (part of the 76 below)
Orgs, workspaces (with isolation anchors: S3 prefix / pg schema / search prefix, provisioned atomically), projects, members, groups, custom permission overrides (including `'none'` as an active revocation), 404-not-403 semantics throughout, full audit trail.

**Key bug fixed:** `INSERT ... RETURNING` under RLS fails when the SELECT policy's helper re-queries the table mid-transaction (rows from the current command aren't visible yet). Fixed by splitting creates into INSERT-then-SELECT rather than weakening any policy.

### 6. Connections (Layer 1) — tests included in the 76
CRUD, credential handling (AWS Secrets Manager only — passwords never touch a response, log, or the `config` jsonb column), connector registry (PostgreSQL fully implemented: test, schema discovery), workspace vs. project scope.

### 7. Datasets — tests included in the 76
Upload (CSV/TSV/Parquet/JSON/JSONL → canonical Parquet via DuckDB), preview, **sandboxed SQL query** (a user can run arbitrary SQL against their dataset with zero filesystem/network access — verified by trying to read `/etc/passwd` and having it fail), export (CSV/Parquet), versioning.

### 8. Connection sync — tests included in the 76
Full-snapshot sync of a source table into the datasets layer, creating or versioning a dataset each run, with a `sync_runs` history table. Wrong passwords, missing tables, and injection-shaped identifiers all fail cleanly rather than 500ing or leaking anything.

### 9. Models — tests included in the 95
SQL transforms over one or more datasets, executed through the same DuckDB sandbox, writing a versioned output dataset. Run history is honest (failed runs show the real DB error; successful runs point at the exact dataset version they produced). **Lineage**: walks the dataset↔model graph in both directions and renders it as Mermaid, per spec.

### 10. Objects / ontology — 19/19 tests (part of the 95 below)
`ontology.py`'s service layer wired into routes (`routes/objects.py`): object types + typed properties and link types (workspace-scoped — the ontology is shared across every project in a workspace), object type sources (project-scoped dataset→type mapping, column-level validation against both the dataset's schema and the type's properties), and the auto-suggestion endpoint (infers a type name, properties, primary key, and title property from a dataset's schema). Delete cascades (type → its link types and sources) rely on the schema's `ON DELETE CASCADE`, matching how the rest of the hierarchy behaves. Role floors are conservative and flagged in the routes module docstring: workspace viewer reads everything; workspace editor+ creates/deletes types and link types (same floor already used for "who can create a project"); project editor+ creates/deletes dataset mappings; suggestion is viewer-level like dataset preview/query since it's read-only.

**Current API regression total: 95/95 passing** (hierarchy 25 + connections 14 + datasets 17 + sync 9 + models 11 + objects 19). Plus control-plane 8/8 and worker 4/4.

### 11. Frontend (`apps/web`)
Next.js 14 App Router, full route tree per the spec's §18 (login via Cognito PKCE + a local dev-token path, workspace grid, project grid, project sidebar with live resource counts), and working UI for every layer above: create workspace/project, invite/manage org members, connections (wizard: pick type → configure → test → save, plus sync), datasets (upload, explore/query dialog, export), models (editor with input-aliasing, run, results), and now **objects** (the project's Objects page: define an object type with a property-row builder, define link types once two types exist, map a project dataset onto a type with a per-column property mapping table, and the flagship "suggest from dataset" flow — pick a dataset, get a suggested type/properties/primary key back, toggle which properties to keep, and create the type + mapping in one action). A from-scratch design system (harbor-ink/paper/teal palette, Archivo/Public Sans/Plex Mono, a "chain line" motif in the sidebar reflecting the org→workspace→project hierarchy) rather than a generic template. Verified live in a browser (Playwright against the real dev API + dev Postgres): type/link/source CRUD, the suggestion flow end-to-end, sidebar badge counts updating on mutation, and viewer role gating (no write controls rendered for a viewer token).

---

## What's not started

- **Object instance materialisation** — syncing mapped datasets into a searchable instance store (OpenSearch in prod); currently `sync_status` on sources honestly reports `never_synced`
- **Actions (write-back)** — Canvas buttons/forms writing back to object instances → source datasets
- **Canvas** (app/BI builder) and **Code** (repo browser) — not started
- **Python model transforms** — explicitly deferred; needs an isolated worker runtime (SQL transforms are fully sandboxed today via DuckDB)
- **Scheduled/large syncs, incremental sync mode** — day-one sync is full-snapshot and inline; cron/upstream triggers and a real cursor-based incremental mode belong to the worker
- **Dockerfiles are written but not build-tested** against the final ontology/objects code

---

## Known rough edges worth knowing about

- The local dev Postgres instance (this sandbox only) needs manual restarting periodically — not a real issue, just a sandbox quirk, documented in the restart command used throughout this session.
- `apps/api/requirements.txt` was missing `duckdb`, `pytz` (DuckDB's own timestamp dependency), and `python-multipart` (needed by FastAPI for file-upload endpoints) — all three are genuine runtime dependencies of code that already existed, not new to this session's work, and the gap would have surfaced as a broken Docker image. Fixed in this session; a `requirements-dev.txt` was added alongside it for the test-only extras (`pytest`, `httpx`).
- Upload/sync/model size caps (50 MB / 200 MB / 5M rows) are conservative day-one limits, each flagged in code comments as the point where the Athena/worker path takes over.
- A handful of spec-silent decisions were made conservatively and flagged in-code with `# Flagged for review` — e.g. who can create a workspace (org admin), who can create a project (workspace editor+), object counts being workspace- vs. project-scoped for `object_types`, and the objects role floors described above.

---

## Running it locally

See `apps/api/dev_server.py` — seeds a dev org with four users at each role level (owner/admin/editor/viewer) and mints tokens for each, printed to stdout, pasteable into the web app's dev sign-in box. Requires local Postgres per the DSNs referenced throughout the codebase's test files.
