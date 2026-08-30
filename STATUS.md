# Anchor - Build Status Summary

_A Palantir Foundry competitor that deploys into the customer's own AWS account. Built from the spec at `foundry_competitor.md`, layer by layer, each layer fully tested before the next began._

**Last updated:** end of this session (phase-1 roadmap items, now archived at `docs/roadmap-phase-1-pillars.md` — every "`ROADMAP.md` section N item M" reference below means that document, not the phase-2 plan that now occupies `ROADMAP.md`: Connections 1–3, 5, 6, 7; Datasets 1–3, 5, 6; Models 1–3, 5, 7; Objects 1–5; Canvas 1–4, 6; Code 1–4; Deployment 1–4 + the vendor bootstrap — see §21–§65). Test counts below are from the last full regression run.

---

## How to read this repo

```
platform/
├── apps/
│   ├── api/            FastAPI backend - the vast majority of the logic lives here
│   ├── control-plane/  Provisions/updates customer AWS stacks (registry, CDK runner)
│   ├── worker/         Dagster background jobs (currently: orphaned-schema cleanup)
│   └── web/             Next.js 14 frontend shell
├── infra/cdk/          AWS CDK app - synths the full customer stack (87 resources)
├── packages/
│   ├── db/              SQL migrations (0001–0026) + migration runner
│   └── types/           Shared TypeScript types (API contract, hand-kept in sync)
```

Everything is real, tested, and runnable locally against a live Postgres instance - nothing here is a stub or mock. Every layer below was verified two ways: an automated pytest suite, and a live end-to-end smoke test through the actual HTTP stack (API + Next.js proxy + real bearer tokens).

---

## What's done

### 1. Database schema (migrations 0001–0033)
Full hierarchy (Organisation → Workspace → Project → resources), RLS on every table, audit log, permissions views. Three RLS policy recursion bugs were found and fixed via SECURITY DEFINER helper functions (0008, 0009) - a real, subtle Postgres gotcha (a policy that subselects its own table, or two tables whose policies subselect each other, causes "infinite recursion detected in policy" at runtime, not at migration time).

### 2. Control plane (`apps/control-plane`) - 52/52 tests
Registers customer AWS accounts, assumes roles via external ID, runs CDK deploys, polls CloudFormation to terminal state, supports version pinning for fleet rollouts, tears a stack down (§19), and since §48 serves the customer-facing onboarding flow that connects an account in the first place.

### 3. Infrastructure (`infra/cdk`) - synths clean, 87 resources
VPC, RDS (encrypted, deletion-protected), ElastiCache, OpenSearch, S3, Cognito (spec-exact: MFA optional TOTP-only, 15 min access tokens, no self-signup), 3 ECS services behind an ALB, CloudFront, WAF, GuardDuty, CloudTrail, KMS, 6 scoped IAM roles.

### 4. Auth (Cognito JWT middleware, built into the API)
Full JWT validation pipeline (JWKS caching → exp/aud/iss → sub → DB lookup → context), 401 on any invalid/expired/tampered/wrong-audience token, disabled users locked out immediately (identity cache invalidation).

### 5. Hierarchy API - 25/25 tests (part of the total below)
Orgs, workspaces (with isolation anchors: S3 prefix / pg schema / search prefix, provisioned atomically), projects, members, groups, custom permission overrides (including `'none'` as an active revocation), 404-not-403 semantics throughout, full audit trail.

**Key bug fixed:** `INSERT ... RETURNING` under RLS fails when the SELECT policy's helper re-queries the table mid-transaction (rows from the current command aren't visible yet). Fixed by splitting creates into INSERT-then-SELECT rather than weakening any policy.

### 6. Connections (Layer 1) - tests included in the total below
CRUD, credential handling (AWS Secrets Manager only - passwords never touch a response, log, or the `config` jsonb column), connector registry (PostgreSQL fully implemented: test, schema discovery), workspace vs. project scope. **Superseded in part by §21–§24**: the registry now covers the extract path too (`snapshot`/`max_cursor_value`, dispatched on `source_type`) and carries four source types — PostgreSQL, MySQL/MariaDB, S3/object storage, and generic REST/HTTP JSON.

### 7. Datasets - tests included in the total below
Upload (CSV/TSV/Parquet/JSON/JSONL → canonical Parquet via DuckDB), preview, **sandboxed SQL query** (a user can run arbitrary SQL against their dataset with zero filesystem/network access - verified by trying to read `/etc/passwd` and having it fail), export (CSV/Parquet), versioning.

### 8. Connection sync - tests included in the total below
Full-snapshot sync of a source table into the datasets layer, creating or versioning a dataset each run, with a `sync_runs` history table. Wrong passwords, missing tables, and injection-shaped identifiers all fail cleanly rather than 500ing or leaking anything.

### 9. Models - tests included in the total below
SQL transforms over one or more datasets, executed through the same DuckDB sandbox, writing a versioned output dataset. Run history is honest (failed runs show the real DB error; successful runs point at the exact dataset version they produced — and, since §32, at the exact definition that produced it). **Lineage**: walks the dataset↔model graph in both directions and renders it as Mermaid, per spec — that is the text export; §28 adds the whole-project graph and §33 the interactive single-node view built on it.

### 10. Objects / ontology - 19/19 tests (part of the 102 below)
`ontology.py`'s service layer wired into routes (`routes/objects.py`): object types + typed properties and link types (workspace-scoped - the ontology is shared across every project in a workspace), object type sources (project-scoped dataset→type mapping, column-level validation against both the dataset's schema and the type's properties), and the auto-suggestion endpoint (infers a type name, properties, primary key, and title property from a dataset's schema). Delete cascades (type → its link types and sources) rely on the schema's `ON DELETE CASCADE`, matching how the rest of the hierarchy behaves. Role floors are conservative and flagged in the routes module docstring: workspace viewer reads everything; workspace editor+ creates/deletes types and link types (same floor already used for "who can create a project"); project editor+ creates/deletes dataset mappings; suggestion is viewer-level like dataset preview/query since it's read-only.

### 11. Object instance materialisation - 7/7 tests (part of the 102 below)
Migration 0012 adds `object_instances` - a Postgres-backed instance store (`services/instances.py`) behind the same shape the production OpenSearch store will have. **Flagged as architecturally significant**: this is not a drop-in gateway swap like storage (S3/local disk) or secrets (Secrets Manager/in-memory) - Postgres RLS gives free per-row workspace isolation that a search index doesn't, so a real OpenSearch-backed store needs its own access-control design; that swap is out of scope here and called out in both the migration and the service module's docstrings.

Sync (`POST .../object-type-sources/{id}/sync`, project editor+) reads the mapped dataset's current Parquet file through the same DuckDB path datasets/models already use, extracts the primary key + mapped columns, and upserts one instance per source row keyed on `(source_id, primary_key)`. A resync also removes any instance whose primary key no longer appears in the current data (mark-and-sweep on a per-sync timestamp), so the store never lags behind upstream deletes - verified by a same-data resync test (idempotent, zero removed) and cascade-on-delete-source test (deleting the mapping empties its instances). Browsing is workspace-scoped and paginated: `GET .../object-types/{id}/instances` (list) and `.../instances/{id}` (detail), both viewer-level like the rest of the read surface.

### 12. Actions (write-back) - 11/11 tests (part of the 113 below)
Migration 0013 adds `action_types` (workspace-scoped, same shape/isolation pattern as `link_types`: a named action on an object type naming a subset of its properties as writable, validated against the type's real properties at create time) and `action_runs` (history, same pattern as `sync_runs`/`model_runs`). Execution (`POST .../projects/{id}/actions/{action_type_id}/execute`, project editor+ - write-back always targets one instance, whose data lives in exactly one project) validates the submitted values three ways: on the action's editable list, type-consistent with the property's declared type, and actually mapped to a dataset column on *this instance's specific source* (an object type is workspace-shared, but which of its properties have a real write-back target depends on the project-specific source doing the mapping - checked at execute time, not at action-definition time, since that's the only point both facts are known together).

A successful execute does two things, both versioned rather than silently overwritten: updates the instance's `object_instances.properties`, and writes the corresponding row in the mapped dataset's Parquet file, producing a new `dataset_versions` row (`produced_by_kind='action'`) via a new `datasets.add_version()` helper - the simpler in-place case alongside the existing create-or-version-by-slug logic uploads/sync/models each already have. **Flagged as architecturally significant, scope**: write-back targets this platform's own dataset copy, not the customer's original external system - connectors in this build only support test/discover, not write, so true write-through to a live external table is out of scope and called out in both the migration and `services/actions.py`'s docstring.

### 13. Frontend (`apps/web`)
Next.js 14 App Router, full route tree per the spec's §18 (login via Cognito PKCE + a local dev-token path, workspace grid, project grid, project sidebar with live resource counts), and working UI for every layer above: create workspace/project, invite/manage org members, connections (wizard: pick type → configure → test → save, plus sync), datasets (upload, explore/query dialog, export), models (editor with input-aliasing, run, results), and **objects** (the project's Objects page: define an object type with a property-row builder, define link types once two types exist, map a project dataset onto a type with a per-column property mapping table, and the flagship "suggest from dataset" flow - pick a dataset, get a suggested type/properties/primary key back, toggle which properties to keep, and create the type + mapping in one action; each mapping row has a "Sync now" button showing live status/last-synced-at/error and a "Browse" link per object type opening a paginated instance table with dynamic property columns). An **Actions** section on the Objects page defines write-back actions (pick an object type, name it, check which properties it can write), and the instance browser gained an "Edit" button per row (only rendered when at least one action exists for that type) opening a small form pre-filled with current values - submitting calls the action, and both the instance row and the underlying dataset version bump in place. A from-scratch design system (harbor-ink/paper/teal palette, Archivo/Public Sans/Plex Mono, a "chain line" motif in the sidebar reflecting the org→workspace→project hierarchy) rather than a generic template. Verified live in a browser (Playwright against the real dev API + dev Postgres): type/link/source CRUD, the suggestion flow end-to-end, sync → instance browsing end-to-end (with real synced rows), define-action → edit-instance → dataset-version-bump end-to-end, sidebar badge counts updating on mutation, and viewer role gating (no write/sync/edit controls rendered for a viewer token, read views unaffected).

### 14. Python model transforms, scheduled/incremental sync, production OpenSearch design (this session)

**Python model transforms**: models gained a `language` column (`sql`/`python`, set at creation, immutable after - the two languages have different input contracts). SQL still runs synchronously inline through the existing DuckDB sandbox; a Python run is left `queued` for the worker and the API returns immediately (`RunResult.status: "queued" | "succeeded" | "failed"`), since a real process boundary is not something DuckDB can give a Python transform. The worker (`apps/worker/src/anchor_worker/python_sandbox.py`) executes user code as a **subprocess** - explicitly documented as process-level isolation, not a hard multi-tenant security boundary - with `RLIMIT_CPU`/`RLIMIT_AS`, a wall-clock timeout, a stripped env, and an isolated cwd/HOME, so a script can't read the caller's filesystem by relative path. Inputs load as named pandas DataFrames; the contract is a variable named `output`. Real production hardening (gVisor/Firecracker/network-denied container) is flagged as out of scope for this build.

**Cron scheduling**: models gained `trigger_mode` (`manual`/`cron`/`upstream`) and `cron_schedule`; setting cron computes `next_run_at` via `croniter` (a `NULL` value means "due immediately" - a deliberate, simple bootstrap rule). The worker discovers due cron models and queued runs the same way it discovers orphaned schemas (db 0010): a `SECURITY DEFINER` function enumerates candidates across every workspace (RLS-blind, since a workspace-scoped connection can't discover work in workspaces it doesn't already know about), then the worker opens one `rls_worker_for_workspace`-scoped connection per candidate to re-verify and act - the discovery bypass is never trusted for the mutation itself. (`upstream` was accepted here but fired nothing until §27, which reuses this exact machinery with a different due-ness test.)

**Scheduled/incremental sync**: rather than a new table, the existing `connections` row (which already carried `sync_mode`/`sync_schedule` since db 0003) gained the columns a schedule needs to be self-contained: `sync_source_schema/table`, `sync_dataset_name/id`, `sync_primary_key_column`, `sync_cursor_column`, `sync_last_cursor_value`, `sync_next_run_at` (db 0014) - one connection carries at most one managed scheduled/incremental target, flagged as a day-one limitation. Incremental mode pulls only rows past the stored cursor (`psycopg.sql`-composed, never string-interpolated) and upserts them into the existing dataset by primary key (anti-join + union in DuckDB) rather than replacing it wholesale; full mode still replaces the dataset each run. New API endpoints (`GET/PUT/DELETE .../scheduled-sync`, `POST .../scheduled-sync/run`) let a connection's schedule be viewed, set, cleared (target survives, only the cron stops), and run on demand - "run now" executes the identical steps the worker's cron firing does. **A real bug found and fixed along the way**: a scheduled incremental sync that finds zero new rows since the last cursor (the ordinary steady state between source writes) produced an empty CSV, which gave DuckDB nothing to infer column types from - it defaulted every column to VARCHAR and then failed comparing against the existing (correctly-typed) dataset in the merge's primary-key anti-join. Fixed in both the worker and the API by skipping the merge entirely when nothing is new, rather than writing a needless version. A second bug: the worker's per-connection try/except only caught `DatasetEngineError`/`LookupError`, so an ordinary driver error (missing table, bad credentials, a missing local Parquet file) on one connection crashed the whole batch instead of being recorded as that connection's failed run - now caught and isolated per connection, matching the API's own `snapshot_source_table` error translation.

**Frontend**: the Models page gained a language selector (locked after creation, with language-appropriate code hints) and a schedule editor (manual/cron + cron expression) on the edit dialog, a schedule chip + next-run time in the list, and a "queued" state in the run result panel distinct from success/failure. The Connections page gained a "Scheduled sync" dialog per connection: mode/table/dataset-name/primary-key/cursor pickers backed by the same schema-discovery endpoint the ad hoc sync dialog uses, a status card (mode, schedule, next run, last cursor, last result), "Run now", and "Stop scheduling" (clears the cron, keeps the target so manual runs keep working). Verified end-to-end in a live browser (dev API + dev Postgres): created a Python model, ran it once queued, ran it via the worker job directly, edited it onto a cron schedule and watched `next_run_at` populate; added a real Postgres connection, set an incremental schedule against a live table, ran it twice (first sync then a true incremental merge), and confirmed "stop scheduling" retains the target for manual runs.

**Production OpenSearch instance store - design implemented; wired in by §35**: `apps/api/src/services/instance_store.py` adds the `InstanceStoreGateway` Protocol and a real `OpenSearchInstanceStore` (async client, HTTP basic auth against the domain's fine-grained-access-control master user via Secrets Manager, matching every other credential in this build). This is flagged as architecturally significant, same as it was when day-one scope skipped it: Postgres RLS enforces workspace isolation as a second, independent layer behind the route's permission check; OpenSearch has none of that built in. The design here reuses the isolation anchor the platform already provisions per workspace (db 0002's immutable `search_prefix`, the same idea as `s3_prefix`/`pg_schema`) - **one OpenSearch index per workspace**, with an `object_type_id` filter applied within it, rather than trusting a shared index's query-time filters alone. Not unit-tested against real infra, same precedent as `S3StorageGateway`/`Boto3SecretsGateway` (no OpenSearch equivalent of moto here). Deliberately **not wired into `routes/objects.py`/`services/instances.py` in this session**: the Postgres-backed functions there take the request's already-open, RLS-scoped `AsyncConnection`, while a gateway object is a long-lived thing independent of any one request's transaction - cutting over is a real service-layer change that deserves its own review rather than riding in on this session's four unrelated deliverables. **§35 did that cutover**, and resolved the tension differently than assumed here: rather than replacing those functions' bodies, it put a `PostgresInstanceStore` behind the same Protocol so both stores coexist. §35 also found that the gateway described in this paragraph could not have run at all - `AsyncOpenSearch` needs an extra that was not declared.

**Dockerfile review**: Docker Hub is not on this sandbox's egress allowlist (confirmed via the outbound proxy's failure log), so an actual `docker build` could not be run; a static review was done instead - `pip download --only-binary=:all: --platform manylinux2014_x86_64 --python-version 312` against every requirement (API, worker, including each package's full transitive closure) resolved cleanly to prebuilt wheels, meaning no image needs a compiler toolchain `python:3.12-slim` doesn't have. `npm ci --dry-run` confirmed the lockfile is in sync with `package.json` for the web image's `deps` stage. All three Dockerfiles' `COPY`/`WORKDIR`/module-path assumptions were checked against the actual repo layout (no relative imports climb outside the copied `src/` tree; `PYTHONPATH`/`-m` module path agree). No build-breaking issue was found, though this is evidence rather than proof - a real `docker build` would also need real internet access to actually pull the base images and packages, which this review could not exercise directly.

**Bug found in local dev setup, fixed**: `apps/web/.env.local` (the file that turns on the dev sign-in token box `dev_server.py`'s instructions rely on) was committed at `apps/web/src/.env.local` - a path Next.js never reads env files from (it only loads `.env.local` from the app's own root). This silently meant the documented local-dev login flow never actually worked from a fresh clone; moved to the correct location and re-verified live (logged in with a `dev_server.py`-minted token, used every page touched this session).

**Current API regression total: 124/124 passing** (113 from before + 10 new scheduled-sync tests + 1 replaced cron test - see `tests/test_scheduled_sync.py`, `tests/test_models.py`). **Worker: 18/18 passing** (4 from before + `test_python_sandbox.py`'s 6 + `test_model_runs.py`'s 5 + `test_sync_configs.py`'s 3). Control-plane (8/8) and frontend typecheck/build were not touched this session beyond the fixes above - carried forward unverified against a fresh environment since this session didn't rebuild that venv.

### 15. Canvas - the low-code app builder (this session)

The schema (`canvas_apps`, `canvas_app_versions`, `canvas_app_shares`) has existed since migration 0003, RLS'd since 0006/0009, but nothing used it until now - this session wired the whole layer: service (`services/canvas.py`), routes (`routes/canvas.py`, project-scoped CRUD + a workspace-scoped read-only path for published apps), types, and a real Craft.js-based visual editor in the frontend.

**Backend**: an app's `definition` is an opaque Craft.js node tree (per the migration's own comment) - this layer only stores, versions (one `canvas_app_versions` row per save, `current_version` bumped in lockstep), and gates visibility on it; it never interprets widget semantics, the same split `services/actions.py` already takes with `submitted_values`. Publishing (`private` → `workspace` → `groups`) requires the workspace admin role to move beyond private, mirroring the exact bar `routes/connections.py` already sets for workspace-scoped connections - both expose project data past the project's own membership. A workspace-scoped `GET .../published-canvas-apps[/​{id}]` pair is the read path for a workspace member who isn't a member of the app's own project.

**A real, pre-existing RLS bug found and fixed**: `canvas_apps`' `app_isolation` policy (written in migration 0009, long before Canvas had a service layer to exercise it) resolved a published app's workspace via a subquery against `projects` - `EXISTS (SELECT 1 FROM projects p WHERE p.id = canvas_apps.project_id AND rls_can_access_workspace(p.workspace_id))`. `projects` is itself RLS-protected, and for a `permission_mode='custom'` project that explicitly revokes a user, that project row is invisible to them - so the "published to the whole workspace" escape hatch silently never fired for exactly the case it exists to serve. Same shape of bug as 0008/0009 (a policy reading a table whose own RLS can hide the row the policy needs), fixed the same way in a new migration 0015: a `SECURITY DEFINER` helper (`rls_project_workspace_id`) that resolves the workspace_id without invoking `projects`' policy. The service layer's own `list_published`/`get_published` queries had the identical bug one level up (an application-level `project_id IN (SELECT id FROM projects WHERE workspace_id = :wid)` filter) and needed the same helper.

**Frontend**: `@craftjs/core` powers the editor (`canvas/[appId]/page.tsx`) - a toolbox of draggable widgets, the live canvas (`<Frame>`), and a settings panel that renders whichever widget is currently selected. Four widgets ship day one, each reusing an endpoint already built rather than adding new data-access surface: **Container** (layout), **Text** (a heading/paragraph), **Dataset table** (bound to a dataset, rendered via the existing preview endpoint), and **Action form** (bound to an action type, rendered via the existing instance-list + execute endpoints - the "write-back forms" the spec calls for). Widgets read workspace/project id and edit-vs-preview mode from a `CanvasEnvProvider` context rather than their own serialised props, since the same saved app renders from more than one route; the Action form widget also disables real submission while the builder is dragging things around (`mode === "edit"`), only going live in Preview. Save (`query.getSerializedNodes()`), a Preview/editing toggle (`actions.setOptions` rather than remounting the editor, so in-progress unsaved changes survive the toggle), and Publish (mode + group picker, admin-gated) round out the top bar.

Verified end-to-end in a live browser against the real dev API/Postgres: created an app, confirmed click-to-select + live two-way prop editing (typing in the settings panel updates the canvas instantly) against a hand-seeded definition bound to a real dataset, Saved (version bumped, persisted, reloaded correctly), toggled Preview (chrome hides, widgets render read-only), and Published to the whole workspace as an admin (editor correctly 403s first). **One thing this session could not verify by automation**: dragging a fresh widget from the toolbox onto the canvas uses native HTML5 drag-and-drop (Craft.js's `connectors.create`, confirmed by reading its source), which Playwright cannot reliably simulate - `dragTo()` and manual mouse events both left the canvas untouched in testing, a known, documented limitation of automating native browser DnD rather than a sign of a bug. The identical underlying mechanism (Craft.js's node tree, `useNode`/`setProp` binding, resolver) was proven correct via the click-select and load-from-saved-definition paths above; the one thing not exercised by a real mouse in this session is the initial drag gesture itself.

**Current API regression total: 139/139 passing** (124 from before + 15 new canvas tests - `tests/test_canvas.py`). Worker unaffected (still 18/18) - Canvas has no worker component.

### 16. Scheduled object-type-source sync (this session)

Day-one object-type-source sync (§11) is interactive-only and capped at 20,000 rows per run - fine for exploring a mapping, not for a dataset that keeps growing or a mapping nobody remembers to re-trigger by hand. This closes that gap the same way §14 closed it for connections: a cron schedule plus a much larger worker-side cap, not a change to *how* the sync works.

**Deliberately not incremental, unlike connection sync**: connection sync (§14) has a real "rows changed since a cursor" concept because the source is a live external table being polled. An object-type-source's input is a dataset's current Parquet file, which is replaced wholesale on every upload/sync/model run - a snapshot, not an append log. There is no cursor to hold. Reprocessing the full current snapshot and upserting-by-primary-key (with mark-and-sweep for rows that disappeared) was already the correct approach in §11 and stays exactly as-is here; the only things day-one was actually missing were capacity and scheduling, both mirrored directly from §14's `sync_schedule`/`sync_next_run_at` pattern. This reasoning is written into migration 0016's own docstring so it doesn't have to be re-derived later.

**Backend**: migration 0016 adds `sync_schedule`/`sync_next_run_at` to `object_type_sources` and a `list_due_object_source_syncs()` SECURITY DEFINER discovery function, joined through to `object_types` for the workspace id - the same discover-then-verify shape every scheduled worker job in this build already uses (list candidates across all workspaces via a security-definer function, then act through a workspace-scoped connection that re-checks the row is still due and still configured before touching anything). `GET/PUT/DELETE .../object-type-sources/{id}/schedule` (viewer/editor/editor) let a schedule be read, set (computing `sync_next_run_at` via the existing `croniter`-based `next_run_after()` helper), and cleared. The worker job (`jobs/instance_syncs.py`, `MAX_SCHEDULED_INSTANCE_SYNC_ROWS = 2,000,000` vs. the interactive path's 20,000) runs the identical extract → upsert → mark-and-sweep logic as the interactive sync endpoint, then reschedules via `croniter` regardless of success or failure.

**A real bug found and fixed**: the job's per-candidate `except` clause caught `DatasetEngineError`/`LookupError`/`OSError` but not `StorageKeyError` (a `ValueError` subclass the storage gateway raises for a malformed key) - so one candidate with a bad key would crash the entire batch instead of being recorded as that one source's failed run, leaving every other due source unprocessed and permanently "due" until the next poll happened to retry the whole batch and hit the same candidate first. This is the third time this exact bug class (a worker job's error isolation not covering every exception type the code it calls can actually raise) has been found in this session - twice before in `jobs/sync_configs.py` (§14). Fixed by adding `StorageKeyError` to the caught tuple; worth treating as a standing checklist item any time a new scheduled job is added - enumerate every exception type on the call path, not just the ones a first test run happens to exercise.

**Tests**: `tests/test_objects.py` gained 6 (default-unset, viewer-cannot-set, next-run-at computed, invalid-cron 422, clear-schedule, audit trail - 145/145 API total below). `apps/worker/tests/test_instance_syncs.py` (new) gained 4: upsert-on-schedule, resync-after-dataset-change (mark-and-sweep still correct on the worker path), a failing sync isolated to its own candidate and still rescheduled, and an unscheduled source left untouched (22/22 worker total below).

**Frontend**: the Objects page's dataset-mappings table gained a "Schedule" button per mapping opening a small dialog - a status card (current cron, next run time) when a schedule exists, and a form to set/change it otherwise.

Verified end-to-end in a live browser against the real dev API/Postgres: mapped a real object type onto a real dataset, opened the Schedule dialog, set a cron schedule and confirmed the dialog immediately showed the computed next-run time, then invoked the worker job directly against the same database and storage root and confirmed it picked up the due source, extracted the dataset's real rows via DuckDB, and upserted them into `object_instances` (log: `upserted=3 removed=0`) - the full pipeline (frontend → API → DB → worker discovery → workspace-scoped verification → Parquet extraction → Postgres upsert) working end to end.

**Current API regression total: 145/145 passing** (139 from before + 6 new schedule tests - `tests/test_objects.py`). **Worker: 22/22 passing** (18 from before + `test_instance_syncs.py`'s 4).

### 17. Real AWS deploy validation (this session)

Everything up to this point had been tested against local Postgres and, for the infra layer, a static review of the CDK synth output and `pip`/`npm` dependency resolution (§14's Dockerfile review) — no `cdk deploy` had ever actually been run against a live AWS account. This session did that, for real, end to end: a dry-run customer stack (`orgSlug=dry-run-customer`) deployed into a real account in `eu-north-1`, iterated through failure after failure until the full stack — VPC, RDS, ElastiCache, OpenSearch, all three ECS services, ALB, CloudFront — came up green with `api`/`worker`/`web` all passing their health checks against a real, migrated database. This is the single most valuable testing this build has had: every bug below is a real gap that no unit test, synth check, or local dev run could have caught, because each one only exists at the boundary between this code and AWS's actual behavior.

**Nine real, distinct bugs found and fixed, in the order a fresh deploy hits them:**

1. **`apps/web/Dockerfile` build context.** `docker build ... apps/web` fails because the Dockerfile's `COPY packages/types packages/types` needs the monorepo root as build context, not the app's own directory — has to be `docker build -f apps/web/Dockerfile .` from the repo root.
2. **`apps/web/Dockerfile` deps-stage layer.** Even with the right context, the build stage only forwarded `/repo/node_modules` from the `deps` stage — but this lockfile nests `next` under `apps/web/node_modules`, not the root, so the binary never made it into the image ("next: not found"). Fixed by forwarding the whole `/repo` tree from `deps` instead of cherry-picking `node_modules`, which is correct regardless of where npm decides to nest a given workspace's deps.
3. **`apps/web/public` never existed.** The Dockerfile's runtime stage unconditionally `COPY`s it (matching Next's standalone output convention); the app just never had one, since all static assets are `@fontsource` npm packages. Added an empty, tracked `public/.gitkeep`.
4. **OpenSearch domain TLS policy.** AWS now rejects new domain creation requesting the old `Policy-Min-TLS-1-0-2019-07` policy outright; the CDK `Domain` construct never set `tlsSecurityPolicy` explicitly, so it fell back to whatever the pinned `aws-cdk-lib@2.150.0`'s (pre-2.201.0) default was. Pinned explicitly to `TLS_1_2`.
5. **Missing OpenSearch service-linked role.** A VPC-joined OpenSearch domain can't provision its ENIs until `AWSServiceRoleForAmazonOpenSearchService` exists in the account, and AWS doesn't create it automatically outside the console flow — every fresh customer account would hit this on first provisioning. Fixed at the right layer: `Provisioner._deploy` now calls `iam:CreateServiceLinkedRole` (idempotent) via the assumed bootstrap-role credentials before the first-time `cdk deploy`, with the bootstrap CFN template granting the narrow permission needed for it.
6. **Invalid security group rule descriptions.** Six ingress rules used `"X -> Y"`-style descriptions; AWS's allowed character set for this specific resource type doesn't include `<`/`>` (IAM role and CFN stack descriptions are more permissive and were unaffected). Changed to `"X to Y"`.
7. **ECS tasks could never pull their own images.** `ecs.ContainerImage.fromRegistry(url)` takes a plain string, not an `IRepository`, so CDK has nothing to grant ECR pull permissions from — the auto-created execution role ended up with CloudWatch Logs and Secrets Manager access but zero ECR permissions. This is exactly what the `ecrImageRequiresPolicy` synth warning (present on every synth all session) was reporting; it just hadn't been addressed. Fixed by explicitly attaching `AmazonECSTaskExecutionRolePolicy` to each task's execution role. Confirmed via CloudWatch: before this fix, log streams were created (the container launched) but contained zero events (it never got far enough to run anything) — a `docker build --platform linux/amd64` architecture mismatch (Apple Silicon default vs. Fargate's x86_64) was investigated and ruled out along the way, but this was the real cause.
8. **The database connection was never actually wired end to end.** `services.ts` injected the whole app-db secret as one JSON blob (`DATABASE_CREDENTIALS`), but `apps/api`'s `Settings`/`apps/worker`'s `definitions.py` both expect a ready-made connection-string env var (`DATABASE_URL`/`WORKER_DATABASE_URL`) that nothing ever set — `api`'s health check 500'd on every single request (uvicorn itself started fine, so this took real log digging, not just a circuit-breaker message, to find). Fixed by having CDK hand over the connection pieces instead of a pre-built URL — plain `DATABASE_HOST`/`PORT`/`NAME` env vars plus separate `DATABASE_USERNAME`/`DATABASE_PASSWORD` secret-backed ones (a connection string can't itself be a single Secrets Manager value) — with both apps assembling the URL themselves, falling back only when the existing `DATABASE_URL`/`WORKER_DATABASE_URL` env vars aren't set directly, so every existing test and `dev_server.py` flow was untouched. A second pass added `sslmode=require` to the assembled URL, since RDS's default parameter group rejects plaintext connections.
9. **`platform_app`'s Postgres password was a hardcoded placeholder, never synced.** Migration `0006_rls.sql` creates the role with the literal string `'change_me_in_secrets_manager'`, and its own comment says this "is overwritten during provisioning" — but nothing anywhere actually did that, because this was the first time migrations had ever run against a real CDK-provisioned RDS instance. `migrate.py` gained an optional `PLATFORM_APP_PASSWORD` sync step (`ALTER ROLE`, idempotent, run after every migration pass) that keeps the role's real password in sync with whatever's actually in Secrets Manager — a no-op when unset, so every local/CI run is unaffected.
10. **Correction to #7, hit for real on a later fresh redeploy (§18/§19's follow-up work, same investigation pattern): the architecture-mismatch theory #7 says was "investigated and ruled out" turned out to be real this time.** `docker build` for `apps/api`/`apps/worker`/`apps/web` was run with no `--platform` flag; on Apple Silicon that defaults to building an arm64 image, while Fargate tasks default to x86_64 and nothing in this CDK stack says otherwise. An arm64 image on an x86_64 task fails to start at the container-runtime level, before any application code runs — the worker service's `CREATE_FAILED` showed the ECS deployment circuit breaker tripping, and its CloudWatch log stream had zero events, same signature as #7's original ECR-permission bug but a different cause; confirmed directly via `docker manifest inspect --verbose`, which showed the pushed image as `arm64`. Fixed durably in the Dockerfiles themselves rather than relying on remembering a build flag: all three now pin `FROM --platform=linux/amd64 <base> AS <stage>` on every stage (three stages in `apps/web/Dockerfile`), so the build is correct regardless of which machine runs it.

**Still a manual step at the time this section was written**: nothing in the deploy pipeline actually ran `migrate.py` against a fresh database automatically, and there was no way to create the first organisation/user either. Both fixed in §18 (same session, following work) — flagged here as the highest-value remaining infrastructure work, and that's exactly what got built next.

**Operational notes from doing this for real:**
- RDS (`deletionProtection: true`) and the OpenSearch domain (`removalPolicy: RETAIN`) both survive stack rollback/deletion by design — every failed dry-run attempt left one or both behind, requiring a manual disable-protection-then-delete dance before the stack itself could be deleted and retried. Expected and correct for production (don't let a bad deploy nuke a customer's data), but worth budgeting time for during iterative dry runs.
- `cdk deploy --no-rollback` turned this from "20-minute full rebuild per attempt" into an actual iterate-and-retry loop once the stack got far enough to be worth preserving — CloudFormation leaves whatever succeeded in place instead of tearing it all down on any single resource's failure, and a subsequent `cdk deploy` retries just the failed resources rather than starting over. Should be the default for any future dry-run debugging session; it is not currently mentioned in `apps/control-plane`'s own real deploy path (which doesn't use it, deliberately — production deploys should roll back on failure).
- ECR login tokens expire after 12 hours (`aws ecr get-login-password | docker login`) — bit a mid-session rebuild once.

No code regression from any of this: **API 145/145, worker 22/22, control-plane 9/9 unaffected**, plus a new `test_update_stack_skips_service_linked_role` covering fix #5.

---

### 18. Automated migrations + first-owner bootstrap (this session)

§17 ended with two gaps every real customer deploy would hit: nothing ran `migrate.py` automatically, and even with a migrated database there was no way to create the first organisation or user at all (self-signup is disabled by spec, and the invite flow deliberately refuses to grant `'owner'`) — both required hand-run SQL via CloudShell the first time. This session builds both, plus a third gap found in the process: the deployed API was silently running dev/test gateway fallbacks in production for Cognito, S3, and Secrets Manager.

**Automated migrations — `infra/cdk/src/constructs/migration.ts`.** A `triggers.TriggerFunction` (VPC-attached, `executeAfter` the RDS instance, `executeBefore` the API and worker ECS services — `customer-stack.ts` wires both) runs on every deploy, first-time or update alike. `migrate.py`'s `main()` was split so its actual logic lives in a new `run(dsn, *, dry_run=False)` function the Lambda calls directly (`packages/db/lambda_handler.py`), rather than shelling out to the CLI. The Lambda resolves connection pieces from Secrets Manager via boto3 at invoke time — `DB_SECRET_ARN`/`APP_DB_SECRET_ARN` env vars carry only ARNs, never resolved values, matching how the API/worker never embed raw secrets either — then calls `migrate.run()` followed by the existing `sync_app_password` step, raising if either fails so the deploy itself fails loudly instead of silently leaving a stale schema. The Lambda's dependencies (`psycopg[binary]`, which needs a real compiled extension, not pure Python) are bundled via `lambda.Code.fromAsset` with Docker-image bundling.

**Correction, found on the first real `cdk deploy` of this construct (a Mac with Docker Desktop running throughout)**: this originally also had a `local` bundling fallback (`pip install --platform manylinux2014_x86_64 --only-binary=:all:`), added so `cdk synth` could run in this repo's own Docker-less sandbox, on the assumption it would only ever apply when Docker wasn't available. That assumption was wrong: CDK tries `local.tryBundle()` *unconditionally* before ever considering Docker, falling back to Docker only if it returns false or throws — it is not "Docker if available, else local." On a real machine with Docker running the whole time, the local branch still ran (and "succeeded," since fetching a `--platform`-tagged wheel via pip doesn't require actually executing it), producing a `psycopg_binary` wheel that imported fine at bundle time but failed at actual Lambda runtime: `CREATE_FAILED` on `Migration/Fn/Trigger`, `"Unable to import module 'lambda_handler': no pq wrapper available"` — none of psycopg's c/binary/python implementations actually worked in the deployed Lambda. Native-extension dependencies need the exact build environment the official Lambda bundling image provides; there's no safe host-pip substitute for that. Fixed by removing the `local` fallback entirely — this construct's `cdk synth`/`cdk deploy` now requires a running Docker daemon, same as this repo's own Dockerfile-based service images already do, and can no longer be synth-verified in this sandbox (which has none). This section originally claimed the migration Lambda was "verified end to end via `cdk synth`," including a working compiled `psycopg_binary`; that verification exercised the Lambda bundle the now-removed local path produced, not the Docker-only path a real deploy actually uses, and didn't catch this. Recorded here rather than quietly edited out — it's exactly the kind of gap only a real deploy catches (§17's whole point).

**Second correction, found redeploying after the fix above (still Docker the whole time — same exact failure)**: removing `local` wasn't enough. `lambda.Runtime.PYTHON_3_12.bundlingImage` (a `DockerImage.fromRegistry` reference) was run via CDK's default `BundlingFileAccess.BIND_MOUNT`, and — confirmed by reading `aws-cdk-lib` 2.150.0's own source, not assumed — neither `AssetBundlingBindMount` nor `AssetBundlingVolumeCopy` forwards a `bundling.platform` option into the `docker run` call they construct; it's silently dropped regardless of what's set. Without an explicit `--platform`, Docker runs a multi-arch bundling image at the *host's* native architecture — arm64 on Apple Silicon — while the Lambda function itself defaults (CDK's own default, never previously made explicit here) to `Architecture.X86_64`. Building `psycopg[binary]` inside an arm64 container for an x86_64 function reproduces the identical "no pq wrapper available" failure, for a completely different reason than the first correction. Fixed by making both sides explicit and matching: `architecture: lambda.Architecture.X86_64` on the function, and swapping the bundling image for a thin wrapper Dockerfile (`infra/cdk/src/constructs/migration-bundling/Dockerfile`, just `FROM public.ecr.aws/sam/build-python3.12`) built via `DockerImage.fromBuild(dir, { platform: "linux/amd64" })` — `fromBuild`'s `platform` option *is* correctly passed to `docker build --platform` (also confirmed against source), producing a single-arch image that needs no further `--platform` flag at run time. Not fully re-verifiable end to end in this sandbox (still no Docker), but the mechanism itself — which option is dropped where, and which alternate path actually forwards it — was confirmed by reading the installed `aws-cdk-lib` source directly rather than guessed a third time.

**First-owner bootstrap — migration `0017_first_owner_bootstrap.sql`, `services/orgs.py`, `routes/bootstrap.py`.** Two `SECURITY DEFINER` Postgres functions (the same bypass-RLS-narrowly pattern used throughout this schema — `rls_is_org_admin` etc. — rather than inventing a privileged connection pathway): `platform_has_any_organisation()` and `bootstrap_first_owner(name, slug, cognito_sub, email, display_name)`. The latter `LOCK TABLE organisations IN EXCLUSIVE MODE` before checking-and-inserting, so two concurrent callers on a fresh database can't both pass the guard — exactly one succeeds, the other gets a `unique_violation` mapped to a `409`. `GET /api/bootstrap/status` and `POST /api/bootstrap/first-owner` (`routes/bootstrap.py`) are the only genuinely unauthenticated write routes in the API, deliberately: there is no user yet to hold a token, and the one-time guard is a database-level check, not a permission check. The Cognito identity is created *before* the DB call, so a race that finds the platform already bootstrapped leaves one orphaned, unused Cognito user rather than a DB row with no matching identity — the safer failure direction, cleanable by hand.

**Frontend — `/setup` page, `login` page link.** A new page at `apps/web/src/app/(auth)/setup/page.tsx`: checks `GET /api/bootstrap/status` on load, shows the create-organisation form only if `needs_setup`, otherwise an "already set up" state linking to `/login`. The login page now shows a "Set up your organisation" banner (linking to `/setup`) whenever the same status check reports `needs_setup: true`. Verified end to end in a real browser (Playwright against the pre-installed Chromium, `apps/api` + `apps/web` dev servers against a freshly migrated, genuinely empty local Postgres): the banner appears, the form creates the org and shows the temporary-password confirmation, the banner disappears afterward, and revisiting `/setup` correctly shows "already set up".

**Third gap found and fixed in passing: production gateway wiring.** While building the above, `main.py` turned out to never call any of the existing `configure_storage_gateway`/`configure_secrets_gateway`/`configure_cognito_gateway` functions with a real AWS-backed gateway — every deployed stack was silently running the in-memory/local/null fallbacks each route module defaults to, meaning connection credentials never persisted past process memory and invites never created real Cognito users, on any deployment, until now. Fixed with the same signal-based selection the worker's `gateway_from_env()` already uses: a new `_wire_production_gateways()` in `main.py` checks for `S3_DATA_BUCKET` (only ever set in the deployed stack's task definition; never set locally or in any test fixture) and, if present, wires `S3StorageGateway`, `Boto3SecretsGateway`, and a new `Boto3CognitoGateway` (added to `services/orgs.py` — `AdminCreateUser` against the CDK-provisioned user pool, returning the Cognito-assigned `sub`) into all three route modules plus `routes/bootstrap.py`. A no-op everywhere else, so no existing test or dev flow changed.

**Testing.** `packages/db/migrate.py`'s refactor and migration 0017 were verified against a real local Postgres (fresh migrate, idempotent re-run, `--dry-run`), including the SQL functions directly (`platform_has_any_organisation` false→true, the atomic one-time guard raising on a concurrent second call) before any Python wrapped them. A new `apps/api/tests/test_bootstrap.py` covers both states the shared dev database can't naturally produce together: the already-set-up path (`409`, validation errors) runs against the ordinary shared `client`/`fx` fixtures, while the true empty-platform happy path runs against its own freshly migrated scratch database — a genuinely empty `organisations` table is the one thing the shared dev database, already populated by every other test module's fixtures, can never provide. **API 151/151 (145 + 6 new), worker 22/22, control-plane 9/9 — all unaffected.**

### 19. Stack teardown — `apps/control-plane`'s Deprovisioner (this session)

The third lifecycle operation alongside `Provisioner.provision()`/`update_stack()`: a `Deprovisioner` (`src/deprovisioner/deprovisioner.py`) that permanently deletes a customer's entire platform stack, database included. Deliberately built as a vendor-side operator tool (`python -m src.cli deprovision --org-slug <slug>`), not a self-service button in the customer-facing product: the thing that actually knows how to destroy a stack is the control plane, which assumes a cross-account role into the *customer's* AWS account — `apps/web` runs *inside* the very stack a delete button would be destroying, and has no path to the control plane's trust boundary at all today (no HTTP API, no auth layer). Fully automated, no confirmation prompt — an explicit choice for an operator tool, not a product surface a customer could fat-finger.

**Why this isn't just `cfn.delete_stack()`.** Two of the stack's stateful resources are deliberately kept out of CloudFormation's own deletion (§17's operational notes: "don't let a bad deploy nuke a customer's data") — RDS has `deletionProtection: true`, and the OpenSearch domain plus both S3 buckets have `removalPolicy: RETAIN`. `Deprovisioner.deprovision()` does, in order: (1) read the stack's outputs — before deleting anything, since nothing is describable once the stack is gone, and every one of these physical names is CDK-auto-generated with no way to predict it ahead of time; (2) disable RDS deletion protection, *poll until it actually clears*, then **delete the DB instance directly** — not left to CloudFormation's own deletion; (3) delete the stack and poll until it's gone (mirrors `Provisioner._poll_until_stable`'s pattern, watching for `DELETE_FAILED`); (4) only then clean up what `RETAIN` left behind — empty and delete both S3 buckets, delete the OpenSearch domain. Step 4 is best-effort and logged, not fatal to the run: by that point the expensive, ongoing-cost resources (RDS, ECS, NAT gateway, ALB, CloudFront) are already gone via the stack deletion, which is the part that actually matters if a human needs to finish the rest by hand.

**Correction, found tearing down the real §17 dry-run stack by hand right after this section was first written**: step (2) originally stopped at disabling deletion protection and left the DB instance itself to CloudFormation's `delete_stack`, on the assumption that clearing the live `DeletionProtection` flag would let CloudFormation delete it. It doesn't — CloudFormation decides whether to delete an RDS instance by checking its *own template's last-declared* `DeletionProtection` property, not the resource's live AWS state. Since that property was still `true` in the deployed stack's template, `delete_stack` silently `DELETE_SKIPPED` the instance rather than deleting it, which left its ENI attached and blocked every security group and subnet that depended on it from ever deleting — exactly what happened running the manual runbook: `DELETE_FAILED` on a security group with "has a dependent object," traced through `describe-network-interfaces` (an `in-use` ENI owned by AWS's own RDS management account) back to `describe-stack-events` showing `DataPostgresA4594A5A-DELETE_SKIPPED`, not failed. Fixed by having `Deprovisioner` call `rds:DeleteDBInstance` directly once protection is confirmed off, waiting for the instance to actually disappear (`db_instance_status` returns `None`), *then* deleting the stack — CloudFormation marks the (already-gone) instance `DELETE_SKIPPED` again, harmlessly, and proceeds to delete everything that depended on it. `customer-bootstrap.yaml`'s `TeardownRds` statement gained `rds:DeleteDBInstance`. All four `Deprovisioner` tests updated and still pass with the fix.

**CDK — discovery, not renaming.** Rather than give the RDS instance/OpenSearch domain/S3 buckets explicit, predictable names (a breaking change for any stack already deployed — CDK treats a previously-unset `bucketName`/`instanceIdentifier`/`domainName` becoming explicit as a replacement), `customer-stack.ts` gained three new `CfnOutput`s (`DatabaseInstanceIdentifier`, `SearchDomainName`, `AccessLogBucketName` — `DataBucketName` already existed) so the Deprovisioner can look up the exact physical names at teardown time instead. Adding outputs can never trigger a replacement, so this is fully non-breaking.

**Bootstrap IAM — reach past CloudFormation for exactly four resources.** `customer-bootstrap.yaml` already grants `cloudformation:*` scoped to `stack/PlatformStack*/*`; three new statements (`TeardownRds`, `TeardownStorage`, `TeardownSearch`) extend that same scoping *style* — CloudFormation auto-generates every unnamed resource's physical name with a `platformstack-` prefix (the literal, fixed `STACK_NAME` this whole codebase already relies on for scoping), so `arn:aws:rds:*:${AWS::AccountId}:db:platformstack-*` etc. reach only this account's one platform stack, without needing per-customer tag parameters or broadening to `*`.

**`KmsSecretsCodec` — the registry's `SecretsCodec` Protocol had no production implementation.** `registry.py`'s own docstring commits to "stored encrypted with a KMS data key in production," but only a test-only `XorCodec` (in `test_control_plane.py`) ever existed — nothing in `apps/control-plane` had a real entrypoint at all before this session (no Dockerfile, no CLI, no requirements.txt), so this gap was never exercised. A CLI that actually needs to decrypt a real customer's external ID needed one to exist; added `KmsSecretsCodec` (`registry.py`) — envelope encryption, a fresh AES-256 data key generated by KMS per `encrypt()` call (never reused or stored), the KMS-wrapped key travels alongside the AES-GCM ciphertext so `decrypt()` needs exactly one `kms:Decrypt` call. Verified for correctness (round-trips, fresh ciphertext/nonce per call) against a fake KMS client standing in for the real service — this codebase has no AWS egress to test the real `boto3` KMS calls against, same boundary `Boto3Gateway`'s own methods have always sat on (this repo's tests fake AWS entirely; nothing here has ever unit-tested boto3 call correctness directly, only through real deploys per §17). `apps/control-plane` also gained its first `requirements.txt`/`requirements-dev.txt` (`boto3`, `cryptography`, `psycopg[binary]`, `pytest`).

**Testing.** Four new `Deprovisioner` tests in `test_control_plane.py` (happy path asserting the exact call order; an older-stack-without-teardown-outputs case that still deletes the core stack and skips best-effort cleanup rather than failing; `DELETE_FAILED` → registry status `FAILED`; refusing a second call once already `DESTROYED`), plus `FakeAws` extended with the six new teardown methods. **Control-plane 13/13 (9 + 4 new)**; API 151/151 and worker 22/22 unaffected (neither package was touched). CDK typecheck and `cdk synth` both clean with the new outputs present; the bootstrap template's YAML (including the new IAM statements) parses cleanly.

**Still true after this**: today's actual dry-run stack from §17 was deployed with direct `cdk deploy`/personal AWS credentials, never through `Provisioner`/the registry — so this Deprovisioner has nothing to look up for it. It's built for stacks the control plane provisions going forward; tearing down *that* one specific stack still means the manual runbook (disable RDS protection, delete the stack, empty/delete the `RETAIN`'d resources by hand).

---

### 20. First fully green real deploy, and a tenth deploy bug (this session, continued from §17–§19)

§17–§19 fixed nine real bugs and built the automated-migration/first-owner/teardown machinery, but no dry-run attempt had actually stayed up long enough to pass every ECS service's health check — every attempt through the end of §19 still died at the ECS circuit breaker. This session's continuation (still the same real `eu-north-1` account, same `orgSlug=dry-run-customer`) chased that down to closure and got the first fully green deploy: VPC, RDS, ElastiCache, OpenSearch, all three ECS services, ALB, and CloudFront all `CREATE_COMPLETE`/healthy, api/worker/web all passing real health checks.

**Tenth bug: `apps/api`/`apps/worker`/`apps/web` Docker images were never actually rebuilt with the §17-item-10 platform pin.** Item 10 above documents pinning all three Dockerfiles to `--platform=linux/amd64`; that fix was correct and committed, but the images already sitting in ECR predated it, and nothing about pulling a code fix rebuilds and re-pushes the actual image — confirmed directly via `docker manifest inspect --verbose`, which showed `arm64` on the pushed `platform-api` image days after the Dockerfile fix landed. A second, sharper version of the same bug then appeared on the *rebuild*: even with the `--platform` pin in the Dockerfile's `FROM` line, a plain `docker build` (no `--platform` flag on the build command itself) still produced an `arm64` image. Root cause: `FROM --platform=X` only selects which variant of the *base* image to pull for that stage's execution; it does not set the *target platform* CDK/Docker exports the final image as — that's controlled by `--platform` on the `docker build` invocation itself, which nothing in this build's documented deploy runbook ever included. Fixed operationally (not in code, since this is a build-command concern, not a Dockerfile one) by always building with `docker build --platform=linux/amd64 ...` explicitly; the STATUS.md runbook and any future CI pipeline (see roadmap) must carry this flag, the Dockerfile pin alone is not sufficient.

**Eleventh bug: the migration Lambda's `currentVersion` logical ID churned between deploys with zero underlying code change, colliding with itself.** `infra/cdk/src/constructs/migration-bundling/Dockerfile` pulled `public.ecr.aws/sam/build-python3.12` unpinned (`:latest`). A `cdk deploy` retry on a later day resolved a different upstream digest than the one an earlier successful deploy had used, even though `packages/db`'s actual source was byte-identical — which changed the Lambda's computed config hash and therefore CDK's generated `MigrationFnCurrentVersion<hash>` logical ID. CloudFormation tried to `PublishVersion` under this new logical ID; since the function's `$LATEST` was unchanged since the version already published under the *old* logical ID, Lambda's (idempotent) `PublishVersion` just handed back that existing version number instead of minting a new one — a collision CloudFormation reported as `HandlerErrorCode: AlreadyExists`, blocking the whole stack update. Confirmed via `describe-stack-resources`: two different `MigrationFnCurrentVersion*` logical IDs existed for the same function, one `CREATE_COMPLETE` (holding the real published `:1`), one permanently `CREATE_FAILED` with no physical resource. Fixed two ways: (1) durably, pinned the bundling Dockerfile to the exact digest (`sha256:b24c57c8...`) rather than `:latest`, so this can't recur from base-image drift; (2) to unblock the already-stuck deploy, manually deleted the orphaned version (`aws lambda delete-function --qualifier 1`) so the next `PublishVersion` call under the new logical ID could mint a genuinely new version instead of colliding. This is the same underlying bug *class* as §19's RDS `DELETE_SKIPPED` correction and §17's ECR-permission/architecture-mismatch pair: CloudFormation's own bookkeeping diverging from AWS's actual live state, only ever surfacing on a real deploy.

**Operational notes added to the running list:**
- **Never build or push a service image without `--platform=linux/amd64` on the `docker build` command itself** — the Dockerfile's `FROM --platform=...` pin is necessary but not sufficient; confirmed live that it silently produces an arm64 image without the build-command flag too, on Apple Silicon.
- **Any base image referenced by tag rather than digest (`:latest` or any other mutable tag) is a live footgun for CDK asset-bundled Lambdas specifically** — a bundling image's resolved digest appears to factor into the bundled asset's computed hash, so an upstream tag update between deploys can churn a `currentVersion`-style logical ID with zero change to this repo's own source, producing an `AlreadyExists` collision that has nothing to do with anything this codebase's own commits changed. Every `DockerImage.fromBuild`/`fromRegistry` reference in this codebase should be audited for pinned digests, not just the one this session hit.
- **`RemovalPolicy.RETAIN` on Cognito (spec §9's "deleting the stack must not destroy the customer's user directory") means every failed dry-run attempt leaves an orphaned User Pool behind** — this session's repeated create/rollback/retry cycles left **21 orphaned Cognito User Pools** in the account by the time the deploy finally went green, none of them cleaned up automatically (`Deprovisioner` only runs against stacks the control plane itself provisioned — see §19's "Still true after this"). Manual cleanup via `aws cognito-idp delete-user-pool` per stale pool is still outstanding as of this section.
- The Cognito hosted-UI domain is deterministic from `orgSlug` (`platform-${orgSlug}`, set in `auth.ts`) but the **client ID and exact domain still have to be looked up post-deploy** (`describe-user-pool`/`list-user-pool-clients`) to wire the web image's `NEXT_PUBLIC_COGNITO_*` build args — there's no CDK output for either today; worth adding (`UserPoolDomain` output alongside the existing `UserPoolId`/`UserPoolClientId`) so this doesn't require an AWS CLI round-trip on every fresh deploy.
- `platformUrl` (the Cognito OAuth callback base) must exactly match whatever URL is actually being browsed to test the deploy — using a real custom domain (e.g. `https://anchor-foundry.com`) before its DNS actually points at the CloudFront distribution breaks the OAuth callback silently until redeployed with the CloudFront domain itself (`https://<distribution>.cloudfront.net`) as a stand-in. A second `cdk deploy` (config-only, no `--no-rollback` needed once the stack is healthy) is the correct way to correct this, not a teardown/recreate.

**Outstanding as of this section**: first login via the Cognito hosted UI (`/setup` → create first owner → log in) is not yet confirmed working — the owner's chosen password was rejected at the login step. Most likely cause, unconfirmed: `auth.ts`'s password policy (12-char minimum, upper + lower + digit + symbol, spec §9) rejecting a password that doesn't meet all five constraints, or the Cognito temp-password-from-`AdminCreateUser` flow requiring a genuinely new password on first login rather than a reuse of the temporary one. Needs a repro with the exact error surfaced (frontend today doesn't display Cognito's specific rejection reason — likely worth fixing regardless of root cause, since a silent/generic password rejection is a real first-run UX gap for every future real customer too, not just this dry run).

No code regression: API 151/151, worker 22/22, control-plane 13/13 unaffected — this section's fixes were entirely in `infra/cdk` (one Dockerfile pin) and operational/runbook corrections, no application code touched.

---

### 21. Connector registry generalised + MySQL/MariaDB, the second source type (this session)

First session of `ROADMAP.md`'s pillar build-out: Connections items 1 and 2, in that order and for that reason — the registry refactor lands *before* the second connector so MySQL proves the abstraction instead of copy-pasting the Postgres path.

**What "one connector type" actually meant before this.** `services/connectors.py` already had a registry, but it only covered `validate_config`/`test`/`discover`. The half that matters for moving data — the extract — didn't go through it at all: `services/sync.py` imported `PostgresConfig` directly and built psycopg conninfo by hand, and `apps/worker/jobs/sync_configs.py` had its own second copy of the same `COPY … TO STDOUT` / `max(cursor)` logic inlined into the job. A second source type would have had to be written into three places, and the sync path had no notion of `connection.source_type` at all.

**The interface** (`services/connectors.py`): `validate_config` / `test` / `discover` / `snapshot_to_csv` / `max_cursor_value`, declared as a `SourceConnector` Protocol with the registry mapping `source_type` to an implementation. Two deliberate shape decisions, both written into the module docstring: the roadmap's `snapshot()` and `incremental(cursor)` are **one** method, because an incremental pull is the same extract with a `WHERE cursor > :last` predicate and splitting them would duplicate the byte-cap and error-translation loop in every connector for no behavioural difference; and the byte cap is a **parameter**, not a constant, because callers own policy (the API's 200 MB interactive cap, the worker's scheduled cap) while connectors own mechanism. `sync.py` keeps two thin dispatchers that supply the cap and know nothing about any driver; `routes/connections.py` passes the connection row's `source_type` through.

**MySQL/MariaDB** (`MySQLConnector`, PyMySQL 1.1.1 — pure Python, so no compiler toolchain the `python:3.12-slim` images lack, per §14's dependency review). The differences from Postgres are exactly the ones a real second connector surfaces, and each is now owned by the connector rather than assumed platform-wide:
- **No schema-within-database.** What Postgres calls a schema is what MySQL calls a database, so `source_schema` carries the database name and `discover` reports each database as a schema — the layers above keep one vocabulary instead of special-casing MySQL.
- **Different identifier rules.** MySQL allows a leading digit (`2024_orders` is a legal table name) and 64 characters rather than 63. The shared Postgres-shaped identifier check would have rejected valid MySQL tables, so the rule moved into the connector; there's a test that syncs a `2024_archive` table specifically to pin this.
- **No server-side COPY-to-CSV.** Rows stream through PyMySQL's `SSCursor` into a shared `_CappedCsvWriter` so the byte cap can still stop a runaway table instead of buffering it all first.
- **A different error vocabulary.** MySQL reports "missing table" and "no privilege" as numeric codes on ordinary exceptions rather than distinct classes, so translation keys on the code (1146, 1142/1143/1044/1045) to produce the same user-safe messages the Postgres path already gives.

**A real bug found while building it — `ssl_mode: required` was a promise the code didn't keep.** The first implementation passed `ssl={}` to PyMySQL to demand TLS. Reading PyMySQL's own source (not assuming, after §18's lesson about guessing at library behaviour) showed the guard is `if ssl:` — an empty dict is falsy, so TLS was never requested. Fixing that to a non-empty dict still wasn't enough: `_request_authentication` only upgrades `if self.ssl and self.server_capabilities & CLIENT.SSL`, so against a server built without TLS PyMySQL **completes the handshake in plaintext and reports success**. Confirmed live against this session's MariaDB (`@@have_ssl = DISABLED`): the connection succeeded and `SHOW STATUS LIKE 'Ssl_cipher'` came back empty. There is no client-side enforcement to lean on, so the connector now verifies `Ssl_cipher` is non-empty after connecting and refuses the connection otherwise. `required` means encrypt-without-verifying-the-certificate — the same guarantee Postgres' own `sslmode=require` gives; verify-ca/verify-full needs a customer-supplied CA this config shape doesn't carry yet. It is the default, so a plaintext source has to opt in explicitly. A test asserts a plaintext session fails an `ssl_mode=required` test rather than silently passing.

**A second real bug, in the sibling worker job.** `jobs/sync_configs.py`'s per-candidate `except` caught `(DatasetEngineError, LookupError, OSError)` but not `StorageKeyError` — even though the job calls `storage.put`/`storage.local_path`, both of which raise it for a malformed key. This is precisely the bug §16 found and fixed in `jobs/instance_syncs.py` and flagged as a standing checklist item; it was still live in the job §16 didn't touch, where one bad candidate would crash the whole batch and leave every other due connection unprocessed. Now caught, along with the new `ConnectorError`, with the full enumeration written out in a comment at the catch site.

**Frontend: no change needed, which was the point.** The create wizard already renders from `config_schema.properties`/`secret_fields`, so MySQL appeared with its own fields the moment it was registered. One improvement went in on top: constrained choices (`ssl_mode`, Postgres' `sslmode`) are now `Literal` types, so the generated JSON schema carries `enum` and the wizard renders a dropdown instead of a free-text box where a typo could only ever produce a 422.

**Testing.** `apps/api/tests/test_mysql_connector.py` (12 new) and `apps/worker/tests/test_mysql_sync_configs.py` (4 new) run against a **real MariaDB 10.11** with a real database and login role — the same standard as the Postgres suites, no mocks. Coverage: registry dispatch and the unsupported-type message, the TLS default and its live enforcement, discover against MySQL's `information_schema`, wrong-password handling with no credential leak, full sync end to end into a real dataset (asserting types survived the CSV round trip rather than collapsing to text), a missing table as a clean failed run, the leading-digit identifier case, cursor-incremental merge including the nothing-new steady state, and — worker side — that the two registries haven't drifted apart plus per-candidate failure isolation. Both MySQL files skip cleanly (module-level) when no MySQL is reachable, so a Postgres-only environment still runs everything else.

Verified in a real browser (Playwright/Chromium against the dev API + dev Postgres): the wizard offers "MySQL / MariaDB", renders its config fields, and shows `ssl_mode` as a dropdown defaulting to `required`.

**Current totals: API 163/163** (151 + 12), **worker 26/26** (22 + 4), **control-plane 13/13** (untouched). All three suites were also re-run green *before* any change this session, against a freshly provisioned local Postgres, so these numbers are a genuine before/after and not a carried-forward claim.

---

### 22. S3 / object-storage connector — the first non-relational source (this session)

`ROADMAP.md` Connections item 3, continuing straight on from §21.

**What it does.** Point a connection at a bucket + prefix; discovery lists every supported file under it (CSV/TSV/Parquet/JSON/JSONL) with columns inferred through the datasets layer's own DuckDB readers, so what discovery reports is what the file will actually land as. One object syncs as one dataset, per the roadmap's "sync each as a dataset". Credentials are optional — the common in-AWS case is a bucket the platform's task role can already read, and forcing a long-lived access key into Secrets Manager to express that would be strictly worse security than using the role; when the secret is absent boto3 falls back to its normal chain. `endpoint_url` makes S3-compatible stores (MinIO, Ceph, R2) work.

**It changed the interface, and that was the point of doing it third.** §21's `snapshot_to_csv` assumed every source has rows to serialise. That is true of a database and false of an object store, which is already sitting on a Parquet file `dataset_engine` can read natively — routing it through CSV would throw away the types Parquet carries and re-guess them. `snapshot()` now returns an `Extract` (path + extension + an `empty` flag) and callers hand the extension to `ingest_to_parquet`, which has always taken one. The `empty` flag is the second half: an object store with no rewritten object writes *no file at all*, so "nothing new" had to become an explicit signal rather than something inferred from a row count after a pointless ingest — the same path that produced §14's all-VARCHAR type-inference bug.

**Coordinate and cursor mapping**, same move the MySQL connector makes for database-means-schema, so the layers above keep one vocabulary:
- `source_schema` is the folder under the connection's configured prefix (legitimately empty for a file at the root), `source_table` the object's file name.
- The cursor is the object's `LastModified`, not a column — the unit of change is the object. `cursor_column` is accepted and ignored, documented at the connector rather than silently dropped. Stored as a fixed-width UTC isoformat because `sync_last_cursor_value` is a text column and the comparison it feeds is a string comparison.
- The configured prefix is a real trust boundary, not a default: `..`, an absolute-looking folder, and a `/` inside a file name are all refused, with a test that tries to reach an object deliberately seeded outside the prefix.

**Three real bugs found, all by tests rather than by reading:**
1. **The worker skipped every root-level file sync.** Its per-candidate guard was `if not source_schema or not source_table`, which is correct for a database and wrong the moment an empty schema is meaningful — it logged "no sync target set" about a target that was set perfectly well. Caught by the worker S3 test; now only the table half is required.
2. **The frontend silently hid every S3 object.** Both sync dropdowns filtered `t.kind === "table"`, so `kind: "file"` entries never rendered — the dialog showed an empty picker with no error, while the API's discover endpoint returned both objects correctly. Now filters on "not a view", preserving the existing behaviour for relational sources.
3. **The table picker's encoding was ambiguous.** A selection was encoded as `"schema.name"` and split on the first dot, which breaks as soon as a schema contains one — ordinary for object storage, where a "schema" is a folder. Now encoded with a separator that cannot occur in either half and resolved back through the discovered list rather than by parsing. This was latent before S3 (a Postgres schema can contain a dot too), just much harder to hit.

**Testing.** `apps/api/tests/test_s3_connector.py` (13) and `apps/worker/tests/test_s3_sync_configs.py` (5) run against a real `moto.server` process over HTTP rather than moto's in-process patching — the connector builds its own boto3 client and the endpoint/credential path is part of what shipped, so the tests drive genuinely signed HTTP requests. Both files skip cleanly without moto. Coverage includes the Parquet-stays-Parquet assertion on both the API and worker paths (the worker has its own reader table), prefix-boundary refusals, the byte cap, unchanged-vs-rewritten object incremental behaviour, and per-candidate failure isolation. Verified end to end in a real browser: created an S3 connection through the wizard, tested green, discovered both objects with column counts, and synced `metrics.parquet` into a dataset.

**A fourth bug, in the test suite itself rather than the product**, found because the worker suite had quietly gone from 16 seconds to over ten minutes: scheduled-sync tests left their connections scheduled, and the job reschedules after every run, so each one stayed permanently due and every later run re-synced it against a source that no longer existed. 81 had accumulated. Both worker `workspace` fixtures now clear the schedule on teardown; the suite is back to ~16s. Written up in the rough-edges list below, since the next fixture that schedules something needs to do the same.

**Current totals: API 176/176** (163 + 13), **worker 31/31** (26 + 5), **control-plane 13/13** (untouched).

---

### 23. Schema drift detection + sync health in the product (this session)

`ROADMAP.md` Connections items 6 and 7, built together: item 6 produces the signal, item 7 is the only reason anyone would see it.

**Drift — migration 0018, `sync_runs.schema_changes`.** Every sync now records what changed about the dataset's shape: `{added|removed|retyped}`, only the non-empty keys present, `NULL` when nothing changed or there was no previous version — so `WHERE schema_changes IS NOT NULL` is exactly "runs that drifted", and a healthy run carries no payload. Written by both the API's inline sync and the worker's scheduled job, which build their `sync_runs` row in completely different places; there's a test on each path, because one working is no evidence about the other.

**One deliberate deviation from the roadmap's phrasing**, argued in the migration itself so it isn't re-litigated: it said "compare against what was recorded at connection-setup time", but nothing records a schema at setup, and adding that would mean a discovery round trip on every sync — for the S3 connector that means listing and downloading objects purely to read their headers — against a baseline that goes stale the moment someone edits the connection. Comparing each new dataset version against the one it replaces is free (both schemas are already computed on the way through), connector-agnostic, and describes what actually landed. The costs, written down: drift is reported one sync *after* it happens rather than as a warning before the write; a change in a source column nobody syncs is invisible; and because the wire format is CSV with re-inferred types, it reports the type the data landed as, not the type the source declares. That last one is not theoretical — the first version of the drift test retyped a column to `bigint` while leaving it all-NULL, and nothing registered, because DuckDB reads an all-NULL column as text either way. The test now retypes with real values, and the caveat is in the migration.

**Health — `GET .../connections/sync-health`.** One aggregate for the whole page rather than a runs request per connection: the list renders every connection, and N+1 requests to fill a status column is what makes a list page feel broken past a handful of sources. Per connection: run counts and a success rate over the last 20 runs (not all time — "has this been failing lately" is the question a health column answers, and an all-time rate takes months to move after a source is fixed), the last run's status/duration/row count/error, its drift, and the schedule plus next run time. A connection with no runs still gets a row with `success_rate: null` — not `0`, which would read as "0% healthy" rather than "nothing to rate yet".

**Frontend.** The Connections list gains a **Sync health** column (last result and when, success rate, duration, rows, next run, and a drift badge) and a **History** button per connection opening the full run list — when, table, rows, duration, result, the error on a failure, and an expandable "schema changed (+1, −1)" detail listing the exact columns. Every cache invalidation that refreshes the connection list now refreshes health alongside it, since a sync changes both and a stale health cell is worse than none.

**Testing.** `apps/api/tests/test_schema_drift.py` (11 new) covers the diff as a pure function (no baseline, unchanged, column *reordering* deliberately not counted as drift, and added/removed/retyped reported separately) and then end to end by actually running `ALTER TABLE` against the real Postgres source between syncs, plus the health summary including a failed run moving the success rate, a never-synced connection, schedule reporting, and outsider 404. `apps/worker/tests/test_sync_configs.py` gains a drift test on the scheduled path. Verified in a real browser: four runs against a live source (one of them drifting the table, one failing), health showing `75% of last 4`, and the history dialog expanding the drift to `+ region` / `− customer`.

**Current totals: API 187/187** (176 + 11), **worker 32/32** (31 + 1), **control-plane 13/13** (untouched).

---

### 24. Generic REST / HTTP JSON connector — the fourth source type (this session)

`ROADMAP.md` Connections item 5, which that document calls "the highest-variance connector to build well" and tells you to scope narrowly. The scope is written into the connector itself rather than left implied, because the way this feature goes wrong is by quietly becoming a general HTTP client:

- **GET only.** A connector that POSTs is write-back (item 8), which wants its own design.
- **The response must contain a JSON array of objects**, found by a dotted `records_path` (`""` when the body *is* the array). XML, CSV-over-HTTP, and an object-keyed-by-id all say so rather than guessing.
- **Two pagination styles** — an incrementing page number, and an opaque cursor echoed back from the response body via a dotted `cursor_path`. Link headers and offset/limit are not handled.
- **Three auth schemes**, as the roadmap listed: API key in a configurable header, bearer token, and OAuth2 client-credentials (token fetched per operation; a cache would need invalidation and a clock, and earns nothing until an API rate-limits it).
- **No server-side incrementality.** There is no universal "changed since" for REST, so `max_cursor_value` returns `None` and every run fetches the whole collection. Incremental mode still merges by primary key — useful for an append-only endpoint, but not a bandwidth saving, and documented as such rather than implied by the mode's name.

**Records land as JSONL.** This is the other half of why §22 made `snapshot` return a format alongside a path: a REST payload routinely nests objects and arrays, and pushing that through CSV would turn them into unparseable text. A test asserts a nested `tags` array survives into the dataset as structure, and that `id`/`active`/`score` arrive as `BIGINT`/`BOOLEAN`/`DOUBLE` rather than all-text.

**Two things that are security decisions, not features.** `allow_insecure_http` defaults false, so plaintext has to be asked for — same shape as MySQL's `ssl_mode` in §21. And the URL is checked against the **link-local range**: this connector fetches an operator-supplied URL from inside the customer's VPC, so a project editor who has no AWS access could otherwise point it at `169.254.169.254` and read the task role's credentials out of the response body. Other private ranges are deliberately *not* blocked — an internal API on a private subnet is a legitimate thing to sync, and blocking it would break the ordinary case to defend against nothing. The OAuth2 error path also refuses to echo the token endpoint's response body, since a token endpoint can quote back the `client_secret` it was sent; there is a test asserting the secret does not appear in the error.

**Empty collections needed handling one level up.** A REST collection that is legitimately empty produces no records, and DuckDB cannot infer a schema from an empty file. `snapshot` reports `empty=True` (the flag §22 added), and both the API's full-sync path and the worker's now honour it: with a dataset already in place, keep the existing version rather than replacing a working dataset with an unreadable one; with no dataset yet, fail with a sentence explaining why instead of a DuckDB error.

**A bug found by looking at a screenshot, not by a test.** While browser-verifying the §23 health column, a connection showed "0% of last 1" — it had an orphaned `running` sync run, and the success rate was `succeeded / total`, so a run still in flight counted as a failure. A healthy connection mid-sync would read as 0% healthy. The rate is now over *settled* runs (`succeeded + failed`), `running` is reported separately, and the health cell gives an in-flight run the neutral dot rather than the red one. Test added.

**Testing.** `apps/api/tests/test_rest_connector.py` (20) and `apps/worker/tests/test_rest_sync_configs.py` (5) run against a real HTTP server (`apps/api/tests/rest_fixture_server.py`, started as its own process) rather than a patched `urlopen` — the same standard as the real Postgres/MariaDB/moto suites, and for the same reason: a mocked client tests the mock's shape. The fixture serves both pagination styles, all three auth schemes, and every malformed-response case (not-a-list, not-JSON, 500, 401/403). Verified end to end in a browser: built a REST connection through the wizard, tested it, discovered the endpoint's 5 columns, and synced 3 records across two cursor pages.

**Frontend.** REST is the first connector with a boolean config field, which the schema-driven wizard was rendering as a text box — a boolean typed as "true" is a wrong answer waiting to happen. Booleans now render as a checkbox, alongside §21's enum dropdowns.

**Current totals: API 208/208** (187 + 21), **worker 37/37** (32 + 5), **control-plane 13/13** (untouched).

---

### 25. Column-level profiling (this session)

`ROADMAP.md` Datasets item 1 — the first work in that pillar, and the item it flags as the highest-value, lowest-effort addition in the whole section.

**What it answers.** Preview is a hundred rows in a grid: it tells you what a row looks like and nothing else. A profile answers what someone unfamiliar with the data actually wants to know — how complete is this column, how many distinct values does it hold, what range does it span. `dataset_versions.column_profile` (migration 0019) stores, per column: type, null count and rate, distinct count, and min/max.

**Lazy, not eager — the one design decision worth arguing.** The roadmap said "computed once per dataset version and cached alongside it", which this satisfies, but the obvious reading (compute at version-creation time) would mean adding a DuckDB aggregate pass to *every* path that creates a version — upload, both sync paths, both model paths, action write-back — to produce something nobody may ever open. Computing on first request instead means one call site, no write-path cost, and the same guarantee: a version's data is immutable (a new version is a new row), so a profile is correct forever once written and never needs invalidating. Two readers racing to compute the same profile write identical bytes, so last-writer-wins is harmless rather than something to lock against. A test asserts the value is `NULL` until first asked for, present afterwards, and keyed per version rather than per dataset.

**Small correctness details that each needed deciding:**
- **min/max are text.** One JSON array holds every column's statistics, and those columns have different types. Nothing computes against these — it is display metadata.
- **Types with no ordering get `NULL` min/max rather than failing the profile.** A JSON source produces list and struct columns routinely (the REST connector in §24 makes that ordinary), and `min()` over a list either errors or answers uselessly. Those columns still get a null rate and a distinct count, which are the useful numbers for them anyway.
- **An empty dataset does not divide by zero.** Zero rows means a zero null rate, not a crash.
- **One query, not one per column.** Every column's aggregates are projected into a single `SELECT` so DuckDB scans the Parquet once however wide the table is.

**Frontend.** The dataset Explore dialog gains a **Rows / Columns** toggle. Rows is the existing SQL grid, untouched. Columns is the profile: an entirely-null column renders its rate in the error colour, and a column whose distinct count equals the row count is chipped `unique` — the two facts you actually scan a profile for. Profiling is fetched separately from preview so an aggregate pass never delays the grid.

**Testing.** `apps/api/tests/test_column_profile.py` (8) against a real uploaded file with a deliberately awkward shape — a complete key, a column with one gap, a mostly-empty column, a constant, and text. Covers the statistics, the empty-dataset case, the unorderable-type case (via a real Parquet with a list column), the lazy-compute-then-cache behaviour asserted against the database, per-version cache keying, and viewer/outsider access. Verified in a browser end to end: uploaded a file, opened Columns, and read back `75% (3)` nulls on the mostly-empty column and the `unique` chip on the key.

**Current totals: API 216/216** (208 + 8), **worker 37/37**, **control-plane 13/13** (both untouched).

---

### 26. Data quality expectations and dataset health (this session)

`ROADMAP.md` Datasets item 2 — the platform's analog of Foundry's Data Health checks, and the thing the Models pillar's build-gating item was waiting on.

**What a rule is.** One assertion about one column: `not_null`, `unique`, `value_in_range`, `regex_match`, or `column_exists` (migration 0020). Severity decides what a failure *means*: `error` fails the dataset's health, `warn` surfaces without condemning it — because "this column has some nulls" and "this join key has duplicates" are not the same kind of news. A dataset's overall status is `pass`, `warn`, `fail`, or **`none`** — that last one because "nothing is checked" and "everything checked out" are different facts and must not render the same.

**`error` is not `fail`, and that distinction is the design.** A rule that *cannot be evaluated* — its column is gone, its bounds are non-numeric, a range check was pointed at a text column — has not proven the data bad. Reporting that as a data failure sends someone looking in entirely the wrong place. Unevaluatable rules report `error`, degrade health to `warn` rather than `fail`, and never stop the other rules running: a dataset's health is the whole picture, and the first broken rule is the least useful place to stop. `column_exists` is the one rule that *does* fail on a missing column, because asserting presence is its entire job.

**When rules are evaluated — the deviation from the roadmap, argued in migration 0020.** The plan said "evaluated against every new version at creation time … one evaluation point, called from wherever `dataset_versions` rows are currently created." There are **seven** such places across two independently deployed codebases (upload, two sync paths, two model paths, action write-back, plus the worker's mirrors). That is a large blast radius, but the deciding argument is different: **a result computed at creation time is stale the moment somebody edits the rules**, which is exactly when a health badge most needs to be right. So results are computed on demand, cached on the version, and *any* rule change clears the cache for that dataset. Consumers go through one function that computes-if-absent, so all seven creation paths are covered without touching any of them. The one thing this genuinely cannot do — flagged in the migration as a decision, not an omission — is alert at the moment a bad version lands, because there is no reader to trigger the computation. Building alerting means adding real eager evaluation there.

**Null semantics, decided rather than inherited.** Nulls do not count against `unique` (SQL uniqueness does not constrain them) or against `value_in_range` (a missing value is outside no range). Double-reporting what `not_null` already covers would make a single gap look like three problems. There is a test pinning it.

**Bad configuration is refused at save time**, not discovered on a later health read: an invalid regex, a range with no bounds or with min above max, a non-numeric bound, and an unknown rule type are all 422s on the form the user is looking at. The one place rule config reaches SQL — range bounds — refuses anything that is not a number rather than interpolating it.

**Frontend.** The dataset Explore dialog gains a third tab, **Checks**, alongside Rows and Columns: current health, each rule with its result and failing-row count, and a form to add one (the form shows min/max or pattern inputs only for the rules that take them). Editors define rules; viewers see health and results but get no controls.

**Testing.** `apps/api/tests/test_expectations.py` (14) against real Parquet written by the real upload path, so a "fail" means DuckDB counted bad rows. Covers each rule type against data engineered to break it, the rules that hold, null semantics, `error`-vs-`fail` on a missing column and on a type mismatch, severity changing the overall verdict, lazy evaluation then caching, cache invalidation on both rule creation and deletion, every bad-config rejection, the duplicate-rule conflict, role floors, outsider 404, and the audit trail. Verified in a browser: added a not-null check and a warn-severity range check through the form and watched health go to `fail` with `1 null value(s)` and `1 value(s) outside the range`.

**Current totals: API 230/230** (216 + 14), **worker 37/37**, **control-plane 13/13** (both untouched).

---

### 27. Upstream model triggers — pipelines (this session)

`ROADMAP.md` Models item 1, which that document calls "the single most-referenced missing piece across the existing 'not started' notes." It was also the platform's most visible broken promise: `trigger_mode` has accepted `upstream` since migration 0003, the PATCH route validated it, and the shared TypeScript contract listed it — and a model set to it **silently never ran**. This is the change that turns isolated transforms into pipelines: one model's output dataset version is the next model's input version, so A feeds B feeds C without anybody scheduling anything.

**Due-ness is a watermark, not a queue.** `models.upstream_watermark` (migration 0021) records the newest input `dataset_versions.created_at` a model has already reacted to; `list_due_upstream_models()` returns models with an input version newer than it. That makes 'upstream' the same machine as 'cron' — a timestamp column the worker polls and advances after acting — rather than a second mechanism. The two alternatives are argued in the migration: a trigger on `dataset_versions` INSERT would be exact but puts scheduling policy where it cannot be retried or rate-limited, and would enqueue runs inside a transaction that might still roll back; an outbox table is the right answer at scale but is a second thing to poll, drain and garbage-collect for no behavioural gain at this size.

**A self-loop guard is required, and the roadmap didn't anticipate it.** A model whose output dataset is also one of its inputs is legal today, and would re-trigger itself on its own output forever, one run per poll pass, with no way to stop it short of editing the model. Versions carrying `produced_by_kind = 'model'` and this model's id are excluded from its own due-ness test.

**What is documented rather than solved.** Two models feeding each other (A→B→A) still oscillate: each run legitimately produces a version the other watches. Detecting that needs the whole dependency graph, not one model's inputs, so it belongs with the DAG view (Models item 2) where the graph is actually materialised — half-solving it here with a hop counter would be a worse answer that looks like a fix. Likewise, a chain settles **one poll pass per link**: the downstream model's input version only exists once the upstream run has committed, which is after discovery ran. Resolving a whole chain in one pass needs topological order — again item 2.

**Coalescing, so a slow model can't build a backlog.** A model with a run already `queued` or `running` is not re-enqueued. Ten versions landing between two passes produce one run, not ten. The watermark only advances when a run is actually enqueued, so a version arriving mid-run still triggers the next one rather than being swallowed.

**A three-valued-logic bug caught by the first test run.** The self-loop guard was first written `NOT (produced_by_kind = 'model' AND produced_by_id = m.id)`. Those columns are nullable — an uploaded version leaves both `NULL` — and `NOT (NULL = 'model')` is `NULL`, not `TRUE`, so the predicate filtered out **every uploaded version**: the guard silently broke the common case in exactly the way the feature exists to fix. Now `IS NOT DISTINCT FROM` on both sides, in the migration and in the worker's watermark query, with the reasoning written at the SQL.

**The API refuses an upstream model with no inputs** (422, rolled back). A model with nothing to watch can never fire — the same silent no-op this section exists to remove — so it is refused rather than stored. Changing the trigger mode at all clears the watermark: switching *to* upstream should fire once promptly (`NULL` means `-infinity`, matching §14's convention that a `NULL next_run_at` is due now), and switching *away* must not leave a stale watermark that swallows the first version after switching back.

**Frontend.** The models table's `Schedule` column is now `Trigger`, and upstream models read `on new input data` with either `due now` or `since <the watermark>` — the same shape the cron rows use for `next:`. The edit dialog's trigger dropdown gains "When inputs change", with the hint explaining the chaining, and Save is disabled for an upstream model with no inputs so the 422 is pre-empted rather than demonstrated.

**Testing.** `apps/worker/tests/test_model_runs.py` (+5) against real Postgres and real Parquet: firing on a new version, not re-firing without one then re-firing when one lands, the self-loop guard, coalescing while a run is in flight, and a genuine two-model chain asserting B fires on the pass *after* A's run commits and that A does not re-fire on its own output. `apps/api/tests/test_models.py` (+1) covers the no-inputs refusal (including that the rejected PATCH rolls back), setting mode and inputs in one request, and the watermark reset. Verified end to end in a browser: switched two chained models to "When inputs change", then ran four worker passes — both caught up on pass 1, B ran again on pass 2 for the version A's pass-1 run produced, pass 3 was quiet, and a manual run of A pulled B along on pass 4.

**Current totals: API 231/231** (230 + 1), **worker 42/42** (37 + 5), **control-plane 13/13** (untouched).

---

### 28. The pipeline graph (this session)

`ROADMAP.md` Models item 2 — which that document calls "the single biggest visible Foundry-parity win in this pillar", and the item three other roadmap entries were deferring a real graph problem to. It follows §27 directly: upstream triggers made pipelines possible, and this is the first thing in the product that can *show* one.

**A different question from lineage, so a different endpoint.** `lineage_for_dataset` walks outward from one node and renders Mermaid — the right tool for "what touches this dataset". `GET .../pipeline` answers "what does this whole project look like", every dataset and model at once with each model's last-run state on it. Adding a flag to the walk would have made one function answer two questions badly.

**The layout is computed on the server, and that is the load-bearing decision.** Each node comes back with a `layer` (longest-path layering via Kahn's algorithm) and a `position` within it, so the browser lays a DAG out with arithmetic and SVG beziers instead of a graph-layout library. The roadmap said to "build it on the same graph-rendering choice as Datasets item 5"; the choice turned out to be **no library at all**. Two reasons, in order of weight: the graph logic then lives somewhere it can be tested against real rows in pytest rather than only by driving a browser, and a real dependency stays out of the web app for graphs that are project-sized. A test asserts the property the frontend actually relies on — *every* edge points from a lower layer to a higher one — rather than checking specific coordinates.

**Cycle detection, which migration 0021 explicitly deferred here.** Layering and cycle detection are the same traversal: whatever still has unsatisfied inputs when Kahn's queue drains cannot be ordered. Those nodes are grouped by reachability (so two independent loops report as two cycles, not one blob), given a layer past their placed inputs so they still draw somewhere sensible instead of vanishing, and returned in `cycles`. The page draws them in the danger colour with an "in a cycle" label and a banner naming the actual consequence: a model in a loop set to run on new input data re-triggers itself indefinitely. **Detecting is not preventing** — the platform still lets a cycle be *created*, because refusing an edit is a separate decision about what an existing model edit is allowed to do. That is now Models item 7 rather than something smuggled in here.

**Nothing is computed that isn't already stored.** Dataset health (§26) is read from the cached column only, never evaluated: this is one request for a whole project, and computing expectations per dataset would turn a page load into a DuckDB pass per node. A dataset nobody has opened reports `null` health rather than a number bought at that price. There is a test for both halves — absent before anything evaluates it, present after.

**Frontend.** A project-level `Pipeline` page, in the sidebar beside Overview rather than in the resource list (both are whole-project views, and the pipeline has no count of its own). Nodes are colour-keyed on the left edge by last-run status for models and health for datasets, with drag-to-pan, zoom controls, and click-to-select revealing a detail bar with a jump through to that resource's own page. Edges highlight when either end is selected — the cheapest way to read "what feeds this" on a dense graph.

**Testing.** `apps/api/tests/test_pipeline.py` (6) in its own project, deliberately: the endpoint returns *everything* in a project, so sharing a fixture with tests that create models would make the assertions depend on test order. Covers the layering invariant, the fields the view renders, lazily-cached health appearing only once something has evaluated it, a real cycle built through the API (feed the second model's output back into the first) asserting the exact membership, the empty project, and outsider access. Verified in a browser: built a four-node chain plus a never-run model, checked all five edges drew, selected a node and read its detail bar, exercised zoom, then closed the loop and watched the cycle banner and red nodes appear.

**One thing the screenshots make obvious and this does not fix:** a model's output dataset is named after the model, so a chain reads "Double → Double". That is existing behaviour from the models layer, not the graph's doing, and renaming outputs is a product decision for the Models pillar rather than a change to make while drawing them.

**Current totals: API 237/237** (231 + 6), **worker 42/42**, **control-plane 13/13** (both untouched).

---

### 29. Data quality gating on model runs (this session)

`ROADMAP.md` Models item 3 — and the item this session's own earlier work made urgent rather than merely nice. §26 made bad data *detectable*; §27 made it *propagate automatically*. A model on an upstream trigger runs the moment its input gains a version, and its output is the next model's input, so one bad upload now reaches the end of a chain with nobody having looked at it. This closes that loop.

**Three modes, one of which the roadmap didn't ask for.** `models.input_health_policy` (migration 0022): `ignore`, `warn`, `block`. The item named refuse-or-flag; `warn` is the flag, and it earned its place for a reason worth stating — it is the mode you turn on *first*, to find out how often blocking would have fired, before committing to breaking your own pipeline to find out. It records exactly what `block` would have recorded and runs anyway.

**The default is `ignore`, deliberately.** Defaulting to `block` would silently change what every existing model does the moment the migration applies: a model that has run fine for months would start failing because someone once added a check to one of its inputs. The roadmap said "let a model's run be *configured* to refuse", and configured is the operative word.

**The gate holds on every path a run can start from, which is what made this a real piece of work.** The interactive API path had the evaluator already; the automated paths — cron, upstream triggers, queued Python — all start in the worker, which did not. A gate that only held where a human was watching would be precisely the advertised-but-does-nothing promise §27 existed to remove, and the automated case is the one that most needs gating. So the evaluator is mirrored into `apps/worker`'s `dataset_engine.py`, the same deliberate duplication as `storage.py`, `connectors.py`, and the rest of that file, with a test asserting `RULE_TYPES` is identical on both sides (it parses the API's source with `ast` rather than importing it — the two apps have separate virtualenvs, and the assertion should fail on real drift, not on the API growing a dependency).

**It incidentally supplies the reader §26 said was missing.** Migration 0020 flagged one thing lazy evaluation could not do: "alert at the moment a bad version lands, because there is no reader to trigger the computation." A gate checking its inputs before every run *is* that reader — it computes health when nothing has cached it, so `block` is enforced against data nobody has opened. That is also its cost, stated in the migration: a gated run pays one DuckDB pass per input the first time each version is seen. An `ignore` model short-circuits before any of it.

**Only `fail` gates.** `warn` health means only warn-severity rules or *unevaluatable* ones tripped, and §26's whole `error`-is-not-`fail` argument applies again: a rule that could not run has not proven the data bad, and stopping a pipeline on it would punish a broken rule. `none` — no rules at all — is not evidence of anything either. There are tests for both.

**Evidence rides on the run, not on a later re-derivation.** `model_runs.input_health` records what the gate saw per input at the moment it decided. Health is cached per dataset *version* and invalidated whenever the rules change, so asking "why did this run block" a week later could give a different answer than the one the run was actually refused on. A blocked run is a thing someone will come back and argue with; it has to carry its own evidence. An ungated run stores `NULL`, not `[]`, so "this was not gated" and "this was gated and found nothing" stay distinguishable.

**A blocked run is a finished run.** It is written `failed` with `started_at` set, not left queued — 0021's coalescing guard suppresses re-enqueueing while a run is `queued` or `running`, so a blocked run that never terminated would wedge the model permanently. There is a test asserting a blocked upstream model settles rather than retry-storming.

**Frontend.** The model edit dialog gains an "Input data quality" selector spelling the modes out in product terms rather than enum names ("Don't run if an input failed its checks"), the models list shows a "blocks on failing input" note under the trigger, and a blocked run renders its reason in full — which dataset, which column, how many rows.

**Testing.** `apps/api/tests/test_models.py` (+6) and `apps/worker/tests/test_model_runs.py` (+6), both against real uploaded data with a genuine null in a not-null column rather than a mocked verdict. Between them they cover all three modes on both paths, the compute-if-absent behaviour asserted directly against `dataset_versions.expectation_results`, passing input not blocking, an unknown policy refused at 422, the blocked-run-still-settles case, and the API/worker rule-type parity. Verified in a browser: ran the model ungated on bad data (it succeeded, no evidence recorded), switched to blocking through the dialog, and watched the same run refuse with `Dirty source (id: 1 null value(s))`.

**Current totals: API 243/243** (237 + 6), **worker 48/48** (42 + 6), **control-plane 13/13** (untouched).

---

### 30. Refusing a dependency loop (this session)

`ROADMAP.md` Models item 7 — an item that only exists because §28 created it. The pipeline graph reports cycles; the platform still let you make one. That is not just untidy: a model in a loop with `trigger_mode='upstream'` re-fires on every worker pass forever, because each run produces a version the loop is watching, and migration 0021's self-loop guard cannot see it (it only ever looks at one model's own inputs, so A → B → A is invisible to it).

**Where and when.** `_validate_and_set_inputs`, via a recursive walk over every dataset downstream of the model's own output; a proposed input that appears in that set is a 422 on the form. `UNION`, not `UNION ALL`, so a pre-existing loop elsewhere in the project cannot make the walk run forever. Checked at edit time and *only* there, because that is the only moment a cycle can appear: a model's output dataset is created by its first run and nothing points at a brand-new dataset yet, so running a model can never close a loop that saving it did not.

**Existing cycles are grandfathered**, which is the question the roadmap item left open. The check validates the *proposed* input set, so a loop created before this existed keeps working until somebody edits one of its models — at which point the edit is refused until they break it, and editing your way *out* is always allowed. Force-breaking on next edit would mean silently deleting an input someone configured on purpose; the Pipeline page naming the loop is a better place to be told. There is a test that writes a cycle straight to the database (the only way to get one now, and exactly the state an older deployment can be in) and asserts the graph still reports it.

**Testing.** `apps/api/tests/test_pipeline.py` (+1, and the old cycle test rewritten): the two-hop loop refused, the direct self-reference refused, the *sibling* case still allowed — a second model reading the same output is not a loop, and a check that said otherwise would be a walk in the wrong direction — plus the grandfathered case and editing out of it.

---

### 31. Dataset schema policy (this session)

`ROADMAP.md` Datasets item 3. §26 and §29 are about bad *values*; this is bad *shape*. A column disappearing or changing type breaks every downstream model, object mapping and canvas widget reading it, and today it lands silently and is discovered three layers away at runtime.

**`datasets.schema_policy`** (migration 0023): `permissive` (default) or `strict`. The default matches §29's reasoning exactly — nothing should silently start failing pipelines the day a migration applies. The roadmap's suggestion that strict be the default *for anything with a downstream dependency* is deliberately not implemented: "has a downstream model" is a property that changes without the dataset's owner doing anything, so it would make a policy that turns itself on.

**Adding a column is allowed under strict, and that is the design.** Taking "must match the previous version's schema" literally would reject the most common and most harmless drift there is — a source gaining a field — and a policy people have to keep switching off is a policy nobody leaves on. What breaks a downstream reader is a column going away or changing type; those are what strict refuses. **Any retype is breaking, including widening ones**: `int → bigint` is safe and `text → int` is not, but deciding which is which means encoding a type lattice per source dialect, and being subtly wrong there is worse than being bluntly right, because a false negative silently breaks the exact thing this protects. The escape hatch is deliberate and auditable — switch to permissive, let the version land, switch back — and the refusal message says so.

**Enforced in a trigger, which reverses migration 0021's argument and is worth being explicit about.** 0021 argued against putting logic in a database trigger, and that still holds for what it was about: enqueueing model runs is *scheduling policy*, which needs to be retried and rate-limited in application code. This is a different kind of thing — an integrity constraint on a table, the same tool 0003's `enforce_dataset_workspace()` already uses. The deciding factor is the alternative: **seven** writers across two independently deployed codebases insert into `dataset_versions`, so an application-layer check holds only until somebody forgets, and the eighth writer inherits nothing. In the trigger it holds for every writer that exists and every one that doesn't yet.

**The cost of that choice, paid honestly.** A refusal arrives as a database error rather than a check the code made, so it has to be translated. It carries its own SQLSTATE (`AF001`) precisely so it can be told apart from every other constraint on the table. Callers that own a record which must be closed truthfully — a model run, a sync run — translate it into `DatasetEngineError` so it lands in their existing failure handling and the run is written `failed` with the reason rather than left `running`. Callers with no such record (upload) leave it alone: `main.py`'s handler turns it straight into a 422, which is the whole answer there. The worker translates it in both its version-writing sites for the same reason STATUS §16 had to catch `StorageKeyError` — an untranslated error escapes the per-item isolation and takes down the whole poll pass, and there is a test asserting a second, unrelated model still runs in a pass where one was refused.

**Frontend.** The schema policy sits in the dataset Explore dialog's **Columns** tab — shape belongs with the columns, the same way the Checks tab owns values — as a two-option selector spelled out in product terms ("Refuse removing or retyping a column"), with the "new columns are always allowed" rule stated next to it rather than left to be discovered.

**Testing.** `apps/api/tests/test_schema_policy.py` (8) driven through a model's output dataset, because that is the only way to produce a *second* version of a dataset through the public API — re-uploading under the same name is a 409 — and it is also the case that matters. Covers the permissive default, removal and retype refused, addition allowed, the refused version not rolling `current_version`, the run recorded `failed`, the permissive escape hatch and the new shape becoming the baseline afterwards, strict never blocking a first version, an unknown policy at 422, and a viewer refused. `apps/worker/tests/test_model_runs.py` (+1) covers the automated path and the batch isolation. Verified in a browser: set a model's output dataset to strict from the Columns tab, re-ran the model with a narrower query, and read back `columns removed: val - set this dataset's schema policy to permissive to allow it`, with the dataset still at v1.

**Current totals: API 252/252** (243 + 9), **worker 49/49** (48 + 1), **control-plane 13/13** (untouched).

---

### 32. Model definition history (this session)

`ROADMAP.md` Models item 5. The asymmetry it names has been in the schema since 0003 and got worse with every step this branch added: `model_runs.output_version` points at the exact dataset version each run produced, so run history is auditable against *data* — but nothing recorded the *code*. Editing a model overwrote its source in place, so "which query produced this number?" was unanswerable for any run older than the last edit. Since §27 a bad edit also propagates to every downstream dataset on the next worker pass, unapproved.

**`model_versions`** (migration 0024): an append-only table of numbered snapshots, the same shape as dataset versioning, with the live `models.code` still holding the current one — nothing about the current-state read path changed. The migration backfills a v1 for every existing model, so "every model has at least one version" holds from that moment and no read path has to special-case an empty history.

**Rollback appends, it does not rewind.** Restoring v2 writes a new v5 whose content equals v2's. History then records that somebody reverted, rather than erasing the thing being reverted from, and a run stamped with a version still resolves to exactly one piece of code — rewinding would make `model_runs.model_version` ambiguous the moment anyone rolled back twice. A test asserts the version being rolled back *from* survives the rollback.

**A version snapshots the code and the inputs together.** Aliases are half the contract: restoring code that says `FROM orders` into a model whose inputs were since renamed would restore something that cannot run. The inputs are copied into jsonb rather than referenced through `model_inputs`, for the same reason §29 stores what the gate saw on the run — a history record must not change when the live state does. Restoring goes through the same input validation an ordinary edit does, so a set that was legal then and closes a dependency loop now (§30) is refused the same way.

**Where the line is drawn.** Trigger mode, cron schedule, input health policy, name and description are explicitly *not* definition changes: they are how and when a model runs, not what it computes, and versioning them would fill the history with entries nobody would ever roll back to. Saving identical code is also not a change. `language` is immutable after creation, so it needs no version of its own. There is a test for each half of that boundary.

**The run stamp is read at execution, not enqueue.** `model_runs.model_version` is set by the worker when it picks a run up, because the code that actually runs is the code read then — a model edited between enqueue and execution runs the new one, and the record has to say so. Runs that predate the migration are `NULL`: genuinely unknown, and pointing them at the backfilled v1 would claim knowledge the platform does not have.

**Not built, deliberately:** a side-by-side diff. It needs either a dependency or a hand-rolled LCS, and the versions are stored, so it can be added later without a schema change. The history dialog expands any version's code instead.

**Testing.** `apps/api/tests/test_model_versions.py` (9): the v1-on-creation invariant, appends on code and input edits, the four non-definition changes that must *not* append, identical code not appending, restore-appends-rather-than-rewinds, inputs restored with the code and the model still running afterwards, two runs carrying two different definitions, a missing version at 404, and the viewer/editor floors. `apps/worker/tests/test_model_runs.py` (+1) covers the edited-between-enqueue-and-execution case directly. Verified in a browser: opened History on a model with a bad second version, expanded v1's code, restored it, and watched v3 appear labelled "reverted to v1" with v2 still in the list — then ran the model and confirmed the new run is stamped v3.

**Current totals: API 261/261** (252 + 9), **worker 50/50** (49 + 1), **control-plane 13/13** (untouched).

---

### 33. Interactive lineage (this session)

`ROADMAP.md` Datasets item 5, the half of §28's graph work that was left. Two things turned out to be true that the item only half-anticipated.

**It was as much "surface lineage at all" as "make it interactive".** The Mermaid lineage endpoint has existed and been tested since §9 — and nothing in the frontend had ever called it. A user could not see lineage in the product by any route. So this is the feature's first appearance, not a re-skin.

**Reusing the endpoint beat reusing the renderer.** The item asked lineage to reuse "whatever graph-rendering approach Models item 2's pipeline DAG view settles on". `GET .../pipeline` now takes `focus=dataset:<id>` (or `model:<id>`) and returns that node's connected component, layered by the same code, marked with `is_focus`. One endpoint, one response shape, and `components/pipeline-graph.tsx` — extracted from the Pipeline page — renders both. There is no second graph implementation to keep in step, which is the failure mode STATUS's rough edges already tracks four instances of.

**The component walk is undirected, deliberately.** A dataset's lineage is both what produced it and what reads it, and a sibling model reading the same input belongs in the same picture — it is exactly what someone tracing "why is this number wrong" needs to see. A directed walk would answer a narrower question than the word lineage promises.

**The Mermaid endpoint stays.** The spec calls for lineage "exportable as JSON or Mermaid", and the walk is still the right tool for a text export; the graph endpoint answers a different question with a different shape.

**Testing.** `apps/api/tests/test_pipeline.py` (+2): the focused graph excludes an unrelated dataset in the same project, includes both directions, marks exactly one focus node (and marks none on the unfocused view), stays a properly layered graph rather than a filtered list, and refuses a malformed focus (422) or one naming a node outside the project (404). Verified in a browser: the project-wide page still draws all four edges after the renderer was extracted, then opened Lineage on a model-output dataset and confirmed the unrelated dataset is absent, the focus node is outlined, and zoom and click-to-detail work inside the dialog.

**A stale-server slip worth recording**: the first browser run "failed" because the dev API server had been started before the `focus` parameter existed, and FastAPI silently ignores unknown query params — so it returned the whole graph and the assertion fired correctly against genuinely wrong data. The pytest run was green throughout. Restarting the dev server is part of verifying an API change in the browser.

**Current totals: API 263/263** (261 + 2), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 34. Dataset forking (this session)

`ROADMAP.md` Datasets item 6, and the last item in that pillar that was not waiting on a decision. `POST .../datasets/{id}/fork` copies one version into a new dataset with `origin = 'fork'` (migration 0025) and provenance columns saying exactly what was copied.

**It got more useful than it looked when it was written.** §29's run gating and §31's strict schema policy are both things you want switched on in production — and both mean you now need somewhere *else* to try the change that would trip them. Forking is that somewhere.

**Deliberately still the small version.** Nothing here knows how to merge a fork back. The item itself warns that real branch/merge semantics are the large lift, and deciding what a merge means for tabular data is a design question, not an extra endpoint. It stays unbuilt until real usage shows forking is not enough.

**Three decisions worth carrying forward:**
- **The bytes are copied, not shared.** "New, independent dataset" is the requirement, and pointing two datasets at one storage key would make deleting the original silently empty the fork — delete removes the dataset's whole prefix. There is a test that deletes the source and then queries the fork.
- **The quality rules travel; their results do not.** Forking is for trying a change and seeing whether it still holds up against the same standard, so arriving with no standard would defeat it — but a result is computed per version and the fork's v1 is new. Tested both ways, including that deleting the source's rule leaves the fork's copy alone.
- **A fork starts permissive** whatever the source's schema policy was. Inheriting `strict` would make the thing you forked *in order to experiment with* refuse the experiment.

**`origin = 'fork'` rather than reusing `'upload'`.** A fork did not come from a file somebody uploaded, and labelling it as though it did would make the origin column lie in the one place a user looks to answer "where did this come from". One enum value against every future reader's confusion.

**A real bug the tests caught, and the fix that came out of it.** `forked_from_dataset_id` was first written as a foreign key with `ON DELETE SET NULL`, which nulls only that column and leaves `forked_from_version` behind — violating the both-or-neither CHECK the moment the source was deleted, which is precisely the case this feature promises to survive. The fix was to drop the foreign key entirely: this is a *historical statement* ("copied from dataset X at version 2") and it does not stop being true when X is gone. That is the same reasoning §29 uses for `input_health` and §32 for the input snapshot, and `dataset_versions.produced_by_id` already sets the precedent for a deliberately non-referential id in this schema.

**Provenance is not a pipeline-graph edge.** §28's graph answers "what recomputes when this changes", and a fork never recomputes — drawing an edge would assert a live dependency that does not exist. The dataset row shows `from v1` instead.

**Testing.** `apps/api/tests/test_dataset_forks.py` (7): the copy is real data rather than a pointer, the fork survives its source's deletion with provenance intact, forking a *named* version recovers a shape the source has since dropped, rules travel but results and later rule deletions do not, a fork starts permissive from a strict source, name clash at 409 and missing version at 404, and the role floors. Verified in a browser: forked a model output at v1 while its current version was v2, confirmed the picker offers both, and read back a fork carrying the column the source had already dropped — then deleted the source and queried the fork.

**Current totals: API 270/270** (263 + 7), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 35. The OpenSearch instance store cutover (this session)

`ROADMAP.md` Objects item 1 — the item both that document and §14 called the biggest structural gap in the pillar, and the one §14 deliberately stopped short of. **Flagged up front: this is the first item this branch has shipped without an end-to-end run against the real thing.** There is no OpenSearch in this environment. What that means precisely is in "what is and isn't verified" below.

**The seam is the actual change.** §14 said the cutover "replaces the Postgres-connection-shaped functions with calls through the gateway" — but replacing them would have deleted the Postgres path on the same day the new one was switched on. Instead `PostgresInstanceStore` implements the *same* `InstanceStoreGateway` Protocol over the request's RLS-scoped connection, `store_for(conn)` picks between them, and `routes/objects.py`/`routes/actions.py` go through that one call. `services/instances.py` keeps every SQL statement and becomes the layer beneath. Postgres stays as the fallback and the local-dev default, which is why **all 43 existing objects/actions tests pass through the seam unchanged** — the roadmap's "re-verify every existing test against the new store" half, done by construction rather than by rewriting them.

**Instance ids became uuid5 so the cutover is not a breaking API change.** The doc id was `f"{source_id}:{primary_key}"`; the API's `InstanceOut.id` is a `UUID` and `action_runs.instance_id` is a uuid column. A `uuid5` of the same string keeps the deterministic upsert (re-syncing a row updates it rather than duplicating, with no round trip to ask whether it exists) while keeping the identifier's *type* the same on both stores. A cutover that changed the type of a public identifier would be a breaking API change dressed up as an infrastructure one.

**No dual-write, and the reason is a property rather than a preference.** The roadmap asked for "a cutover flag or dual-write period". Because every id is derived from `(source_id, primary_key)`, `backfill()` is idempotent — a second pass rewrites exactly the same documents. That turns the procedure into **backfill, flip, backfill again**, where the second pass is the catch-up for anything written between the first and the flip. Dual-write buys the same safety for considerably more moving parts, and it is the thing that fails quietly when one of the two writes does.

**Two things found by doing it that neither document anticipated:**
- **`action_runs.instance_id` had a foreign key into `object_instances`.** Once instances live in OpenSearch that constraint is unsatisfiable — and `ON DELETE SET NULL` meant it would have degraded to silently forgetting which instance every historical write-back touched rather than failing loudly. Migration 0026 drops it; the column stays a uuid, now a historical statement in the same sense as §34's fork provenance and `dataset_versions.produced_by_id`. Found by writing the backfill's test, not by reading the schema.
- **`opensearch-py` does not ship `AsyncOpenSearch` on its own.** The async client needs `aiohttp`, which comes from the `[async]` extra and was not in `requirements.txt`. The gateway §14 shipped as "complete and production-shaped" would have raised `ImportError` the first time a deployed stack actually used it. Now `opensearch-py[async]==2.7.1`, with the reason written at the pin.

**One small design correction:** the gateway hardcoded `use_ssl=True`. The endpoint's scheme now decides — a deployed domain is always `https` so production is unchanged, and it is what makes the class testable over a local socket instead of untestable by construction.

**What is and isn't verified.** `tests/opensearch_fixture_server.py` is a real HTTP server in its own process implementing the REST subset the gateway uses — index exists/create, bulk upsert, delete-by-query over term+range filters, search with filter/sort/from/size/total, get, partial update — driven through the genuine `opensearchpy` client, the same standard `rest_fixture_server.py` set in §24. That proves the requests this gateway forms and the responses it parses are correct, and it caught the TLS and dependency problems above. It is **not** OpenSearch: no analyzers, no mapping enforcement, no refresh semantics, no sharding. The first deployment against a real domain remains the last verification step, and the fixture's own docstring says so rather than implying coverage it does not have.

**Testing.** `apps/api/tests/test_instance_store.py` (9): idempotent upsert, stale-instance removal not touching a sibling source, reads scoped by object type (a doc under another type is invisible), paging and newest-first ordering plus the `search_after` refusal past the result window, property merge and a missing instance refused, index-per-workspace isolation — then the cutover itself: the whole instance API on the OpenSearch store with nothing landing in Postgres, a 404 still a 404, and the backfill moving data across, remapping `action_runs.instance_id`, and running twice without duplicating.

**Current totals: API 279/279** (270 + 9), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 36. The Object Explorer (this session)

`ROADMAP.md` Objects item 2, sequenced directly after §35 because it is the read the cutover was for. `GET .../object-instances?q=&type_id=` searches every instance in a workspace at once; the objects page gains an **Explore instances** panel over it.

**Like lineage in §33, this is also "surface it at all".** The per-type instance endpoints have existed since §10 and nothing in the web app called them either — a user could not see a single object instance in the product by any route. The Explorer is the first place instances appear.

**Workspace-scoped, not project-scoped.** Object types are workspace-wide, so an explorer that stopped at a project boundary would show a partial ontology and present it as the whole one. It lives on the project's Objects page because that is where the ontology is administered, but it reads across the workspace, and the tests assert against the types they create rather than workspace totals *because* of that — a global count would be asserting test isolation the feature deliberately does not promise.

**`search()` is on the Protocol, so the Postgres store implements it too — honestly.** It is `ILIKE` over the properties JSON: no tokenisation, no relevance, no prefix semantics, and "ada" matches a department called "Adaptive". That is the real capability of the fallback, it is written into `services/instances.py` in those words rather than left to be discovered, and it is exactly why the roadmap sequenced this item after the cutover. The OpenSearch implementation uses `multi_match` with `phrase_prefix` across `properties.*` and `primary_key`, so a half-typed value still matches.

**Each row says what it is.** A cross-type result set is meaningless otherwise, so the response carries the type's id, api_name and display_name — resolved from Postgres, which still owns the ontology definition whichever store held the instances. A row whose type has been deleted since indexing is dropped rather than rendered as an orphan. The table shows the *union* of property names across the page (capped at six), not the intersection: a column only some rows have is still worth seeing.

**Testing.** `apps/api/tests/test_instance_store.py` (+3, parametrised over both stores for the search case): both types present in one unfiltered result each labelled with its type, search by a property value across types, filter by type, query and filter ANDed, no matches, paging, and an outsider refused. Verified in a browser: two object types synced in one workspace, both appearing in one table with their own columns; searching `Widget` narrowed to the Part row; the type filter narrowed to the two Person rows.

**Current totals: API 282/282** (279 + 3), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 37. Link traversal — the ontology becomes connected (this session)

`ROADMAP.md` Objects item 3, described there as a UI item: "add an *explore* panel on an instance showing its linked objects, with click-through navigation across the link graph". The panel exists and does that. But the item's first hour was not UI work.

**There were no links to traverse.** `link_types` (0003) records `from_object_type_id`, `to_object_type_id` and a cardinality — a statement that Person relates to Department, and nothing whatsoever about *which* Person relates to *which* Department. `grep -rn "link_instances\|object_links" packages/db/migrations/*.sql` returned nothing across all twenty-six migrations. So the item was a data-model decision wearing a UI item's clothes, and it had to be made before a single component could be written.

**Links are derived by joining on property values, not stored as edge rows** (migration 0027 adds `link_types.from_property` / `to_property`). The reasoning, argued at length in the migration itself: an object instance is not authored here, it is *materialised* from a dataset column mapping (§14) and re-materialised on every sync, with vanished rows deleted. The relationship arrives in that same data — a Person row synced from a relational source already carries the department code pointing at a Department row. A `link_instances` table would have meant (a) a second sync mechanism with its own staleness, running beside the one that produces the rows its edges point at, and (b) a reconciliation problem on every resync, since instance rows are upserted by `(source_id, primary_key)` and edges keyed on instance ids would have to be diffed and pruned in step or point at instances that no longer exist. Deriving cannot go stale because there is nothing to keep in sync: the answer is a question asked of the current data at read time. The cost is honest and recorded — a traversal is a query per link per instance, so it scales with fan-out, and that is where a materialised edge cache would go if fan-out ever became the problem. Nothing in the API shape assumes derivation, so that change would stay behind the service.

**`'$primary_key'` is a reserved join reference, and it is necessary rather than convenient.** The far end of a foreign key is nearly always the referenced row's *key*, and an instance's primary key is a first-class field, not an entry in its properties JSON — without the sentinel the commonest join in relational data would have been inexpressible. The `$` prefix cannot collide with a property api_name (which must start with a lowercase letter), so no property can ever be shadowed.

**The join needed a new store operation, not the one that already existed.** The Explorer's `search()` is `multi_match`/`phrase_prefix` (OpenSearch) and `ILIKE` (Postgres) — reusing it would have answered "who works in ENG" with the people in "ENG West", and returned them with a straight face. `find_by_property()` is on the Protocol and is an exact equality on both stores. Two details fell out of that: the OpenSearch index mapping is now *declared* (a `dynamic_templates` entry mapping string properties as `text` with a `keyword` subfield at `ignore_above: 8192`) rather than left to dynamic defaults, because equality needs a keyword subfield to exist and the default `ignore_above: 256` would silently stop indexing longer join keys; and the query sends two `should` clauses — `properties.x.keyword` and `properties.x` — requiring one, so a property mapped as a long or a boolean matches without the service having to trust the object type's *declared* `data_type`, which describes the ontology rather than what the mapper actually wrote.

**Joins are on the text form of the value** (`instance_store.join_key`, shared by both stores). The two sides of a link are two independently mapped datasets, so a department code can arrive as an integer on one side and text on the other; a type-strict comparison would find nothing in exactly the case the feature exists for. `None` means "no key" — a null property points at nothing, not at every instance whose property is also null. `1` and `1.0` are different keys, which is also true of the upstream data.

**Both-or-neither, and mappable in place.** The property pair is nullable with a `CHECK` that they are set together: half a join is not a weaker join, it is an unanswerable question. Every link type that existed before 0027 stays a valid ontology statement and is simply *absent* from traversal results rather than present-and-empty — "no links found" and "this link has no join" are different facts. `PATCH .../link-types/{id}` maps the join on an existing link, because delete-and-recreate as the only route would break every reference to a link people already built their ontology around; only the join is patchable, since changing an endpoint or the cardinality makes it a different relationship wearing the same name.

**One response per instance, not one per link.** `GET .../object-types/{t}/instances/{i}/links` returns every mapped link at once, each reordered into the instance's own point of view (`direction`, `near_property`, `far_property`, `far_type_*`) so the client never works out which end it is on. A **self-link is returned twice**, outbound and inbound, on purpose: Person→Person by manager means "my manager" one way and "my reports" the other, and one group would answer neither. Each group carries a `total` plus a first page of ten, since a one_to_many link can traverse to thousands.

**The panel keeps a trail rather than a route per hop.** Traversal is lateral — Ada → Engineering → Alan — so a route per instance would put every hop in browser history and lose the path you came by, which is the context that makes the walk legible. `components/instance-links.tsx` holds the trail explicitly and shows it as breadcrumbs; a hop needs no refetch, because a link group already carries the far instances in full. Reachable from both the per-type instance table and the workspace-wide Explorer.

**Testing.** `apps/api/tests/test_link_traversal.py` (12 tests): join validation against the type's real properties, half-a-join refused, mapping an unmapped link in place and clearing it again, and five traversal tests **parametrised over both stores** — a link that traverses differently depending on which store is configured is wrong on one of them. The fixture data is chosen for the failure modes: `ENG`/`ENGW` (one code a prefix of the other) proves the join is exact, an integer `manager_id` against a text primary key proves the text-form join, a blank `manager_id` proves a null points at nothing. The OpenSearch fixture server gained dotted/`.keyword` field resolution and real `should`/`minimum_should_match` handling — a fixture that quietly required both should-clauses would have passed the wrong query. Verified in a browser end to end: mapping a join through the dialog and watching the column change from "not traversable" to `manager_id = primary key`; traversing from the Explorer; clicking Grace → Ada and getting Ada's two reports plus "no manager_id on this object, so this link points at nothing"; walking back up the breadcrumb; and ENGW traversing to nothing while ENG traverses to its two people.

**Current totals: API 294/294** (282 + 12), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 38. Ontology change history — and the edit it records (this session)

`ROADMAP.md` Objects item 5, which said changing an object type has "no audit/version trail today". Understated in exactly the way item 3 was: **there was no way to change one at all.** `create_type` and `delete_type` were the whole surface, and delete cascades — a type's properties, dataset mappings, link types, actions and every materialised instance go with it (0003, 0012, 0013). So the only route to "rename a property" was to destroy the ontology around it and rebuild by hand. Versioning a change nobody can make is not a feature, so this shipped as a pair: the edit, and the history that records it.

**Nothing downstream raises when a property disappears. That is the whole argument.** Each consumer degrades quietly, in its own way, and the three ways are worth knowing because they are why a warning had to be a refusal:

  * a **dataset mapping** keeps writing the property on every sync — `instances.extract_rows` works from `column_mappings` alone and never consults the type — while the browse UI iterates the type's *declared* properties. The data keeps arriving and stops being visible. Nothing errors.
  * an **action**'s value check is `_validate_value(property_types.get(prop, "string"), value)`, so a removed integer property silently starts accepting any string.
  * a **link join** whose property is gone traverses to nothing, forever, and the panel reports "nothing matches" — indistinguishable from data that genuinely has no matches (§37).

There is no exception anywhere on any of those paths. A logged warning would be a warning nobody sees, so `update_type` **refuses** a breaking change and requires `acknowledge_breaking` to proceed — a 409 (`BreakingChangeError`) carrying the impacts as data next to the message, since a list of four affected consumers is a list in the UI and parsing it back out of prose would be absurd.

**One deviation from the item's list of consumers.** It named "a Model, a Canvas app, a mapped dataset". Models do not reference object properties at all — they read datasets — and a Canvas widget references a dataset or an *action*, not a property, so the action check already covers every reachable case. Checking three consumer kinds (mapping, action, link join) rather than five is not a gap; the other two have nothing to check. The link join is a consumer the item could not have known about, since §37 created it in the same session.

**A retyped link join is reported but not blocking**, and the reason is a fact about §37 rather than a judgement call: the join compares the *text* form of both values (`instance_store.join_key`), so an integer that becomes a string still matches exactly what it matched before. Everything else — any removal, and a retype a mapping or an action depends on — blocks. One crisp rule with one exception that follows from how the feature actually works.

**A rename is reported as a removal plus an addition.** Properties are matched by api_name, and nothing in the schema distinguishes "renamed" from "deleted one and added another"; every consumer naming the old api_name breaks either way. Offering rename-with-migration would mean rewriting mappings, action lists, link joins *and* stored instance keys across a store this code cannot reach — a much larger feature, and one that must not be implied by a text field.

**The edit is a whole-definition replacement, not granular operations.** The form already holds the whole definition, so an `add_property`/`drop_property` API would make the client compute a diff the service must recompute anyway; and impact is a property of the *whole* change — dropping `a` while adding `b` is one edit a reviewer should see together, not two warnings arriving in sequence with the type briefly invalid in between. `api_name` is not a parameter at all: 0003 calls it the stable machine name used by exports, and no in-product warning reaches an external consumer holding it.

**Two schema details, both instances of a rule this branch keeps re-deriving.** The snapshot stores the title property's **api_name, not its id**, because an edit deletes and re-inserts property rows — a stored `title_property_id` would dangle precisely when the history was needed. And restore **appends** rather than rewinding, so history stays a true record including the fact that somebody reverted. A restore also goes through the same impact check as any other edit, deliberately: reverting to a definition from before a property existed removes that property *now*, from consumers built since. "It used to be like this" is not evidence that going back is safe.

**The warning is live, not a confirmation step.** `POST .../object-types/{id}/impact` dry-runs a proposed definition at viewer level, and the edit dialog re-queries it as the properties change — keyed on a signature of just the api_names and types, so editing a display name asks the server nothing. The warning is therefore on screen while there is still a decision to make, and Save stays disabled behind an explicit "I understand" tick. The PATCH recomputes the analysis itself rather than trusting that the preview was called. The property editor moved to `components/object-type-editor.tsx` and is now shared by the create and edit dialogs — one renderer, following §33's precedent rather than adding a fifth mirror to the list in the rough edges below.

**Testing.** `apps/api/tests/test_ontology_history.py` (14 tests): version 1 written at create with the title property named rather than pointed at; an edit appending a version while leaving `api_name` and older versions untouched; property order following the order sent; a removal refused with the mapping named, *and* nothing changed and no version written by the refused call; the impact endpoint previewing the same answer without side effects; acknowledgement pushing it through with `acknowledged_breaking` in the audit row; mappings, actions and link joins all named in one refusal; a retyped link join reported but allowed; a rename reported as a removal; restore appending with `restored_from` set; a restore refused because of a consumer built *after* the version being restored; unknown version 404; and the role/tenancy floors. Verified in a browser end to end: adding a property with no warning, removing a mapped one and reading the two named consumers, Save disabled until acknowledged, restoring v1 to bring the property back, and a restore of v3 refused with an override offered.

**Current totals: API 308/308** (294 + 14), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 39. Richer property types — making the type system typed (this session)

`ROADMAP.md` Objects item 4, which guessed that "today's typed properties are presumably basic scalars". Wrong in a more useful way than it is right: **`geopoint` and `timestamp` had been in the `property_data_type` enum since migration 0003 as labels nothing enforced.** `actions._validate_value` checked integer/float/boolean/string and silently accepted *anything* for date, timestamp, geopoint and json — a property declared `geopoint` took the string "banana" without complaint — and `instances.extract_rows` wrote whatever the mapped column held, never consulting the declared type. So the work was not "add types". It was "make three existing types mean something, and add the one genuinely missing".

**One coercion, shared by both write paths, because that is the whole point.** A type enforced on the sync path but not the action path is not a type: the same property would hold a `{lat, lon}` object or a raw string depending on who wrote it last, and every reader — including the Canvas map widget this item exists to unblock — would have to handle both. `coerce_property_value` returns the *normalised* value rather than just checking, so "51.5074,-0.1278" typed into a form and a Parquet struct read from a dataset land in storage identically.

**Coerce, do not merely check — and the difference is where the judgement is.** The first version was strict: an integer column mapped to a `string` property was refused. That broke the link-traversal suite immediately and would have broken nearly every real mapping, because an id column DuckDB reads as BIGINT mapped to a string property is the commonest mapping there is. The rule that replaced it: **total conversions are performed, ambiguous ones are refused.** A number becomes a string, a numeric string becomes a number, `3.0` becomes the integer `3`. But `3.5` is refused rather than truncated (quiet data loss), `"maybe"` is refused as a boolean, and a JSON `true` is refused for a string property — a number in a text column is a *format* difference between CSV and Parquet, whereas a `true` submitted for a name field is a caller mistake, and rendering it as "true" would store the mistake instead of reporting it. Booleans read the spellings a CSV actually contains (`t`/`no`/`0`/…) rather than Python truthiness, because a boolean column that reads every non-empty cell as true is worse than no boolean column.

**A bad value fails the whole sync, loudly, naming the row.** `row 'A9': location (geopoint) - expected a geopoint as 'lat,lon', got 'banana'`. The alternative — null it out and carry on — is the failure mode this branch keeps refusing: the row arrives looking complete with a field silently missing.

**geopoint is lat,lon, and the range check enforces it rather than a comment.** The order has no right answer (GeoJSON says lon,lat; nearly every consumer UI says lat,lon), so a latitude outside ±90 is refused with "did you send lon,lat?", which catches the transposed case for most of the world. It renders as coordinates, not a map: a map needs a tile source, which means an outbound request from a page displaying a customer's own data, and that decision belongs in the Canvas map widget — made once, deliberately, not smuggled into a table cell.

**timestamp did not split into timestamp/timestamptz**, which the item allowed for. It was genuinely indistinguishable from a plain string (nothing validated it) and now parses as ISO-8601 with an offset preserved when present and absent when not. A separate `timestamptz` was considered and rejected: values arrive from CSV and Parquet columns whose own timezone awareness varies by file, so a type promising "always has an offset" would promise what the ingest path cannot keep.

**Attachments, and the two findings they forced.** The value is `{key, filename, content_type, size}` referencing the existing storage gateway — a key rather than a URL, because a permanent URL is a public read of private bytes and a presigned one expires inside a value claiming to be stable. Then: (1) **an attachment property must be mapped to a dataset column** like any other. Not a check that could be relaxed — instances are re-materialised from their dataset by mark-and-sweep on every sync, so an ontology-only value would be *deleted by the next sync*. (2) Consequently write-back stores the **whole reference as JSON** in that column, not just the key: storing the key alone lost the filename, content type and size, so the attachment degraded a little on every sync, and refusing the string on the way back in meant an attachment survived exactly until its source was re-synced. Both were caught in browser verification, not by the unit tests, which is why the re-sync round trip is now a test.

**Two security decisions on the download route.** The key is checked against the *workspace's own storage prefix* rather than trusted — an attachment value is a plain string inside a JSON blob, so without that check a workspace editor could store another tenant's dataset key as an "attachment" and read it. And the response is always `application/octet-stream` with `Content-Disposition: attachment`, never the uploader's declared content type inline, because serving user-supplied content inline with a user-supplied type is how a stored XSS happens. The storage key grammar was widened from `datasets/…` to `(datasets|attachments)/…` in both the API and worker copies — a validator narrower on one side than the other is how a key written by one service becomes unreadable by the other.

**This is the fifth mirrored file, and it is recorded as debt rather than hidden.** `property_values.py` is byte-identical in `apps/api` and `apps/worker`, and STATUS's own rough edges say the fifth mirror should have been a shared package. The judgement, stated in the file's docstring: it is ~200 lines of pure standard-library Python with no imports from either app, so parity is a **hash comparison** rather than a behavioural test — unlike the connector registries, whose drift can only be caught by asserting behaviour — and the shared package needs both service images moved to a repo-root Docker build context, which is a change with its own risk that should not ride along inside a property-types feature. `test_property_types.py` asserts the two files' SHA-256 match and says in its docstring what to do instead if a sixth mirror is ever needed.

**Testing.** `apps/api/tests/test_property_types.py` (21 tests): both geopoint input shapes, the lat/lon range guard, temporal parsing with and without an offset, the coercion/refusal boundary in both directions, the attachment round trip, sync storing the declared type rather than the raw column, sync refusing a bad value and writing nothing, write-back normalising identically to a sync, attachment upload/download including a key from another workspace (404) and the octet-stream headers, and the mirror parity hash. Verified in a browser end to end: a geopoint rendering as coordinates where it used to be `[object Object]`, a file attached through the action form, the attachment downloading with the right bytes, the attachment surviving a re-sync, and a bad geopoint typed into the form refused with a usable message.

**Current totals: API 329/329** (308 + 21), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 40. Canvas parameters — the mechanism charts need (this session)

`ROADMAP.md` Canvas item 1, taken in the order the pillar's own sequencing insists on: "build this first — chart widgets and cross-widget interactivity both depend on it existing". It is the first canvas widget that **publishes** state rather than only consuming data.

**A second context, not an extension of `CanvasEnv`.** The item suggested extending the existing provider "to carry shared parameter state alongside workspace/project id and edit-mode". Kept separate instead, and the reason is a rendering one: parameter values change on every keystroke, while `CanvasEnv` changes only when the app remounts or the edit/run mode flips. Merging them would re-render every widget that only wanted to know which workspace it is in.

**Values are runtime state and are deliberately not saved with the app.** A parameter's name, label and options are Craft.js node props and serialise with the definition; the value a viewer currently has selected does not, for exactly the reason `CanvasEnv` doesn't — it belongs to this render, not to the definition. So a published app opens at its defaults for every viewer rather than at whatever the last person happened to pick. The provider sits *inside* the env provider and *outside* the Craft.js editor tree, so a filter set in Preview survives switching back to Edit; the alternative resets every filter on each mode flip, which makes a filter impossible to actually try out.

**Dropdown options come from the column's distinct values, not a list typed by the builder.** A hand-typed list is a copy of the data that goes stale the first time a new value appears — the same argument that made object links derived rather than stored (§37). It costs one `SELECT DISTINCT … LIMIT 200` through the query endpoint that already exists.

**Filtering is server-side, and that is the load-bearing decision.** The shortcut is to fetch the preview page and filter rows in the browser. That would be quietly wrong in this codebase's least favourite way: the widget would filter *the first 50 rows* while appearing to filter the dataset, and a table showing "no matches" because the match is on row 2,000 is worse than no filter at all. So a filtered table issues a real query instead of the preview.

**On building SQL in a widget.** The value comes from a viewer and is escaped (a doubled quote — a customer called "O'Brien Ltd" must filter, not raise); the column comes from a picker populated by the dataset's own schema. Worth stating precisely: `/datasets/{id}/query` **already** accepts arbitrary SQL from a project *viewer*, so this grants nothing anyone lacked, and the escaping is about correctness rather than a privilege boundary. Structured filters on the endpoint — server builds the SQL — is the better long-term shape and is recorded below rather than pretended away. Values are `CAST(col AS VARCHAR)` before comparison, because a dropdown hands back text whatever the column's type and comparing text to a BIGINT is an error rather than a non-match.

**An unset parameter means "show everything".** `filteredQuery` returns null rather than `WHERE col = ''`, and the caller falls back to the preview — an app whose table is empty until you touch a dropdown looks broken on first load.

**What is not built:** the date-range control the item names. `select` and `text` are; a range needs a two-value parameter shape, and that should be designed against a real chart's needs rather than guessed at before item 2 exists.

**Testing, and what it caught.** There is no frontend test runner in this build, so the half of the widget that can break silently — the SQL — is tested server-side in `apps/api/tests/test_canvas_filters.py` (6 tests) against the real DuckDB engine: the exact query shapes `filter-sql.ts` emits, a value containing an apostrophe, a filter on a numeric column, case-insensitive contains, the distinct-values query, and the viewer floor. **Writing them caught the first bug immediately**: the widget said `FROM src`, which is the alias the *model* layer gives its inputs, while the query endpoint exposes the dataset as `FROM dataset`. Verified in a browser end to end: a table starting unfiltered, options populated from the data (`All / North / South`), selecting a value narrowing the table with a "Filtered by region: South — 2 rows" note, clearing it showing everything again, and the apostrophe row surviving. Placement itself still needs a real mouse — Craft.js's toolbox uses native HTML5 drag-and-drop, which Playwright cannot drive (a standing rough edge below), so the verification builds the app definition through the same `PUT .../definition` the Save button uses and drives everything after placement.

**Current totals: API 335/335** (329 + 6), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 41. Charts — closing the "BI" half of "app/BI builder" (this session)

`ROADMAP.md` Canvas item 2, which that document calls the single most-requested-sounding gap in it. Bar, line, pie and scatter, bound to a dataset, reactive to §40's filter parameters.

**Aggregation is server-side, and neither option the item offered was taken.** It suggested "aggregated client-side for small results or via a new lightweight aggregation endpoint for larger ones". There is no reliable way for a widget to know a result is small *before* fetching it, so the first option is a guess; and the second is unnecessary, because `GROUP BY` through the existing `/datasets/{id}/query` endpoint already **is** a lightweight aggregation endpoint — and going through it inherits the sandboxing it already applies (`enable_external_access=false`, a memory limit, a row cap) rather than re-deriving them. The deeper reason is the sharper version of §40's: a chart that sums the preview page and puts an axis on it does not show less data, it shows a **wrong number**, and a wrong number with an axis on it looks authoritative.

**No charting library.** The same call §28 made for the pipeline graph — server-side layering so the web app needed no graph library — applies here: four shapes at a few dozen lines of SVG each, against a dependency with bundle size, its own theming to fight and a version to keep current. `charts.tsx` names where the trade flips rather than leaving it implicit: tooltips, zoom, brushing and stacked series are the point to reach for a library instead of growing a bad one.

**The details that are judgement rather than drawing:**

  * **Bar and pie sort by value and cap the categories; line sorts by its dimension.** A line chart is a series — sorting it by magnitude draws a shape that means nothing. A bar chart with 400 categories is a smear, so the cap is part of the chart's definition rather than something the browser discovers.
  * **Scatter does not aggregate at all.** Grouping a scatter plot destroys the thing being looked at. Its x axis is numeric when the dimension is, and ordinal otherwise, and it *says* which — a scatter of two categorical columns is a grid of dots, and drawing it silently would be pretending it means something.
  * **A non-numeric measure fails with DuckDB's own message** ("Conversion Error: Could not convert string 'Acme' to DOUBLE"), which names the column and the value. `CAST`, not `TRY_CAST`: the alternative sums to null and draws an empty chart that reads as "no data" rather than "you picked the wrong column".
  * **The zero baseline is always included.** A bar chart whose baseline is not zero exaggerates differences, which is the single commonest way a chart lies.
  * **A non-numeric value is dropped, not charted as zero.** A zero bar is a claim about the data; "this row could not be measured" is not that claim.

**Charts and tables share one predicate.** `filterPredicate` was factored out of §40's `filteredQuery` so both build their `WHERE` from the same place — a chart that contradicted the table beside it, because the two disagreed about what "filtered" meant, is exactly the bug a dashboard cannot afford. Browser verification asserts both narrow together, and also that a chart with **no** parameter bound stays unfiltered, which is the point of naming parameters at all.

**Testing.** `test_canvas_filters.py` grew to 12: the aggregation shapes, a sum over a numeric column, the non-numeric measure failing visibly, chart and table filtering identically, a line sorting by dimension, and scatter keeping individual points. Verified in a browser: bar and pie rendering as real SVG with the server-side sums in their tooltips (`South: 485`, `North: 350`), the bad-measure chart showing the engine's conversion error, selecting a filter value narrowing both the chart and the table, and the unbound pie staying put.

**Current totals: API 341/341** (335 + 6), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 42. An object-bound table widget — canvas apps that read the ontology (this session)

`ROADMAP.md` Canvas item 3. A widget bound to an **object type** rather than a raw dataset, reusing §36's Explorer query surface and reactive to §40's parameters.

**The item's dependency was real but not sufficient.** It says to "reuse the query surface" of the Global Object Explorer, and that surface exists — but the Explorer only ever asked one question: `q`, a prefix search across every indexed property of every type. That is the right question for a search box and the wrong one for a **filter**. A dropdown bound to `name` that quietly matches `Depot North` when the builder chose `Depot` is not filtering, it is searching with a filter's UI, and the failure is invisible: the rows all look plausible. So the widget needed an exact read path first, which the store Protocol already had — `find_by_property`, added for §37's link traversal, where a link join is exactly "give me the instances whose property equals this value". `GET .../object-instances` now takes `property` + `value` and routes to it.

**Three constraints came out of the endpoint rather than the widget:**

  * **A property filter requires exactly one `type_id`,** and says so (422). A property api_name only means something *within* a type: `name` on `Site` and `name` on `Customer` are different properties that happen to share a spelling, and filtering "across types where name = X" would be a union of unrelated questions dressed as one query.
  * **`property` and `value` are refused unless both are present.** A `property` with no `value` silently degrading to "unfiltered" is the same class of quiet wrongness the filter itself exists to avoid.
  * **`$primary_key` is filterable** using §37's existing sentinel, mapping to `property_name=None` in the store — the primary key is not in the properties map, but it is the one field every instance certainly has.

Rows from this path get `object_type_id` filled back in before they are returned, because §36's contract is that every row in an Explorer response says what it is, and the single-type read path knows the answer without asking the index for it.

**The widget picks one question rather than blending two.** `filterParameter` (exact, one property) and `searchParameter` (prefix, all properties) are separate settings, and when both have values the exact filter wins — the endpoint's property filter is its own read path, not a refinement of `q`, and pretending otherwise would mean claiming an intersection the store was never asked for. The header states which is in force (`3 Sites where name = Depot`), so a viewer can see the question, not just the answer.

**Values render through §39's `PropertyValue`.** A geopoint inside a canvas app reads as `51.5074, -0.1278` and an attachment as a download link, because the widget reuses the browse UI's renderer rather than stringifying — a canvas app is a *view* of the ontology, and a type that means something in one place and `[object Object]` in another does not mean anything.

**Testing.** `test_property_types.py` grew to 25: the exact filter returning type metadata with the row, exact-vs-prefix (the same value that `q` matches as a prefix, `property` does not match as an exact), `$primary_key` filtering, and both refusals. Verified in a browser against three deliberately-overlapping objects (`Depot`, `Depot North`, `Yard`): the table listing all three with the geopoint rendered as coordinates, the dropdown narrowing to `Depot` alone, and the search box beside it matching both `Depot` and `Depot North` — which is the whole reason the two are separate controls.

**Current totals: API 345/345** (341 + 4), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 43. A map, with its basemap in the bundle (this session)

`ROADMAP.md` Canvas item 4, unblocked by §39's geopoint type — which deliberately left the tile-source question to this item rather than smuggling it into a table cell.

**The decision the item was waiting for: no tiles.** Every mapping library defaults to raster tiles from a third-party host, and that default is wrong for this product specifically. Anchor deploys into the customer's own AWS account, often into a VPC with no egress; a tile layer makes the **viewer's browser** call out to somebody else's server on every pan, and each of those requests carries the viewport — which, on a map of the customer's own sites, vehicles or incidents, approximates where their data is. So the basemap is Natural Earth's 1:110m country outlines (public domain), simplified to one ~60 KB SVG path that ships in the bundle: no outbound request, works air-gapped, and nobody is asked to accept that trade without being told. `scripts/make-basemap.py` regenerates it, so the data is reproducible rather than a blob somebody pasted in once.

**What that costs is stated on screen, not buried.** There is no street-level detail and there never will be from this file, so the map says "country outlines only, no detail at this zoom" below three degrees of span rather than letting an empty background read as "nothing here". For the same reason the *fitted* view has a ten-degree floor: fitting tightly around three sites in one city would open on a view where the outline is a meaningless polygon. A deployment that genuinely needs detailed tiles wants a **configurable tile URL** pointing at a host the customer chose — named here as the extension point rather than half-built.

**No mapping library either**, for a sharper version of §41's argument: a mapping library's reason to exist *is* tile handling, and with tiles gone what remains is an affine transform, a drag handler and a grid clustering pass. That is `map.tsx`. Configurable tile sources are the moment to reach for a library instead of growing one.

**Both halves of the platform feed it, through one parser.** `toLatLon` accepts `{lat, lon}`, `"lat,lon"` and `[lat, lon]` — the accepted shapes of the API's `_coerce_geopoint` — because §39 established that a geopoint property synced back to a dataset column *is* `"lat,lon"`. A widget that understood the ontology's shape but not the dataset's would fail against the very datasets its objects came from. Object mode reads §42's explorer path (and so inherits its exact-property filtering); dataset mode reads a location column or a latitude/longitude pair through the existing query endpoint.

**What it refuses to do quietly**, which is most of the design:

  * **An unreadable location is counted, never dropped** — "3 placed, 1 without a usable location". A map that silently plots the rows it liked is a map of an answer nobody asked for.
  * **Out-of-range coordinates are rejected, not clamped.** The usual cause is lon/lat sent the other way round, and clamping turns that into a pin at the edge of the world drawn with total confidence.
  * **Points panned off the edge are counted too**, because "no pins here" and "you have scrolled away from your data" look identical otherwise. `Fit to data` undoes it.
  * **Rows beyond the limit are reported.** Object mode is capped by the explorer endpoint's own 200-row page, and says "of N matching" rather than raising a platform-wide bound to suit one widget.

**Two browser-only bugs, both in the same place.** Craft.js makes the block around each widget a native HTML5 drag source, and `dragstart` fires on *that* element, not on the SVG under the pointer — so no handler inside the map could see it, and once a native drag begins the browser stops sending `mousemove` entirely. The symptom was a map that panned by exactly one frame and then froze, with the SVG transform proving it had moved. Panning now listens on the window and suppresses `dragstart` at the document while a pan is in progress. Neither would have shown up in a unit test; both were found by dragging the thing.

**Testing.** `test_canvas_filters.py` grew to 18 with the map's SQL shapes: a single `"lat,lon"` column coming back intact, a lat/lon pair as three columns (arity is how the widget knows which it asked for), rows with no location surviving the query so they can be counted, an out-of-range coordinate reaching the client for the parser to refuse, and a map and a table filtering identically. Verified in a browser: two maps in one app — one from an object type with a geopoint property, one from a dataset's lat/lon pair — pins clustering into a labelled bubble, the null-location object and the swapped-coordinate row both reported, the filter parameter narrowing the object map while the unbound one stays put, and panning away producing "all of them outside the view".

**Current totals: API 351/351** (345 + 6), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 44. Somewhere for a published app to lead (this session)

`ROADMAP.md` Canvas item 6, which describes itself as polish: "the read API already exists — just needs a list page and a nav entry".

**The list page was the easy half. Publishing had nowhere to lead.** The only route that rendered an app was the project editor, which resolves its project by slug and reads the project-scoped endpoint — so anybody without project membership, *the exact audience publishing exists for*, followed a link to an app published to them and got a 404. The workspace-wide read path has been in the API since §15 with nothing in the web app calling it. So this shipped as a pair: `/{workspace}/apps` (the gallery) and `/{workspace}/apps/{appId}` (the viewer), the latter rendering the definition with Craft's editor hard-disabled rather than merely chrome-hidden.

**The gallery is workspace-scoped, not a project tab**, and that is the whole point of it: somebody who opens a dashboard every Monday does not know which project its author filed it in, and making them find the project first is asking them to learn the builder's filing system.

**Publishing shares the layout, not access to the data**, and the new route is what makes that observable. Every widget in a published app still reads its dataset or object type *as whoever is looking* — an app must never become a way to launder access to data somebody was not given. For a project on inherited permissions (the default) every workspace member already has viewer access, so an app published to the workspace simply works; in a `permission_mode='custom'` project the widgets report what they could not read. `test_canvas.py` now pins that boundary directly — the same viewer who can read the published app gets 404 on that project's datasets, models and object sources — so nobody later "fixes" the empty widgets by widening the read path. The Publish dialog's copy was wrong about the other half too: it said "shares the current saved version", implying a pinned snapshot, when publishing is a visibility flag over the live definition. It now says so, and the browser check asserts it (reorder, save, and the published view follows).

**Reordering got two buttons rather than only drag.** Craft.js already lets a placed widget be dragged, but native HTML5 drag-and-drop is the one canvas interaction automation cannot drive (an entry in the rough edges below since §15) — *and* it is the one a keyboard cannot do at all. Move up/move down in the settings panel is both testable and the only accessible way to reorder an app. One trap worth keeping: Craft's `move(id, parent, index)` inserts at an index in the parent's list *before* the node is removed from it, so moving down by one is `index + 2`; get it wrong and the widget silently stays put.

**Testing.** `test_canvas.py` grew to 16 with the access-boundary test above. Verified in a browser: the workspace page's Apps link, the gallery listing a published app and *not* a private one in the same project, the published view rendering with live widget data and no palette or Save button, move down/move up reordering, and the new order surviving a save, a reload, and showing through to the published view.

**Current totals: API 352/352** (351 + 1), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 45. The Code pillar's design spike — decided, not built (this session)

`ROADMAP.md` Code item 1, the one item in that document which forbids writing code until it is settled: self-hosted git backend in the VPC, or federation with the customer's own GitHub/GitLab. Written up in `docs/decisions/0001-where-code-lives.md`; the summary here is what it decided and why it matters to the rest of the repo.

**Neither, as posed. The system of record stays in Postgres, and git — if it appears at all — is an outbound mirror to a remote the customer already owns.**

The argument that settles it was already in the schema. `model_runs.model_version` pins each run to the exact definition that executed, and 0024 makes rollback *append* rather than rewind precisely so that pointer resolves to one piece of code forever. **A git ref cannot promise that**: branches move, history can be rewritten, and a commit reachable today can be gone after a force-push and a GC. Git as the store means either accepting runs that point at code which no longer exists, or rebuilding immutability on top of git — pinning every run to a SHA and never collecting garbage, which is a worse version of what the database already does.

That collapses the rest of the choice. A self-hosted server becomes a *second copy* whose remaining value is developer tooling interop — clone, local editing, existing CI — and a server in `PRIVATE_WITH_EGRESS` subnets cannot deliver that without new public ingress and a new auth model, on top of new state (there is no EFS in the stack, and Fargate tasks are ephemeral). Meanwhile federation to *the customer's own* git host is the same category of thing Connections already does: outbound over egress the VPC has, credential in `SecretsGateway`. What the self-contained-deployment pitch protects is that **the vendor** holds no customer data, not that the customer may not use their own SaaS.

**Three consequences that change the remaining items** rather than sitting in a document nobody re-reads:

  * **Item 2 shrinks.** "A git-backed store for model definitions" is not what gets built, because the store exists — it is a repository-shaped surface over `model_versions`. The one genuinely new concept is the **change set**: a save writes one version row per model today, so "these three transforms changed together, for one reason" cannot currently be said.
  * **Item 3 evaporates.** There is no round trip, because there is no second copy: editing through Code calls the same service the inline editor calls and takes the same build path by construction. The roadmap's "may end up being the same mechanism viewed two ways" is stronger than it guessed — they are the same rows.
  * **Item 4 gains a boundary.** Approval state is platform-native, in Postgres against platform identities. If a merged pull request on the customer's GitHub authorised a change to what runs here, whoever administers that org — people the platform neither manages nor can enumerate — would control what a transform computes. Same refusal as §44's: a mirror may carry the diff, it may not be what says yes.

**Flagged for whoever implements federation:** CodeCommit is the option that would satisfy both halves (in-account *and* clonable, IAM-authenticated, no new auth model), and AWS closed it to new customers in 2024, so a freshly provisioned account cannot be assumed to have it. Verify that rather than taking the doc's word for it — if it has changed, it is the best target by a distance.

No code, no tests: this item is a decision. **Totals unchanged: API 352/352, worker 50/50, control-plane 13/13.**

---

### 46. Code, without a repository (this session)

`ROADMAP.md` Code item 2, built to the shape §45 decided: the project's transforms *are* the repository, `model_versions` *is* the history, and this is the surface that renders both. `/{workspace}/{project}/code` replaces the "No repositories yet — New repository" placeholder that had been sitting there since §15, and the button is gone rather than disabled, because there is nothing to create.

**What is genuinely new is one table.** Migration 0030's `code_change_sets` gives a name to something the schema could not previously say: *these three transforms changed together, for one reason*. A save has always written one `model_versions` row per model, so an edit spanning several models was several unrelated events. A change set groups them and holds the message; it holds no code, because the code stays where a run resolves it.

**Membership is nullable and stays that way.** Every version written before 0030 has no change set, and every save from the inline Models editor still writes one without. Backfilling a synthetic single-model change set onto those would invent an intention nobody expressed — the same refusal 0024 made about pointing pre-migration runs at a backfilled v1. So the commit log has **two kinds of entry**: a change set with a message, and a standalone save that says which transform was edited (or "Reverted X to v2", read off `restored_from`). That is the truth about how this codebase gets edited, and the UI shows it rather than smoothing it over.

**Every write goes through `models.update`.** `apply_change_set` loops over the files calling the same service the inline editor calls, in one transaction, so Code cannot bypass a check the other surface enforces — a test drives cycle refusal (Models item 7) through a change set and asserts the whole thing rolls back, log included. This is also `ROADMAP.md` Code item 3 answered by construction: there is no round trip to get right, because there is no second copy. A second authoring surface with weaker validation is a bug with a UI in front of it, and the role floors match Models exactly for the same reason.

**A change set that changes nothing is refused**, not recorded. `update` already declines to write a version when code and inputs are unchanged, so a change set built from no-ops would be a commit message attached to nothing — a claim about history rather than an empty entry in it. The browser check produces that state the way a person does (type something, take it back) and asserts the reason appears on screen.

**Two smaller decisions worth keeping:**

  * **Paths are derived, and collisions suffix *both* sides.** "Daily orders" and "Daily Orders!" collapse to one stem; if only the second took an id suffix, one model's path would move when an unrelated model was renamed. A path that changes between two reads is not a path.
  * **Diffs are computed on read.** A stored diff is a second copy that can disagree with the versions it describes. One bug came out of that: `unified_diff` with `keepends=True` runs the last `-` line into the first `+` line when the source has no trailing newline (transform source usually doesn't), which rendered as one nonsense line in the browser and looked fine in the API tests.

**The nav count was quietly wrong and now isn't.** The project sidebar read `code_repos` — a table from the original spec that has never had a row written to it — so Code showed "0" beside a section listing two files. It now counts the project's models, which is what the section contains. `code_repos` itself is left in place: it is a spec §16 table the schema verifier asserts, and removing it is a claim about the spec rather than about this feature. It is dead by design, and named as such below.

**Testing.** `test_code.py`, 16 tests: stable paths and both-sided collision suffixes, reading an old version with the inputs it was saved with, diffs including "before v1", change sets grouping several files, a change set writing rows Models' own history endpoint returns, cycle refusal through a change set, the no-op and duplicate-file refusals, the two-kind timeline, revert entries, the permission floors, and the audit record. Verified in a browser: two files staged and saved as one change set, the change set detail naming both files with their `v1 → v2` steps, a save made *outside* Code appearing as a single save, its diff rendering, and the no-op refusal.

**Current totals: API 368/368** (352 + 16), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 47. Review-gated promotion (this session)

`ROADMAP.md` Code item 4, the last unbuilt item in that document. It asks for "a PR-like review step before a change to a transform's code takes effect on whichever branch/environment is considered live", and names "branch-to-environment mapping" as part of the scope.

**There are no branches and no environments here**, and §45 explains why there will not be a branch: `models.code` is the live definition and `model_runs.model_version` pins every run to the row that produced it. So "live" means the project, and the review step gates **the write that makes a definition live** rather than a merge between two refs. That is the item's stated scope minus a third of it, and the missing third is a Foundry structure this platform deliberately does not have — recorded rather than quietly skipped.

**A proposal is a request, not a definition.** Its files live in `code_proposal_files` (migration 0031), never in `model_versions`, because that table is what a run resolves against and must never contain code nobody approved. Applying writes the versions — through §46's change set path, so an approved change lands in the same log as every other edit rather than a parallel history — and only then does the code exist as a definition. Nothing runs a proposal, and nothing can.

**The gate lives in `models.update`, not in a route.** That function is what makes a definition live, and the Models editor and the Code change-set endpoint are two doors into it; a check on one screen is a check on one screen. It gates *code and inputs only*: trigger mode, schedule and health policy stay editable, because 0024 already drew that line and a project that required review to pause a job would be one people turn the gate off for. Review is **off by default** — turning it on for every existing project would break how every existing project is edited.

**Three ways round a review, all refused:**

  * **Approving your own proposal.** A review somebody gave themselves is not a review, and letting it count makes the gate a formality anyone in a hurry can perform alone.
  * **Approve, then swap the code.** Editing a proposal's files bumps `files_updated_at`, and approvals older than that no longer count — otherwise a reviewer's name ends up against a change they never saw. Editing only the summary keeps the approval: the reviewer approved code, not prose.
  * **Applying a stale proposal.** Each file records the version it was written against, and applying re-checks it. Without that, approving on Monday and applying on Friday silently discards whatever happened in between — a lost update wearing a reviewer's approval. The check is at *apply* time rather than review time, because the gap between the two is exactly where the race lives.

**Blockers are a list, not a boolean.** `get_proposal` returns every reason it cannot be applied, in the API's own words, and the UI prints them. A disabled button with no explanation leaves somebody guessing which rule they tripped — and there are four of them.

**Reviews are append-only**, like every other history in this codebase: a reviewer who changes their mind leaves a second row, and what counts is each reviewer's latest verdict. Setting the policy is **owner**-level (a governance decision about the project), reviewing is **editor**-level (a viewer who could approve would be authorising an edit they are not allowed to write themselves).

**Two bugs worth keeping.** A nullable enum filter written as `:state IS NULL OR state = CAST(:state AS ...)` makes Postgres refuse the whole statement — "could not determine data type of parameter" — and the API tests never hit it because only the browser asked for `?state=open`; there is now a test for the list endpoint itself. And `npm run build` while `next dev` is running overwrites `.next` under the dev server, which then 500s on every route with `Cannot find module './vendor-chunks/...'`: nothing to do with the code, but it looks exactly like a broken page. Kill the dev server, delete `.next`, restart.

**Testing.** `test_code_review.py`, 20 tests: the gate off by default, refused on both surfaces when on, not blocking scheduling, owner-only policy; the proposal lifecycle (not a definition until applied, applying writes one change set and closes it, no double-apply, withdraw); and the three refusals above, each asserting the *other* person's work survived. Verified in a browser with two identities: turning the gate on, a direct edit refused, staged files becoming a proposal, self-approval refused, a second identity approving and the change applying, and a stale proposal blocked with its Apply button disabled and the reason on screen.

**Current totals: API 388/388** (368 + 20), **worker 50/50**, **control-plane 13/13** (both untouched).

---

### 48. Onboarding somebody could actually do (this session)

`ROADMAP.md` section 7 item 2 — the first item outside the six pillars, because a platform nobody can stand up is a platform nobody uses. Section 7 exists because the honest answer to "how do I launch this on a new instance?" was a runbook with a Python REPL in the middle of it: the operator CLI could `deprovision` a customer but had **no `provision` command at all**.

**The structural gap: there was no surface the customer could touch.** `apps/web` cannot be it — it runs *inside* the stack being provisioned, so at onboarding time it is the thing that does not exist yet, and §19 already recorded that it has no path to the control plane's trust boundary either. So this is a second, small FastAPI app in `apps/control-plane`, server-rendering one page. A second Next.js app for five steps and a poll would have been more scaffolding than page, and this has to deploy in front of the registry without the product's web build anywhere near it.

**The customer types twelve digits, and nothing else.** The bootstrap template hardcodes `RoleName: platform-bootstrap`, so the role ARN is *derivable* from the account ID — the ARN paste that used to travel by email was pure ceremony, and ceremony is where typos live. Everything else is in a **prefilled CloudFormation launch URL**: template, stack name, control-plane role ARN, and the 43-character external ID, all in the query string. Click, tick the IAM box, Create.

**Detection is a probe, not a form field.** "Have they run the template yet?" is answered by trying to assume the role — the same call provisioning makes a minute later. A checkbox saying "I've done it" can be wrong; an `sts:AssumeRole` that succeeds cannot, and it proves the external ID matched too, which is the other half of what could have gone wrong.

**Preflight fails in plain English before CloudFormation fails in a wall of events.** The five checks are the ways the deploys in §17/§20 actually broke: the role is assumable, the region is one this build has been deployed to, the region is CDK-bootstrapped, there is Elastic IP headroom for the NAT gateway, and there is not already a stack. **Every failing check carries a remedy** — a check that reports a problem without saying what to do about it has moved the confusion rather than removed it — and provisioning is *refused* while one stands, because otherwise the customer waits ten minutes to be told something the page already knew.

**The fifteen minutes are no longer silent.** CloudFormation knew what it was doing the whole time and nothing surfaced it; the status endpoint now carries stack events and the page tails them, then hands off to `/setup` in the new deployment.

**Two credentials, two audiences.** The vendor creates an onboarding with an operator token; the customer drives it with a per-customer onboarding token minted at that moment, stored as a SHA-256 hash and authorising exactly one org's onboarding. An unknown token gets the same flat 404 as an expired one — distinguishing them tells a stranger that a token existed. The external ID is **not returned by any route**, not even the one that creates the onboarding: an earlier draft handed it back to the vendor on the assumption they would paste it into a link, and once the link is minted server-side that is a secret with no caller.

**One bug worth keeping**, found in a browser and invisible to the tests: the five-second poll re-opened step 4 on every tick, wiping the "checked" state the preflight had just set, so the page kept forgetting what it had established. Polling loops that write UI state need to *open* steps, never reset them.

**Testing.** `test_onboarding.py`, 19 tests against the real registry with AWS and the provisioner faked: the launch URL carrying both parameters and URL-encoding the external ID, the derived ARN, one link reaching exactly one onboarding, the flat 404, the operator route refusing an absent or wrong token, the external ID never appearing in a token-authenticated read, detection before and after the template is run, bad account IDs and unsupported regions refused before AWS sees them, preflight passing and failing with remedies, provisioning refused on a failing check, running once, reporting its failure, and stack events reaching the status payload. Verified in a browser end to end against a scripted fake account: not-connected → connected → preflight failing with the `cdk bootstrap` command on screen and the button disabled → preflight passing → provisioned, with events tailing and the hand-off link live.

**Current totals: control-plane 32/32** (13 + 19), **API 388/388**, **worker 50/50** (both untouched).

---

### 49. The rest of section 7: a CLI, an image, a runbook, a checklist, and a failure that explains itself (this session)

Items 1, 3 and 4, finishing the deployment section §48 opened.

**Item 1 — operator ergonomics.** `python -m src.cli` gained `onboard` (register a customer, print their link), `provision` (detect → preflight → deploy, streaming CloudFormation events to stdout), `status`, `serve` (the customer-facing app) and `demo`. It had exactly one command before this: `deprovision`. A control plane that could destroy a customer's stack but not create one was the sharpest single fact about how this got deployed. Both paths — CLI and page — run the same `OnboardingService`, so they preflight identically and refuse identically; a CLI that drifted would eventually provision something the page would have refused.

**The control plane can now be run at all.** It had no Dockerfile: the other three services have one each, and it never needed one until §48 gave it a web surface. Its image carries **Node and the CDK CLI plus `infra/cdk` itself**, because `cdk deploy` is a subprocess — a control plane that can take an order and not fill it is not one.

**`docs/deploying.md` is the runbook that did not exist**, written as three test levels rather than a list of commands: the whole onboarding flow with **no AWS at all** (`cli demo`, which scripts an account that starts un-assumable so the failure screens can be walked before anybody spends fifteen minutes), one stack **by hand**, and the real thing **through the page**. It names what level 3 exercises for the first time: `stack_events`, `cdk_bootstrap_version` and `elastic_ip_headroom` have only ever run against fakes, so that is where to expect the first real-AWS surprise — most likely a permission the bootstrap role lacks.

**Item 3 — the first-run checklist**, on the project overview: bring data in → transform it → give it a shape → build something on it. **Every item is derived, not stored**: it is true when the thing it names exists, so nothing is ticked by hand, nothing goes stale, and a project somebody else set up shows the right state to whoever opens it next. It retires itself once all four are done.

One bug the browser caught immediately, and worth keeping because it is this codebase's recurring shape: the "give it a shape" step first used `resource_counts.objects`, and **object types are workspace-wide**. A brand-new project in this dev workspace opened with that step already ticked by 26 types somebody else had made — a green tick claiming work nobody had done. It now counts the project's *object type sources*, which is what actually belongs to the project. The screenshot of the fix shows "2 of 4" next to a sidebar reading "Objects 26", which is the whole argument in one frame.

**Item 4 — failure recovery.** A failed deploy now returns its failures in plain English with the one action that resolves each, and offers a retry. The hints are the failures this build actually hit (§17, §20): a cancelled resource pointing at the *earlier* failure that really caused it, the migration Lambda's "no pq wrapper available", an image built for the wrong architecture, no Elastic IPs, a dependent object blocking a delete, a missing bootstrap-role permission. **An unrecognised failure gets no invented advice** — CloudFormation's own reason beats a guess dressed as guidance.

**Testing.** `test_onboarding.py` grew to 22 (the three failure-recovery tests). Verified in a browser: the documented level-1 walkthrough end to end against `cli demo`, and — against `cli demo --fail` — the failure block naming the real cause with a working Try again. The checklist was verified by creating each resource in turn and watching the count move without anything being clicked.

**Current totals: control-plane 35/35** (32 + 3), **API 388/388**, **worker 50/50** (both untouched).

---

### 50. The vendor's own bootstrap (this session)

§48 and §49 made the *customer's* path one page: pick a region, type twelve digits, click a prefilled CloudFormation link, come back. What they did not touch is the asymmetry underneath it — **everything the customer touches is one page; everything the vendor touches to make that page exist was still five manual steps**: create a KMS key, create a role with the right trust policy, create three ECR repositories, put the bootstrap template somewhere CloudFormation can read, then work out which environment variable wants which ARN.

`python -m src.cli init --region <region>` is those five steps, and it ends by printing the exact environment block and the three `docker build` commands.

**Idempotence is the feature, not a nicety.** Running it again is how you check the state of an account somebody set up months ago, and it is what makes the command safe to put in a runbook people follow twice. Two things are rewritten on every run and everything else is left alone: **the role's inline policy**, so an account bootstrapped a year ago picks up a permission this build has added since, and **the template**, because a stale one is worse than a missing one — the launch link keeps working and hands the customer a role lacking exactly the permission the new deploy needs.

**Two IAM policies, both narrow on purpose.** The control plane may assume `arn:aws:iam::*:role/platform-bootstrap` and nothing else — one that could assume *any* role in a customer account would be a far bigger promise than this product makes — and it may use exactly one KMS key, the one that wraps external IDs. Trust defaults to the account root, which is not "anybody": it delegates to the account's own IAM rather than naming a person who will later leave, and `--trust` narrows it to a principal.

**It stops at two things and says so.** It does not create the registry's Postgres and does not host the onboarding page, because both are decisions with a bill attached: a first customer's registry can live on the operator's laptop, and where the page runs is an availability call that differs at one customer and at fifty. Both are printed under "still yours to decide" — the difference between a tool that finished and a tool that stopped.

**One detail that only shows up in a real account:** the customer's bootstrap template trusts a **role**, so the control plane has to *run as* the role `init` creates. `docs/deploying.md` now says to assume it before `serve` or `provision`; running as your own user with the role ARN configured looks right and fails at `sts:AssumeRole` with a message about trust policies.

**Testing.** `test_vendor_bootstrap.py`, 10 tests against a fake gateway: a first run creating everything, the environment block being the *whole* configuration (anything missing is something somebody has to work out by hand), a second run creating nothing while still reporting everything, the template and role policy being rewritten anyway, both policies' scopes, trust defaulting to the account and narrowing on request, JSON-serialisability of what goes to IAM, and the output naming what is still manual.

**Current totals: control-plane 45/45** (35 + 10), **API 388/388**, **worker 50/50** (both untouched).

---

### 51. Python 3.13 (this session)

Found the way these things are always found: somebody cloned the repo on a current machine and `pip install` died on `psycopg-binary==3.2.1`, with an error naming a wheel rather than a Python version. **3.13 is what a fresh machine gets by default now**, and every native pin here predates it.

Four pins were below the first version publishing a cp313 wheel — `psycopg` 3.2.1→3.2.2, `greenlet` 3.0.3→3.1.0, `duckdb` 1.0.0→1.1.1, `pandas` 2.2.2→2.2.3 — each moved to exactly that version and no further, because the point is to install, not to be current.

**Dagster was not a pin bump.** 1.7.x declares `Requires-Python <3.13`, so it cannot be installed there at all; the first release that can is 1.11. That is four minor versions of an orchestration framework, and it is the only change here with real risk. It needed **no code change**, for a reason worth writing down: this worker's entire Dagster surface is `Definitions`, `ScheduleDefinition`, `@job`, `@op`, `OpExecutionContext` and `ConfigurableResource`, all still current in 1.11 — a small surface is what made a four-version jump a requirements edit. Whoever bumps it next should not assume that holds.

**Both versions are supported, and both were run.** The images stay on `python:3.12-slim`; nothing about the deployed stack changes. All three suites were run on **3.12 and 3.13** with the new pins - 388 API, 50 worker, 45 control-plane on each - and the DuckDB bump got a browser pass as well (charts, the Code pillar, the map), since 1.0→1.1 is the one change with query-behaviour surface rather than just packaging.

**One thing deliberately left alone:** `instance_store.py` calls `datetime.utcnow()`, which 3.13 deprecates loudly. Changing it makes the stored `updated_at` gain a `+00:00` offset - more correct, and a change to written data - so it belongs in a change that is about that, not in one about installing.

**Then it failed again on the same machine, for a second reason.** `psycopg-binary==3.2.2` publishes a cp313 arm64 wheel, but tags it `macosx_14_0_arm64`; 3.2.4 is the first release tagged `macosx_11_0` and the first with a cp39 arm64 wheel at all. So the pin was invisible to an Apple Silicon Mac on macOS 13, and invisible to anyone who reached for `python3` — which on macOS is still CommandLineTools 3.9. Both produce the identical "no matching distribution" naming the wheel, so the second failure looked exactly like the first one not being fixed. `psycopg` is now **3.2.4** everywhere.

**The rule that was wrong: "lowest version with a cp313 wheel" is not the same as "lowest version that installs".** A wheel exists per (interpreter, platform, minimum OS), and pip's "from versions:" list is already filtered by all three — so a release that does not suit *this* machine is indistinguishable from a release that was never published. The pins are now chosen as the lowest publishing wheels across cp312/cp313 on both linux and macOS arm64, with a deployment target below the current OS. The other three were checked against that rule and are fine as they stand: `greenlet` 3.1.0 (`macosx_11_0_universal2`), `duckdb` 1.1.1 and `pandas` 2.2.3.

**Current totals unchanged: API 388/388, worker 50/50, control-plane 45/45** — on both Pythons, re-run on 3.13 after the psycopg bump (376 + 46 with MariaDB down, which skips 12 and 4).

---

### 52. `[object Object]` on the one screen with no support channel (this session)

Someone walking the demo typed an account ID the schema did not like and the onboarding page said **`[object Object]`**. Two defects, and the second is the interesting one.

**`ConnectIn.aws_account_id` carried `Field(pattern=r"^[0-9]{12}$")`.** So FastAPI rejected the request during validation, and its `detail` for that class of failure is a *list of error objects*, not a string — which the page renders straight into `textContent`. Meanwhile `detect_account` validates the same thing and raises "that does not look like a 12-digit AWS account ID". **The good message was unreachable, shadowed by a duplicate check one layer higher.** Validating in two places is not belt and braces when the outer one answers in a different shape: it silently wins, and it is the one that cannot explain itself.

**The test asserted the status code and nothing else.** `test_a_bad_account_id_or_region_is_refused_before_aws_sees_it` checked `== 422` and passed in both worlds — the schema's 422 and the service's 422 are the same number. A refusal has two jobs and the test only ever checked one of them; `docs/deploying.md` level 1 exists precisely because that gap is invisible from the API and obvious in a browser, which is where it was in fact found.

Fixed at both layers, because either alone leaves a hole: the pattern is off the field so the readable refusal is the only reachable one, and a `RequestValidationError` handler flattens FastAPI's list to one sentence — a missing field reaches that validator no matter what the models say, so the guarantee belongs in a handler rather than in each field. The page also stringifies a list-shaped `detail` defensively, since a page that renders `[object Object]` is broken regardless of who was right about the payload. Tests now assert the *shape* and the wording, not just the number. **Control plane 45 → 51.**

Browser-verified against the demo: empty, short and non-numeric account IDs all render the sentence; a valid one still connects and opens step 4.

**Same walkthrough, same class of defect one route over.** Re-running `POST /api/onboardings` with a slug already in the registry returned **500 and a traceback**: `register_customer` raises `ValueError: customer 'demo-co' is already registered` and the route did not catch it. It is an ordinary thing for an operator to type — the registry is in Postgres, so restarting the demo does not clear it — and now answers **409** with that sentence. Deliberately *not* made idempotent: re-registering would have to mint a fresh token, invalidating a link the customer may already be holding, possibly mid-provision. Re-issuing a lost link is a different operation and should be named like one.

Both defects are the same shape — a real refusal already existed, phrased for a human, and the HTTP layer replaced it with something machine-shaped on the way out. **Control plane 45 → 52.**

---

### 53. The resource registry (this session)

First item of the phase-2 roadmap, and the precondition for everything after it: Foundry's unit of navigation is the *resource*, and a schema with six unrelated kind tables cannot answer "what is in this project?". `resource_counts` on the project endpoint was six separate `COUNT(*)`s, which is the shape of a missing table.

**Migration 0032 adds `resources`** - identity, location, name, lifecycle - and a `resource_id` on each of the six kind tables. It is a registry, not a rewrite: `datasets` still owns everything true of a dataset and nothing else. The alternative, one table with a jsonb blob per kind, trades six verified schemas for one unverifiable one and leaves the schema tests nothing to check.

**Two kinds do not live in a project, and the registry says so.** `object_types` are workspace-wide - no `project_id` column at all, which is what made the first-run checklist tick a step in an empty project (§44) - and `connections` are workspace-wide when `scope = 'workspace'`. So `project_id` is nullable and means what it says: NULL is a resource belonging to the workspace, not a resource whose project is unknown. Forcing every kind into a project would have made the registry lie about two of them on day one. The listing endpoint keeps them out by default and returns them only for a caller that asks, with `project_id: null` so the UI can say which scope a row came from.

**Registration is structural, not a convention.** A BEFORE INSERT trigger creates the registry row and fills in `resource_id`; `NOT NULL` on that column means a kind row without a registry row cannot be written at all. Nothing in the API had to change to register anything - the datasets endpoint still knows nothing about the registry and the registry is still right. That was the point: partial adoption of a registry is worse than none, because the browser is then confidently incomplete rather than obviously empty.

**One writer for the name.** The kind table stays the source of truth; triggers mirror name and description into the registry, guarded by `IS DISTINCT FROM` so an unrelated column change does not churn the `updated_at` the browser sorts on. Two writable copies of a name is a guarantee of drift. One generic trigger function serves all six kinds, reading the row through `to_jsonb` rather than naming columns - the six tables disagree about which columns they have (`object_types` calls its name `display_name`, `connections` has no description, `models` have no `workspace_id`), and six near-identical functions would drift the moment one kind gained a column.

**The backfill is in the migration**, not a follow-up script, for the same reason. 12,025 existing rows registered, verified per kind against the source tables with zero orphans. The id is generated on the *source* side first, so correlating a registry row back to the row it describes is a column comparison rather than a clever trick that has to be trusted - the first attempt correlated by `row_number()` and was thrown away for being unverifiable.

**RLS matters more here, not less:** this table holds resource *names* across every project in a workspace, which is precisely the metadata a project boundary exists to keep private, and a leak would be uniform across every kind at once. The policy mirrors the connections one, because the nullable `project_id` has the same meaning in both places.

Tests assert the invariant rather than the endpoint - rows are created through the existing per-kind endpoints and the registry is checked to have noticed, which is the only version that fails if a trigger is dropped - plus a whole-database check that no kind table has an unregistered row, which is what will fail when a future migration adds a kind table and forgets to wire it up. **API 388 → 400** (376 → 388 with MariaDB down); worker unchanged at 50, which is the answer to "did adding a trigger to six hot tables break anything".

---

### 54. The resource browser and the application shell (this session)

Phase-2 items 0.2 and 0.3, built together because neither is worth much alone: the browser is a list of links to applications, and the shell is what those links open.

**The project page is now a directory rather than a menu.** The six pillar cards were a menu of *types*; the browser lists the resources themselves with the type as a column, sorted by what changed most recently, with per-kind filter chips carrying live counts, substring search, and paging. The pillar pages stay in the sidebar - deleting them would strand anyone who navigates that way, and keeping them as a second implementation of the same list is what would cause drift, so they remain the per-kind views they always were.

**Workspace-level resources are opt-in and labelled.** Object types and workspace-scoped connections have no project, so the browser shows them only when asked and marks each row `workspace`. Defaulting them in would repeat §44's mistake in a more visible place.

**`/r/{id}` is a route group outside `(platform)`**, so an application gets the whole viewport with no topbar or project sidebar - the point of the phase. A shared `ApplicationShell` carries the breadcrumb, the name and the kind; per-kind applications are later items, and until each lands its entry renders the resource's own summary plus a link to the pillar page that handles it today. That is not a placeholder for the shell: resolution, breadcrumbs, the tab and the stable link all work, and it names the roadmap item rather than saying "coming soon".

**The browser found the bug the tests could not.** Rows open in a new tab, and the new tab landed on `/login`. The session token lives in `sessionStorage`, which is **per-tab** - and Chrome does not clone it into a tab opened from a link, with or without `rel="noopener"` (both were tested; `noopener` was dropped anyway, since it guards against an untrusted page reaching `window.opener` and this is our own origin). **Per-tab token storage is structurally incompatible with a multi-tab, resource-centric product**, which is what this phase makes Anchor into.

Fixed as far as it can be without changing the security posture: the route guards now carry the requested path into `/login?next=…`, the dev sign-in honours it, and the hosted-UI round trip carries it through `sessionStorage` so a *shared* link survives a cold load and returns the reader to the resource. `safeReturnPath` refuses anything that is not a same-origin path - an absolute URL or a protocol-relative `//host` would make the login page an open redirect. Verified end to end in a browser: a cold context opening `/r/{id}` is bounced, signs in, and lands back on the resource.

**What that leaves open is a decision, not a bug:** every new tab still costs an authentication round trip. Choosing between shared storage, an httpOnly cookie session brokered by the API (which `lib/auth.ts` already flags as the stronger design), and living with the redirect is a change to the platform's security posture, so it is the owner's call rather than a detail to settle in a UI commit.

Browser-verified: chips and counts, kind filtering, the workspace-level toggle (24 scope markers on, 0 off), the shell with zero platform chrome, a real "this resource is not here" page for an unknown id, and no console errors. **API 400 → 403** (388 → 391 with MariaDB down).

---

### 55. An httpOnly session, because per-tab storage could not survive the phase (this session)

§54 ended on a decision rather than a bug: with the token in `sessionStorage`, every resource tab cost an authentication round trip. The owner chose the httpOnly-cookie session that `lib/auth.ts` had been flagging as the stronger design since it was written.

**The token no longer exists in JavaScript.** `POST /api/auth/session` takes a token, verifies it through exactly the path every other route uses, and answers with nothing but a `Set-Cookie` - httpOnly, `SameSite=Lax`, `Secure`, session-scoped. The direction is the point: a credential that only ever travels inward cannot be exfiltrated by a script that gets to run on this origin. An XSS can still *act* as the user while the page is open; nothing short of removing the browser from the loop prevents that. What it can no longer do is walk away with something that outlives the page.

**CSRF is handled by a header, not only by SameSite.** A cookie is attached to any request to this origin, including one another site caused, so cookie authentication is accepted only when the request also carries `X-Anchor-Session`. Cross-site markup cannot set headers, and a cross-origin `fetch` that sets one triggers a preflight this API does not answer - `allow_credentials=False` and no named origins, which is now load-bearing rather than incidental. `SameSite=Lax` is the second layer.

**The `Authorization` header still wins.** Extraction tries the header first and the cookie second, so every non-browser caller - the tests, the worker, anything holding a token deliberately - is untouched. The cookie is purely an addition for the browser.

**One thing broke on the way and is worth recording.** The session route first tried to reuse `get_current_user` by rewriting the request's headers in place. Starlette caches `request.headers` on first access, so it silently did nothing and the endpoint 401'd on a token it had just been handed. The fix was the structure the reuse was reaching for anyway: `authenticate_token(token)` split out of the dependency, called directly by the route and through `_extract_bearer` by everything else. Same verification, one implementation.

**`SESSION_COOKIE_SECURE` defaults to true and is turned off explicitly** by the test suite and the dev server, both of which speak http. The default is not `False`-for-convenience because the failure modes are asymmetric: a Secure cookie on `http://localhost` is a dev annoyance noticed in seconds, and a non-Secure cookie in production is a session token on the wire.

`localStorage` keeps one non-secret flag, `anchor.signed_in`, so the route guards can render or redirect without waiting on a request. Being wrong about it costs a redirect, not access - the API's 401 is what decides.

Browser-verified: `document.cookie` is empty and `sessionStorage` holds no token; the cookie reports `httpOnly: true`, `sameSite: Lax`; a ctrl-clicked tab and a fresh typed-in tab both load the resource with no sign-in; signing out clears the cookie and the next tab to act is bounced to `/login?next=…`. **API 403 → 409** (391 → 397 with MariaDB down); worker 50 unchanged.

---

### 56. The dataset application (this session)

Phase-2 item 3.1, and item 3.2 folded into it. Sequenced first among the applications on purpose: every answer it shows already existed, so it proves the application shell against endpoints known to work rather than co-developing an app and its backend.

**Five tabs over one resource** - Preview, Schema, History, Lineage, Details - replacing a list page, a row expander and two dialogs. Schema is where column profiling finally belongs (item 3.2): nulls, null rate, distinct count, min and max per column, computed once per version and cached on the version row (§22), so the tab costs nothing after the first open. History reads the version list and shows the row-count delta between consecutive versions, which is the question anybody opening a history actually has. Lineage reuses `PipelineGraphView` and the same focused-pipeline endpoint the old dialog used - one renderer, still only one.

**The tab is in the URL** (`?tab=schema`), so a link to a dataset's schema is a different link from one to its rows. `router.replace` rather than `push`: flicking between tabs should not bury the page the reader came from under a stack of back-button steps. Verified by deep link and by reload.

**`resolve` now returns `kind_id`.** `/r/{id}` knew *what* a resource was and could call nothing about it - every per-kind endpoint is keyed by the row's id in its own table, not by the resource id. Two id spaces, both needed: the resource id survives renames and is what links carry; the kind id is what `/datasets/{id}` takes. Six LEFT JOINs on a unique index, one of which matches.

**A 500 the application turned into the whole screen.** A dataset whose Parquet file is missing - storage cleared under a dev machine, a lifecycle rule, a database restored against the wrong bucket - raised `FileNotFoundError` out of the storage gateway and surfaced as `Internal Server Error`. That was survivable as one broken row in a list and is not survivable as an application's entire content. It is now a 409 saying the file is missing, that the metadata and history are intact, and that rebuilding or re-uploading restores it - three facts the reader needs and a traceback contains none of. Found by opening a real dataset in a real browser; the API tests had never deleted a file behind a live row.

Browser-verified: all five tabs, a 60-row upload previewing in full, profiling with correct types and distinct counts, deep links opening the named tab, tab surviving reload, and the missing-file refusal rendering as a sentence. **API 409 → 411** (397 → 399 here, MariaDB down): one test that the two id spaces are distinct and that the kind id works against that kind's endpoints, one that a dataset whose file has been deleted refuses in a sentence.

---

### 57. What a Workshop module is, on disk (this session)

Phase-2 item 1.1, the spike that blocks 1.2–1.5. Written up as `docs/decisions/0002-workshop-module-format.md`; the summary is that a module becomes one document with three parts - `layout`, `variables`, `events` - and Craft.js keeps the first and loses the other two.

**What the spike found, by reading a real saved app.** A parameter is declared as a *side effect of placing a widget*: a Filter node with `props.name = "region"` is the only place `region` comes into existence. A consumer binds to it with `filterParameter: "region"` - a string that happens to match. Nothing links them, so renaming the filter leaves the map asking for a parameter nobody sets, silently and forever, because a missing parameter reads as "no filter" (deliberately, so an app is not empty on first load). **The map then shows more rows than it should.** That is not a bug to fix in place; it is what an implicit, untyped, string-keyed namespace does, and it is exactly what Workshop variables are not.

**Decisions.** Variables are declared with an opaque id, a kind and a label; widgets reference the id, so renaming is free, deletion can be refused with "used by 2 widgets", and kinds can be checked. Ids are **not derived from the label** - a derived id is a rename waiting to break every reference, which is the failure being removed. Values stay runtime-only, as they already are: a saved app is not a saved session. Events live beside the layout rather than inside a widget's props, because an event routinely spans widgets and nesting it makes a table's behaviour depend on a node the table cannot see.

**Conversion is one-shot, in Python, and keeps the original.** Lazy conversion was rejected because apps nobody opens stay v1 forever and every reader then carries both formats indefinitely. A Node script running the renderer's own converter was rejected on evidence: this repo has no TypeScript test runner, so that converter would be the one piece of format-critical logic with no automated test. `services/canvas.py` still does not interpret definitions - `workshop_format.py` is a format tool imported by the migration and its tests and by nothing serving a request.

**A broken binding is recorded, not repaired.** A reference to a parameter nothing declares is left exactly as it is and listed under `broken_bindings`. The app is already wrong; a converter that quietly tidied the document would destroy the only evidence of it.

**Real data found the defect the fixture could not.** The fixture was copied out of the development database, so it looked authoritative - but every node in it had `type: {"resolvedName": …}`. Running the converter across all 163 saved apps failed on the first one containing a plain element, where Craft.js writes `type: "div"`, a bare string. One `AttributeError`, thirty seconds in, on data no hand-written fixture would have contained. Fixed and given its own test.

Proof, beyond the unit tests: conversion run over **every canvas app in the database** - 163 apps, 92 still in v1 - asserting the layout survives apart from reference props, that converting twice equals converting once, and that no rewritten reference dangles. All passed; 27 variables extracted, zero broken bindings in real data. **API 411 → 427.**

---

### 58. Object sets, and two ways a set can mean two things (this session)

The half of phase-2 item 1.2 the roadmap calls the thing that "decides whether Workshop parity is real": a set is a **query**, evaluated where the data is. Canvas filters a page of at most 200 rows in the browser (§36), which is fine for narrowing what is already on screen and cannot answer "how many match" or "give me the next page of the filtered set" - the two questions every Workshop widget asks.

**A definition, not a result.** A variable holds the *description* of a set - one object type plus filters - which is small, serialisable and identical for every viewer. Rows come from evaluating it. Storing rows would make a saved app a saved session, which decision 0002 rules out.

**`POST /workspaces/{ws}/object-sets/evaluate`**, viewer floor, returns a page plus the size of the whole set. Implemented in *both* stores - Postgres in SQL, OpenSearch in its query DSL - behind the existing gateway Protocol, with the object type verified to be in the workspace before it is used (an id in a request body is never trusted to be in scope).

**The cross-store test was the point, and it earned its keep twice.** `object_sets.matches` is the written-down definition of "does this row match"; the same rows and filters go through it, through Postgres and through OpenSearch, and all three must agree. Two disagreements fell out on the first run, both in code I had just written:

- **Ordered comparison.** Properties are stored untyped - jsonb in Postgres, a dynamically-mapped text field in OpenSearch - so `capacity > 40` means 250 > 40 on one store (which can cast) and `"250" < "40"` on the other (which compares indexed text). **`gt`/`gte`/`lt`/`lte` are now refused**, in a sentence that says why, rather than picked: a numeric-only reading breaks dates and codes, a lexicographic one is indefensible to anyone filtering a number, and the right answer is to honour the declared property type (`object_type_properties.data_type`, db 0026) and index accordingly - a mapping change with a backfill behind it, which is its own item.
- **Substring versus prefix.** The first implementation paired Postgres `ILIKE '%x%'` with OpenSearch `phrase_prefix`, so "los" matched "closed" on one store and not the other. The operator is now **`starts_with`** on both, which is also the only version that can use an index - a substring match is a wildcard query, fine on a hundred rows and pathological on a million, which is the exact cost server-side evaluation exists to avoid.

Neither would have been visible from one store. Both would have surfaced as an app giving different answers in staging and production.

**The OpenSearch fixture grew twice to keep its promise** of covering every call the gateway makes: it ignored `must_not` (so `neq` looked like it matched everything and passed), and it read `properties.status` as a top-level key rather than a path, so it matched nothing at all.

Not done here, and named rather than implied: aggregations (what Metric Cards need, roadmap 1.5 - they need a second implementation in both stores plus aggregation support in the fixture), search-around, derived variables and the builder's variables panel. **API 427 → 435.**

---

### 59. Multi-file repositories, on Postgres (this session)

Phase-2 item 2.1, the spike blocking 2.2–2.8. Written up as `docs/decisions/0003-repository-storage.md`, stored by migration 0033, implemented in `services/repositories.py`.

**It had to reconcile with decision 0001**, which said the Code pillar is a *projection* of `model_versions`. A multi-file repository cannot be one. The reconciliation is one-directional: repositories are where code is **authored**; publishing creates a model version that **copies the source in**; `model_versions.code` remains the immutable record of what ran. So 0001 is superseded in one direction only, and the constraint it was built around - `model_runs.model_version` resolving to exactly one piece of code, forever (db 0024) - is untouched. The copy is not redundancy: a version's code has to be readable without resolving a commit that may since have been on a deleted branch.

**Git's data model without git, and without trees.** Content-addressed blobs, so a file unchanged across a hundred commits is one row. But a commit carries a **flat `{path: sha}` manifest** of the whole snapshot rather than nested tree objects. Git splits snapshots into trees so a deep repository can share unchanged subtrees; a transforms repository here is tens of files, and the flat form makes a diff a dict comparison, a checkout one join, and a commit **verifiable by reading it** - which matters for the part of the system that decides what code ran. The cost, paths repeated per commit, is written down along with when to come back to it.

**Fast-forward only.** Merging text in a browser is a product in itself, and its blast radius is production transforms. A rejected move names the branch and its head, because accepting it discards commits silently - which is what the rule exists to prevent.

**Blobs are keyed by `(workspace_id, sha256)`, not by hash alone.** A shared blob table would make "does this hash exist?" a cross-tenant question, and existence is information. Costs storage; buys the isolation property the platform rests on.

**Deleting a branch never deletes commits** - they are still referenced by anything published from them, and `ON DELETE RESTRICT` on both `parent_id` and `model_versions.source_commit_id` makes that structural rather than a convention. Unreferenced commits are garbage, not errors; collecting them is named as a separate decision rather than designed here.

Two things the tests taught, both about the test rather than the code: `pytest-asyncio` is not installed (the suite uses anyio, whose plugin handles async fixtures directly), and a commit created inside the fixture's open transaction is invisible to a second connection - so the pinning test does its work on one connection, with a savepoint so the deliberately-refused DELETE does not poison the surrounding transaction.

**API 435 → 454.**

---

### 60. The repository HTTP surface (this session)

§59 built the store; this gives it a door, and gives `code_repos` the first writer it has had. The table has been in the schema since migration 0003 and empty in every deployment - decision 0001 declined to build a git server and left it with nothing to do - which is the state §46 flagged as "a table with no writer". Shipping a storage layer and stopping would have repeated it.

Create and list repositories, commit a snapshot, read a tree at a branch or a commit, list and create branches, delete a branch, walk history, diff two commits. Viewer reads, editor writes. Publishing a transform from a commit is deliberately *not* here: that is a separate act with its own review gate (§47).

**A new repository appears in the project browser and resolves at `/r/{id}` without this code knowing either exists** - db 0032's trigger registers it. That is the registry invariant paying off rather than being maintained: the route never mentions `resources`, and a test asserts the resource resolves with `kind: "code_repo"` and the right `kind_id`.

Two bugs, both found by the tests and both worth recording.

**`AmbiguousParameter`, the same family as §46.** `create_repository` built the vestigial `s3_prefix` column with `'repos/' || :pid || '/' || :slug`, so the same bind was a uuid column value in one place and a string operand in another and Postgres refused to deduce a type. Built in Python now. (The column itself is vestigial - it was for the bare git repository on S3 that decision 0001 rejected - and is filled with a derived value rather than dropped, because dropping a column the schema verifier asserts is a claim about the spec rather than about a feature.)

**A brand-new repository 404'd on its own default branch.** Branches are created by the first commit, so a repository nobody has committed to has no branch row at all, and `resolve_ref` treated that as "no such branch". An editor cannot open a repository it is told does not exist. The distinction now lives in the signature: a caller that *names* a branch gets a 404 for a typo; a caller falling back to the default gets an empty repository, because that is what it is.

**API 454 → 468.**

---

### 61. The repository application (this session)

§59 decided how repositories are stored and §60 gave them a door; this is the first thing that lets a person *look* at one. Until now a `code_repo` resource resolved to the placeholder summary, so the whole of decision 0003 was invisible outside a test.

Read-only, deliberately. The editor is roadmap 2.2 and brings Monaco with it; shipping a viewer first answers every question the editor will need answered - which branch, which commit, what changed - without a large dependency in the way, and makes the storage layer something you can point at.

**A tree at a ref**, so the ref is in the URL alongside the open file: `?branch=…&file=…`, or `?commit=…` when pinned to a point in history. "Look at this file on this branch" has to be a link, or reviewing anything means describing where to click. History lists commits on the selected branch with each one's diff, and clicking a commit pins the file view to it with a way back.

Two small things that only exist because the API was built first and honestly. A repository nobody has committed to has **no branch row at all** - branches are created by the first commit - so the branch picker offers the default anyway rather than rendering an empty select, and the files tab says the repository is empty rather than erroring. And switching branches while a file is open falls back to the first file rather than blanking the pane, because a file on one branch need not exist on another.

Per-commit diffs are fetched per row rather than returned with the history: a history endpoint that carried every diff would do that work whether or not anybody looked at it.

Browser-verified against a seeded repository with two branches and three commits: the file tree, the file choice surviving in the URL, `experiment` showing a genuinely different tree from `main`, per-commit diffs reading `added`/`changed`/`deleted`, and pinning to a commit showing that commit's files. No console errors. **API unchanged at 468** - this commit is frontend and shared types only.

---

### 62. A real editor, bundled (this session)

Phase-2 items 2.2 and 2.3. Monaco, and a working set you can commit from.

**The dependency decision is the item.** `@monaco-editor/react` fetches Monaco from jsDelivr by default, and the deployed stack runs inside the customer's VPC behind a strict egress policy - a CDN import is an editor that works on a laptop and is a blank rectangle in production. `loader.config({ monaco })` hands it the bundled copy instead. The browser check asserts it directly: **zero off-origin requests** while the editor loads and runs. Anything less would have been a bug that only appears after a real deploy, which is the class this phase keeps producing.

Workers are routed to the plain `editor.worker`. The languages offered - SQL, Python, Markdown, YAML, JSON - are tokenised by Monarch on the main thread and have no worker-backed language service; the ones that do (TypeScript) are not offered. Without this Monaco asks for a worker URL, does not find one, and logs on every keystroke.

**Loaded through `next/dynamic` with `ssr: false`**, so nothing but an editor pays for it: the production build puts `/r/[resourceId]` at 10.9 kB and 119 kB first-load, with Monaco outside both. Verified with a real `next build` rather than assumed - dev mode and production webpack are different enough that a bundling change unverified in production is a bundling change untested.

**The working set** is the committed tree with unsaved edits laid over it, kept out of the query cache so a refetch cannot silently discard typing, and reset only when the ref changes. Editing is against a *branch*: a pinned commit is read-only, because history that could be typed into would stop being a record of what happened. Files can be created and deleted; a changed file is marked in the tree; a commit sends the whole working tree, which is what a flat manifest means (decision 0003).

An unknown extension gets `plaintext` rather than a guess - mis-highlighted code reads as broken code. The editor is keyed by path, so switching files swaps the model rather than replaying new text into the old one, which would put a change in the undo stack of a file it did not come from.

Browser-verified end to end: the editor mounts with SQL colouring, typing raises the commit bar and marks the file, committing clears it, and the new commit appears at the top of history with its diff. No console errors, no off-origin requests. **API unchanged at 468.**

---

### 63. Where customer code runs, and what it could reach (this session)

Item 2.5's blocker, spiked before building the way 1.1 and 2.1 were. Written up as `docs/decisions/0004-running-customer-code.md`. It found something.

**Stating the threat model changed the answer.** `python_sandbox.py` already says it is "not a hard multi-tenant security boundary", but not what it is not a boundary *against*. The author of a transform is a customer employee with editor access, writing in the customer's own deployment in the customer's own AWS account - not an anonymous attacker, and already entitled to the data in their project. So the bar is not "run hostile code safely"; it is **a transform must not reach anything its author could not already reach**. By that measure process isolation with resource caps is close to right. One thing is not.

**The finding.** The sandbox builds the subprocess environment as an allowlist - `{"PATH", "HOME"}` - so no database URL and no AWS keys are inherited. Correct, and where the reasoning stopped. **In the deployed stack credentials do not arrive in the environment**: ECS delivers the task role over the network from `169.254.170.2`. Stripping `os.environ` does not touch it, and the same docstring already notes the sandbox "does not stop the transform from opening a network socket" - the two facts had never been put next to each other.

The worker's task role holds `dataBucket.grantReadWrite` (every project, every workspace in that deployment) and `appDbSecret.grantRead`. The second is worse than it looks: that secret is `platform_app`, which RLS applies to - but `rls_worker_for_workspace` (db 0006) grants visibility to any connection that sets `app.service = 'worker'` and `app.workspace_id`. That escape hatch is sound *because only the worker holds those credentials*. Three HTTP requests from inside a transform - fetch task credentials, fetch the secret, connect - and workspace isolation is gone.

**Not a live vulnerability**: Python transforms do not execute at all today, the API leaves them queued. Exactly the constraint that had to be settled before they run, which is what spiking is for.

**Decided:** the runner gets its own ECS task definition with no egress and an empty task role. Inputs are staged into its working directory by the caller, which holds the credentials; the output is read back the same way. The runner never touches S3 or Postgres and has no role worth stealing, which makes the network rule defence in depth rather than the only wall. Until both exist, Python stays off. SQL is unaffected - DuckDB with `enable_external_access` off is a real boundary for what SQL can express.

**Declarations are read statically, and that is part of the same decision.** Foundry evaluates a decorator at import time to find a transform's inputs and outputs; doing that here would mean *executing the file on the API's request path* to find out what it builds - the exact thing under discussion, before any sandbox is involved. `services/transform_declarations.py` parses with `ast` instead. Only literals are read: a computed output is refused rather than guessed, because a lineage graph that is right most of the time is worse than one that says it cannot read a file. SQL declares the same shape in its leading comment block, and only there - a `-- output:` inside a query is somebody explaining a column.

The load-bearing test is a file whose import would `rmtree("/")` and which parses fine. **API 468 → 482.**

---

### 64. The transform runner, and a correction to §63 (this session)

The infrastructure decision 0004 requires, and one thing §63 got the wrong way round.

**The correction.** §63 said "the runner is network-denied, and that is enforced outside the runner" as the control, with the empty role as defence in depth. That is backwards. ECS hands a task its role credentials over **link-local** networking from `169.254.170.2`, which a security group does not filter - so no egress rule prevents a transform *obtaining* credentials. What makes them harmless is that these ones grant nothing. **The empty role is the control; closed egress is the blast radius.** Both are built; the ordering matters because it decides which one must never be quietly relaxed.

**Built:** a Fargate task definition of its own, a task role with no policies of any kind, no `commonEnv` and no database secret, `AWS_EC2_METADATA_DISABLED` as a further layer, and a security group with `allowAllOutbound: false`. Run on demand rather than as a service - a transform is a job, and a service would be a container sitting idle with customer code in it.

**A no-egress task cannot start without help**, and this would have been found on a deploy. Fargate pulls the image and ships logs over the *task ENI*, so both are subject to that security group: with no route out the container never runs and CloudWatch shows an empty log stream - the same symptom as the arm64 problem in §20 and just as unhelpful. So the stack gains interface endpoints for ECR, ECR Docker and CloudWatch Logs, plus the **gateway** endpoint for S3 that people forget, since layers come from S3 rather than the ECR API and without it a pull authenticates and then hangs. **Cost, stated rather than discovered on a bill: roughly $21-24 a month per deployment.** That is the price of customer code that cannot phone home.

**`infra/cdk` had no tests**, and `cdk synth` needs Docker here (the migration Lambda bundles psycopg in a container, deliberately). So the check builds *only* the constructs under test into a throwaway stack and asserts the synthesised template, which needs neither: the runner has a role, that role holds no inline, managed or attached policies, its security group has no `0.0.0.0/0` egress, its container is given no secrets, and - the counterweight - the worker still has the permissions it needs, so a future tightening cannot strip the wrong task.

**The checks were mutation-tested rather than trusted.** Granting the runner the data bucket and opening its egress makes exactly those two fail, with the count in the message; reverting makes them pass. A check that cannot fail is theatre. `npm test` in `infra/cdk` now runs them, where it previously exited 1 with "no test specified".

Still missing before Python transforms run: the worker has no code that calls `RunTask` against this definition, and `transform_runner` does not exist as a module. The task definition names it, so the container would fail loudly rather than run something unintended.

---

### 65. The transform runner module, and the gap it exposed (this session)

§64 built the task definition and named a module that did not exist. This is that module - the container entrypoint customer transform code runs as, in a container with no egress and a task role that grants nothing.

**Everything it can reach is in its working directory, because that is all there is.** No S3 client, no database connection, nothing worth having credentials for. A test asserts it imports neither boto3 nor psycopg nor requests - not style policing: a client for any of them could only fail confusingly in that container, and its appearance would be a sign somebody had started to undo decision 0004.

**The design point is what `result.json` means.** It is written when the transform fails and *not* written when the run never got off the ground. A task that was never staged, ran out of memory or was killed leaves no result file, and that absence is how the caller tells "your SQL has a typo" from "the platform did not manage to run anything" - different problems, different owners, and a caller that could not distinguish them would report the wrong one to the wrong person. `read_job` therefore sits deliberately *outside* the try block that writes failures.

Execution reuses the contract `python_sandbox.py` established (inputs as DataFrames bound to their alias, result assigned to `output`), so the two paths do not disagree about what a transform is.

**The gap this exposed, and it is a real one.** With an empty task role and no egress, *how do inputs get in and outputs get out?* Not S3 - the runner cannot reach it, by design. The answer is a shared filesystem mounted by the infrastructure rather than by code holding credentials: an EFS access point, mounted into both the worker and the runner, with the ECS agent doing the mount. That preserves the empty role exactly - the container never authenticates to anything - and it is a filesystem, a mount target per subnet and a security group rule that do not exist yet.

Naming it rather than improvising: the transport is the next decision, and picking it while writing the runner would have meant deciding infrastructure inside a module that must not know any exists.

**Worker 50 → 55.** Still missing before Python transforms run: the EFS transport above, and worker-side dispatch that calls `RunTask` and waits.

---

### 66. The EFS scratch share, and the checks that turned out to be theatre (this session)

§65's named gap, built. A transform's inputs and its output now travel over a shared filesystem: an `efs.FileSystem` with its own security group, an access point at `/runs` pinning uid/gid 1000 and mode 750, mounted at `/work` in the runner and `/transform-scratch` in the worker (`makeService` gained a `mountScratch` option rather than a second copy of the service definition).

**Why a filesystem and not a bucket.** The runner's role grants nothing and its egress is closed, so it cannot reach S3 — deliberately, that is the whole of decision 0004. A mount works precisely because **the ECS agent performs it, not the container**: the runner authenticates to nothing, its role stays empty, and the property the decision rests on survives contact with the transport. The access point is what stops one run reading another's staging directory by walking up a level; transit encryption is set explicitly because it is *off* by default on an EFS volume configuration, which is the kind of default nobody notices.

Egress grew one destination — TCP 2049 to the scratch security group, reciprocated as an ingress rule — and that is still not a route out: the only two things this group can reach are AWS endpoints inside the VPC and one filesystem.

**Then mutation testing found a flaw in my own checks, which is the part worth recording.** §64's `transform-runner-check.ts` asserted that the runner's security group has no open egress. It read `Properties.SecurityGroupEgress` off the `AWS::EC2::SecurityGroup` resource. Adding a deliberate rule on port 8080 did not fail it. A throwaway probe printed the reason: **inline egress on the runner SG: NONE; standalone egress resources: 4**. An egress rule whose destination is *another security group* cannot be inlined — CloudFormation renders it as a separate `AWS::EC2::SecurityGroupEgress` resource — and every one of the runner's rules is of that kind. Both egress checks had been reading an empty array and passing on nothing since the day they were written. They were theatre, and they were theatre about the one property a reader of decision 0004 would most want assurance on.

The fix is `egressRulesFor()`, which merges inline and standalone rules and **refuses to pass on zero of them** ("found no egress rules to check - has the rendering changed?"). That guard is the actual lesson: a check that reads a structure CDK is free to re-render must fail when it finds nothing, or the next re-rendering turns it silently green again.

Re-run against four mutations, all now caught and each naming its own cause: an extra egress port (→ "can reach unexpected port(s): 8080"), a `0.0.0.0/0` rule on an *allowed* port 443 (→ "1 open egress rule(s)", correctly a different check from the port one), the container's mount point removed (→ "the runner container mounts nothing"), and both egress rules deleted. That last one exposed a smaller edge: a group with `allowAllOutbound: false` and no rules is not rendered empty — CDK inlines a placeholder to `255.255.255.255/32` so CloudFormation accepts it — so the check failed blaming "port 86", a rule nobody wrote. It now recognises the placeholder and says what it means: "has no egress rules at all - a task in it cannot pull its image or start".

8 checks, all passing, and now demonstrably for a reason. `npm test` in `infra/cdk` runs them.

**Still missing before Python transforms run:** worker-side dispatch that stages a job onto the scratch share, calls `RunTask` against the runner task definition, waits, and reads `result.json` — including what it does when there is no result file (§65's distinction, which only pays off if the caller honours it).

---

### 67. Dispatch: the worker's half of the runner contract (this session)

`anchor_worker/transform_dispatch.py`. Stage a run directory, `RunTask`, wait, read the result, clean up. Split into `stage`/`start`/`wait`/`collect` rather than one call, because those are the pieces ECS has and a caller that wants to record a task ARN against a run row can.

**One filesystem, two paths — the bug this module is shaped to avoid.** The worker mounts the scratch access point at `/transform-scratch`, the runner mounts it at `/work`, so a run directory is one directory with two names and `ANCHOR_TRANSFORM_WORKDIR` must carry the *runner's*. Handing over the worker's path produces a container that starts, finds no job file, and reports it — a symptom that reads like a caller bug and is a mount bug. `RunHandle` therefore carries both names and a test asserts the override never contains the worker's root.

**The exit code is not consulted.** §65 has the runner write `result.json` on failure *and* exit non-zero, deliberately in two places. This side reads the file: a result saying `failed` is `TransformFailed` carrying the author's own traceback; **no result file at all is `DispatchError`**, carrying whatever ECS gave as `stoppedReason`, because "OutOfMemoryError: Container killed due to memory usage" is the useful sentence and "your transform failed" would be a lie about whose problem it is. Mutation-tested: making a missing result file report as a failed transform fails exactly that test and nothing else.

Also refused rather than papered over: an input alias that is not a plain identifier (it becomes both a file name and the name the transform's code binds — silently renaming it would bind a name the author never wrote), a result claiming `ok` with no output file (recording a successful run against a dataset version with no bytes is the quietly-wrong outcome), and a run that overruns, which is stopped rather than left burning a Fargate task. `run_transform` removes the run directory in a `finally` — scratch is one shared filesystem, and a failed run that leaves its inputs behind leaves the customer's data behind.

**Testing.** Real `moto.server`, a real VPC and subnet, real RunTask/DescribeTasks/StopTask. Nothing here runs a container, so where ECS would start the runner the tests call `transform_runner.main()` on the staged directory — the actual entrypoint, so the files it reads and the result it writes are the ones the container would produce. Three mutations, each caught by one test: conflating the two failure kinds, handing over the worker's path, and cleaning up only on success. One branch is deliberately unproven and says so in the test module — `RunTask` returning 200 with an empty `tasks` list and a `failures` entry, which moto never produces; the handling stays because a caller waiting on a task ARN it never received is the exact failure this module exists to prevent.

**Two moto quirks worth knowing** if these tests ever look strange: it computes Fargate placement from the *container's* cpu/memory rather than the task-level values, so the fixture's container definition carries them; and `describe_tasks` advances the task's lifecycle a step per call (RUNNING → DEACTIVATING → STOPPING → DEPROVISIONING → STOPPED), which is what lets a real polling loop terminate against it.

**The infrastructure that makes it legal**, and one line of it is the security-relevant one. The worker gains `ecs:RunTask` on exactly the runner's task definition with an `ecs:cluster` condition, `DescribeTasks`/`StopTask` pinned to the same cluster, and **`iam:PassRole` naming exactly the runner's task role and execution role**. An unscoped `PassRole` is not a convenience — it lets the holder register a task definition naming any role in the account and start a container as it, which would make the runner's empty role, the whole control in decision 0004, beside the point. Three more checks in `transform-runner-check.ts` (11 total), each mutation-tested: `PassRole` widened to `*`, `RunTask` widened to `*`, and a missing env var each fail exactly one check.

**Worker 55 → 67.** What remains is wiring this into `jobs/model_runs.py` so a Python model run actually takes this path instead of `python_sandbox.py`'s subprocess — a substitution at one call site, but one that changes where every existing Python transform runs, so it is its own step rather than a rider on this one.

---

### 68. The substitution: customer Python actually moves into the runner (this session)

`jobs/model_runs.py` now imports `run_python_transform` from `transform_dispatch` rather than `python_sandbox`. One line at the call site; the decision lives in `transform_dispatch.isolation_mode()`, with the same signature and return shape as before so the model run path cannot tell which it got.

**All four settings or none, and a half-configured worker is refused.** This is the only interesting decision in the item. The obvious design — use the runner when configured, fall back when not — silently downgrades a deployment that lost an environment variable back to `python_sandbox`, which its own docstring is explicit is process isolation and *not* a security boundary. A deployment that believed it had the isolation and did not is worse than a worker that will not start a transform, so three-of-four raises and names what is missing. None-of-four is local development and falls back, which is what every Python transform has done until now.

**Where the §67 distinction stops.** `model_runs.status` has no value between 'succeeded' and 'failed', so an infrastructure failure is recorded as a failed run with a message beginning "the platform could not run this transform: …", and a failed transform carries the author's own traceback. The distinction survives in the text and nowhere else. That is a real limitation, not a design: expressing it properly means a status value and a UI that shows it, which is a migration and a screen, not a rider on this.

**Verified.** The 18 existing model-run tests pass unchanged (they exercise the fallback path, since this sandbox has no ECS). The runner path through the same function is covered directly: `AWS_ENDPOINT_URL_ECS` points boto3 at moto — a real service endpoint from the environment, the same mechanism a deployment uses to pick a region — so `run_python_transform` runs for real with no injected client. Two mutations, each caught by one test: a half-configured worker downgrading silently, and an infrastructure failure losing its attribution.

**One thing this found in my own code.** `wait()` took `poll_interval_s: float = DEFAULT_POLL_INTERVAL_S`, and a test that set `dispatch.DEFAULT_POLL_INTERVAL_S = 0` changed nothing — a default argument binds when the function is defined, not when it is called. The test passed either way and took 49 seconds doing it; the giveaway was the clock, not a failure. Both limits now default to `None` and read the constant at call time (4 seconds). Same family as the Starlette header-cache mistake in §57: a change that appeared to take effect and did not.

---

### 69. Preview: running a transform without committing it (this session)

Roadmap item 2.6. `POST .../repositories/{id}/preview` takes a path and **the editor's buffer**, reads the file's declaration, resolves its declared inputs to datasets in the project by name, runs the transform over a sample, and returns rows and schema. Nothing is written. The panel sits under the editor in the repository application and runs when asked, never on a keystroke — a preview reads real datasets and costs real work.

**Previewing the buffer rather than the commit is the whole point.** The question a person asks is "does what I just typed work", and they ask it *before* they are willing to commit. A preview that could only run committed code would answer a question nobody has. Sending no `content` still previews the committed file, which is what the history view wants.

**A sample is not the dataset, and the response says so in three places.** Each input reports `rows_available` / `rows_used` / `sampled`; the result reports `sampled`; the panel prints a warning that names the number. A `group by` over the first thousand rows of an input produces smaller groups than the real thing and a join finds fewer matches than it will — the number looks like an answer, so anything that shows it without saying otherwise will be believed. The counterweight matters too, and has its own test: an input that fits entirely is *not* flagged, because crying sample on a two-row table teaches people to ignore the warning that counts.

**The drift check the roadmap asked for.** When the declared output names a dataset that already exists, the response carries `engine.diff_schemas` between that dataset's stored schema and what the transform now produces — added, removed, retyped columns. Finding out at preview that an edit drops a column from `daily_orders` is the difference between a conversation and a support ticket. It reuses the connectors' existing drift comparison rather than inventing a second notion of what a schema change is.

**Python is refused, with a sentence.** Decision 0004 puts customer Python in an isolated task, never in the API process; previewing it means dispatching Fargate and waiting sixty-odd seconds, which is a job with a status rather than an HTTP response. The refusal says that and says SQL previews now. That is the honest half-built state rather than an endpoint that quietly runs Python in the wrong place.

`preview_transform` lives in `dataset_engine.py` beside `run_transform` because it needs the same sandbox discipline and a second almost-identical one would drift from it. It is simpler in one respect: nothing is written, so there is no trusted writer connection and user SQL never leaves the sandbox where `enable_external_access` is off.

**On mutation testing, including one I got wrong.** Four mutations each fail exactly one test: never reporting a sample, ignoring the editor buffer, reporting no drift, and letting Python through. A fifth — deleting `SET enable_external_access=false` from the preview sandbox — appeared to fail nothing, and I concluded the sandbox tests were theatre and rewrote them. **The mutation was wrong, not the tests**: `run_transform` and `preview_transform` set up their sandboxes with byte-identical statements, and a first-occurrence string replace was hitting `run_transform`'s. Correctly targeted, the test fails on exactly the right assertion — the file's contents come back in the response body. Worth recording twice over: the preview path had no sandbox test at all until this (a *second* sandbox proves nothing about the first), and a mutation that appears to survive is a claim about the mutation as much as about the test.

**14 preview tests**, real Postgres, real uploads, real Parquet, real DuckDB; 100 tests green across the six API files this touched. Verified in a real browser end to end: preview the committed file, edit the buffer, preview again and watch the columns change while the commit bar still says the file is uncommitted.

---

### 70. The typed variable graph (this session)

Roadmap item 1.2's server half. `services/workshop_variables.py` validates a module's variables, computes derived ones in dependency order, and answers "what would break if I deleted this" by reading the document.

**Read this section knowing what it is not.** Nothing produces a `format: 2` document yet. Item 1.1 was the *spike* — decision 0002, the converter, and its tests — and the one-shot conversion it designed has not been run; the builder still saves a bare Craft.js map. So this is a validated layer with an endpoint and no producer. Deliberate order (the format is the thing most expensive to get wrong, so its rules exist before anything writes to it), but it means **the refusals below are proven by tests and have never refused a real save**. The conversion and a builder that speaks v2 are the next step, and until then a v1 definition passes through the save path untouched — a test asserts that, because refusing one would break every app that exists.

**Three refusals, each removing a failure Canvas commits today** (decision 0002, "what exists today, precisely"):

- **A binding to a variable nothing declares.** Today that reads as "no filter", so the widget shows *more* rows than it should — silently, forever, and looking like data rather than like a bug. It is now a save that does not happen, and the refusal says "the widget would quietly show everything" rather than naming a constraint.
- **Deleting a variable something uses.** `usages()` reads the layout, so "used by 2 widgets" is answerable. A derivation counts as a usage too — deleting an input out from under one is the same mistake, and naming only the widget case would make the refusal look arbitrary.
- **A derivation cycle.** The precedent is Models item 7 (§30); the reason is sharper here because there is no run loop to notice — a cycle is either an infinite recompute in the browser or a value depending on its own previous value. Reported by *label*, sorted, because the person reading named the variables and has never seen `v_7f3a1c`.

**Two semantics that two implementations would get quietly different**, which is why they have tests naming the reasoning rather than the behaviour. `if_else` does not use Python truthiness: `0` and `""` are values somebody typed, and treating them as absence would make a numeric filter of zero behave as though the filter were off — only `None` and `false` are false. And `cast` *refuses* what it cannot convert rather than returning nothing, because a blank card sends the reader to look at the widget instead of at the variable feeding it.

**Why evaluation is a server round trip**, given the transforms are pure and the values are shown in the browser. This repo already carries five files mirrored between two runtimes and a standing note that a sixth should become a shared package instead. A TypeScript copy of `if_else`'s truthiness and `cast`'s refusals would be that sixth, and those are precisely the semantics that drift invisibly. The cost is close to zero where it matters — derived values change when their inputs change, which is the same moment the app is already asking the server to re-evaluate an object set, so it rides along with a call that was happening anyway. The honest exception is a text input, where every debounced keystroke now costs a request a local computation would not.

**Where validation lives.** In the route, not in `services/canvas.py`, which stores an opaque blob and does not interpret it — a property decision 0002 records as worth keeping. The API refuses the document; the storage layer stays uninterested in what is inside it.

`object_property` and `object_set_aggregation` are declared and refused with "not built yet": both read the instance store, so they are a round trip rather than a pure function, and quietly returning `None` for them would make every caller guess which of its results were real.

**24 service tests + 5 route tests**, all green with 79 across the canvas/workshop files. Three mutations, each caught: cycles not refused, dangling bindings allowed, and `if_else` switched to Python truthiness.

---

### 71. The format-2 conversion, run (this session)

§70's variable graph had no producer. This gives it one: migration `0034_workshop_module_format.py` converts every stored Canvas app to a `format: 2` module, and the builder reads and writes that format.

**The first `.py` migration.** The runner was SQL-only; it now applies `NNNN_name.py` files exposing `apply(cur)`, in the same numbered sequence, in the same transaction, with the same checksum guard and the same once-only record. Python because the thing being rewritten is a jsonb document whose *meaning* the application defines — which props name a parameter, which widget declares one. Re-expressing that in PL/pgSQL would be a second implementation of the format, in the language with no tests, drifting from the one `test_workshop_format.py` exercises. The migration imports the converter instead. A `.py` step that raises anything at all rolls back and records nothing, same as a SQL failure: a half-converted database is not a state this can leave behind.

**What the conversion touches, precisely.** Only `canvas_apps.definition`, the live document. Historical `canvas_app_versions` rows are left alone — they are the record of what the app was, and rewriting them would make the history lie about the format it was written in. The conversion appends a *new* version row carrying the converted document, so the change is itself in the history rather than an edit nobody can see.

**Run against this sandbox's database: 109 of 212 apps converted**, the other 103 being apps nobody ever saved (skipped rather than given an empty module — an app with no layout has nothing to preserve, and converting it would put a version row in the history of an app that has never had one). Afterwards: 116 documents at format 2, **zero left at v1**.

**The check that mattered, and a finding from running it.** Every converted document was fed through §70's `validate_module`. First pass: 114 pass, 2 fail. The two turned out to be **residue from my own mutation testing** — the runs that disabled the cycle and dangling-binding refusals let those test saves through, and the rows stayed in the shared dev database. Deleted; 114 of 114 then validated. That ad-hoc check is now two tests in `test_workshop_format.py`, because the converter and the validator meeting is not something anything else makes them do: if they disagree, this migration converts every app in a deployment into something the API then refuses to save, and nobody finds out until the first person edits one. They agree because the converter leaves an *unresolved* reference as its original parameter name rather than inventing a `v_` id for it — so the validator sees a legacy name, which is not its business, rather than a dangling variable id.

**The builder speaks v2**, via `lib/workshop-module.ts`. Both shapes are handled rather than only v2, because a deployment that has not run the migration still serves v1 and the browser is not the place to discover that. `isV2` is a structural check, not a version compare. Saving carries variables and events across untouched — a save that dropped them would unbind every widget in the app on the first save after opening, which is to say immediately and invisibly.

**Verified in a real browser** against a converted app: the widgets render (a builder handed the whole v2 document would render nothing), Save works, and the document comes back still `format: 2` with its variables intact. **527 API tests green.**

**What is still missing from item 1.2** is the variables panel itself — create, rename, retype, see usages. `usagesOf` is written and unused; the server already refuses the deletions that matter, so the panel is the affordance rather than the enforcement. (Built in §72.)

---

### 72. The variables panel (this session)

The last piece of item 1.2's builder work. A tab beside the widget settings: create, rename, retype, set a default, build a derivation, delete.

**Renaming is the whole point of the format, so the panel says so.** The field is labelled "Label"; the id sits under it as unchangeable fact — `id v_pbez9mvg — never changes, so renaming is free`. Canvas's parameters were string keys, and renaming one silently unbound every widget reading it; here the id is what widgets point at and the label is free to change.

**Two refusals, and the panel is the affordance rather than the enforcement.** Deleting a variable something binds to is refused *before* the button does anything, naming what uses it: *"Region is used by 2 things (bar1.filterParameter, table1.filterParameter). Unbind it there first."* Saving a cycle is refused by the server, and the top bar now surfaces that instead of going quiet — *"these variables depend on each other in a loop: Full greeting, Greeting prefix"*. Both verified in a real browser. The server is still what enforces both; the panel exists so somebody does not walk into a 422 after doing the work.

**Layout and variables save together, and that is a real constraint.** Craft.js owns the layout and the panel owns the variables, so `moduleFrom` takes both and carries across whatever it was not given. A save with only one half would silently discard the other's edits — and the variables state is reseeded only when a new *version* arrives, so a background refetch cannot throw away typing.

**Small choices with reasons.** The transform picker omits `object_property` and `object_set_aggregation` — the API refuses them until they are built, and offering a choice that fails on save is worse than not offering it. The input picker omits the variable being edited, so "a variable may not read itself" is a refusal nobody can walk into. Changing a transform clears its inputs rather than carrying them, because three inputs meant as condition/then/else are not three parts of a join. And the value shown is labelled "as last saved", because it comes from the server reading the *saved* document — it cannot show a derivation nobody has saved, and implying otherwise would be worse than showing nothing.

**The one thing genuinely mirrored** is `REFERENCE_PROPS`, which decides what the API refuses and, separately, what the builder shows as a usage. Drift makes the *builder* wrong — it would offer to delete a variable a widget binds to, and the save would then be refused with a message the panel had just implied was impossible. A test asserts the two lists match by parsing the TypeScript, the same mechanical shape `test_property_types.py` uses. That list grows widget by widget through item 1.5, which is exactly when one copy gets updated and the other does not.

**528 API tests green.** The panel itself has no unit tests — this repo still has no TypeScript test runner, which decision 0002 already named as the reason it chose a Python converter. The browser verification is the coverage: create a variable, derive a second from it, save, and confirm the document comes back with the derivation, the converted variable, and the layout all intact.

---

### 73. Object-set variables: the spine, end to end (this session)

The half item 1.2 calls "the item that decides whether Workshop parity is real". **Dataset → object type → object set → variable → widget**, working in a browser.

**An object-set variable holds a definition, not rows.** A type plus filters — small, serialisable, the same for every viewer. `/object-sets/evaluate` turns it into instances. Storing rows would make a saved app a saved session (decision 0002 §3), and it would also mean a table, a chart and a count each holding their own copy of "the set" rather than reading one.

**A filter variable narrows a set through a derivation.** `filter_set` takes two inputs — the set to narrow and the variable holding the value — plus a property and an operator. That makes Foundry's Filter-List-drives-Object-Table into an ordinary edge in the variable graph, so it gets cycle detection, usage-aware deletion and dependency ordering for free rather than as a special case. Filters chain: two controls narrowing one set is two derivations, and the second reads the first.

**An unset filter shows everything rather than nothing**, and this is the decision most worth stating. A viewer who has not touched the filter yet should see the whole set; filtering for `region = null` would make every app open empty and look broken. That is *not* the failure decision 0002 removed — that one was a binding to a variable nothing declared, which the save path now refuses outright. This is a declared variable with no value yet, which is an ordinary state with an obvious meaning. Mutation-tested: dropping the guard fails exactly that test.

**Narrowing does not mutate what it read.** `filter_set` copies; a second consumer of the base set would otherwise silently get the narrowed one. Also mutation-tested.

**Refusals that keep the two halves honest.** A set variable must have a type *or* a derivation, never both (two answers to "where do these rows come from"). A non-`object_set` variable carrying a set is refused. The set definition is validated at *save* with the same `object_sets.parse` the read path uses, so a definition that would be refused at read time is refused where somebody can still fix it. And `filter_set`'s operator list is `object_sets`' own — `gt` and friends stay refused, because Postgres casts and OpenSearch compares text, so an app's results would otherwise depend on which store the deployment runs.

**Two contexts in the browser, deliberately.** `values` is what the viewer has set and is written by widgets; `resolved` is what every variable is worth and is written only by the server. Merging them would let a widget write a derived variable — a value that is a function of its inputs — so one document could show two things depending on which write the reader believed. `VariableBridge` posts the raw values, debounced, and holds a request ticket so an older resolve landing late cannot overwrite a newer one (which would show the previous filter's rows under the current filter, and read as the filter being broken).

**A bug caught before it shipped.** The evaluate endpoint was project-scoped, and a *published* app is opened by a workspace member who may not be in its project at all (§15). Every published Workshop app would have resolved no variables for exactly the audience it was published to — and the symptom would be widgets showing nothing, which reads as no data rather than as no permission. There is now a `published-canvas-apps/{id}/variables/evaluate` on the workspace router, scoped by `get_published` exactly as the read path is.

**Proved in a browser** against real data: a CSV of five sites, an object type over it, a real sync, then an app whose filter narrows a set the table reads. Opens showing 5; type "north" and it shows 3, naming what narrowed it (`where region = north`); clear it and 5 return. No reload, no console errors. **538 API tests green**, 10 of them new for object-set variables.

**Still open in 1.2:** `object_property` and `object_set_aggregation` as *variable transforms*, which would need the variable evaluator to reach the instance store. §74 shows a Metric Card does not need that.

---

### 74. Aggregating a set, and the Metric Card that shows it (this session)

Item 1.5's first widget, and the one that makes an object set worth having as a shared thing: **the card and the table read the same variable**, so "3 sites" and the three rows under it cannot disagree.

**Two aggregations, and the line between them is principled.** `count` and `count_distinct` ship; `sum`, `avg`, `min` and `max` are refused with a sentence. The reason is the one that already refuses ordered operators: instance properties are stored untyped, so summing one means deciding what "3" and "10" are without being told. Postgres would cast; OpenSearch cannot aggregate numerically over a text-mapped field at all. **A card whose number is right on one deployment and absent on another is worse than one that says the platform cannot answer yet.** The two that ship are *text-identity* operations — how many documents, how many distinct values — so both stores agree without either knowing a property's type. The fix for the rest is the same single piece of work: honour the declared property type (db 0026) in the index mapping, with a backfill behind it.

**Not a variable transform, and this is a correction to what §73 implied.** A Metric Card does not need `object_set_aggregation` as a *variable*; it needs an aggregation, which is an endpoint. Making the variable evaluator reach the instance store would turn `evaluate()` from a pure function into an async store-dependent one for every caller, to no benefit here. `/object-sets/aggregate` takes the resolved set definition, exactly as the table does with `/evaluate`.

**Separate from `/evaluate` rather than a flag on it.** They are different questions with different costs: a page of rows, or a number over every row. A card that got its number by paging would be wrong the moment a set outgrew a page — which is exactly when the number starts mattering. A test asserts a set of 5 pages 2 and counts 5.

**One definition of the set, in both stores.** The filter-clause builders were extracted (`_set_clauses` in OpenSearch, `_set_predicate` in Postgres) so paging and aggregating share them. Two copies would be two definitions of what a set *is*, and the first time they drifted a Metric Card would count rows the table beside it does not show.

**The fixture server gained cardinality**, implemented exactly rather than approximately — OpenSearch's cardinality is approximate above ~40k distinct values, and a fixture copying that would be imitating an error budget it cannot reproduce. Its existing caveat still stands and is now load-bearing here: it has no analysers, so `properties.x.keyword` and `properties.x` are the same value to it, and whether the real mapping's keyword subfield exists is still something only a real cluster can confirm.

**4 cross-store cases** assert Postgres and OpenSearch produce the same number for count and count_distinct, filtered and unfiltered — different mechanisms, one answer, or an app's headline figure would depend on which store the deployment runs.

**547 API tests green.** Verified in a browser beside §73's table: opens at 5 with the card reading 5; type "north" and both go to 3; clear it and both return to 5.

**What is left in 1.5** for this thread: the chart reading a set (a grouped count is cross-store safe the same way; a measure is not, for the same reason as above). Built in §75.

---

### 75. The chart over a set, and item 1.2's proof completed (this session)

A chart bound to an object-set variable plots a **grouped count** — how many in each distinct value of one property. With it, the roadmap's proof for item 1.2 is met in full: *a filter list narrowing an object set that an object table and a chart both read, live, with a metric card over the same set; change the filter, all three update, no page reload.*

Verified in a browser on real data. Opens with 5 sites, the card reading 5 and the chart showing open 3 / closed 2. Type "north": the table drops to 3 rows, the card to 3, and the chart regroups to open 2 / closed 1 — and the chart's counts sum to exactly the table's total, asserted rather than eyeballed.

**A grouped count, not a grouped sum**, for the third time and the same reason: bar *heights* from a sum over untyped properties would differ between the two stores. Counting is text-identity and both agree.

**Ordering is part of the contract.** Count descending *then value ascending*, asked for explicitly on both sides. Count alone leaves ties to each store's own tie-break, so two deployments would draw the same data in a different order and one of them would look wrong to whoever knew the other. The cross-store test compares the ordered list, not a set.

**Truncation is reported, not silent.** A terms aggregation is capped (`MAX_GROUPS = 20`) because an unbounded group-by is a real cost and a chart with three hundred bars is not a chart. The response carries `distinct_total`, and `truncated` is derived from it rather than from "did we fill the page" — which would be wrong on a set with exactly `limit` groups. The widget prints "showing the largest N of M values". Same principle as the sampled preview in §69: a number that looks like the whole answer will be believed.

**Missing properties are excluded rather than grouped under a blank label**, because OpenSearch's terms aggregation skips missing fields — a bar labelled "" appearing on one store only is exactly the disagreement this module is arranged to avoid.

**One dimension control, not two.** Binding a set disables the dataset picker and repoints the group-by at the *set's* properties. Offering both equally would let somebody configure a dataset and a set and leave the reader to work out which won.

**553 API tests green**, including 3 cross-store grouping cases. The fixture server gained a terms aggregation with the same explicit ordering, so the fixture is not the reason a test passes.

**A false negative in my own verification, worth recording.** The first browser probe looked for bar labels in `svg text` and found none, which read as "the chart did not render". The screenshot showed it rendering correctly. The probe was wrong, not the widget — and rather than loosen the assertion I repointed it at the `/object-sets/group` responses the bars are drawn from, which is both a real assertion and one that cannot pass for the wrong reason.

---

### 76. Events: a click that does something the app author chose (this session)

Roadmap item 1.3. An event is a **trigger** — which widget, what happened — and an **ordered list of effects**. Clicking a row in an object table now sets a variable, and a text widget shows it: click Aberdeen Yard, the app says *Selected: Aberdeen Yard (open)*; click Carlisle Works and it says *Carlisle Works (closed)*. Verified in a browser.

**The widget does not decide what a click means.** It announces that a row was chosen and hands over the row; the module's events say what happens. That is the difference between a widget with a hardcoded behaviour and one an app author can wire — and it is why events live beside the layout rather than inside a widget's props (decision 0002 §4): an event routinely spans widgets, and nesting it in the trigger's node would hide it from the widget it acts on.

**The execution semantics are Foundry's, matched deliberately.** Effects run in configured order; setting a variable copies the value immediately so the next effect sees it; nothing awaits downstream recomputation. The implementation detail that makes the second one true is worth stating: `run()` threads a plain object through the loop rather than reading React state between effects, because state updates are batched and an effect reading a variable a previous effect just set would otherwise read the **old** value — silently, and only sometimes. Awaiting each effect instead would serialise a click behind network round trips *and* change what the second effect sees; the roadmap called this "the kind of difference that is invisible until someone's app misbehaves", and it is right.

**One click is one render.** The context gained `setMany`, so a run's writes apply together. Applying them one at a time would let a widget re-fetch against a half-applied set of writes.

**What the server refuses**, in `workshop_events.py`, wired into the same save path as variables: a trigger on a widget the layout does not contain (it can never fire, so it is not an event — it is a fragment of a previous design), a write to a variable the module does not declare, a write to a **derived** variable (a function of its inputs; honouring the write would let one document show two different things depending on which write the reader believed — the same rule `evaluate` already enforces for viewer values), and a `javascript:` url. That last one matters because an app author is not necessarily trusted by everyone who opens the app, and a published app is opened by the whole workspace.

**`navigate`, `run_action` and `export` are named and refused**, each blocked on something real rather than on effort: pages and overlays do not exist until item 1.4; binding an action's parameters to variables is its own design question; export needs a download surface the viewer route lacks. Refusing with the reason beats accepting and silently doing nothing, which is what an unknown effect type would otherwise do.

**Two smaller decisions.** `{{token}}` resolving to nothing yields an empty string rather than the literal `{{token}}` — a half-substituted label reads as a data problem, an empty one reads as a missing value, which is what it is. And an unknown effect *type* at run time is skipped rather than thrown: the server refuses them at save, so one arriving here means an older document, and a click that does part of its job beats one that throws in the middle of the list.

`CanvasText` interpolates resolved variables, because without it an event that sets a variable has nothing to show for itself and "did the click work" is only answerable from the network tab. Rows are only styled clickable when the module actually wires an event to that table — a row that looks clickable and does nothing is worse than one that looks inert.

**561 API tests green**, 8 of them new for events.

---

### 77. Pages, tabs, and the effect that was waiting on them (this session)

The first slice of roadmap item 1.4. An app can have more than one screen: a `Page` widget, a `Tabs` widget, and the `navigate` effect §76 refused for want of somewhere to navigate to.

Verified in a browser: a two-page app whose tab bar lists Browse and Selected; the running app opens on the first page; clicking a row **sets a variable and changes page** — two effects of one event, in order; the tab bar goes back.

**A page is a node in the layout tree, not a separate document.** That keeps decision 0002's "the layout is a Craft.js tree" true, keeps the builder editing one tree, and means the set of pages is *read* from the layout rather than stored beside it — the same argument `usages()` makes: a second copy of a fact disagrees with the first the moment something deletes a node without knowing to update it.

**Which page is showing is runtime state, never persisted** — the rule variable values already follow (decision 0002 §3). A published app opens on its first page for every viewer, not on whatever page the last person was looking at; a saved app is not a saved session. `current` starts null and a page reads that as "show me if I am the first", rather than state being seeded with the first page's id at mount: the *layout* decides which page is first, and a copy of that decision in state would disagree the moment somebody reordered them.

**In the builder every page is visible**, stacked and labelled; in the running app exactly one renders. Hiding all but one in the builder would make the other pages uneditable without a page switcher in the chrome, and would hide from the author that they exist at all.

**Tabs go through the event system rather than calling `go` directly**, so "what does this tab do" is answered by the same list as every other trigger and a tab can set a variable on the way. It still navigates when nothing is wired — a tab bar that did nothing until somebody configured an event would look broken, and "go to the page this tab is for" is the only thing a tab could reasonably mean.

**The server refuses navigating to a widget that is not a page.** Not a smaller version of navigating to a page: a click that would do nothing, and save time is the only moment anybody can fix it.

**A bug my own design hid, and the fix.** The first browser run showed the row click setting the variable but *not* changing page. Cause: `run()` skips an effect whose capability is absent, and the object table assembled its event context by hand and forgot `goToPage`. The skip is the right runtime rule — a click that does part of its job beats one that throws mid-list — which is exactly why the capability must not go missing by accident. There is now one `useEventContext()` hook that assembles all three capabilities, so a widget has nothing to forget. The lesson is the general one: a rule that tolerates a missing piece needs a construction that cannot omit it.

One stale test updated honestly rather than around: `test_an_unbuilt_effect_says_so` used `navigate` as its example and now uses `run_action`, with a comment saying why. `run_action` and `export` remain refused — binding an action's parameters to variables is its own design question, and export needs a download surface the viewer route lacks.

**567 API tests green**, 6 of them new for pages.

**What is left in 1.4:** sections (columns, rows, toolbars), overlays, the Layout sidebar, and drag-to-resize. Pages were the piece the rest hangs off and the one blocking an effect.

---

### 78. Sections and overlays: a page that is not one column (this session)

The second slice of 1.4. A `Section` widget splits a page into columns or rows, and an `Overlay` widget puts a modal or a drawer over the page instead of navigating away from it.

Verified in a browser, in both modes: the running app lays the demo app out as a 1:2 split — metric card and chart stacked on the left, object table on the right; a row click opens a modal showing the clicked row with the page still underneath; Close returns to it; at 700px wide the columns stack. In the builder, dropping a widget into a column puts it in that column, and editing the proportions from `2,1` to `1,1` re-lays out live.

**Widths are proportions, not pixels.** A section's children share the space by weight (`weights: "1,2"`), so a two-column split stays a two-column split on a narrower screen instead of overflowing, and the arithmetic never has to know how many gaps there are (`flex-grow`, `flex-basis: 0`).

**Drag-to-resize is deliberately not built.** It is an affordance over these same numbers. Building the handle first would have meant a layout nobody could describe in the saved document; the numbers exist now, so the handle can arrive without a format change.

**A toolbar is not a section type**, though Foundry lists one. A tabbed section is the Tabs widget over pages — the same idea one level up — and a toolbar is a row with different padding. Three of the four would have been the same code with a different label.

**An overlay is the same kind of node as a page, and `navigate` takes either.** What differs is what the browser does: a page replaces, an overlay covers. **Closing is its own effect** (`close_overlay`) rather than "navigate to nothing", because closing returns you to the page underneath — which navigate has no way to name. In the builder an overlay renders inline like a page, so it stays editable and visible; only the running app makes it a layer.

**Below 900px a column section stops being columns.** That is the roadmap's "responsive rules per section type": rows are already a stack and need no rule.

**The bug that made every section one column, and why nothing errored.** Craft.js hands a canvas node its children as a *single* Fragment holding one element per child, and `React.Children.toArray` does not look inside a Fragment — so the obvious `toArray(children)` returned a one-element array no matter what the section contained. Every section rendered as one column and looked, from the outside, like a feature that simply did not work. There is now one `childList()` helper with the explanation attached, so the next canvas widget that needs its children individually does not rediscover it.

**A check that passed while the modal was invisible.** Every structural assertion about the overlay — it opens, it shows the clicked row, the page is still underneath, Close returns — passed while the panel was fully transparent, because the CSS named `var(--surface)` and there is no `--surface`; an undefined custom property is not an error, it just computes to nothing. The check now asserts the pixels too (the scrim covers the viewport and dims, the panel is opaque). The same typo was already in `.repo-preview-table th`, where it left a sticky header transparent and rows scrolling under it; fixed in passing.

**A section needs somewhere to click that is the section.** Its children fill it, so the settings panel for proportions, direction and gap was unreachable — settings you cannot open are not settings. In the builder a section now carries a small label ("COLUMNS · 1:2"), the way a page does, and that label is the click target. The Layout sidebar, still to come, is the general answer.

**571 API tests green**, 4 of them new for overlays. All four were mutation-tested: dropping overlays from `navigate`'s accepted targets, making `overlays()` return pages, removing `close_overlay` from the saved effects, and making `pages()` ignore its widget argument each fail at least one test.

**What is left in 1.4:** the Layout sidebar, drag-to-resize, and a module header.

---

### 79. The Layout sidebar (this session)

The third slice of 1.4, and the panel Foundry's own docs name: layout elements are edited "from a Layout sidebar panel or by selecting them in the module view". Both, not either — selecting in the view is the fast path for a widget you can see, and the tree is the only way to reach one you cannot.

**It closes a structural hole, not a convenience gap.** A section is filled by its children and a page by its sections, so a container has no pixels of its own to click. §78 had to give sections a builder label purely to make their settings reachable, and that trick does not generalise — not to a container three levels down, not to an empty one. A tree does: every node in the document gets exactly one row whether or not it has any area on screen.

**It holds no state.** Craft's node map *is* the layout (decision 0002), so the panel reads the editor's state and renders it. There is nothing here that can disagree with what is being edited — the same argument `pages()` and `usages()` make server-side, applied to the builder.

**Each row carries what distinguishes it from its siblings** — a page's title, a section's direction and proportions, a widget's bound variable. A page of four sections would otherwise be four identical rows, which is a tree that tells you the shape and not the thing.

**Rows never wrap.** The indent is the only thing showing the nesting, so a wrapped row would make the one signal ambiguous; the detail truncates instead.

**Stacked above the widget palette rather than tabbed with it.** The right-hand column tabs Widget against Variables because they answer different questions about different things and one is usually irrelevant. These two are both about the document in front of you, and an author dropping a widget wants to see where it landed — a tab would trade a scroll for a click on every edit.

Verified in a browser: eleven rows for the demo module's eleven nodes in tree order, indent tracking depth across four levels, clicking a section's row opening its proportions, an overlay reachable the same way, and deleting a widget removing its row.

**What is left in 1.4:** the module header, and drag-to-resize.

---

### 80. The module header (this session)

The last structural piece of 1.4: Foundry's persistent toolbar, holding the module-wide title, the tabs that move between pages, and any module-wide buttons.

**Why this is a node type when §78 refused to make a toolbar one.** That refusal said a toolbar is "a row with different padding rather than a different concept", and the test it failed is the right one to apply here: a header differs in *behaviour*. It is pinned while the page beneath it scrolls, and there is at most one per module. Decoration would not have earned a node type; those two rules do.

**It persists across page changes structurally, not by special case.** It is not inside a page, and only pages hide themselves when another page is showing — so nothing in the header had to be taught about pages at all.

**At most one, enforced by the server.** Two nodes both claiming to be *the* module-wide toolbar is a document no renderer can settle. The refusal counts what it found — "a module may have one header and this one has 2" — because a number is something an author can act on where "invalid header" is not. It lives in `validate_module`, not the builder: a document can arrive by any route, and a rule only the builder applies is not a rule.

**A header is not a navigation target.** It is always showing, so `navigate` refuses it exactly as it refuses any other non-page widget — which came out of the existing check for free, and there is a test pinning that so it stays that way.

Verified in a browser: the header renders above the page in the running app with the tab bar inside it, survives a page change, and its title reads a variable (`Sites · {{v_region}}` becomes `Sites · north` when the filter is set). The live API refuses a second header with the counted message.

**A check that would have passed either way, caught and fixed.** The first stickiness assertion scrolled 84px against a header sitting 259px down the page — the header could not have left the viewport whether or not it was sticky. Re-run against a short viewport it now scrolls 404px past that offset and asserts the header is at y=0, which only a sticky one can be. Same lesson as §78's transparent modal: an assertion that cannot fail is not evidence.

**575 API tests green**, 4 new for the header, all mutation-tested: dropping the one-header rule, making the limit two, and making a header count as a page each fail at least one test.

**1.4 is done bar drag-to-resize**, which stays deferred for §78's reason — it is an affordance over numbers that already exist and can arrive without a format change.

---

### 81. The Button: the event system's primary trigger surface (this session)

Roadmap 1.5's third priority-1 widget, and the trigger source 1.3 was missing. A button runs whatever events are wired to its click.

**One button is one node, and Foundry's "Button Group" is a row of them in a Section.** A trigger is `(node, on)`. A node holding several buttons would need a third part naming *which* button — in every event, in the saved format — to express something the layout already expresses. The row is the grouping; the node is the button. This is the same test §80 applied to the header and §78 applied to toolbar sections: a new concept has to earn itself against what the format already says.

**`enabledVariable` is what makes it a widget rather than a control.** Item 1.5's rule is that a widget consumes input variables and emits output variables; this one consumes a variable to decide whether it can be pressed at all — "Clear Aberdeen Yard (open)", greyed out until something is selected — and emits whatever its events write. It is a reference prop, so deleting the variable a button is gated on is refused like any other usage rather than quietly making the button permanently live.

**Only an explicitly falsy value disables it.** `undefined` means "not resolved yet", and a button dead until the first resolve lands is a button people click twice. Unset means always pressable, for the same reason: an app whose buttons are all dead until somebody declares a variable looks broken.

**A button with nothing wired says so, in the builder.** Unlike Tabs there is no default meaning to fall back on — a tab self-evidently goes to its page, a button could mean anything — so silence would be indistinguishable from a broken click.

**What the browser check found: the modal was right and the check was wrong.** The first run tried to click the header's button while the overlay was open and Playwright reported the scrim intercepting it — which is a modal doing its job. The demo module now has two buttons, and both are better for it: the header's clears the selection, the modal's own clears *and* closes, which is the `close_overlay` effect a modal's action needs and a button on the page beneath cannot reach.

Verified in a browser: the header button starts gated shut, opens when a row is selected, and its label interpolates the selection; the header button is genuinely unreachable behind the scrim (asserted with `elementFromPoint`, not assumed); the modal's button runs both its effects in order; and once the modal is gone the header's button clears the variable and gates itself shut again.

**577 API tests green** at the time, 2 new for the button's gate. Both mutation-tested, along with the mirrored `REFERENCE_PROPS` list: dropping `enabledVariable` from the server's copy fails three tests, and dropping it from the browser's copy fails the mirror test that exists for exactly this.

---

### 82. The Filter List, and the derivation under it (this session)

Roadmap 1.5's first priority-1 widget and, the roadmap says, "the canonical Workshop widget": property-aware filters over an object set. It is a rewrite rather than an extension — Anchor's existing Filter emits a scalar for one configured property, and this one lets a viewer narrow on several properties and several values at once.

**It writes clauses; a derivation makes the set.** The widget does not produce an object-set variable directly, and that is the design rather than a shortcut. Object sets resolve on the server — that is what makes "how many are there" and "the next page" answerable at all — so a widget that wrote a set would be a second place sets come from, with no rule for which one wins. Instead the widget writes a plain list of clauses into an `array` variable, and a new **`narrow_set`** derivation applies them to the input set. Widgets write values; derivations make sets.

**`narrow_set` carries no property or operator, unlike `filter_set`.** Which properties a Filter List narrows on is what the *viewer* chooses, so it belongs to the value rather than to the declaration. That is the whole difference between the two transforms, and why the older one is still right for "a dropdown drives one fixed filter".

**The clauses are runtime data and get the same parse every object set gets.** They arrive from a browser, so unknown operators, ordered comparisons and missing values are refused with the sentence `object_sets.parse` already writes, rather than dropped. A dropped clause is a set wider than the viewer asked for — the failure decision 0002 exists to remove.

**A bug this introduced, and the fix.** `/variables/evaluate` wrapped validation *and* evaluation in one `except VariableError`, reporting both as 409 "this saved app no longer validates". That was true when only the document could fail. Now a Filter List sends clauses with the request, so a bad clause is a bad **request** against a perfectly good document — and a 409 would send whoever read it to edit an app with nothing wrong with it. The two calls are now separate: 409 for the document, 422 for the values, on both the project-scoped and published routes.

**The options are the data's own values with counts, not a list somebody typed**, read from `/object-sets/group` — the same endpoint the chart uses. A hand-typed list goes stale the first time a new value appears, the argument that made object links derived rather than stored (§37).

**The counts come from the unfiltered input set on purpose.** Recomputing them against the narrowed set would make every unpicked option read "0", which tells a viewer nothing about what picking it would do.

**One value is `eq`, several are `in`.** A one-element `in` would work identically on both stores, but `eq` is what a reader of the saved document expects to see for a single choice.

Verified in a browser, against the demo app rebuilt around it: a group per configured property with the real values and counts (`north 3`, `south 2`); every row shown before anything is picked; one value narrows 5 rows to 3; a second property narrows to 2; a second value of that property widens back to 3 (an OR within a property, AND across them); the metric card and chart move with the table because all three read the same set; and clearing every checkbox is the whole set again rather than an empty one.

**584 API tests green**, 7 new. All mutation-tested: trusting clauses instead of parsing them, dropping the base set's own filters, making an empty choice mean an empty set, and blaming a bad request on the saved app each fail at least one test.

---

### 83. The Object Table upgrade: columns, a sort, and real paging (this session)

Roadmap 1.5's second priority-1 item. Three of its four parts: which columns to show and in what order, a server-side sort, and paging that fetches a page rather than truncating one.

**Sorting is by key or by when a row last changed, and sorting by a property is refused.** The same refusal `ORDERED_OPERATORS` makes and for the same reason: instance properties are stored untyped, so ordering by one means choosing between "250 after 40" and "250 before 40" on the caller's behalf, and the two stores would choose differently. A table sorted one way on Postgres and another on OpenSearch is the invisible kind of wrong. The refusal says what it would take — the declared property type behind the index — so it is a sentence somebody can act on, not a "no".

**The settings panel offers the four sorts rather than making column headers clickable.** A header that errored on some columns and not others would be worse than one that never invited the click.

**Every sort ties on the primary key**, on both stores. A bulk sync writes every row in one instant, so `updated_at` ties are the normal case, not the rare one — and without a tiebreak two pages of one sort can share a row and miss another, with nothing about the symptom pointing at the sort.

**Paging is runtime state and resets when the set changes.** Same rule as pages and variable values (decision 0002 §3): a saved app opens on page one for every viewer. The reset matters more than it sounds — narrowing a filter while on page 3 would otherwise leave a viewer looking at an empty table that has rows.

**A test that could not fail, caught by mutation testing.** The paging test asserted no row repeats and none is missed, which passed *with the tiebreak removed* — a small table comes back in a stable order from a sequential scan by accident. It now also asserts that tied timestamps fall through to ascending keys, which is the whole of what the tiebreak promises and is checkable. Third time this session that a green check turned out to be checking nothing (§78's transparent modal, §80's stickiness); the pattern is always the same — the assertion was about the shape of the result rather than the thing the code decides.

**A finding, not fixed here: two sources feeding one object type produce two instances per primary key.** Instance identity is `(source_id, primary_key)`, so pointing a second dataset at an existing object type duplicates every overlapping key rather than updating it. Hit while growing the demo fixture from five rows to nine. Left as a finding because multi-source object types are a real Foundry pattern and changing instance identity is an ontology decision with a backfill behind it, not a footnote in a widget upgrade. It is in the rough edges below.

Verified in a browser: the three configured columns in the configured order with the fourth property absent; three rows a page sorted by key; "1–3 of 9" with Previous dead on the first page; Next fetching S4–S6 from the server and Previous returning to exactly the page left; and picking a filter while on page 3 returning to page 1 with rows on it.

**592 API tests green**, 9 new — including a cross-store case per sort, extending the check that already stops a *filter* meaning two things to cover ordering. All mutation-tested: accepting any property as a sort, dropping the key tiebreak on Postgres, reversing OpenSearch's descending key sort, and ignoring the sort argument entirely each fail at least one test.

**What remains in the Object Table item:** row selection emitting a *single-object* variable rather than the text payload it emits today. That is an events question rather than a table one — it turns on what a `single_object` variable holds, a key to fetch or the row you clicked — and it is recorded that way in the roadmap.

---

### 84. What a single-object variable holds, and `object_property` (this session)

The last part of roadmap 1.5's Object Table item — row selection emitting a single-object variable — which also settles a question left open since 1.2 and turns one of its two refused transforms on.

**The decision: a `single_object` variable holds the object the viewer picked**, whole — `object_type_id`, `primary_key`, `properties` — not a key to fetch later. Three consequences, and the middle one is the price:

*Reading a property is a lookup, not a round trip*, which is why `object_property` left `STORE_TRANSFORMS`. It was there on the assumption that the variable holds a key; the fetch it was waiting for does not need to happen.

*The value is a snapshot of the click.* If the object changes afterwards, a widget reading it keeps showing what was clicked until something clicks again. That is the honest reading of "the row you picked", and it is why the reference travels with the snapshot — a widget that needs live values has the type and the key to re-read with, and an object *set* re-evaluates on every resolve regardless.

*Nothing here is persisted*, so this does not make a saved app a saved session (decision 0002 §3). The objection that keeps object-set variables holding a definition rather than rows does not apply to a value that only ever exists for one viewing — which is exactly why that objection is written down where it is.

**`set_variable` gained a `from`, not a magic template token.** `{"variable": "v_site", "from": "object"}` writes the object the trigger was about. A list rather than a boolean, because "the set the trigger was about" is the obvious next one and would otherwise arrive as a second flag. Giving both a `from` and a `value` is refused: two ways of saying what to write, and no rule for which wins.

**The primary key is readable by name.** It is not inside `properties` — a row's key is its own field — so without this it would be the one thing about an object an app could not show.

**Nothing picked reads as empty; a wrong-shaped value is refused.** A detail panel before the first click is an ordinary state. A variable holding a string cannot have properties, and rendering blank there would hide a document wired wrongly.

**The table hands over the same row twice, deliberately**: flattened as `payload` for `{{...}}` in a label, and whole as `object` for a `single_object` variable — which needs to know which field is the key, and a flattened map cannot say.

Verified in a browser: before any click the derived label is empty rather than broken; clicking Carlisle Works writes the object and three separate `object_property` variables read the key, the name and the status off it (`S3 · Carlisle Works · closed`); picking another row moves every reader at once; clearing the object empties everything derived from it.

**603 API tests green**, 11 new. All mutation-tested: reading a non-object as blank, making the primary key unreadable, making "nothing picked" an error, accepting a `from` and a `value` together, and accepting any `from` name each fail at least one test.

**One stale test updated honestly rather than around**: the case asserting that "the ontology transforms" are unbuilt now names only `object_set_aggregation`, with a comment saying `object_property` moved and why.

---

### 85. The events panel: wiring an app without writing the document (this session)

Roadmap 1.6's third panel, and the thing that had been quietly missing since §76: **the event system could only be authored by writing JSON.** Every event in this repo's demo module was put there by a seed script. A widget library and a variable graph are not an application builder if the thing that connects them is unreachable from the builder.

The panel lists the module's events by the widget they fire from, opens one to show its trigger and its ordered effects, and edits all of it: add and delete events, add, configure, reorder and remove effects.

**It offers only what the server accepts.** Trigger widgets come from the Craft tree, triggers from what that widget can actually fire, variables from the declared ones *minus the derived*, pages from the pages and overlays that exist. That is §77's lesson applied deliberately rather than after the fact: a rule that tolerates a missing piece needs a construction that cannot omit it. Every refusal in `workshop_events.py` is a shape this panel cannot build.

**Effect order is numbered and reorderable, because it is semantic.** Effects run in configured order and setting a variable copies immediately, so the same two effects the other way round produce a different result. A list you could not reorder would hide the one thing about an event that is not obvious from reading it.

**Changing an effect's type clears its config.** A `page` left behind by a navigate would ride along inside a `set_variable` and be saved as debris nobody put there.

**Nothing here validates.** The server does. This panel's job is to make the invalid unbuildable, not to re-implement the rules — a second copy of them is a second thing to keep in step, which this repo already has enough of.

**The working events run in Preview before they are saved**, the way an unsaved variable already resolves. The builder now holds all three parts of the document — layout, variables, events — and `moduleFrom` writes all three in one save, which is the same argument its docstring already made for two.

**Two panels caught up with the last two slices.** The variables panel offered `filter_set` as the only way to narrow a set and refused to offer `object_property` at all — both true when written, both stale after §82 and §84. It now offers `narrow_set` ("a filter list the viewer builds") beside `filter_set` ("one value, on a property you choose"), hiding the property and operator fields for the former since it has neither, and offers `object_property` with its property field. `object_set_aggregation` is still absent, still for its original reason.

Verified in a browser: the three seeded events read back correctly with their effects in order; only the three writable variables are offered as `set_variable` targets (the four derived ones absent); `navigate` offers the two pages and the overlay; a new event wired from the panel — header button, clicked, opens the overlay — saves without a refusal and **runs on click in Preview**.

**603 API tests green**, unchanged: this is a builder surface over rules that already existed and are already covered. The check that matters here is the browser one.

**A check that picked the wrong widget.** The first run wired the event to "the first thing called Button" and asserted a click on the header's button ran it — which it did not, because the overlay has a button too. Fixed by naming the one it means. The same shape as §84's row that was on another page: an assertion that is precise about the outcome and vague about the subject.

---

### 86. The Map over an object set (this session)

Roadmap 1.5's last priority-2 widget that could not be wired to anything. The map now reads an `object_set` variable — the same set the table, the chart and the card read, narrowed once on the server — and a pin click emits the object it stands for.

**One trigger, worded for where it fires.** A pin click means what a row click means: an object was picked. It is therefore the *same* trigger, `row_select`, and the events panel labels it "Pin selected" on a map and "Row selected" on a table. A second trigger name meaning the same thing would be a second thing every document, every panel and every refusal has to know about, bought with nothing but a nicer word in one place.

**The instance travels with the pin.** `MapPoint` gained an optional instance, so the click can hand over the whole object the way §84's row click does — and it stays optional, because a dataset row is not an object and has nothing to emit.

**The set names the type, so the author does not.** With a set bound, the geopoint picker offers the properties of *that set's* type and the inline type/filter fields are hidden — the same ordering the object table uses, for the same reason: offering both invites configuring both and wondering which won.

**What is not built, and why it is not effort.** The roadmap asks for selection emitting a *set* — draw an area, filter everything by it. That needs numeric comparison on latitude and longitude, which is exactly what `ORDERED_OPERATORS` refuses: properties are stored untyped, so a bounding box would compare text on one store and numbers on the other. It is the same blocker as numeric aggregations (§74), property sorts (§83) and ordered filters, and it now has four things waiting behind it — which is the strongest argument yet that honouring declared property types in the index is the next piece of real work in the ontology.

Verified in a browser: nine pins for the whole set, five after the Filter List narrows it to the north — the map moving with everything else because it reads the same variable — and a pin click opening the detail overlay with `S1 · Aberdeen Yard · open`, read off the emitted object by three `object_property` variables.

**A fourth check that could not fail, caught the same way.** The narrowing assertion compared a Playwright locator's count with itself: locators are live, so `before` was re-evaluated after the filter and the check compared 5 with 5. Counted into an integer first. That is now four in this session (§78, §80, §83, here), and the pattern has not varied — the check held a *reference* to the thing it was measuring instead of a measurement.

**603 API tests green**, unchanged: this is a widget reading an endpoint that already existed, and the browser check is what covers it.

---

### 87. The inline action form, and a cluster of features behind one missing capability (this session)

**First, the thing I set out to do and did not.** The intended next item was honouring declared property types in the instance index — the blocker behind ordered filters, numeric aggregations (§74), property sorts (§83) and map area selection (§86). It cannot be done honestly *in this sandbox*, and the reason is worth writing down rather than discovering twice:

The whole point of that work is that the two stores must agree — `ORDERED_OPERATORS` exists because the first implementation shipped and the cross-store test caught Postgres and OpenSearch ordering `250` and `40` differently. Postgres can be tested here for real. OpenSearch cannot: the tests drive `tests/opensearch_fixture_server.py`, which says in its own docstring that it has no analyzers and **no mapping enforcement**. Numeric mapping verified against it would be verifying my own stub's arithmetic. There is no Docker daemon in this environment and `artifacts.opensearch.org` is not reachable through the proxy, so a real cluster cannot be stood up either. Whoever picks this up needs a real OpenSearch; the code is not the hard part, the agreement is. **Not blocked in general — blocked here**, which is a different sentence and the useful one.

**What I built instead**: roadmap 1.5's Inline Action Form, which §84 had just made possible.

**The form takes its subject from a `single_object` variable.** Bound, the record dropdown disappears and the form edits the object somebody picked — which is the whole difference between a form *beside* an app and a form *in* one. Unbound it keeps the dropdown, so apps built before this still work.

**The fields start at the object's current values** and are re-seeded whenever the subject changes. A form still holding the last object's edits when you pick a new one is an edit about to go to the wrong record.

**It writes the updated object back into the variable.** This is §84's stated cost being paid: a `single_object` variable holds the object as it was when it was picked, so after a write every reader of it would show the values you had just replaced — the staleness argument at its most visible. The widget that changed the object is the one place that knows what it now says, so it writes it back, and it invalidates the object-set queries the table, the map and the filter list read.

**The emitted object gained its instance id.** An action executes against an instance id, so an object you can look at but not edit would be half a reference — the same argument §84 made for carrying the type and the key.

Verified in a browser: clicking a row opens a modal that says "Editing S1" with `status` prefilled to `open`, no record dropdown; changing it to `closed` and submitting saves, the detail line above the form moves to `closed` immediately, and the table underneath shows `closed` when the modal closes. The check puts the fixture back afterwards.

**A silent no-op in my own tooling, worth naming.** The instance id did not arrive on the first run because a `str.replace` in my edit script matched nothing — I had asserted on some replacements in that script and not on that one, and Python's `replace` returns the string unchanged rather than failing. Every scripted edit in this session now asserts its target exists. The symptom was a form that said "nothing picked yet" while an object was plainly picked, which cost a debugging pass to trace back to an edit that never happened.

**603 API tests green**, unchanged: the action execute path already existed and is already covered — what changed is which widget calls it and with what.

---

### 88. Publishing pins a version (this session)

Roadmap 1.7's first half, and a sharp edge the publish dialog admitted to in its own copy: *"Publishing is not a snapshot either — each save you make from here is immediately what they see."* Every keystroke an author saved went straight to everyone the app was published to, half-finished layouts included. Publishing did not mean anything; it was a visibility checkbox.

**It is a pointer, not a new store.** `canvas_app_versions` has held one row per save since migration 0003. Migration 0035 adds `canvas_apps.published_version`, publishing sets it to the current version, and the published read path joins to that version's definition. Saving never touches it.

**The backfill pins what each app's viewers are looking at right now.** An already-published app gets `published_version = current_version` at migration time, so nobody's view changes at the moment of migration and from then on it changes only when somebody publishes. A migration that moved every viewer to something they had not seen would be an odd way to introduce the idea that viewers should not be moved without a publish.

**Going private forgets the pin**, so a later re-publish pins what is current *then* rather than resurrecting a version nobody has looked at since. Publishing an app that has never been saved pins nothing and its viewers get the live (empty) definition, which is the same thing, rather than a 404 for a version row that does not exist.

**`current_version` is still reported next to it**, because "published v1, editing v2" is the sentence an author of a live app needs and one number cannot say it. The builder shows `· viewers see v32` in the subtitle whenever the two differ, and the publish dialog says which version each side is on. The dialog's copy was rewritten: it described the old behaviour accurately, and leaving it would have been worse than never having written it.

**The evaluate route reads the published document too.** It resolves variables from the stored definition, so without this a viewer's app would render one version and resolve another — a variable added after publishing would reach a viewer whose layout has no widget bound to it. There is a test for exactly that.

Verified in a browser with two sessions side by side: the author publishes, changes the header to "Work in progress" and saves; the builder says `viewers see v32`; the viewer reloads and still sees `Sites`; the author publishes again and the viewer moves.

**609 API tests green**, 6 new.

**A stale check, found and repaired.** `packages/db/verify_schema.py` asserts "no unexplained extra tables" against a list written when the spec had 22. Sixteen tables have been added by migrations since, so the check had been *failing on every run* — the one check watching for tables nobody meant to create had been reporting a wall of expected ones and telling nobody anything. The list now names each table and the migration that added it, plus `customer_stacks`, which is the control plane's and appears only because this sandbox points both services at one Postgres.

**And why it went unnoticed: the verifier is single-use per database.** It creates a fixture organisation, and `audit_log` carries an append-only `DELETE` rule (migration 0004) that *silently swallows* deletes — `DELETE 0` with the row still there, even as superuser with `row_security = off`. So the fixture org can never be removed and a second run dies on a unique-slug violation before it checks anything. The rule is right; the verifier needing a fresh database is the thing to know, and it is in the rough edges now.

---

### 89. Visibility conditions, and 1.7 finished (this session)

The rest of roadmap 1.7: a layout node can be bound to a variable and shows only while that variable is truthy. Foundry's own example of the feature is "a section that appears only when a set is non-empty".

**The condition is a variable, not an expression.** `is_empty`/`is_not_empty` have been in the variable graph since item 1.2 — the roadmap says they exist "precisely for this" — so anything a viewer's state can decide is already expressible as a derivation. An expression language here would be a second grammar to validate, explain, and keep in step with the first, bought for nothing.

**It lives on the layout nodes, not on every widget.** Section and Container carry `visibleWhen`. Hiding a section hides what is in it, which is what "this part of the page does not apply yet" means; a single widget that needs hiding goes in a container, which is one node rather than a new concept, and the alternative was a prop on all fourteen widgets.

**Unresolved means visible.** `undefined` is "the first resolve has not come back yet", and a section that vanished until it did would flash on every load. Only an explicitly falsy value hides — the rule §81's button gate already follows, now shared by both through one hook.

**In the builder a hidden node renders anyway, marked** `HIDDEN UNLESS ANY FILTER CHOSEN`. Hiding it there would make it uneditable and hide from the author that it exists, which is the argument §77 made for pages and is the same argument. The marker never reaches a viewer.

**A visibility binding is a usage**, so `visibleWhen` joined the mirrored `REFERENCE_PROPS` lists and deleting the variable a section depends on is refused rather than quietly making the section permanent.

Verified in a browser: the builder shows the demo's results section marked as conditional; the running app opens with it absent and its Filter List present; ticking a filter reveals the section with its table, chart and card; unticking hides it again.

**611 API tests green**, 2 new.

**Roadmap item 1.7 is now done**, and with it every item in section 1 except the pieces named as blocked or deferred: drag-to-resize (an affordance over numbers that exist), chart drill-down, and the four features behind the typed-property index.

---

### 90. Closing the way back to v1, and a docstring that was lying (this session)

Roadmap 1.8 asked for a one-shot conversion of every saved app to the Workshop format. §71 ran it. This is what was missing to call the item done, and it was found by checking the claim rather than accepting it.

**The API still accepted v1 documents on save**, with a comment saying "or every unconverted app would stop being saveable" — and a test asserting it. That was true when written and had quietly stopped being true: migration 0034 converted every stored app, and the migration container runs *before* this code does (`migrate.py`'s own docstring), so an unconverted app cannot reach the route. What could still reach it is a script or a client older than the conversion, and what either would write is an app with no variables, no events and no pages — silently, since a v1 document is valid and simply has none of those things.

**So a v1 document is now refused on save**, in a sentence that says what it is and why it cannot be what the sender meant. Reading v1 is untouched: 0034 deliberately leaves historical version rows in the format they were written in, and the browser still renders them (`layoutOf` is a structural check, not a version compare).

**A conversion is only finished when the old format cannot come back.** That is the general form of it, and it is why this belongs to 1.8 rather than being a tidy-up.

**The test that asserted the opposite was updated, not deleted**, with its old premise written down — the same treatment §77's stale test got. A second test now pins that `{}` still saves: an empty document is not a v1 document, it is an app with nothing in it, which is what every app is before somebody drags a widget onto it.

**A docstring contradicting itself, and why it mattered.** `0034`'s summary said "`canvas_apps.definition` becomes a `format: 2` document, **and every version row is converted alongside it**", while the next paragraph said historical version rows are **left untouched**. The code does the latter. That is not a cosmetic error: §88 made the published read path join to a version row, so "are old version rows v1?" is now a question with consequences, and the file answered it both ways. **Corrected in `packages/db/migrations/ERRATA.md`, not in the file** — see §92: the correction was first made in place, and editing an applied migration breaks `migrate.py` for every database that already ran it.

For the record, the answer: **a `published_version` can only point at a post-conversion row**, because 0034 bumped `current_version` for every app it converted and §88's backfill pinned `current_version`. A v1 document therefore cannot reach a viewer through that path — and if one somehow did, the browser renders it rather than failing.

**612 API tests green**, 1 new; two existing ones updated where their premises had changed. Re-verified in a browser that the builder still saves through the stricter route.

### 91. Branches, and the merge that decision 0003 chose (this session)

Roadmap 2.4 asked for create/switch/list/delete, a diff view, and fast-forward merge. §60 built the first four as service functions with an HTTP surface; what was missing was **the merge path and any screen at all**. Both are here.

**Merging is a comparison plus a pointer move, and the comparison is the interesting half.** `compare_branches()` classifies two branches into one of four states — `identical`, `fast_forward`, `contained`, `diverged` — and reports both directions: how many commits `head` has that `base` does not, *and* the reverse. Only one of those numbers is needed to merge; the other is what makes a refusal actionable, because "I cannot merge this" without saying what is on the other side leaves somebody guessing at what they are missing.

**`contained` is deliberately not an error.** Merging a branch that has already landed is a no-op, and calling a no-op a failure sends people looking for a problem that is not there — the second click of a double-click lands exactly here.

**The refusal is where fast-forward-only earns its keep, and where it costs.** Decision 0003 chose it over three-way merge, on the grounds that merging text in a browser is a product in itself with production transforms as its blast radius. The cost is that two branches which both moved cannot be merged at all. So the refusal carries what it takes to act: both counts, and the files that would have to be re-committed on a branch cut from the base. `move_branch()`'s own refusal was also wrong in a small way that mattered — it advised a **rebase**, and there is no rebase here. It now names the recovery that exists.

**The screen shows the verdict before the button, not after the failure.** A merge that can only report "no" once you have pressed it teaches people to press and hope, so the Branches tab runs the comparison as you pick the two refs and renders the sentence for whichever of the four states applies; the diverged one gets a paragraph and a disabled button rather than a live button and a 409. The button itself names the branch that moves and the commit it moves to. The API refusal stays as the backstop for the race where somebody commits between the comparison and the click.

**The default branch can no longer be deleted**, and the check is in the service rather than the route because it is a rule about the repository. Deleting it does not fail: `read_tree` falls back to the default branch, finds no row, and the repository **opens as empty** — which is also what losing everything looks like. Quietly indistinguishable from catastrophe is the worst shape a delete can take.

**Ten mutations, ten caught.** Treating `diverged` as mergeable, classifying it as `fast_forward`, classifying `contained` as `fast_forward`, never moving the branch, counting the landing commits against the wrong side, taking the file diff the wrong way round, ordering commits by the clock instead of by the history, allowing a branch to merge into itself, allowing the default branch to be deleted, and calling an empty base a divergence — every one of them turns the suite red.

**626 API tests green**, 14 new (8 service, 6 route). The browser check drives the whole screen against real servers: both verdicts, a merge that moves `main` and is then reported as having nothing left to do, a delete, the default branch's delete being unavailable, and a created branch that the whole application switches to. It holds the head it measured *before* merging rather than comparing a live locator with itself — the failure shape §78–§86 kept producing.

**One check failed for a real reason and was fixed rather than loosened**: `inner_text()` returns *rendered* text, so a tag styled `text-transform: uppercase` reads `DEFAULT`, not `default`. Worth knowing before writing the next assertion against a styled label.

### 92. The review surface, and a guard that fired on my own commit (this session)

Roadmap 2.7 asked for the part of code review a reviewer touches: side-by-side diffs, inline comments anchored to lines, per-file resolution, a description template. The governance half — proposals, reviews, blockers, the gate — has existed since §45–§47. What stood on top of it was a sidebar panel showing a unified diff and four buttons.

**One idea in the data model, and everything else falls out of it: a remark about a line is a claim about a *version* of the file.** Line 14 of the code somebody read is not line 14 of the code somebody else will apply. So a comment records the proposal's `files_updated_at` it was written against, and goes *outdated* when the proposal is edited. Migration 0031 already applied that rule to approvals; 0036 applies the sharper form of it to comments and to "I have read this file".

**Derived, never reset.** Staleness is a comparison at read time rather than a flag some write has to remember to clear. A reset is a write that can be missed; a comparison cannot be. The same three lines give per-file resolution its meaning for free.

**An outdated comment is shown, marked.** It said something true about the code it was written against, and hiding it loses the reason a change was made. **Resolution is the opposite, and deliberately so**: "we settled this" is a decision somebody made, so it survives an edit — unsettling it silently would put the conversation back without anybody saying anything.

**The alignment is computed server-side from `SequenceMatcher` opcodes, not by parsing a unified diff in the browser.** A unified diff is a rendering; recovering line numbers from it means re-reading hunk headers and counting, and a comment anchored to a number recovered that way is anchored to a parser bug waiting to happen. An uneven replacement pairs what it can and leaves the rest one-sided, so three lines becoming five reads as three changes and two additions.

**Commenting is viewer-level; approving is not.** A verdict is editor-level because approving a change is as consequential as making one. Asking a question about line 14 is not a verdict, and an author who cannot answer a question about their own change makes the conversation one-directional — so the author may comment on their own proposal, and still may not approve it.

**Reviewing became a mode rather than a panel.** The first version rendered inside the code page's 300px right-hand column, and two columns of source in 300px is a diff nobody can read — which is the whole point of the item. It now takes the page, with a way back to the editor.

**The description template is built in and not per project, on purpose.** A configurable template needs somewhere to live, and in every system that has one that place is the repository — which proposals are not connected to: they change `models`, not a branch. Shipping a project-level setting now would put it in the wrong place and make moving it a migration. Prefilled, and editable to nothing, because a template that cannot be emptied is one that gets submitted with its headings still blank.

**Eleven mutations, nine caught, two survivors — both real.** Anchoring a comment to the API's clock rather than to the proposal's own timestamp survived (two clocks deciding whether a comment is current is one clock too many, and the tests only noticed the effect, not the cause); so did resolving a comment without checking it belongs to the proposal in the path — an id in a path trusted to belong to the resource in the path, the same rule the repository routes already enforce for commits. Both now have tests, and all eleven are caught.

**643 API tests green**, 17 new.

**And a guard fired on my own commit.** Migration 0036 would not apply: `migrate.py` refused because `0034_workshop_module_format.py` had changed since it was applied. §90 corrected a docstring in that file — a docstring, and the correction was right — but the checksum guard cannot tell a comment from a statement and should not try to. What it was telling me is true of every database that had already run 0034, not just this sandbox. **0034 is reverted to exactly what was applied, and the correction now lives in `packages/db/migrations/ERRATA.md`**, which the runner ignores. §90's claim that it was "corrected to match the code" was itself no longer true and has been fixed.

### 93. Checks that run on a proposal, and where the verdict comes from (this session)

Roadmap 2.8 asked for "lint and schema-compatibility checks that run on a proposal and block merge", reusing the existing quality-gate machinery. Both halves of that machinery already existed and neither ran at review time, so the item is a **sequencing problem, not a missing feature**:

* migration 0023 gave a dataset a `schema_policy` enforced by a trigger on `dataset_versions`, so a transform that drops a column from a strict dataset **was already refused** — by the database, at run time, hours after somebody approved it and applied it;
* §69 gave the API a way to run a transform over a sample of its inputs and report the schema it produces, writing nothing.

Putting the second in front of the first is the whole item.

**Two checks, and the second depends on the first.** `transform_runs` executes the proposed SQL against a sample of its declared inputs; `schema_compatible` compares the schema that produced against the dataset the transform writes. Nothing else is new — the verdict that separates `fail` from `warn` is **the dataset's own `schema_policy`, read rather than reimplemented**. Predicting anything else would be a second opinion the database is about to overrule.

**Four statuses, and the fourth is the one worth arguing about.** `pass`, `warn` and `fail` are ordinary. `error` means *the check could not run* — a Python transform (which by decision 0004 runs in an isolated task, never in the API), or an input with a dataset row and no bytes behind it. It is deliberately not `pass`: nobody has been told anything about the code, and saying "pass" would be a claim we have not earned. It is also deliberately **not blocking**: refusing to apply because *we* could not answer would make every outage a freeze on every project.

**A failing check blocks; an absent one does not.** A gate that engages by default would leave every project that turns review on unable to apply anything until somebody finds the button — the argument 0031 already made for review being off by default, with more force here because a check costs real work. What the surface must never do is let silence read as a pass, so a proposal with no results says "None have run", and one whose results have all gone stale says "None have run against the code as it now stands".

**Staleness is 0036's rule again**: a check result records the `files_updated_at` it ran against, and one older than that describes code nobody will apply. Stale results are shown, marked, and do not gate — blocking on one would mean an edit made to *fix* a failure keeps the failure in place until somebody re-runs.

**Re-running replaces rather than appends** (`ON CONFLICT … DO UPDATE`, with `UNIQUE NULLS NOT DISTINCT` so a proposal-wide check cannot be inserted twice). A list of every time a check ran is a log; what a reviewer needs is the answer. The case that makes this matter is not a repeated click — it is a dataset's policy being tightened from permissive to strict while the files sit still, which must turn a `warn` into a `fail`.

**Thirteen mutations, thirteen caught** — after three survived the first pass. One was a bad mutation of mine (a no-op edit); the other two were real gaps: nothing tested that re-running *updates* a verdict the world had changed, and nothing tested that a schema check whose transform never ran reports `error` rather than `pass`. That second one is the most dangerous result the screen could show, and it was uncovered.

**657 API tests green**, 14 new. The browser check drives the panel against real servers: the "nothing has run" state, running from the button, a `fail` with a real red pill that reaches the blocker list and disables Apply, and a proposal where everything passes. It needed a project with actual bytes behind its dataset — the dev seed's datasets have rows in Postgres and nothing on disk, which is a legitimate `error` and not a useful demonstration of anything else.

### 94. Publishing a transform from a repository (this session)

The half of roadmap 2.5 that stayed open. SQL transforms were authored in a textarea against a model; a repository was a place to keep files that nothing read. Migration 0033 had already written down the shape of the join, and then nothing wrote the columns it added:

> "Repositories are where code is *authored*; publishing creates a `model_versions` row that copies the source in. The copy is the point — a record of what ran must not change when a branch does."

**Publishing copies; it does not point.** A published version holds the source, the same as every other definition, and records the commit and path it came from. The test that matters is the one that deletes the branch afterwards and checks the transform still runs what it published.

**Identity is (repository, path), not the model's name** — migration 0038. Identity by name would leave the old model running forever when a file's declared output changed, and start a second one, with nothing in the data afterwards to say which was which. A rename in the file now moves the same model.

**A model authored in a repository refuses direct edits**, and the refusal sits beside the review gate in `models.update` because that is the function which makes a definition live. The reason is not the obvious one: an edit the next publish overwrites is bad, but an edit it *does not* overwrite is worse — until that publish, the repository describes a pipeline that is not the one running, and lineage read from it is wrong in a way nobody can see.

**Publishing is subject to the review gate, and currently refuses under it.** Publishing changes what runs, so letting it through would make `require_code_review` avoidable by putting the code in a repository first — a gate with a documented way round it is not a gate. Reviewing a *publish* needs proposals that understand commits, which do not exist (§92: proposals reference models, repositories hold branches, nothing joins them). So a project that requires review is told, in a sentence, that it cannot publish yet. **That is a real limitation, stated rather than papered over**, and it is the shape of the next piece of work in this section.

**A plan, separate from the act**, for the same reason 2.4's comparison is separate from its merge. Every refusal a publish can make is knowable without publishing — a missing input, two files claiming one output, a name already taken — so `plan()` raises all of them and `publish()` calls `plan()` rather than re-deriving them, which makes the two agree by construction.

**Three refusals, each because the alternative is unrecoverable**: an input the project does not have is named rather than dropped (a transform that runs and is wrong is worse than one that will not publish); two files declaring the same output are refused naming both (applying them in filename order makes the winner depend on what the files are called); and a name already taken by a hand-written transform is refused rather than adopted (silent adoption is how a publish deletes work nobody asked it to touch).

**An orphan is reported, never deleted.** A file that stops declaring a transform — deleted, or edited to drop its declaration, which are the same thing as far as the pipeline is concerned — leaves a model that still produces a dataset other things read. Removing a file is not the same act as deciding that dataset should stop being produced.

**674 API tests green**, 18 new. Twelve mutations, twelve caught after one survived: nothing tested the file that *keeps existing* and loses its declaration, only the one deleted outright.

The browser check drives the Publish tab against real servers: the plan listing only declared files, the button naming how many it would write, publishing, and a second visit finding nothing to do. Two small dishonesties were fixed after looking at the screenshot — the button still offered to publish transforms it had just published, and a full-page empty-state style was being used for a one-line result.

### 95. Joining the two halves of Code Repositories (this session)

§92 exposed a gap and §94 made it load-bearing: **proposals reference `models`, repositories hold branches, and nothing joined them.** The consequence was concrete — a project with `require_code_review` on could not publish from a repository at all, because letting a publish through would make the gate avoidable by putting the code in a repository first. §94 stated that limitation rather than papering over it. This closes it.

**A proposal can name a commit.** Migration 0039 adds `source_repo_id` / `source_commit_id` to `code_proposals`; when set, applying the proposal *publishes* rather than writing a change set, and the direct-publish refusal now says where to go instead.

**A commit-backed proposal stores no files, and that is the stronger property, not a shortcut.** 0031 keeps `files_updated_at` and invalidates approvals whenever the proposed code changes, because approve-then-swap-the-code is how arbitrary code gets past a reviewer who read something else. A commit is immutable, so for this kind of proposal the code under review **cannot** change — there is nothing to swap. Its files are derived from the commit's declared transforms at read time, through the same `plan()` the Publish tab uses, so the screen and the write cannot disagree.

**What can still move underneath is the live definition**, which is what `code_proposal_files.base_version` guards for a stored proposal. A commit-backed one derives the same thing: the model's version *as of the proposal's `files_updated_at`*, computed from `model_versions.created_at`. Versions are append-only and carry their own timestamps, so the question is one the data already answers — and an answer computed from the data cannot disagree with it. The test that matters is two proposals over the same file where one lands first: the other goes stale and is refused.

**Comments needed a second anchor.** `code_proposal_comments.model_id` was NOT NULL, which is right for a change to an existing transform and impossible for a file that will *create* one. A comment on such a file anchors to its repository path instead — the thing that is stable across the publish, and the thing the reviewer is looking at. The same applies to checks and to "I have read this file", and `anchor_key()` is the one place that decides which.

**Applying a commit proposal creates a change set around the publish**, so four files land as one entry in the project's history rather than four — and 0031's own `(state = 'applied') = (change_set_id IS NOT NULL)` keeps meaning what it says.

**689 API tests green**, 15 new. Thirteen mutations; three survived a first pass and two were real gaps — nothing tested that a commit-backed proposal goes stale when another lands first, and nothing tested a comment naming *both* a model the proposal really changes and a path (the anchor lookup catches a wrong model on its own; that case reaches the database's own CHECK as a 500). The third survivor was an unreachable guard, deleted rather than tested: `plan()` already refuses a commit that declares nothing.

**Two real bugs the join exposed in the browser, both fixed.** The Code page rendered its open-proposals list only when the project already had transforms — so a proposal that would create the *first* ones was unreachable, which is exactly the case this whole feature exists for. And the review surface keyed each file on `model_id`, which is null for every file of a commit-backed proposal: React duplicates or drops children that share a key, silently.

**One omission from §93 caught while here**: `code_proposal_checks` was never added to `verify_schema.py`'s `POST_SPEC_TABLES`, so the verifier would have reported it as an unexplained extra table.

### 96. Time travel, and the bill that was already being paid (this session)

Roadmap 3.3: *"Browse a dataset at a previous version. Needs a decision on retention, and it is the one item here that has a storage bill attached — say so in the item rather than in the invoice."*

**The finding that shaped the whole item: every version's bytes have always been kept.** Since migration 0003 each version has been written to its own key — `datasets/{id}/v{n}/data.parquet` — and nothing has ever deleted one. A dataset synced hourly for a year is 8,760 complete copies of itself. Nobody decided that; it fell out of writing versioned keys and never writing a sweeper, and the first time it becomes visible is on a bill.

So time travel needed **no migration and no backfill**. What was missing was a way to *ask* for a version: `preview`, `profile` and `query` now take one, and `dataset_versions.s3_manifest_key` — written since 0003, read by nothing — is where they look.

**A version is described by its own schema and row count, not the current one's.** Reading v1's rows against v7's column list would describe the data wrongly in exactly the case somebody looks at an old version: to find out what changed.

**The bill is now on the screen.** Each version reports its size, and `GET /datasets/{id}/retention` totals them. `null` size is its own state — the object is not where the row says it is, which is different from "this version is small" — and the total says how many were unmeasured so it is never quietly short.

**The retention decision is written down** (`docs/decisions/0005-dataset-retention.md`) rather than left implied. Default: keep everything, because a default that expires data would silently delete it on every existing deployment the moment it shipped, to fix a problem none of them have reported. When expiry is built it must **delete bytes and keep rows** — `model_runs.output_version` points at versions, and deleting those rows would make history lie. Nothing is protected except the current version; in particular a version a model run points at is *not*, because protecting those protects almost everything and a policy that cannot expire anything is not a policy.

**702 API tests green**, 13 new; the worker's 74 re-run because `size()` was mirrored into its copy of `storage.py` to keep the two in step. Nine mutations, nine caught after two rounds.

**The two rounds are the interesting part.** The first left one survivor — profiling an old version and caching it against the current one — which survived only because the fixture had two versions and the test asked for v1, which is also what the broken code defaulted to. Rebuilding the fixture with **three** differently-shaped versions and asking for the *middle* one killed it. That change then broke a different check: v1 and v3 both had three rows, so the query test could no longer tell "read version 1" from "ignored the parameter". It now asks for v2, the only one with a different count. **A fixture where the interesting case is neither the first nor the last is worth more than a fixture with more rows in it.**

One test found a real hole in itself: it deleted `v1/data.parquet` by globbing, and matched the *source* dataset's v1 rather than the one under test — so the assertion about a shrinking total passed while measuring nothing. Scoped to the dataset id.

### 97. The Ontology Manager, and the last resource that was not an application (this session)

Roadmap 4.2. An object type now opens as its own full-page application at `/r/{id}` — Objects, Properties, Links, History — rather than as a card saying "open in Objects" and sending you to a workspace page to find it again.

**It is the last kind that resolved to a placeholder.** `datasets` got theirs in §56, repositories in §62; `object_type` was the remaining one whose card literally read *"building in roadmap item 4.2"*. Section 0's whole argument is that a resource opens as an application; this is that argument applied to the one place it had not been.

**Almost no new behaviour.** Properties, links, versions and instances are services that have existed since §31–§35. What is new is that they are in one place keyed by the resource id, so "look at this object type" is a link.

Three things it takes care over, all about reading rather than editing:

- **A property's type is shown as declared, not inferred.** The instance store keeps properties untyped (§87), so a screen that guessed from values would disagree with the declaration exactly when they had drifted — which is the moment somebody is looking.
- **A version is shown as it was**, including properties the type no longer has. The seeded example deliberately *drops* a property between v1 and v2, because a history that rendered every version with the current shape would look right and be worthless.
- **Links are shown in both directions.** A link this type is the target of is as much a fact about it as one it is the source of. A link with no join mapped says "not traversable" rather than leaving an empty cell — db 0027 calls that a valid ontology statement that cannot yet be traversed, and it is worth saying so.

**One simplification found while writing it**: the links list already carries `from_display_name` / `to_display_name`, so the second query I had written to resolve type names was removed rather than kept.

**702 API tests green**, unchanged — this item added no server code, which is the honest measure of how much of it already existed. The browser check drives all four tabs against real servers, including the dropped property appearing in v1 and not in the current columns.

Seeding it needed three corrections that are worth knowing: `SourceCreate` takes `column_mappings` as **column → property**, `LinkTypeCreate` takes `from_type_id`/`to_type_id` rather than the `*_object_type_id` names the *response* uses, and there is no `many_to_one` cardinality.

---

### 98. The Object Explorer, and a saved search that cannot lie (this session)

Roadmap 4.1, which closes section 4. Workspace-wide instance search, type filtering, saved searches and link traversal now live at `/{workspace}/explore` — a destination, not a panel two thirds of the way down a project's Objects settings page, which is where the explorer had been since §32.

**Why it moved is the same argument as §97's.** Object types are workspace-wide (db 0003), so the explorer always searched across every project whatever project page you opened it from; reaching it meant picking a project first, which is asking somebody to guess a filing decision that has no bearing on the answer. The apps gallery is at `/{workspace}/apps` for exactly this reason, so the precedent was already there. The project page now *links* to it rather than keeping a second copy.

**What is new is saving a search** — migration `0040`, `object_searches`. Three things it is careful about:

- **A saved search stores the question, never the answer.** "Vessels flagged NO" reads differently tomorrow; storing rows would turn a live question into a stale report, and the first person to notice would be the one who trusted it. The table holds `{q, type_ids, property, value}` and nothing else.
- **A search that cannot run cannot be saved.** The explorer's rule — a property filter needs exactly one type, because a property api_name only means something *within* a type — used to live in the route. It now lives in `services/object_searches.parse`, which both the route and the save path call, so the two cannot disagree. The one place they legitimately differ is named rather than left to each to remember: `require_criteria=False` lets the explorer browse everything, while saving an empty search is a named question with no question in it. The form mirrors the rule instead of teaching it by rejection: with two types ticked the property inputs are not offered, and the fieldset says why.
- **A search naming a deleted type still opens, and keeps naming it.** The rail marks it, the form says how many are gone, and the dead id stays in the query — dropping it would silently *widen* the question, so the search would start returning rows it never asked for and read as though nothing had happened.

**The browser check found a real inconsistency, and it is the reason the check exists.** A saved search whose only type had been deleted returned `404` when it also carried a property filter, and `200` with nothing when it did not — two behaviours for one question, and which one you hit depended on a filter that has nothing to do with the type being gone. The explorer route's `get_type` lookup now answers an empty page instead of refusing. Isolation does not rest on that lookup: the search prefix is already workspace-scoped, so another workspace's instances are unreachable either way.

That bug also exposed a **weak assertion of my own**: "opening it matches nothing" was checking that no rows rendered, which a 404 error page satisfies perfectly. It now asserts the words *Nothing matches that.* and the absence of an error state.

**Two smaller things.** `ObjectTypeSummary` gained `resource_id`, so a row's type chip opens that type's application (§97) without a second lookup — tested by *resolving* the id, since a plausible-looking uuid that 404s is worse than no link. And `LinkExplorerDialog` took a workspace/project slug pair purely to build one "Browse all X" href; it now takes a function returning a href or `null`, because traversal is no longer only reachable from inside a project.

**720 API tests green** (+18), 74 worker, production build clean. **Twelve mutations, twelve caught** — including one from the previous run that had reported `2 errors in 0.98s` and was not a catch at all: the substitution put a literal `{}` into an f-string, so Python failed at collection and the run read like a pass. `jsonb_build_object()` is the same empty object with no braces in it, and the mutation is genuinely caught.

---

### 99. Deep links, and the state that was never anybody's to keep (this session)

Roadmap 0.4, which closes section 0. A link now carries what you are looking at — the tab, the version, the branch comparison, the whole of a search — and every application offers **Copy link** in its shell.

**Most of this was already true and had no affordance.** The dataset, repository and object type applications each kept their tab in the query string, and each had grown its own eight-line `setParams` to do it. Those three copies are now one hook, `useUrlState`, and the fourth caller is where a copy quietly starts pushing history entries instead of replacing them.

**The URL is the state, not a copy of it.** The explorer (§98) read its criteria from `useState` and was the one surface built this phase that a link could not reproduce — which is a strange thing for the surface that *saved searches* were built for. It now derives them from `useSearchParams`, so restoring from a link is not a code path: there is nothing to restore, because nothing was kept anywhere else.

**The same argument removed a piece of state rather than moving it.** The rail marked the saved search you had opened by remembering its id — which is a lie the moment you tick another type, and once the state is in the URL the *link* tells the lie too. Which saved search is on screen is now derived by comparing definitions. Nothing to go stale, and a pasted link marks the matching search with no wiring at all.

**The browser check found three things, and two were mine.**

- **A write built on the last render, not the last write.** `router.replace` does not land synchronously, so typing a property name and then its value each built on the same snapshot and the second dropped the first — producing `?property=` gone, `?value=NO` left: a filter the form displayed and the server was never asked for. Fixed in two places, because it needed both: `useUrlState` keeps the last write until the router catches up, and a caller that changes one parameter now writes *only* that parameter instead of re-sending all four from a stale copy. `set` also takes a function of the current params, for the case where the new value is derived from the old one — ticking two checkboxes faster than the router settles.
- **A hidden property filter was still being applied.** With two types ticked the filter is not offered — and was still sent, so the panel showed a 422 where results should be. Hidden now means not applied: the query, the save, and the rail's "which search is this" all read the same `inEffect(criteria)`. The typed filter stays in the URL so unticking brings it back, and the form says in so many words that it is not being applied.
- **An assertion of mine that could not fail.** "A fresh page restores the same rows" compared row *counts*, and blanking one of four parameters can leave the same number of rows. It compares the keys now.

**Copy link admits when it cannot.** `navigator.clipboard` only exists in a secure context, so on a plain-http deployment — which this platform supports — the write does nothing. The button shows the link to copy by hand and says why, rather than reporting a success it did not have. Mutation testing also showed the explicit `if (!navigator.clipboard)` guard was equivalent to the `catch` beneath it, so it is gone: the `catch` covers a clipboard that is absent *and* one that refuses, which a presence check would have sailed past.

**720 API tests green and 74 worker, both unchanged — no server code was touched.** Production build clean. **Seven mutations, seven caught**, which for frontend-only work is the whole of the evidence that the browser check can go red: it is the only test this code has.

---

### 100. The trigger nothing fired, and the effect that writes (this session)

Roadmap 1.3's two remaining pieces: the **change** trigger, and the **`run_action`** effect. `export` stays refused — it needs a download surface the viewer route does not have, which is a thing to build rather than a thing to decide.

**The change trigger was already a promise the runtime did not keep.** The events panel offered "Changed" on the dropdown and the filter list, the server accepted it, and *no widget ever fired it* — so an author could wire "when this dropdown changes, go to a page", save it, and watch it do nothing. That is precisely the failure `workshop_events.py`'s own docstring says the refusals exist to prevent, live in the product. Both widgets fire it now, with `{{value}}` carrying what was chosen. Not in the builder, though: a `navigate` fired by touching a control while arranging a page would move the builder off the page being edited.

**`run_action` was blocked on a design question, and the answer is that the subject is a variable.** An action runs against one object instance, so the effect names a `single_object` variable holding it — usually set by a row click in an earlier effect of the same click, which is the copy-immediately semantics doing exactly what they exist for. The values it writes are one field per the action's *own* editable properties, not a free-form map: the server refuses a property an action does not make editable, and a text box would have taught that rule by rejection after the save.

**The refusals, and the one that is deliberately asymmetric.** A subject that is not declared, or holds a string rather than an object; an action with nothing to write (`validate_submitted_values` refuses an empty write, so saving one saves a click that fails every time); a non-text value. Plus two that need the workspace: the action must exist, and every property must be on its editable list. **Those two run only when a document is written, never when one is read** — an action deleted after an app was saved would otherwise stop the app opening at all, and a record of what somebody built must not become invalid because live state moved. A `run_action` naming an action that has since gone reports when it is clicked.

**A write fired by an event has nowhere to report**, unlike the action form, which has a form to put an error in — the button that fired it looks the same either way. So there is one status strip for the module. A click with no object picked is silent: that is an effect that does not apply, not a failure, and reporting it would train people to ignore the strip.

**Two things the browser check found, one of them years older than this item.**

- **The action form never refreshed the object table.** The invalidation after a write named four query keys by hand, and the object table's (`canvas-object-table`) was not among them — so submitting the form left the table showing the value it had just replaced. `run_action` inherited the bug verbatim. Both now invalidate by prefix (`canvas-*`), which cannot drift when a widget is added; a hand-kept list of "every widget that reads objects" is a second copy of a fact, and the next widget is the one left out of it.
- **A survivor that was really a gap in the fixture.** "A failed action is reported as a success" survived because nothing in the seeded app ever failed. Reaching the failure meant a property that is *editable but unmapped* — saveable, and refused at click time, which is the exact case the strip exists for. That also showed the two failure handlers (a refused request, and an accepted request whose write-back fails) were two chances to say "Saved." about something that was not, so they became one. **The `ok: false` with HTTP 200 path — a `DatasetEngineError` during write-back — is still not reachable from a fixture**; what is proven is the shared reporting, not that specific server response.

**732 API tests green** (+12), 74 worker, production build clean. **Ten mutations, ten caught** — five against the server's refusals, five against the browser behaviour.

---

### 101. Chart drill-down, and the equality that makes it buildable (this session)

Roadmap 1.5's chart upgrade. Object-set input already existed (§74); what was missing was **drill-down**: clicking a bar or a slice narrows the set everything else on the page reads.

**Clauses, not a set.** The chart writes `[{property, op: "eq", value}]` into a variable, and a `narrow_set` derivation the server resolves does the narrowing — the same shape the Filter List writes, so one derivation reads either, or both. A widget that wrote a *set* would be a second place sets come from with no rule for which wins, which is the argument §82 already made.

**Why this is buildable and the map's area selection is not.** Both are "select on a chart, filter by it", and they are not the same problem. `region = "north"` means the same thing on Postgres and on OpenSearch whatever the property's declared type; `lat > 51.5` does not, and that is the untyped-property blocker (§87) that also holds ordered operators, numeric aggregations and property sorts. Drill-down is equality, so it needs nothing that does not exist.

**Three things it is careful about.** Clicking what is already drilled into clears it — without that there is no way back out from inside the chart, and a filter you cannot remove is one you have to remember you applied. The selected category is drawn at full strength and the rest dimmed, rather than outlined, because the point of drilling in is that the others are no longer what you are looking at. And a chart with nothing to drill into is a **picture**: no pointer, no `aria-pressed`, no hover affordance promising something that will not happen. Scatter takes no drill-down at all — its label is an X *coordinate*, so a click would narrow to one exact value of a continuous axis.

**Two gaps found on the way, and one of them was waiting.**

- **`subjectVariable` was not in `REFERENCE_PROPS`.** An inline action form (§87) bound to a variable somebody then deleted was neither refused nor reported — the form pointed at nothing and edited whatever it found. Added, along with `drilldownVariable`. This can make an already-saved app fail to open, and that is the intended answer: such an app is already broken, and saying so beats a form that silently does the wrong thing. The list is now exercised by a loop over itself rather than a case each, because what goes wrong is somebody adding a ninth prop and not a ninth test.
- **The parity test caught me, exactly as its own docstring predicted.** `REFERENCE_PROPS` exists twice — the server's copy and the builder's — and `test_the_reference_prop_list_agrees_with_the_browser_s_copy` says it "will grow widget by widget through item 1.5, which is exactly when one copy gets updated and the other does not". It grew, one copy got updated, and the test failed. Worth recording as evidence that mechanical parity assertions earn their keep.

**Two surviving mutations, and only one was a real gap.** "Clicking a bar writes nothing" survived because my mutation was equivalent — a guard on a label that is never empty. "A chart with no drill-down is still clickable" survived because every chart in the fixture had one; the fixture now carries a second chart with nothing to drill into, which is the claim the comment above makes and nothing was checking.

**733 API tests green** (+1), production build clean. **Seven mutations, seven caught.**

---

### 102. The Card List, and one implementation where there were nearly two (this session)

Roadmap 1.5's Object/Card List — the card-shaped alternative to the object table.

**Set-only, deliberately.** The table still carries a pre-variable path where it names an object type and a filter parameter itself. A new widget does not, because item 1.5's own rule is that a widget consumes input variables and emits output variables: one that reaches for a type id directly cannot be wired to anything, which is the flaw in the original eight.

**What makes it a card list rather than a table with rounded corners.** A table compares many objects across the same columns; cards are for reading one object at a time, so a card leads with a *heading* — the type's title property, or the key when it has none — and shows a few fields under it, capped at six. Past six a card is a folded table row and the table is the better widget. The key is always shown even when it is also the heading: it is what identifies the object to every other part of the platform, and a card you cannot match back to a row is a card you cannot act on.

**It fires the same `row_select` the table does**, with the same payload, so anything already wired to a table can be pointed at this instead — which is the claim the browser check makes by drilling into a chart and watching the table and the cards move together.

**Two things were extracted rather than copied.** Both are places a second implementation would drift, not merely repeat: *paging resets when the set changes* (narrowing a filter while on page 2 otherwise leaves a viewer looking at an empty widget that reports a total), and *how a selected object is announced* — twice, deliberately, flattened for `{{...}}` and whole for a `single_object` variable, with the `object_type_id` coming from the widget's set rather than the row, because a row does not carry one. The table now uses both, so there is one implementation where there were about to be two.

**Three mutations survived the first run, and only two were real.**

- **Paging never paged.** The fixture had nine objects and a page size of twelve, so the reset rule could not fire. North now has fourteen, and the check goes to page 2 and narrows from there.
- **Every card list in the fixture had a click wired**, so "a card is clickable with nothing wired to it" changed nothing. There is a second, unwired card list now — the claim its own comment makes.
- **The third was equivalent, and that is a finding.** Nothing reads a selection's `object_type_id`. It is carried because a snapshot of a click needs a reference to re-read from, and the server is what makes a wrong-type action safe — `execute` fetches the instance *by the action's* type, so an object of another type is simply not found. The mutation was removed rather than left standing, since a mutation on a field with no consumer proves nothing.

**One layout bug the screenshot caught**: each field's `<div>` wrapper was a grid item, so two fields sat side by side with their labels on one line and their values on the next — four unrelated words in a box. `display: contents` puts the `dt` and `dd` into the card's own grid.

**733 API tests green and the build clean**, both unchanged — this widget added no server code. **Eleven mutations, eleven caught.**

---

### 103. Search, and the difference between composing and competing (this session)

Roadmap 1.5's *Search / Prominent Terms Filter* row — and **half of it was already built**, which is worth saying rather than shipping a near-duplicate. *Prominent terms* is the Filter List (§82): `group_object_set` returns buckets ordered by count descending, so the widget that shows each value with its count already shows the prominent ones first. What was missing is search.

**It writes clauses, like every other narrowing widget, and that is the point.** The Filter List, a chart drill-down (§101) and this all produce `[{property, op, value}]` and all feed `narrow_set`. Each owns *its own* clause variable and they **chain** — `narrow_set(narrow_set(all, filters), search)` — rather than sharing one. Sharing would make two widgets overwrite each other and leave the resulting set depending on which was touched last, which is a bug nobody would report as a bug. The settings panel says so where somebody is about to pick the variable.

**`starts_with`, not "contains", and that is the server's decision showing through.** A substring match is `ILIKE '%x%'` on Postgres and a wildcard query on OpenSearch, neither of which uses an index — fine on a hundred objects, pathological on a million, which is the cost server-side set evaluation exists to avoid. A prefix is indexable on both and the two stores agree about it. The box says "starts with" on its own hint and in its placeholder, because a control that quietly did something narrower than the word on it is how somebody concludes their data is missing. The browser check types a substring and asserts it matches **nothing**.

**One property, named in Settings.** Searching every property at once is the Object Explorer's job (§98) and it is a different query — the store's `search`, not a set filter. Offering it here would be a second path to a set with no rule for which definition wins.

**A write per keystroke, deliberately.** `VariableBridge` already debounces the resolve, so this costs one request per pause rather than one per character; debouncing again in the widget would only delay the box under the cursor.

**733 API tests green and the build clean**, both unchanged — no server code.

**Fourteen mutations, fourteen caught** — eleven across the drill-down and the Card List, and three aimed at this widget: a prefix silently becoming an equality match, an empty box filtering for nothing rather than dropping the filter, and search writing into the drill-down's variable instead of its own.

**Getting that evidence took three attempts, and both interruptions were self-inflicted.** Worth recording, because the failure mode of the second one is a checking harness that lies:

* I ran a production build while the mutation suite was driving the dev server — the rough edge this file already documents. Both write `apps/web/.next`, so every check after that point failed against a 500, which a harness looking for failures reads as a *catch*. That entire run was discarded rather than reported.
* The container then restarted mid-run, so the script's cleanup never ran and **a mutation was left applied on disk**. The next verification failed and read as a product bug until `git diff` showed a single deleted line. The script now does `trap restore EXIT INT TERM`, and a killed run restored correctly on the next attempt — though a `kill -9` still outruns the trap, which is why the tree is checked with `git diff` before committing rather than trusted.

The lesson is not "be careful". It is that a harness which infers a catch from *any* failure cannot tell a caught mutation from a broken environment, and will report a clean sweep for a server that is returning 500 to everything. A run whose environment was disturbed has to be discarded rather than read.

---

### 104. The blocker that holds four features, decided (this session)

`docs/decisions/0006-typed-instance-properties.md`. Not built — decided, which is the part
that can be done well without a cluster and the part that is expensive to get wrong later.

**Four refusals share one cause**: ordered filters, numeric aggregations, property sorts and
the map's area selection are all refused because instance properties are stored untyped. Each
refusal is correct and this changes none of them.

**What the spike found that was not written down anywhere.** The obstacle is not "nobody wired
the declared type through". It is that **the OpenSearch index is per *workspace***
(`_index_name` → `{search_prefix}object-instances`), holding every object type together — so an
Order whose `status` is text and a Reading whose `status` is a number cannot share a mapping
for `properties.status`. Honouring declared types in the index as it stands is not hard, it is
not expressible. That is why this needed a decision rather than a commit.

**Decided: one index per object type**, because an object type *is* a schema and two schemas
are two mappings. The two alternatives are named and rejected in the document — type-qualified
paths make the stored shape differ from the API's, and type-suffixed field names put a schema
in the index that nobody wrote down. The costs are stated rather than left to be discovered:
shard count grows with object types, and the workspace-wide explorer becomes a pattern search.

**Decided: text ordering is refused permanently, not postponed.** Lexicographic order is the
database collation on Postgres and byte order on OpenSearch, so `'Z' < 'a'` differs between
them — the same disagreement the whole exercise exists to remove, one layer down and harder to
see. This is the one decision that *shrinks* what will eventually be built, and it is the one
worth arguing with.

**Decided, and worth carrying elsewhere**: the map's area selection is a `geo_bounding_box`,
not four ordered comparisons — four comparisons get the antimeridian wrong, silently, for the
customers whose data crosses it.

**One thing changed in code today**, because the decision made an existing message false:
`PROPERTY_SORT_HINT` implied every property would be sortable one day. It now names the types
sorting will cover and says text will not be among them, and the test asserts both — a refusal
should not make a promise the decision has already withdrawn.

**Also decided: what the fixture must gain before any of this is checkable.**
`opensearch_fixture_server.py` has no mapping enforcement by design, which is why a *typed*
cross-store disagreement would not be catchable the way the first one was. The document lists
the three things it needs, which narrows the unproven claim from "does any of this work" to
"does OpenSearch behave like the mapping it was given".

**733 API tests green**, build untouched. No behaviour changed beyond one refusal's wording.

---

### 105. The Pivot Table, and the arithmetic it refuses to fake (this session)

Roadmap 1.5's *Pivot Table* row: counts by two properties at once over an object set. `POST /object-sets/cross-tab`, a `cross_tab_object_set` on both stores, and a `CanvasPivotTable` widget.

**The axes are the chart's numbers, by construction rather than by agreement.** The route builds each axis with the same `group_object_set` a bar chart plots — one call for the rows, one for the columns — and the store method computes *only the cells*. A second implementation that derived the axes from the cells would have been shorter and would have drifted the first time either changed; here a row total and a bar over the same property are the same number because they are the same call. A test asserts exactly that, comparing the grid's axes against `/object-sets/group`.

**That decision has a visible cost, and the widget states it rather than hides it.** A row's cells can sum to *less* than the row's total, for two reasons that are both real: an object with no value for the column property is in no cell, and the column axis is capped. The tidy alternative — make each margin the sum of the cells drawn — produces a grid that adds up and quietly contradicts the chart beside it. So the margins are whole rows and whole columns, and the widget says *"Totals count every object; the cells count objects with both values. 4 of 16 are outside the grid."* when the two differ. Both notes are asserted in the browser check, with their numbers.

**The axes are passed *into* the store, which looks redundant until you look at OpenSearch.** A nested terms aggregation truncates its inner buckets per outer bucket, so a store left to choose its own columns would return a grid whose third column meant something different on every row. Both stores are told the axes and answer only "how many are in this cell" — pinned with `include` on OpenSearch, `= ANY(:colvals)` on Postgres. The cross-store test covers a population where one object is missing the column property entirely, which is where the two implementations would most easily part company.

**Clicking a cell narrows, through the drill-down's existing mechanism with one more clause.** A cell writes two equality clauses into the same kind of `array` variable a chart drill-down writes, read by the same `narrow_set` derivation; a heading writes one. Nothing new was invented for it, so a pivot and a chart can narrow the same set without either of them holding one. An empty cell is not a click target — narrowing to nothing is something a viewer does by accident and never on purpose.

**A cross-tab of a property against itself is refused in a sentence**, and the settings panel does not offer it. It is not ill-defined — it is a diagonal with every other cell empty — but it is a grouped count in a grid's clothes, so the refusal points at the thing that answers it properly. Counts only, like every aggregation over a set, for the untyped-property reason decision 0006 (§104) records.

**The fixture grew, and then was mutated to check it was not the reason a test passed.** `opensearch_fixture_server.py` now supports `include` and nested aggregations, which is what a cross-tab needs. A fixture whose inner aggregation counted every matched document rather than its own bucket's would turn every cell into a column total — so that mutation is in the suite alongside the product ones.

**One correction carried out of §104**: two comments in `object_sets.py` cited `db 0026` for `object_type_properties.data_type`. It is db 0003, widened by 0029. Both now say so.

**747 API tests green** (57 in `test_object_sets.py`, 11 new), `tsc --noEmit` clean, 21 browser checks green with no console errors.

**Seventeen mutations. Twelve caught on the first pass, five survived — and every one of the five was a real hole, not a wash.** They are worth listing, because four of the five survived for the same reason: *the fixture data could not tell the mutation apart from the original.*

* **The cell query dropped the set's filters.** Every excluded object happened to have a column value no drawn column used, so the wrong query returned the right grid. Fixed with a case where an excluded object *shares a cell* with an included one — two south sites, both open — so the cell reads 2 where the set has 1.
* **The Postgres cells stopped being pinned to the column axis**, and the route never noticed because it only reads the pairs it asked for. Extras are invisible through the route, so the contract is now asserted where it is stated: a direct store test requiring *exactly* the pairs requested.
* **OpenSearch's `include` was deleted** and nothing changed, because the inner `size` equalled the distinct count — nothing was ever truncated, which is the only condition under which `include` matters. Fixed with a deliberately *cut* axis: north's two statuses tie, `_key` ascending picks "closed", and "closed" was not asked for.
* **The empty-axis guard was deleted** and the test still passed, because the fixture cheerfully returns empty buckets for `size: 0` where real OpenSearch rejects it. **This one was a fault in the fixture, not in the test**: the fixture now raises the way the real cluster does, which is the same class of fidelity gap decision 0006 (§104) says has to close before typed properties are checkable at all.
* **The row total became the sum of the drawn cells.** In the first grid those are equal — nothing missing, nothing capped — so the check could not see it. The capped second grid can: totals `[9, 5, 2]`, cells `[9, 3, 0]`.

All five caught on re-run; **17 of 17**. The pattern worth carrying: a mutation that survives usually means the *fixture population* has no case that distinguishes the behaviours, not that the behaviour is untested. Four of these five were fixed by changing the data, not by adding an assertion.

---

### 106. The Time Series, and saying which question it answers (this session)

Roadmap 1.5's *Time Series / Timeline* row. `POST /object-sets/time-series`, a `time_series_object_set` on both stores, and a `CanvasTimeSeries` widget.

**It plots `updated_at`, and the widget says so on screen, unprompted.** That is the honest half of a half-blocked item rather than a stand-in for the blocked half. A resync stamps every object in a set with the same instant, so this answers *"what has been changing"* and not *"when did things happen"* — and those two produce a line of the same shape, which is exactly why the caption is not optional and not a tooltip. Bucketing a *date property* is the other question, and it is blocked for the reason ordered operators are: properties are stored untyped, so "03/04" is March on one reading and April on another, and the two stores would pick differently (decision 0006, §104). The Settings panel says so where the property picker would otherwise be, because an absent control reads as an oversight.

**UTC is stated three times, because it is silent everywhere it is not.** `updated_at` is a `timestamptz`, so Postgres's `date_trunc` follows the *session's* TimeZone unless pinned; OpenSearch's date histogram defaults to UTC; the browser's `Intl` formats in local time by default. Any one of the three left alone puts the day boundary somewhere else on one deployment, and nothing on the chart would say which. All three are pinned and all three now have a check that fails when they are not.

**`calendar_interval`, not `fixed_interval`.** A month is not 2,592,000 seconds and `date_trunc('month', ...)` lands on the first whatever the month's length, so a fixed interval would drift past every 31-day month — starting correct and diverging slowly, which is the worst way for a cross-store difference to begin. The fixture now *rejects* `fixed_interval` rather than answering it plausibly.

**Gaps are filled once, and the range comes from the data.** Both stores return only populated buckets and `object_sets.fill_time_buckets` fills the rest — one implementation, so the two cannot fill differently, and a server-side one, so a chart and an export of the same series agree. A line drawn straight through a silent week is not a smaller claim than the truth, it is a different one. The range is the first and last populated bucket rather than "the last 30 days", so a saved app does not draw a different picture tomorrow with nothing changed.

**Too long a span refuses and names a coarser interval** rather than truncating: a truncated time series is a *different period*, and nothing on it would say which one. My own test population tripped this — the first version spanned into 2025 and the day-interval test hit the 200-bucket refusal. That was the refusal working; the test was about the wrong thing, so the span was narrowed and year rollover left to the pure filling test. It is a fair signal about the cap: real data over a year genuinely will refuse at day resolution.

**No drill-down, deliberately.** Every narrowing widget in the platform writes property-equality clauses. A time bucket is a *range* over a system field, which is not in that vocabulary and would need the ordered operators decision 0006 holds. A second narrowing mechanism for one widget would be two answers to one question — the same reason the scatter chart takes no drill.

**765 API tests green** (75 in `test_object_sets.py`, 21 new), `tsc --noEmit` clean, 15 browser checks green with no console errors.

**Sixteen mutations. Eleven caught first pass, two survived, and two never applied** — the last were quoting mistakes in the mutation script, which is worth recording because a mutation that fails to apply prints a loud error and could just as easily have printed nothing.

The two survivors were different failures and only one was mine to fix:

* **Postgres bucketing in the session's time zone survived a test written for exactly that.** The test did `ALTER DATABASE ... SET TimeZone`, which only reaches connections opened *afterwards* — and the pool was already full of old ones, so the setting never took effect and the test passed against the mutation. Rewritten to `SET LOCAL TIME ZONE` on the very connection the query runs on, and confirmed failing against the mutation before re-running. **A test that sets up the condition it is testing can fail to set it up, and then it tests nothing while looking green.**
* **The label mutation was equivalent, and separately my check was too weak.** I had picked Kiritimati (UTC+14) — a bucket starting 00:00 UTC is still the *same date* fourteen hours ahead, so nothing moved. Reporting that as a catch would have been worse than reporting it as a survivor. But the check was also only asserting the *shape* of a label ("starts with w/c", "ends with 2024") and never that a label **is** its bucket; it now compares every day label against a reference the same browser formats from the seed's recorded bucket starts, pinned to UTC. Re-run with Pacific/Midway (UTC-11), which does move the date: caught.

All four caught on re-run — **16 of 16**.

---

### 107. The browser checks, moved into the repo (this session)

`e2e/`, `scripts/dev-up.sh`, `scripts/check.sh`, and a CI workflow.

**Every browser check built over the last several sections lived in a scratchpad outside the repo.** They found real defects — a hidden filter still being sent, an action form that never refreshed the table beside it, a pivot margin that agreed with its cells and disagreed with a chart — and none of that was reproducible by anyone else, or survived the container it ran on. `ROADMAP.md`'s cross-cutting section is explicit that "Playwright coverage of the builder is not optional", and this was the gap between that sentence and the repo.

**11 tests, ported faithfully rather than re-imagined**: the Pivot Table (§105) and the Time Series (§106), including the awkward cases each mutation pass forced into existence — the capped grid where the margins provably differ from the cells, and the UTC label reference the browser formats for itself.

**Python, and the cost is stated rather than glossed.** The seeding is API calls, the assertions are about server-computed numbers, and the repo has one test runner; a second one with its own lockfile would be a second place test setup lives. The cost is that a change to `widgets.tsx` is verified by a suite in another language in another directory, which `scripts/check.sh` exists to paper over. What it does **not** buy, and a JavaScript runner still would, is unit tests for the pure functions in the widget layer — `seriesLabel`, `pivotClauses`, the `useUrlState` reducer. Those deserve tests and still do not have them.

**Two things were changed to make the suite deterministic rather than clever:**

* `dev_server.py` gained `--tokens-file`. The scratchpad scripts scraped the token out of the server's stdout, which worked until a log was truncated and a whole run authenticated as nobody — reported as twelve assertion failures rather than as "there is no token".
* The suite **skips** with the command to run when the stack is down, and `ANCHOR_E2E_REQUIRED=1` turns that into a failure. A suite that reports twelve assertion failures because Next was not running has told you nothing about the code; in CI, a missing stack *is* the bug. Both paths are checked.

**The ported tests still have teeth**, which a port can quietly lose: two mutations were run against them and both were caught — a pivot margin computed from its cells, and the time-series caption removed. Worth recording that in the first of those, `test_the_margins_are_whole_rows_and_columns` **passed**: in an uncapped grid the two formulas give the same numbers, which is precisely why the capped-grid test exists and is exactly the equivalence §105's mutation pass turned up. The test is not weak; it is the wrong instrument for that question, and the right one is next to it.

**`scripts/dev-up.sh` found its own bug on the first run** and it is the pattern this file keeps flagging: the `pg_ctl` start was `>/dev/null 2>&1 || true`, so a start that failed because the log file was not writable by the postgres user looked exactly like a server that was merely slow. The command is no longer silenced and a failure prints the log.

**The CI workflow is the one part of this that has never run.** There is no way to execute GitHub Actions from here. It is deliberately thin — every command it invokes is `scripts/check.sh` or `scripts/dev-up.sh`, both run locally on every change — so the unverified surface is the wiring rather than the checks. Its YAML parses and every path it references exists; treat the first run as the thing that proves it.

**765 API tests, `tsc` clean, 11 browser tests — all three through `scripts/check.sh`.**

**Now complete** (§108): the chart drill-down, Card List and Search checks moved in too, so nothing under `STATUS.md` §101–§106 is checked only from a scratchpad.

---

### 108. Finishing the port, and a test that could not tell two answers apart (this session)

`e2e/test_narrowing_widgets.py` — chart drill-down (§101), the Card List (§102) and Search (§103), eleven tests in one module.

**One module for three widgets, because the claim that matters spans them.** They all narrow the same object set, none of them *holds* one, and they **compose**: the chart writes clauses into `v_clauses`, search writes into `v_search`, and `narrow_set(narrow_set(all, clauses), search)` chains them. Sharing one variable would make them overwrite each other and leave the set depending on which was touched last — a bug nobody would report as a bug. Splitting them across three files would have meant three modules and no test of the thing they are for.

**Two mutations run against the port, and the second one found a real hole in a test I had just written.**

* Clicking a bar writes nothing → caught by two tests.
* Search writes `eq` instead of `starts_with` → **`test_search_matches_a_prefix_not_a_substring` passed it.** The mutation was caught, but by an unrelated test, and that is worth reading carefully: the prefix test checked "east 2" (matches nothing under either rule) and "Site east 2" (matches exactly one row under either rule). It discriminated prefix from *substring*, which is what its name claimed, and not prefix from *exact* — and a prefix sits between two wrong answers, so two cases cannot separate three behaviours. Now three, with a partial prefix matching several rows, and the test written for the mutation is the one that catches it.

**A restore failed silently and left a mutation on disk.** The `cp` back ran from `e2e/` rather than the repo root because an earlier `cd` had persisted, so the path did not exist. `git status` caught it immediately — which is the only reason it is a footnote rather than an incident, and the reason the tree is checked rather than trusted after every mutation run.

**Coverage is now stated rather than implied.** `e2e/README.md` carries a table of what is covered and a sentence naming what is not: the Filter List, the Map, the Action form, the builder's own panels, publishing and the Object Explorer have API tests and no browser test. That is a gap, not a decision.

**765 API tests, `tsc` clean, 22 browser tests.**

---

### 109. Drag-to-resize, and the bug it found on the way (this session)

Roadmap 1.4's last open item, which closes the section. A splitter between a section's parts, in `CanvasSection`.

**Dragging is a way of typing.** The handle writes the same `weights` prop the Settings field edits, so after a drag the field shows the new numbers. A resize that stored pixels alongside the proportions would look identical on screen and be a second answer to "how wide is this" — and the two would disagree the first time a window changed size. The typed-proportions-first sequencing the roadmap chose is what made this arrive without a format change.

**Builder-only.** A viewer dragging a divider is editing the *saved document*, which decision 0002 rules out for the same reason a viewer's filters are not saved: a module is a definition, not a session. What a viewer sees is what the author laid out.

**Committed once, on release.** During the drag the section renders from transient state; the prop is written when the pointer lifts. One undo step per drag rather than one per pixel, and no second copy of the layout at rest.

**Clamped to 8% either side, and keyboard-operable.** A part dragged to nothing leaves no handle to grab and no way back except the Settings field — an unrecoverable state reached by an ordinary gesture, which is worth preventing rather than documenting. And a splitter only a mouse can move is one a keyboard user cannot use at all, so it is a `role="separator"` with arrow keys and `aria-valuenow`.

**The test found a bug that had nothing to do with drag-to-resize, and it is the more useful result.** The row-direction drag moved nothing. The diagnosis was not the handle:

> **Row-section proportions had never worked.** `weights: "3,1"` on a row section laid out exactly like `"1,1"` — two parts of 22.5px. `flex-grow` shares out *free* space, and a column of content-height children has none. Columns were never affected: a row of children in a full-width container has free space by construction.

Both the Settings hint ("2,1 for two-thirds and a third") and the widget's own docstring ("children share the space by weight") said otherwise. Nothing had ever asked a row section to change shape, so nothing had ever contradicted them. **A feature can be documented, shipped, and simply not exist**, and the thing that finds it is the first test that asks it to do something rather than to be there.

Fixed rather than papered over: a row section gained a `minHeight`, blank meaning "as tall as its contents" — which is the sensible default and the reason this was invisible. Proportions apply once there is a height to divide, the Settings panel says so where the number goes, and **a row section with no height offers no handle at all**, by the rule the empty pivot cell follows: an affordance that promises nothing is worse than no affordance.

**Nine mutations, nine caught first pass** — including the two guarding the new behaviour (a row section offering a handle it cannot honour; a row section ignoring its configured height) and the one guarding readability (weights written at full float precision, which would make the saved layout undescribable).

**765 API tests, `tsc` clean, 28 browser tests.**

---

### 110. Making CI runnable, and what running it found (this session)

The workflow added in §107 had never executed. Reading it against the repo, and then *running the parts that could be run*, turned up **five defects — and one of them was not in the workflow at all.**

**In the workflow:**

1. **`playwright` was installed by nothing.** The browser job pip-installs `requirements.txt` and `requirements-dev.txt`, and Playwright was in neither — it existed only in a local venv, installed by hand. A fresh checkout could never have run the browser suite. Now pinned in `requirements-dev.txt`.
2. **The migrate step connected as a role that does not exist yet.** `migrate.py` reads `DATABASE_URL`, which was set job-wide to the *app* role — and that role is created by migration `0006_rls.sql`. On a fresh database the first connection fails before any migration runs. Overridden to the owner role for that step.
3. **`migrate.py` rejects SQLAlchemy's URL scheme.** It talks to psycopg directly, so `postgresql+psycopg://` is not a DSN it can parse; the step would have failed on the URL form whatever the role. Found by running it against a scratch database, not by reading it.
4. **`scripts/dev-up.sh` probed the wrong Postgres.** Bare `pg_isready` asks a local Unix socket; a service-container Postgres answers on TCP. It reported "no response" for a database that was up, and refused to start anything. It now probes the DSN the app will actually use — and a wrong port was checked to still report *down*, so the fix is not vacuous.

**And the one that was not in the workflow:**

5. **`pip install -r requirements-dev.txt` was unresolvable.** `playwright` needs `greenlet>=3.1.1`; `requirements.txt` pinned `greenlet==3.1.0`. Bumped to 3.1.1 — a patch release, and the constraint SQLAlchemy places on greenlet is permissive.

**The finding underneath all of that is the uncomfortable one.** Chasing (5) meant comparing the local venv against the pins, and **four packages had drifted**: pydantic 2.8.2 → 2.13.4, greenlet 3.1.0 → 3.5.4, psycopg 3.2.4 → 3.2.1, duckdb 1.1.1 → 1.0.0. Two newer than the pin, two older. The ad-hoc Playwright install had upgraded greenlet, and the venv had never been a clean install of `requirements.txt`.

**So every test result reported in §98–§109 ran against a dependency set that did not match the pins.** That is stated plainly rather than quietly corrected. It has now been checked: a clean venv built exactly as CI builds one runs **765 passed, 1 skipped** — the same as the drifted environment — and the pinned Playwright drives the browser suite unchanged. The drift was not hiding a failure. But nothing had established that until now, and the reason nothing had is precisely that CI had never run.

**This is the argument for CI in one paragraph.** Not "a pipeline is good practice": a pipeline installs from the pins on a machine with no history, and that is the only thing that can catch a lie between what a repo says it depends on and what its author happens to have installed.

**Still unproven**: the workflow itself. Four of the five fixes were verified by running the affected command locally; the fifth (the install) was verified by building the venv CI would build. What remains unverified is GitHub Actions' own wiring — the service container, the caches, the runner image — and that cannot be exercised from here.

---

### 111. A JavaScript test runner, and two tests that could not see their own bug (this session)

Vitest, scoped to `apps/web/src/components/canvas/pure.ts` — the widgets' arithmetic and formatting, extracted from `widgets.tsx` where nothing but a browser driving the whole application could reach it. **23 tests in under a second**, against twelve minutes for the browser suite.

**The boundary is structural, not a convention.** `pure.ts` imports no React and touches no DOM, so a component test *cannot* be written in it. That is deliberate: a JavaScript runner tends to grow jsdom "integration" tests that pass while the real application is broken, and that is precisely the class of defect the browser suite exists to catch — a widget reading the right data and drawing the wrong thing, a section laying out in one column. `e2e/README.md` says so where somebody would go looking.

**The extraction paid for itself immediately** by making the section-resize arithmetic reachable. `resizeWeights` was trapped in a closure; the browser suite could only ask about it through pixels. It now has a 30-part case, which is not reachable in a browser in any reasonable time and is exactly where an off-by-one in the pair arithmetic would show.

**Ten mutations. Two survived, and both were the same mistake in different clothes — a test that cannot see the bug it was written for.**

* **`timeZone: "UTC"` deleted from the day formatter, and the tests passed.** This container's clock *is* UTC, so removing the option changed nothing. The test asserted a real property and was incapable of failing. `vitest.config.ts` now pins the process to `America/New_York` — a zone *behind* UTC, because one ahead leaves a midnight-UTC bucket on the same date and hides it again, which is the trap a browser-suite mutation fell into in §106. **And the test now asserts its own precondition first**: if the process is ever in UTC, it fails rather than passing vacuously. That is the §106 lesson written into an assertion instead of a commit message.
* **`timeZone: "UTC"` deleted from the *month* formatter, and the tests still passed.** The fix above was not enough: the month case used the 4th, which is still March in New York. Midnight UTC on the *first* of a month is the only place the two diverge — that instant is the previous month locally. With that case added, caught.

Both survivors were mine, in tests written minutes earlier, and neither was a missing test — both were tests aimed slightly to one side of the thing they named.

**One process note.** The first mutation run reported nine survivors and was wrong: the harness grepped Vitest's "Failed Tests" banner instead of reading its exit code, so every genuine catch was reported as a survivor. A harness that infers a result from output text rather than from a status code is the same failure §103 recorded, inverted. It now reads the exit code. A second run was also invalid — a `cd` persisted between commands and the mutation never applied, while the harness cheerfully printed "caught". Both runs were discarded rather than reported.

**765 API tests, `tsc` clean, 23 unit tests, 28 browser tests**, and `scripts/check.sh` now runs them cheapest-first so a broken pure function does not cost twelve minutes of browser time to discover.

**Pre-existing and untouched**: `npm audit` reports two advisories in the Next 14.2.5 tree (`next` critical, `postcss` high). Vitest introduced neither — the audit simply ran for the first time. Fixing them means `next@14.2.35`, which is its own change with its own verification.

---

### 112. Mapping enforcement in the OpenSearch fixture (this session)

Decision 0006 §7's prerequisite, and the part of the typed-property work that can be done honestly without a cluster. `tests/opensearch_fixture_server.py` now remembers the mapping `indices.create` was given, coerces and compares by it, and refuses what contradicts it.

**Why this was the blocker rather than a nicety.** Until now every field in the fixture was text. A store that mapped `capacity` as an integer and one that left it alone produced *identical* answers here — so the disagreement typed properties exist to remove was invisible to the only test that could have seen it. The fixture could not have failed a wrong mapping, which means a green cross-store test proved nothing about types.

**What it does now**, against the three things §7 asked for:

1. **Remembers the mapping**, resolving explicit `properties` before `dynamic_templates` — a named field beats a pattern, as a cluster resolves it. The `.keyword` subfield now comes from the template that declares it rather than from the fixture treating any dotted path as the same value.
2. **Compares by declared type.** `capacity >= 40` is true of 250 on an `integer` field and false on a `keyword` one, and both are asserted — the second is not a fixture bug, it is exactly why `ORDERED_OPERATORS` refuses to choose. Dates compare chronologically, so `+00:00` and `Z` are one instant.
3. **Refuses contradictions.** A value the type cannot hold is a `mapper_parsing_exception` per bulk item, and nothing is stored — which makes §5's reindex failure reachable in a test. A *query* value the type cannot hold is a 400, not an empty result: silently empty is the worst answer available, a wrong query that looks like a true one.

**`geo_bounding_box` is answered properly, antimeridian included** (§3). A box whose west edge is east of its east edge is a union of two ranges, not one interval — which is what four ordered comparisons get wrong, silently, for exactly the customers whose data crosses it. A store reaching for comparisons instead would now be visibly wrong here rather than merely slower.

**The fixture has its own tests now, and that is the point.** It is what every OpenSearch-side claim in this repo rests on, and it has twice been the reason a check passed for the wrong reason: `size: 0` (§105) and a nested aggregation that could have counted the wrong documents (§105). A load-bearing fake needs its own evidence. **Nine mutations against the enforcement, nine caught.**

**782 API tests, 1 skipped** — 765 existing with no regressions, plus 17 new. That the existing ones still pass is itself a result: the mapping `_ensure_index` declares is consistent with everything the suite does, including `updated_at` range queries that now compare as dates rather than as strings.

**What this still does not prove**, unchanged and worth repeating: that a real cluster agrees. It narrows the unproven claim from *"does any of this work"* to *"does OpenSearch behave like the mapping it was given"* — a much smaller thing to check on first deployment, and one 0006 lists as a runbook step. The fixture's docstring no longer claims it has no mapping enforcement, because that would now be a lie; it states the limits it does still have.

---

### 113. The browser suite stops sleeping (this session)

Every test in `e2e/` waited a fixed 6–9 seconds after each interaction, tuned to this machine. **The suite went from 12m23s to 1m26s** — an 8.6× speedup with no test removed and no assertion weakened.

**Speed was the smaller half.** The real problem was that the numbers were tuned to one machine: a slower CI runner would have started failing tests that were merely late, and a suite that flakes gets ignored, which is worse than no suite. The waits are now deadlines rather than durations — Playwright's `expect` where a locator assertion fits (a count, a text, an attribute), and an `eventually()` helper for values derived from several reads, like a grid parsed out of table cells or a series pulled from SVG tooltips. A test ready in 200ms takes 200ms; a slow machine takes longer instead of failing.

**The hazard this introduces, and the guard for it.** A polling assertion on an *absence* passes instantly: `expect(x).to_have_count(0)` is true of a page that has not drawn yet. Converted naively, "an unwired grid offers no buttons" and "a viewer gets no resize handles" would both have gone green *before the widgets existed* — faster, and meaningless. **Every absence check now waits for a presence first**, and the two mutations aimed at exactly those assertions were re-run and still caught. That is the same shape as §111's vacuous UTC test and §106's `ALTER DATABASE`: a check that cannot fail is worse than a slow one, and speed is a good way to acquire one by accident.

**Five mutations re-run against the converted suite, five caught** — the two absence checks above, a bar click that writes nothing, a drag that never commits, and the time-series caption removed. The conversion did not cost the suite its teeth.

**One self-inflicted defect worth recording.** The bulk of the conversion was a regex, and it swallowed a compound assertion whole: `assert table_rows(page) == COUNTS["south"] and regions(page) == ["south"]` became `to_have_count(<boolean>)`. Playwright refused it outright — "expected float, got boolean" — which is the good kind of failure, and the reason it was a two-minute fix rather than a silently weakened test. A more forgiving API would have accepted the boolean and compared a count against `True`.

**28 browser tests, 782 API tests, 23 unit tests, `tsc` clean.**

---

### 114. One module inside another (this session)

Roadmap 1.5's *Embedded module*, priority 4 — the last widget on the list, and the one 1.4 had to land first for.

**The design unknown was whether Craft.js tolerates a nested `<Editor>` at all.** Every widget calls `useNode()`, which needs an editor above it, so an embedded module cannot be rendered by a plain recursive walk without rewriting every widget. Two editors on one page share a document, a selection and a set of drag handlers, and reading the library's source would not have settled it with any confidence. A browser test did, in twenty minutes: **it works**, and there is now a suite that would notice if it stopped.

**The inner editor is always disabled**, in the builder as well as the viewer. Editing a module means opening it; a nested *editable* canvas would put two documents' undo stacks and drop targets on one screen with no way to say which one a gesture meant.

**The boundary is a wall, not a leak.** The inner module resolves its own variables through its own `VariableBridge` and shares nothing with its host. A shared namespace would collide the first time two modules both declared `v_filter`, and the collision would be *silent* — the inner module would read the outer's value and look like it was working. The test makes that visible rather than arguing it: the inner module's set is filtered to north and the host's is not, so inheritance and independence produce different row counts. Passing values in deliberately needs an explicit mapping, which is a format change and its own item; the Settings panel says so where somebody would otherwise assume.

**What may be embedded is decided when the author saves** (§113's commit, the server half): no self-embedding, no cycles through other modules, nothing outside the project, nothing deeper than three. A cycle found at render time is a browser that hangs, and the person who meets it is a viewer who did not build the thing.

**Six defects on the way, and the ratio is the point: four were mine and dull, two were tests that could not fail.**

* A helper inserted between a route's decorator and its function, so FastAPI registered *the helper* as the route.
* A parser assuming a node's `type` is always `{"resolvedName": ...}`, when hand-written documents use a bare string — it raised instead of refusing.
* Two test helpers colliding with existing module-level names, breaking ten unrelated tests. Twice.
* **The depth test built its chain outermost-first**, so every save saw a chain of length one and the limit was never reached however long the chain was. It passed while checking nothing.
* **The render test asserted presence rather than visibility.** `to_contain_text` reads `textContent`, which a `display: none` element still has — a mutation hiding the whole embed sailed through. Now it asserts visibility, and the mutation is caught.

Also worth recording: the browser fixture originally put the two modules in *separate projects*, and the widget dutifully reported that it could not load the module — which was the server's cross-project refusal working correctly, discovered by tripping over it. The suite's `Module` helper gained a `beside=` argument so two modules can share a project.

**788 API tests, 23 unit tests, 32 browser tests, `tsc` clean.** Four mutations against the widget: three caught, one invalid (it edited a prop that does not exist) and re-run properly.

**Section 1.5 is now complete except Comments/Notepad**, and section 1 has nothing else open.

---

### 115. One command to stand the thing up, and a guide that says what it did (this session)

Until now "running it locally" was one sentence in this file pointing at `dev_server.py`. Everything else — which of two DSN forms goes where, that migrations need `PLATFORM_APP_PASSWORD`, that the app connects as a *different role* from the migrator — lived in the heads of whoever had done it recently. `scripts/setup.sh` does it, and `docs/local-setup.md` says what it did.

**The script asks rather than assumes, and refuses rather than guesses.** It will not install Postgres, Node or Python: how you install those differs per machine and a wrong guess is worse than a clear "not on PATH". Everything downstream of them it does — role, database, virtualenv, pins, `npm ci`, migrations, browser, seeding, both servers — each step checking before acting, so it is also the right thing to run when you are not sure what state a machine is in.

**A test client is now a flag rather than a source edit.** `--extra-user EMAIL:NAME:ORG_ROLE[:WORKSPACE_ROLE]` on `dev_server.py` and `dev-up.sh`, repeatable and idempotent.

Six things were found by running it — first with `--defaults`, then on a pseudo-terminal against a brand-new role and database — and every one is the kind that only running it finds:

* **Migrations ran before the virtualenv existed**, so `migrate.py` met the system Python and died on `ModuleNotFoundError: psycopg` — a message that says nothing about setup order. Dependencies now come first, in the script and in the guide.
* **The Playwright check disagreed with the suite it was checking.** It launched a bare `chromium`, while `e2e/conftest.py` launches `/opt/pw-browsers/chromium` when that exists; so it reported "not installed" on a machine with a working browser and then spent two minutes failing to download a second copy. It now reads `CHROMIUM` from the suite's own conftest — one rule, not two that can drift.
* **`pkill -f "dev_server.py --port 8300"` killed the shell that typed it**, because `-f` matches any command line containing the pattern, including the one doing the matching. Now `pgrep` with own pid and parent excluded.
* **`ON CONFLICT (workspace_id, user_id)` cannot infer a partial index.** `uq_workspace_members_user` is partial (a row may name a group instead of a user), so the clause needs the index's `WHERE` too.
* **`psql` prompted for a password in the middle of setup.** The superuser probe exists to answer "does this connection work"; without `-w` it instead sat waiting for input, which on a real terminal is an indefinite hang showing a bare `Password for user root:` and no clue what asked. Only the pty run could show this — piped stdin makes the same probe fail instantly and fall through to the next candidate, which is why the `--defaults` runs all looked fine.
* **Every migration applied, then the last statement failed:** `permission denied to alter role`. `migrate.py` finishes by setting `platform_app`'s password, and since Postgres 16 that needs `CREATEROLE` *and* ADMIN OPTION on the target role. A cluster where `platform_app` does not exist yet is fine — 0006 creates it, so the migrating role owns it — but one where it already exists under a different owner is not, and the failure reads as though the whole run collapsed. The script grants ADMIN OPTION when the role pre-exists; the guide names the error.

**The one that was a real design mistake, not a bug:** the first version seeded an extra user with an org role only. `effective_workspace_role` returns NULL without a `workspace_members` row, so that user signed in perfectly and saw an empty home screen — indistinguishable from a broken install at exactly the moment you are trying to judge whether the thing works. `--extra-user` now grants a workspace role as well, defaulting to `editor`. Org owners and admins are the exception and get no row: they already resolve to workspace `admin` org-wide, and a row saying so again is a second copy of a fact, free to disagree with the first.

Verified by deleting the seeded user's membership and confirming they then see nothing, which is what makes the grant load-bearing rather than decorative; and by re-seeding with a changed workspace role, which changes it rather than raising.

Also fixed here, before the guide could document it wrongly: `seed()` minted tokens against a *derived* `cognito_sub` rather than the one already stored. Widening the derivation to cover the whole email address (so `sam@a.local` and `sam@b.local` are not one identity) would therefore have orphaned all four existing users at once. The stored identity now wins.

**788 API tests, 1 skipped, 32 browser tests, all green** after the change to `seed()`.

**Still true and worth stating:** there is no UI for workspace membership. The API has it; the web app does not. `--extra-user` is currently the only way to grant it without SQL.

---

### 116. External IDs — one mechanism, three features (this session)

Parity stage 2's structural item, and the one both `docs/parity/README.md` and `workshop.md` §3.4 single out. Foundry documents embedding, URL initialisation and state saving separately; they are one thing:

> "The module interface is the set of variables that are able to be mapped to variables from a parent module when embedded, **and initialized from the URL**. You can think of the module interface as the API for a Workshop module." (`docs/pal/foundry_workshop.pdf` p.163)

So a variable gains an **external ID** — a stable, author-chosen name — and an **interface** block publishing it under that name. The external ID is deliberately not the variable id: `v_7f3a…` is generated by the builder, means nothing to somebody writing a URL by hand, and a saved state pointing at one would break the first time an app was rebuilt. Its character class is the URL's, because p.165 documents writing one as a query parameter and anything needing percent-encoding makes that recipe wrong.

**This closes the §114 deferral.** Embedding shipped with the boundary as a wall and the Settings panel saying so; there is now a door in it, and §114's test still proves the wall is there for everything unmapped.

**The precedence rule is implemented, not noted.** p.122: "Workshop always uses the parent module's variable definition and ignores the embedded module's interface variable definition." A bound variable therefore skips its own derivation entirely and does **not** fall back to its own default — p.127's first stated consequence. The test asserting the fallback was gone caught the implementation doing it anyway, which is the whole reason it was written before the code was believed.

**Sharing is two-way** (p.127: "any change to a variable value in either the child or parent module will be reflected in all modules where the variable is mapped"). A mapped name does not live in the child's parameter scope at all — reads come from the host's resolved values, writes go to the host's setter. One value with two views, rather than two values and a synchronisation problem.

**Four refusals, split by what they can see.** The host half — a mapping naming a variable the host does not declare — is in `validate_module`. The child half needs the child's document and sits in the route beside the embed walk that already reads other modules: an external ID the child does not publish (the refusal lists what it does offer), a kind mismatch, a required interface variable left unmapped. A child that does not itself parse is passed over rather than blamed on the host.

**`required` is ours, not Foundry's**, and is marked as such in the spec. No documented counterpart was found; it exists because the alternative to refusing an unmapped variable is an embedded module rendering against a default nobody chose. Opt-in, so no existing module becomes unsaveable.

**Three defects, and two of them were tests that could not fail.**

* `toEqual` treats `{v: undefined}` as `{}`, so two of the three URL-seeding tests could not tell "skipped" from "set to undefined" — which was the entire assertion. They assert on keys now, and the mutation goes red.
* The seed was applied as initial `useState` only. Seeding needs the module's declared variables to map an external ID to a variable id, and those arrive from a fetch — so at mount the seed is empty and the real one lands a beat later. It silently did nothing, in every case, and the browser test is what found it.
* A CSS token that does not exist (`--surface-sunk`) — the rough edge already recorded in this file, hit again. An undefined custom property is silently nothing.

**Every refusal and every rule was mutation-tested**: removing the check turns a named test red, in all three suites.

**810 API tests, 1 skipped, 43 vitest, 43 browser, all green.**

**Not built, and it is the third consumer:** state saving (`workshop.md` §7). It keys on the same external ID (p.202–203), so it should drop into the mechanism rather than add one — and its assertion belongs in `e2e/test_module_interface.py` against that file's existing fixture. If it needs anything new, the design here was wrong.

---

### 117. A widget's configuration, in Foundry's three tabs (this session)

`docs/parity/workshop.md` §2. Our settings panel was one flat list of whatever a widget's own `related.settings` offered. Foundry splits it three ways (p.65–68) and the split says what kind of statement each control is:

- **Widget setup** — "the input and output variables of a widget … as well as any additional configuration and display options" (p.65). The panel we already had, moved behind a tab.
- **Metadata** — rename, and the raw JSON (p.67–68).
- **Display** — sizing only: Auto (max), Absolute, Flex (p.68).

The tab names are asserted in a test rather than assumed, because an earlier roadmap draft guessed "Widget setup / Display / Actions" and was wrong on two of the three. Reading the actual page is what corrected it.

**The raw JSON editor is why this was worth doing early.** It "displays how the current widget's setup is stored in JSON and offers advanced module builders the option to quickly view, edit, or copy this configuration in its raw format" (p.68). We already persist `format: 2` documents, so this was hours of work — and it makes every widget option Foundry documents and we have not built a form for *survivable* rather than blocking. That matters most for the widget long tail, where the alternative is a form per option before anything can be configured at all.

**It replaces rather than merges**, so a prop deleted in the editor is deleted from the widget. Merging would make deletion impossible and the editor would be showing a configuration that is not the widget's.

**Sizing is height, deliberately, and the reason is in the docs.** Foundry's description is height-first and says Auto (max) "is not available for setting the width of widgets in a column layout". Per-widget *width* here is already a solved problem with a different mechanism — a section distributes width to its children by weight, draggable between them (§section-resize). A second per-widget width control would put two numbers in charge of one dimension with no rule for which wins. Not built, and the spec says so rather than leaving it to be discovered.

**One wrapper, not twenty-odd widgets.** Sizing is applied through `<Editor onRender>`, Craft's supported hook for exactly this, wired into all three editors (builder, published viewer, embedded module). It **returns the node untouched when there is no sizing**, which is the common case — so a module that configures none renders exactly as it did before, with no extra element in any flex chain. There is a test that the wrapper is absent by default, and it needed its own module fixture: the sizing tests save onto the shared one, and a claim about the default cannot be checked against a module that has since been configured.

**The unknown that needed a browser:** does Craft.js carry `custom` through `serialize()` and back? Both the rename and the sizing config live there rather than in props, and if it did not, the symptom would be controls that work perfectly until you reload. It does — but that is now asserted by saving and reloading rather than believed.

**Four defects, and the ratio is worse than last time: three were my tests, one was the code.**

* Selecting a widget by clicking the canvas is a coin toss — the click lands on a table cell and Craft selects from the connected element. The Layout panel row names the node it selects, so that is what the fixture uses now.
* The table draws a title column of its own, so "two columns configured" is not "two `<th>`". Every column assertion is relative to a count read first.
* `get_by_role("alert")` is ambiguous: Next.js renders its own route announcer with that role, so the query failed on strict mode rather than on the thing under test.
* **The one that was a real gap in the checking:** every raw-JSON assertion I first wrote passed against a *merging* implementation, because they all change a value and a merge applies a changed value. What a merge cannot do is delete. There is now a test that only deletion satisfies, and the merge mutation turns it red.

**810 API tests, 43 vitest, 52 browser, all green.** Both sizing modes and the replace-not-merge rule are mutation-tested.

**Newly unblocked by §116:** Loop layouts (`workshop.md` §1.3, §4) are one embedded module per entry in an object set, and p.135 says their variable mapping "works the same way as the embedded module interface configuration". That mechanism now exists, so the remaining section layouts are Flow, Toolbar and Loop rather than Flow, Toolbar and a prerequisite.

---

### 118. Loop layouts, and the last two section types (this session)

`docs/parity/workshop.md` §1.3. Foundry has six section layouts; we had three. Flow and Toolbar are small. Loop is not, and it is the one §116 made possible:

> "Loop layouts allow you to loop over an object set or array, displaying an embedded module for each object in the set or each entry in the array used as input." (p.129)

**Why it is not a Card List.** An Object Table or Card List has a fixed set of features; a loop renders a whole *module* per object, so "any feature combination available in Workshop" applies to each one (p.129) — its own widgets, events and actions. Foundry's example is a kanban board where every ticket is a module instance.

**It was unblocked rather than built alongside.** p.135: loop variable mapping "works the same way as the embedded module interface configuration". So this is §116's mechanism applied per row — the loop supplies one object to a child interface variable, and every *other* mapped variable is shared across all copies, which is what p.135 says: they are "the same variable reference for each looped instance".

**The claim the feature rests on is per-instance scoping** (p.129: each copy "has its own variable scope and layout state"). One shared scope is the failure that looks like success — the right number of cards, all showing the same object. So the browser test derives each card's text from the object it was handed and asserts three different names. The mutation that makes every copy receive the first row turns it red; the mutation that collapses the React key does not test the same thing and was replaced.

**Flow and Toolbar are distinguished by what they do *not* do.** Columns and Rows divide their space between children by weight; Flow and Toolbar leave children their natural size. A toolbar whose three buttons each took a third of the page is a Columns section, so the test asserts they are side by side *and* together take well under the full width — the second half is the one that fails when the distinction is removed.

**Two things refused with a reason rather than half-built:**

* **Looping an array** (p.132–133). Our `array` kind has no element type, so "a variable typed to the array type" (p.134) cannot be expressed or checked. It needs a typed-array kind first.
* **Sorting by property** — decision 0006 again, the same untyped-properties gap that already blocks ordered filters and table sorts. Worth noting p.132 says Foundry applies a primary-key sort behind any user sort "to ensure a consistent ordering", which is what the object set evaluation already does, so the order is stable without the control.

**The server had to learn that a Loop embeds a module.** `CanvasLoopSection` joins `CanvasEmbeddedModule` in the set of embedding node types, so the cycle walk, the depth limit and the interface checks all see it. A loop invisible to that walk would be a hole in a rule enforced everywhere else, and the cycle would be found by a viewer's browser rather than by its author. Four loop-specific refusals, all mutation-tested: an item variable the child does not publish, one that is not a `single_object`, a cycle through a loop, and the ordinary mapping refusals. A *required* item variable counts as satisfied — the set being looped supplies it — which the required check had to be told, or no loop could ever be saved.

**One divergence, named rather than smoothed over.** p.134 says the child "must have a module interface object set variable" for an object-set loop, while p.135 describes mapping "objects from the object set". We require `single_object`, the kind that actually describes one object. If Foundry genuinely passes a one-object set, this differs in the type and not in the behaviour.

**The test helper had a real bug.** `e2e/api.py`'s `layout()` forced every node to `parent: ROOT` and listed all of them as ROOT's children, so a section's children were also drawn as its siblings — nesting was simply not expressible. It now respects a spec's own `parent`, `nodes` and `isCanvas`, and ROOT lists only top-level nodes.

**816 API tests, 1 skipped, 43 vitest, 58 browser.**

**One flaky browser test, and it is not this change.** `test_resource_filter.py::test_kind_in_the_url_filters_the_table` failed once in a full run and passed in isolation, alongside these files, and on a full re-run. **Diagnosed in §119, and the guess here was wrong** — it was not a torn read of the Type column, it was a dev-server console message. See §119.

---

### 119. The vertical header, and the "flake" that was not one (this session)

`docs/parity/workshop.md` §1.1. Most of a header is styling — a title colour, a background, a logo. One part is a **rule**, and it is the whole reason this was worth doing before the versions dialog:

> "When enabling collapsed headers, the Button Group and Tabs widgets will also have collapsed states that will only show the icons; the text will be dropped in this state. **All other widgets will be hidden** when a module header is collapsed." (p.49)

So a collapsed header is not a narrower header; it is a different set of widgets. The header reads its children's node types and renders only `CanvasButton` and `CanvasTabs` when collapsed. `e2e/test_vertical_header.py` asserts all three halves in one place — the header is collapsed, the two survivors are drawn, the third widget is *not* — and the mutation that renders everything anyway turns it red.

Also done: orientation, vertical width, horizontal height, collapsibility and collapsed-by-default (p.47–48). Collapsing is offered only on a vertical header, because a collapsed horizontal one would have no control left to undo it.

**Two divergences, both named in the spec rather than left to be discovered.**

* **There is no icon library.** Foundry has an icon picker; a Button and a Page take a one-or-two-character `icon` instead, falling back to the label's first letter when unset. The behaviour p.49 describes — drop the text, show a glyph — is faithful; the picker is not built. The label survives as `aria-label` and `title`, so a collapsed header stays navigable by anything that is not eyes.
* **A collapsed header of blank buttons would be worse than an approximate glyph**, which is why the fallback exists at all: with no icons configured there would be no way to tell one button from another.

**The container becomes a row in code, not in CSS.** A vertical header needs its *parent* laid out as a row, and a child cannot set that, so `CanvasContainer` reads its own children for one. A `:has()` selector would have been three lines shorter and is exactly the silent-failure shape this file already records twice: an unsupported or misspelled selector is nothing at all, and the symptom would be a header rendered above the page rather than beside it — wrong, but not obviously broken.

**The correction: §118's "flaky test" was not flaky.** It failed again here, and this time the message was visible:

```
Failed to fetch RSC payload for http://localhost:3100/home.
Falling back to browser navigation.
```

That is Next's router prefetching a route while the **dev server is recompiling** — which happens exactly when somebody is editing source during a suite run, and never in a deployed build. The message names its own source (`hot-reloader-client`) and says it *recovered*. §118 guessed at a torn read of the Type column and was wrong; the guess is now corrected there rather than left standing.

`no_console_errors` ignores it, alongside the favicon 404 it already ignored, and the reasoning is in the code. Matched narrowly on purpose: a bare "Failed to fetch" would swallow a real API call that never came back, which is the class of bug the assertion exists to catch.

**43 vitest, 65 browser, all green.** No server changes, so the API suite is unaffected.

**Still open in stage 2:** the versions dialog, and organising the Widget setup tab variables-first.

---

### 120. The Versions dialog (this session)

`docs/parity/workshop.md` §6, and the last item in parity stage 2.

§88 made publishing mean something — saving does not move viewers, publishing does — but that is only an improvement if a builder can see it and act on it. p.191 is the surface around it: "The Versions dialog is where builders can view a history of the saved versions for a module. Each saved version displays a timestamp, editor, and description if available."

Built: the history with the editor's **name** rather than their id, descriptions that can be added and edited after the fact (p.192), **publish a named version** rather than whatever is newest, **view** one read-only with the conditional warning banner, **revert** as a new version with a generated description, and p.192's two settings.

**Revert saves the old document as the newest version rather than rewinding**, which p.192 specifies and which matters: the history in between survives, so reverting a revert is another save rather than an archaeology problem.

**"Publish this version" is an editor's right, not an admin's**, and the split is deliberate. It changes *which* version an existing audience sees; widening the audience is `set_publish_scope` and still needs a workspace admin. Folding the two together would let a project editor widen an audience by choosing a version number, and there is a test that the scope does not move.

**"View this version" is read-only, which is ours rather than Foundry's wording.** A historic document in an editable canvas is one Save away from silently becoming the current one, and whoever did it would have thought they were only looking. Foundry's own recipe for editing an old version — revert, duplicate the file, revert back (p.192) — reads as the same caution.

**"Always prompt for a description" is a prompt, never a validation rule.** The server accepts an empty description whatever the setting says, and there is a test for it: a save refused for want of a sentence is a save somebody loses.

**Two real bugs, and one of them was in the product rather than the tests.**

* **Craft's `<Frame data>` is read once, at mount.** Changing it afterwards does nothing — fine for a save, where the tree already *is* what was saved, and wrong for a revert, where the document changed underneath the editor. The symptom was a Revert button that appeared to do nothing until the page was reloaded. Fixed by remounting the editor on a token that only revert bumps, so an ordinary save does not throw away the selection of somebody still working.
* **`e2e/api.py`'s `Module.define()` created a new app on every call**, so a fixture wanting a version *history* got a 409 on its second save rather than a second version. It creates once and saves thereafter now, which is what its name always said. Found by the first test that ever needed to save the same module twice.

**And the same test-isolation lesson as §117**, which is now twice in three sessions: publishing and reverting change what the *next* test reads, so each mutating test has its own module. A claim about "the published version" cannot be checked against a module an earlier test already published something else on.

**828 API tests, 1 skipped, 43 vitest, 72 browser, all green.** Migration 0041 adds the description column and the two settings; all three default to today's behaviour, so no existing module changes.

**Not built, and it is the biggest thing §6 still lacks:** the **Changelog panel** (p.193) — range or single-version diffs highlighting "additions, deletions, changes, moves, and newly unused elements". It is also the prerequisite for module branching and rebasing, which is out of scope, so building it is a decision about branching rather than about versioning. *(Built in §132, and finished in §183.)*

---

### 121. Property visibility, and what it is deliberately not (this session)

Parity stage 3 opens, and `docs/parity/ontology.md` §7 puts this first for a reason: it is small, and it is the *input* to standard Object Views. Foundry, `object-link-types` p.111:

> "Visibility: An indication to user applications for how prominently to display the property. A **prominent** property will lead applications to show this property first to users. A **hidden** property will not appear in user applications. By default, the start date property will have visibility `normal`."

Stored (migration 0042), editable in the object type editor, carried through the edit dialog — that last one mattering more than it sounds: without it, opening the dialog to change a display name and saving would have silently reset every property to `normal`, which is the worst way to lose a setting.

**It is a display hint and not a permission, and that is the load-bearing decision here.** A hidden property is still stored, still synced, and still returned by the API to anyone who may read the object type at all. Foundry's own wording is "an indication to user applications". Making it *look* like access control would be worse than not having it, because somebody would eventually rely on it as one — and access control is RLS, which is somewhere else entirely. There is a test asserting the definition still declares a hidden property, so a later well-meaning change that starts withholding it goes red.

**The first consumer is the Object Explorer**, which no longer draws a hidden property's column. Cross-type results share one set of columns, so a property one selected type hides and another does not has no honest single answer; it is hidden, which is the safer of the two.

To do that, the type *list* now reports `hidden_properties` — only the hidden names, not every property of every type. A list endpoint that carried full property metadata to answer "which columns do I skip" would be paying for a detail endpoint nobody asked for.

**One test does less than its name suggests, and says so.** `test_an_unknown_visibility_is_refused` gets its 422 from `PropertyIn`'s pattern, not from the service — a bad value never reaches `_validate_properties`, so removing that service check leaves the test green. The check is kept as defence for a non-HTTP caller and the test now carries a note saying it does not cover it. Found by mutation-testing, which is exactly what mutation-testing is for.

**835 API tests, 1 skipped, 43 vitest, 72 browser, all green.**

**Next, and now unblocked:** standard Object Views (`ontology.md` §4.1) — generated per object type, no builder UI, prominent properties surfaced above a table of the normal ones and hidden ones absent. `object-views` p.10–11 is the spec. It is the biggest visible gain in that file, and visibility was the input it was waiting for. Two of Foundry's type-aware renderings will not be reachable yet: time series and media reference are property types we do not have. Geopoint → Map is.

---

### 122. The standard Object View, generated from the object type (this session)

`docs/parity/ontology.md` §4.1; Foundry `object-views` p.10–11: "Foundry automatically creates a standard Object View… The standard Object View matches the object type's configuration by spotlighting prominent properties… Normal properties are displayed in a regular table, and hidden properties are not visible."

**Generated, never configured** — there is no builder, no saved document and nothing to publish. The view *is* the object type's configuration read back, which is what makes it worth having early: every object type became navigable the moment it existed, with no per-type work at all. §121's visibility is the whole input, and the Linked objects groups moved inside the view rather than sitting beside it, per p.11.

Two of Foundry's four type-aware renderings are out of reach, and the reason is a missing property *type* rather than a missing view: media reference and time series are ○ in `ontology.md` §1.1 and will land with the types. Geopoint → Map is built.

**Four bugs, all mine, and the last cost the most.** `e2e/api.py` built CSV by joining on commas, so a geopoint (`"51.5,-0.12"`) made a row wider than its header and the upload came back "primary key column 'id' is not in the dataset" — a message about the key, from a fault in another column; it uses the `csv` module now. The Explorer is workspace-wide at `/explore`, not under a project. The dev database holds thousands of objects from past runs, so "click the first row" opened a stranger's object. And **`conftest.settled` waits for a canvas widget, which the Explorer does not have** — so it timed out before any of the test body ran, and every assertion reported "the view is not here" about code that had never executed. Three rounds of diagnosis went into the component before the fault turned out to be the wait.

That last one exposed a real design flaw, now fixed: the view's test id was only on its *success* branch, so a failure to load and a failure to render looked identical from outside. The marker belongs on the view, not on its success — `data-state` says which.

*(Written later, in §126: the commit that built this never added its own section here, and `ontology.md` §4.1 had been pointing at a number that did not exist. Reconstructed from the commit and the code, not from memory.)*

---

### 123. Naming both sides of a link, and a gap that was not one (this session)

`docs/parity/ontology.md` §2. Foundry, `object-link-types` p.192:

> "A link type is **bidirectional**: it always has two sides, one for each of the two object types it relates. Each side of a link type can be traversed independently and **has its own display name**."

We named a link once, so one of its two directions always read backwards: from an Employee, "Employment" is a poor label for the company, and from the Company it is a poor label for the people. Migration 0043 adds `from_side_name` and `to_side_name`, both nullable and both falling back to the link's own name — so every link type that existed keeps exactly the label it had.

**The spec was wrong about self-links.** §2 listed them as absent. They already worked: `link_types_for_type` has returned a self-link *twice*, once per direction, since §18, with a docstring explaining why. What was actually missing was the two names — both rows carried the link's single label, so "my manager" and "my reports" were the same word. Corrected in the spec rather than left to mislead the next person.

**A gap I wrote down and then found I could close.** I first concluded that `side_name` resolution was untestable here — the only HTTP surface calling it is the per-instance links endpoint, which needs seeded instances the object-type fixture does not build — and marked §2 ◑ with a comment saying so. That was wrong: `tests/test_link_traversal.py` already has exactly that fixture, and it already contains a person→person self-link. Naming its two sides and asserting they read differently *is* §8's acceptance test, and it took four lines. The lesson is the cheap one: check whether the fixture exists before declaring the test impossible.

**842 API tests, 1 skipped, 43 vitest.** The resolution is mutation-tested — collapsing `side_name` back to the link's own name turns both new tests red.

---

### 124. Action parameters and rules, decided rather than half-built (this session)

`docs/parity/ontology.md` §5's own instruction is "do parameters and rules before any of the features that depend on them", and seven separate features in that section depend on them. It is a schema change, a service change, two call sites and a form — too much to start at the end of a session and leave half-standing, which is exactly the situation this repo already answers with a decision document (0002, 0004, 0006).

**`docs/decisions/0007-action-parameters-and-rules.md`.** The problem in one sentence: our action model has no word for "what the user typed". `editable_properties` is a list of property names, so the input *is* the output and there is nowhere to put an input that is not a property being overwritten. Foundry separates parameters (p.25, "the inputs of an action type… treated like variables that contain external values") from rules (p.75, "define the ways objects should change when the action is applied"), and defaults, submission criteria, filtered dropdowns, create/delete of objects and links, multi-object transactions and function-backed actions all hang off that one distinction.

Three decisions worth arguing with:

* **Rules are a closed vocabulary, not an expression language.** p.75 distinguishes "simple rules" from cases where they "are not sufficient" and answers the second with *functions* — which are `[fn]` and out of scope. Inventing a half-expression-language to avoid them would be building the thing we said we would not build, badly.
* **The conversion names each parameter after the property it writes.** That is what makes the migration safe: `{property: value}` and `{parameter: value}` are the same wire shape by construction, so every saved Workshop `run_action` (§60) keeps working with no change. The consequence is that renaming a converted parameter is a breaking change, so the editor must refuse to rename one a module references — the same refusal §1.2a already makes for variables.
* **Criteria are checked before the first rule runs**, and the acceptance test is that a refused action creates *no* dataset version. "Refused" and "refused after writing half of it" look identical from the caller, and our write-back appends a version per write.

**The alternative recorded and rejected:** keep `editable_properties` and bolt criteria onto it. Cheaper, buys one of the seven, and leaves every other feature needing its own side channel — which is how a model ends up with four ways to say the same thing.

Nothing is built, and the document says so at the top.

---

### 125. Every geopoint in the Object Explorer read "[object Object]" (this session)

Small, real, and found sideways: the failure dump of a browser test written for the standard Object View (§122) showed a table cell containing `[object Object]`, which had nothing to do with what that test was about.

The Explorer lists instances across *several* object types at once, so its columns are the union of whatever keys the current page carries and there is no single type to look up — which is why it could not use `PropertyValue`, and why it called `String(value)` instead. Correct for scalars. For a geopoint, which is `{lat, lon}`, `String` produces `[object Object]` — the same six words for every geopoint in the table.

`components/object-value.ts` is the fallback for that one case: no linking, no fetching, no guessing at a type, just making sure a structured value shows something a person can read. Geopoints in both stored shapes, arrays joined, anything else as compact JSON.

**The test that stops the fix being worse than the bug** is the one for `"Smith, Ada"`. A geopoint round-trips through a dataset column as `"lat,lon"`, so the string form has to be recognised — and a name with a comma in it must not then be reformatted as a coordinate pair. Mutation-tested along with the absence check, where `!value` instead of an explicit null/undefined test would have rendered `0` and `false` as "∅".

**50 vitest tests.** Nothing else changed.

---

### 126. The browser tab, and a line of code no test could fail (this session)

`docs/parity/workshop.md` §1.1's last ◑. Foundry, `workshop` p.47: "Set a title for the header. This title will also be used to set the browser tab or Carbon workspace tab name. **If a title is not set, the Workshop module resource name will be used instead.**"

We set a header title and it stayed in the header — `document.title` appeared nowhere in `apps/web/src`, so every module, published or in the builder, sat in a tab reading `Anchor`. Small, and the kind of thing that only matters when somebody has six of them open.

`components/canvas/module-title.ts` is the fallback chain as a pure function — header title, else resource name, with whitespace-only treated as unset — and `useModuleTitle` is the two-line effect that assigns it. Both the builder application and the published route call it. **Interpolation is deliberately not done**: a title may contain `{{v_id}}`, variables resolve after the first render, and a tab that flickered from `Site {{v_name}}` to `Site Alpha` on every load would be worse than a stable one.

**Two mutants earned their keep, in opposite directions.**

The first found a missing test. Deleting the `CanvasHeader` type check — so *any* node's `title` prop became the tab — left all five unit tests green, because no fixture had a non-header widget carrying a title. Several widgets do; a chart's caption is not the tab name. The sixth test fixes that.

The second found dead code. The hook originally captured `document.title` and restored it on unmount, on the reasoning that leaving a module would otherwise strand its name in the tab of every page visited afterwards. Deleting that cleanup left the whole browser file green — Next re-applies the route's own metadata on a client-side navigation, so the tab is already right by the time a restore would run. **The cleanup was removed rather than kept unfalsifiable**, and the check that would have caught it stayed: it now documents the assumption instead of the code.

Four browser checks in `e2e/test_module_tab_title.py`, and unwiring the hook turns all four red. **56 vitest tests**, `tsc` clean.

---

### 127. Action parameters and rules, built (this session)

Decision 0007 (§124), which had been settled and deliberately not built. `docs/parity/ontology.md` §5 names this as the thing to do before anything else in that section, and the reason is one sentence: **our action model had no word for "what the user typed."**

`action_types.editable_properties` was a list of property names. Executing an action posted `{property: value}` and each value was written to the property of the same name — so the input *was* the output, one list playing both parts, with nowhere to put an input that is not literally a property being overwritten. Foundry separates them: parameters are "the inputs of an action type… treated like variables that contain external values" (`action-types` p.25), rules "define the ways objects should change when the action is applied" (p.75). Defaults, submission criteria, filtered dropdowns, creating objects, editing several objects at once — every remaining feature in §5 needs that separation and none of them are buildable without it.

**Migration 0044** creates `action_parameters` and `action_rules`, converts every existing action type, and drops the column. Executing is now two steps that answer different questions: `bind_parameters` asks what the caller supplied (defaults filled, required enforced, unknown names refused), `apply_rules` asks what the rules write with it (coerced to the property's type, refused when the property has no dataset column). `hidden` and `default_value` are honoured. The four rule kinds this build cannot apply are storable and **refused loudly** — a skipped rule would report success for an action that did half of what it says.

**The conversion is the whole safety argument, so it is tested by running it.** Each name became one parameter of the property's own type plus one `modify_object` rule writing it back, which makes `{property: value}` and `{parameter: value}` the same wire shape by construction — that is why no saved Workshop `run_action` needed changing. `tests/test_action_conversion.py` builds a scratch database, migrates it to 0043, seeds a legacy action type, then migrates the rest of the way and asserts what came out. Five mutations of the migration's own SQL were checked, including the one that matters most: point a rule at the wrong property and it goes red. Seven more mutations cover the executor.

**Two details of the conversion are load-bearing and easy to get wrong.** Converted parameters are `required = false`, because submitting a subset of an action's properties has always been legal and a conversion that changed that would refuse calls that work today — a behaviour change that looks like none until somebody's module starts failing. And a duplicated name converts once: `editable_properties` was a plain array with nothing uniquing it, and a duplicate that converted twice would break the parameter key outright, failing the migration on somebody's database and not on ours.

**One bug, and it was a repo convention misfiring.** The defensive `json.loads(x) if isinstance(x, str)` used all over the routes is a no-op for a jsonb object and *wrong* for a jsonb scalar: the driver decodes `"triaged"` to the Python string `triaged`, and parsing that again raises "Expecting value: line 1 column 1". A parameter default is the first jsonb in this codebase that is routinely a scalar, which is why the convention held everywhere until here.

**`editable_properties` survives on the wire as a projection of the rules**, so the object-type screens and the Workshop `run_action` editor keep working unchanged. Exact while `modify_object` is the only rule kind; it goes when the form moves to parameters.

**856 API tests** (was 842), **82 browser**, all green. Next in the decision's order: submission criteria, then the parameter editor, then the form.

---

### 128. Submission criteria, and the rule that a check it cannot decide must fail (this session)

Decision 0007's next slice, and the first thing that needed §127's parameters: a criterion is a condition over *inputs*, so until inputs had a name there was nothing to write one about.

Foundry, `action-types` p.49–50: "Submission criteria (formerly known as validations) are the conditions that determine whether an action can be submitted… Actions can only be submitted if **all** the submission criteria are met." Migration 0045 stores one condition per row, each with the **failure message** p.56 requires — "the failure message informs the user about why they are blocked from submitting an Action" — and the executor refuses with that message rather than with anything of ours.

**The operator names are Foundry's own** (p.54–55): `is`, `is_not`, `matches`, `is_less_than`, `is_greater_than_or_equals`, `includes`, `is_included_in`, plus p.55's "no value" for emptiness, which is a property of the right-hand side rather than an operator. A builder reading Foundry's table should find the same words here.

**Two things the decision did not anticipate, both from the docs.** Conditions are over parameters *and the current user*, because p.140 is explicit that criteria are how Foundry does per-action permissions — "simple submission criteria can require a specific user ID or group ID" — and building the mechanism while omitting its main use would have been a strange thing to ship. Group membership is read server-side, so a criterion cannot be satisfied by a client claiming a group.

**A condition the executor cannot decide fails.** An operator it does not know, a comparison between things that do not compare, a user attribute we cannot answer — every one of them refuses. That is not defensiveness for its own sake: p.52 warns that a NOT condition against a missing attribute "caus[es] the condition to pass and grant more access than intended", and a check whose entire job is deciding who may write has exactly one safe direction to be wrong in.

**Ordered comparisons are numbers only**, and that is a refusal rather than a gap. Dates arrive as ISO-8601 text whose ordering is lexicographic *only* when the offsets match, and a criterion that is right in London and wrong in New York is worse than one that declines to answer.

**The check runs before the run is opened**, which is decision 0007's own acceptance test: a refused action leaves no dataset version *and* no `action_runs` row. "Refused" and "refused after writing half of it" look identical from the caller and are very different in the data, and our write-back appends a version per write.

**Eleven mutations, two of which found tests that could not fail.** Turning `is_less_than` into `<=` passed everything, because no assertion sat on the boundary — the one input that distinguishes the two operators. And writing emptiness as `not left` passed too, which would have made "priority is 0" and "approved is false" read as *unanswered*; the same trap §125 hit rendering `0` as "∅". Both tests were fixed, not the code.

**872 API tests** (was 856), 82 browser. Nesting (p.56's all / any / none), multipass attributes beyond id and group, and criteria over linked objects (p.138) are named in the migration as not built rather than left to be discovered missing.

---

### 129. Editing an action's definition, and the rename it refuses (this session)

Decision 0007's last named acceptance test, and the thing that made §127 and §128 reachable by anything other than a `psql` prompt: `PUT /workspaces/{id}/action-types/{id}/definition`.

**Whole-document, not per-row.** The three lists constrain each other — a rule names a parameter, a criterion names a parameter — so a per-row API would have orderings in which every individually valid edit passes through an invalid state. Saving a Workshop module (decision 0002) is the same shape for the same reason. Position in the list *is* the sort order, so nothing carries a number the caller has to keep consistent with anything else.

**What it refuses at save time**, all with one justification: the executor would refuse it later, at click time, in front of somebody who did not write it. A rule reading a name that is not a parameter; a rule writing something that is not a property of the object type; a criterion with no failure message (p.56 — a criterion that refuses in silence is the problem the message exists to solve); a criterion reading a user attribute this build cannot answer. That last one is refused at *save* as well as at execute, because §128's fail-closed rule would otherwise produce an action that always refuses and never says why until somebody reads the code.

**The refusal decision 0007 named.** A saved `run_action` effect names parameters in its `values`, so renaming or removing one breaks every module that names it — silently, at click time. `set_definition` compares what is *going* against what is arriving (a parameter that survives under a new name is, to a saved module, a parameter that vanished), scans the workspace's modules, and refuses with both the parameter and the module names. §1.2a already refuses deleting a Workshop variable in use; this is the same refusal one table over.

**One bug, and it was mine reading the document at the wrong depth.** An event is `{trigger, effects: [{type, config}]}` — a trigger and a *list* of effects — and my first scanner read `event["config"]`, which exists on no event. It found nothing, reported no usages, and let every rename through. The test caught it immediately because the test asserted the refusal rather than the scan; a test written the other way round would have agreed with the bug.

Nine mutations, all red, including the two that matter: remove the refusal, and remove the `DELETE` that makes a save a replace rather than a merge.

**880 API tests** (was 872). Next: the editor UI, then the action form rendering one input per *visible* parameter.

---

### 130. The action form, rendered from parameters — and two tests that could not fail (this session)

Decision 0007's last piece of user-facing work. The form drew one text box per *editable property*; it now draws one per **visible parameter**, which is what p.25 describes and what makes §127's `hidden`, `required` and `default_value` mean anything to somebody who is not holding a `psql` prompt.

**What it does.** Visible parameters get a field labelled with their display name, typed loosely (`number` for integer and float, `date` for date, text otherwise — the *server* coerces, and a browser-side type stricter than `coerce_property_value` would refuse values the platform accepts). Fields start at the object's current value, falling back to the parameter's default (p.27) and then to empty. Required parameters block submission — the one rule the form can decide by itself. A refused submission draws the criterion's own failure message (p.56).

**What it deliberately does not do:** evaluate criteria itself to grey the button out in advance. That would be a second implementation of a rule governing writes, in another language, free to disagree with the first — and this repo has already paid for mirrored logic more than once (the connector registries, the expectations evaluator).

**A gap found while wiring it.** Seeding only ever ran when the form was bound to a `single_object` variable, so the dropdown form started blank. Cosmetic before parameters; not after — a hidden parameter is *seeded* rather than typed, so in the dropdown form it was never sent at all and its rule quietly wrote nothing. Both ways of choosing now seed.

**Two tests could not fail, and both were found by mutation rather than by reading.**

The first: "a hidden parameter is still applied". A hidden parameter that the form drops is simply *not supplied*, and an unsupplied parameter's rule writes nothing — so the stored row is identical whether the form sent it or not. The test passed against a form that filtered hidden parameters out of its submission entirely. What makes the difference observable is a criterion *over* the hidden parameter, which is p.25's own use for one: the action is refused when it does not arrive. Fixed in the fixture, not the assertion.

The second was in `test_widget_config_tabs.py` and is older than this work. Three of its tests had been failing intermittently — a different subset each run, passing in isolation — and there were two causes stacked. Four tests **saved onto a shared module fixture**, so each got whatever the last one left behind (the third time this repo has paid for that; §118 and the versions dialog were the others). And `save()` clicked Save and **reloaded without waiting for the write to land**, so under load the reload beat the PUT and the page came back showing what the server still had — which reads exactly like a feature that does not persist. The builder already says when a save has landed ("· saved" in the version line); the helper now waits for the application's own statement rather than for a sleep. Three consecutive full-file runs green, and *faster* than the flaky version.

**65 vitest** (was 56), **87 browser** (was 82), `tsc` clean. Six mutations on the seeding helper and four on the form, all red.

---

### 131. The action editor, and a test that was editing somebody else's action (this session)

The last piece of decision 0007 a person could reach for and not find. The model (§127), the criteria (§128), the API (§129) and the form (§130) all landed first, so until this dialog existed the only way to declare a hidden parameter or a submission criterion was a `psql` prompt.

One dialog on the Actions table, saved as **one document** — the three lists constrain each other, so there is no per-row save that could not pass through an invalid state. Parameters get a name, label, type, default, required and hidden; rules pick a property and the parameter that feeds it; criteria get a message, a parameter, one of p.54–55's operators and a value, where **leaving the value blank is p.55's "no value"** — the only way to say "must be filled in", and a different question from "equals the empty string".

**Nothing is validated twice.** Every refusal lives on the server and the dialog shows what came back, including the one that names a Workshop module using a parameter the save would remove (§129). A browser-side copy of those rules would be a second implementation free to disagree with the one that actually decides whether a write happens. The dropdowns narrow what can be *said* — the parameters that exist, the properties the type has — because that is a convenience rather than a rule.

**One real gap, found by the test rather than by thinking about it.** Renaming a parameter left the rules pointing at the old name, so every rename was refused for the wrong reason: "a rule reads 'status', which is not a parameter" — true, unhelpful, and about a row nobody touched. A rename now carries through the rules and criteria that name it. It deliberately does *not* rewrite a saved Workshop module: that refusal is the server's, and rewriting somebody else's app to make your rename go through is not something an editor should do quietly.

**And a test that was editing a stranger's action.** The Actions table is workspace-wide, and the dev database has carried an action called "Close ticket" since August. Matching the row by display name picked *that* one, so both tests were driving a fixture from a previous session — which surfaced as a refusal naming a Workshop module this file had never created, and cost a detour through the usage scanner looking for a bug that was not there. The same trap §122 hit clicking the first of 2,219 accumulated objects. Rows are matched by `api_name` now.

**Four mutations, and the fourth needed the test fixed rather than the code.** Storing a blank value as `{"value": ""}` instead of `{"kind": "none"}` passed, because the test never typed in that box and so never ran the handler that decides. It types a value and clears it now.

**65 vitest, 89 browser** (was 87), `tsc` clean. Decision 0007 is built; what is left in `ontology.md` §5 is the rule kinds that write no property at all.

---

### 132. The Changelog panel (this session)

`docs/parity/workshop.md` §6's biggest remaining gap, and the prerequisite the spec names for module branching. Foundry p.193: "Use the Changelog panel to visualize differences between module versions… The Changelog panel highlights **additions, deletions, changes, moves, and newly unused elements**."

Five kinds, and they are not interchangeable — which is the whole reason this is not `JSON.stringify(a) !== JSON.stringify(b)`:

* **a move is not a change.** A Craft node stores its parent and its siblings' order inside the same object as its props, so a deep comparison calls every drag a change and buries the one thing that is actually different about it. Position is compared separately: parent *and* index, because a widget dragged into another section changes the first and one dragged up a column changes the second.
* **a newly unused variable is not a deletion.** It is still declared and still valid; the widget that read it is gone. Saying "deleted" would send somebody looking for a removal that never happened. "Newly" is doing work too — a module full of variables nothing ever read would otherwise flag all of them on every save.

**Variable references are found by walking the whole document**, not by checking a list of known prop names. Widgets bind variables through a dozen differently-named props (`objectSetVariable`, `subjectVariable`, `selectionVariable`, …) and text reads them through `{{v_id}}` interpolation; a list would go stale the first time somebody added a widget, silently, by reporting a variable as unused because nothing knew to look at the prop that reads it.

`workshop.md`'s own acceptance criterion for this — "moving a widget between sections produces a *move*, not a delete plus an add" — is a test, and the mutation that compares whole nodes turns it red. **Seven mutations on the diff, three on the panel**, all red, including the one that would have made the panel compare a version against itself.

**Not built, and named rather than implied:** p.193's JSON diff view and its visual hierarchy. This answers *what* changed; showing the exact modification is a second piece of work. The rebasing UI p.193 says reuses this panel needs branching, which this build does not have.

**80 vitest** (was 65), **92 browser** (was 89), 880 API.

**Two environment failures cost time and are worth recording.** `apps/web/node_modules` came back pruned to 19 packages — no react, no vitest — and my first repair made it worse: `npm ci` *inside* `apps/web` is wrong for an npm workspace, and it replaced a correct hoisted tree with a standalone partial one. The install belongs at the repo root, which is where the workspace's `node_modules` lives. Separately, the dev **database had been rolled back five migrations**, which surfaced as a 500 on creating a canvas app (`column "auto_publish_on_save" does not exist`) rather than as anything resembling a missing migration. `packages/db/migrate.py` is idempotent and fixed it in one command.

---

### 133. One transaction per action, decided rather than half-built (this session)

Decision 0007 ended by naming its own blocker: the rule kinds that write no property — `create_object`, `create_link` and the rest of p.75's "simple rules" — need something this build does not have. `docs/decisions/0008-one-transaction-per-action.md` settles what that is.

**The problem in one sentence: an action can be half-applied, and nothing notices.** Foundry is unambiguous — "an action is a **single transaction** that changes the properties of one or more objects" (p.2), and "all edits are applied **atomically** at the end of the action call" (p.84). Ours is not one transaction. `add_version` puts a Parquet object in storage and then bumps `datasets.current_version`, once per write, and the search index is updated separately.

Today the blast radius is small, and it is worth being precise about *why*, because it is not a property of the design: §127's executor collects every rule's writes into one `{property: value}` dict and applies them as one row rewrite. That is a single write, not a transaction — a different thing that happens to look the same while there is one rule kind and one object. Every remaining rule kind is a *second* write, and two writes today means two dataset versions and a failure that can land between them.

**The decision, in three parts.** `add_version` splits into `stage_version` (writes the Parquet object, returns a pending record) and `commit_versions` (inserts every `dataset_versions` row and updates every `datasets` row in one Postgres transaction). One version per dataset per action, not per write. And the instance store is **repaired, not transacted** — OpenSearch has no transactions, so writing to it inside the Postgres transaction would only move the failure rather than remove it.

The ordering is the whole argument: the slow, non-transactional, discardable part happens first, and the cheap atomic part happens last. A staged-but-uncommitted Parquet object is garbage in a bucket that no `datasets` row points at, so no reader can see it. The reverse order would need a distributed transaction to be correct.

**The consequence is stated rather than buried:** for a window after a partly-failed action, the Object Explorer can show stale values while the dataset is correct. That is detectable and repairable by a re-sync, on a path that already exists. A half-written dataset is neither.

**The alternative rejected:** keep versioning per write and add a compensating undo. No schema change, and wrong where it matters — the compensation is itself a write that can fail, the history fills with pairs of versions that have to be read as one, and a reader between them sees a state that never existed. A compensating write is what you build when you cannot have a transaction; all our metadata is in one Postgres database, so we can have one.

Nothing is built, and the document says so at the top.

---

### 134. Staging a dataset version before committing it (this session)

Decision 0008's first part, and the mechanism the rest of `ontology.md` §5 waits on. `add_version` wrote the Parquet object and bumped `current_version` in one breath — fine for one write, and impossible to make atomic for two.

It splits: `stage_version` writes the bytes and touches no metadata; `commit_versions` makes a *set* of staged versions current. `add_version` stays, implemented as stage-then-commit, so the single-write callers did not change and "one write" is still one line.

**The ordering is the whole point.** The slow, non-transactional, *discardable* half happens first. A staged version is invisible — no `datasets` row points at the object, no `dataset_versions` row mentions it — so if the commit never comes, what is left behind is an unreferenced key in a bucket rather than a dataset whose history disagrees with its contents. The reverse order would need a distributed transaction to be correct.

**Atomicity was already there and unused.** `user_connection` opens one transaction for the whole request (`lib/db.py`), so the UPDATEs and INSERTs in `commit_versions` already commit or roll back together. What the function adds is that the *set* is written in one place, so an action with several writes cannot commit half of them by construction rather than by each caller remembering to be careful. Worth stating plainly: this piece of work is mostly *shape*, and the shape is what makes the next piece possible.

**One refusal the decision did not anticipate.** Staging reads `current_version` and the commit happens later, so another writer can land in between. Both silent options are worse than a refusal: the INSERT would collide with the row somebody else created, or — if it took whatever number was free — these bytes would be filed in the history under their version. It refuses by name and says nothing was applied.

**Five tests, four mutations.** Two of decision 0008's five acceptance tests are now green; the other three need a rule kind that produces a second write, and the document says so rather than implying they are done. The mutation that matters most — make staging commit — turns every test in the file red.

**885 API tests** (was 880).

---

### 135. `create_object`, the first rule that writes twice (this session)

The rule kind decision 0008 was written for, and the one that turns two of its acceptance tests from ○ into ✅. p.75 lists creating objects among the "simple rules"; until now the executor had one kind and one object, which is a single write and not a transaction — a different thing that had been looking the same.

**A modify and a create in one action produce one dataset version.** `write_back_row` generalised into `write_rows`, which applies a set of updates *and* a set of appends into one DuckDB table and copies the file out **last**. So a failure on the third row leaves the file on disk untouched — there is no half-written output to clean up, because the output is written at the end. The version is staged and committed through §134's split.

**The failure case is now real and tested**: a create whose primary key already exists refuses, and the modify beside it never reaches the dataset. That is `ontology.md` §8's requirement, and before this there was no way to write it because there was no second write to fail.

**The fixture found a hole in my own design.** A `create_object` rule mapped properties to parameters, exactly like `modify_object` — and could therefore never give the new object an identity, because **the primary key is a dataset column and frequently not a property at all**. The fixture ticket type has `status` and `site` and no `ticket_id`. The rule config now carries `primary_key` naming the parameter that supplies it, separate from the properties, and a rule without one is refused at save time.

**DuckDB buries the one message a user needs.** A create whose key will not convert to the column's type reports as *"Attempting to execute an unsuccessful or closed pending query result"* — a sentence with nothing in it — and puts `Conversion Error: Could not convert string 'T9' to INT32` on the **second** line. `_clean` keeps the first line everywhere else in this module and is right to; the append path reads further, because supplying a value of the wrong type is a thing people will do rather than a bug.

**Only the action's own object type.** Creating another type's object needs that type's source resolved in this project — a lookup rather than a difficulty, not built, and refused at save time with a sentence saying so rather than accepted and silently ignored.

Six mutations, all red, including the one that drops the modify when a create is present and the one that allows a duplicate key. **892 API tests** (was 885).
---

### 136. Link rules, which turn out to be property writes (this session)

p.75 lists creating and deleting links among the "simple rules", and the shape they take here is decided by something already in the repo: **migration 0027 does not store edges.** A link is derived — "which instances of the far type have `to_property` equal to this instance's `from_property`" — because storing edges would mean a second sync mechanism with its own staleness and a reconciliation problem on every resync.

So a link *is* the join property's value, and `create_link` writes it while `delete_link` clears it. That is the same write a `modify_object` makes, arrived at from the ontology's side rather than the dataset's — and it is worth saying plainly rather than dressing up as new machinery, because the interesting part is not the write but the four refusals around it:

* **the far side.** The foreign key lives on the *from* side, so a rule attached to the other type would write a different object in a different dataset. Decision 0008's boundary can hold that; nothing resolves that dataset yet, so it is refused with a sentence rather than silently applied one-sidedly.
* **many-to-many.** One foreign key cannot express it and there is no join table to put the second half in. A value that means half a link is worse than a refusal.
* **`$primary_key` joins.** Rewriting a primary key is not linking, it is replacing the object.
* **a `create_link` with no target**, which could only ever write nothing.

Each is checked at save time, where the rule is still in front of the person who wrote it.

**The happy-path test needed a link whose join property is actually mapped.** The first version only asserted the *refusal* for an unmapped one — true, and it never showed a link landing. The second link type joins on `status`, which the fixture's source maps, so the write can be read back; and the delete test sets a value first, because asserting "empty" against an already-empty property passes against a rule that does nothing.

Six mutations, all red, including the two that make each rule kind a no-op. **898 API tests** (was 892). `delete_object` is the last unimplemented kind, and it is the one that needs a row *removed* rather than written — a different shape again.
---

### 137. The rule kinds, reachable from the editor (this session)

§135 and §136 built `create_object`, `create_link` and `delete_link`, and the editor still offered only "set a property" — so the executor could run four kinds and a person could type one. The Rules section now has a kind selector.

**`delete_object` is deliberately absent.** The schema stores five kinds and the executor runs four; offering the fifth would be an editor that lets somebody save an action which fails the first time it is clicked. It appears when it executes, and a browser test asserts the list rather than its length.

**Changing a rule's kind drops its config.** The shapes have nothing in common — a leftover `property` on a link rule is a field the server would refuse for a reason nobody could see on screen. The mutation that carries the old config across turns the round-trip test red.

**The link dropdown offers only links this action can set** — from side, not many-to-many, joined on a real property — which is a convenience rather than a rule: the server still decides, and §136's refusals still fire for anything typed past the UI.

Two mutations, both red. **95 browser tests** (was 92).

**The sandbox ate `node_modules` and the database again**, mid-unit, exactly as §132 describes: `tsc` started failing on `Cannot find module 'vitest'` (root install pruned to 16 packages) and the API 500'd on `column "visibility" does not exist` (five migrations rolled back). Both recoveries are the ones already recorded — `npm ci` at the *root*, and `migrate.py`. Worth noting the frequency rather than only the fix: twice in one session, and neither failure announces itself as environmental.
---

### 138. `delete_object`, and the projection that has to be told (this session)

The last of p.75's five simple rules, and the only one that **removes** rather than writes — which makes it the only one where the search index has to be told something the dataset cannot tell it by itself. A modify or a create leaves a row for the next sync to find; a delete leaves an absence, and an absence is not something a re-sync of that row can communicate.

So this needed the first new store method since the OpenSearch cutover: `delete_instances`, in both implementations, **scoped by `(source_id, primary_key)`** because that pair *is* instance identity here — two sources feeding one object type can each hold a "1", and deleting a row from one dataset must not remove the other's.

**Order follows decision 0008.** The row goes first and the projection follows: a failure between them leaves a findable object whose row is gone — visible, wrong, and repairable by a re-sync. The reverse order would lose the object while the row survived, which nothing would ever notice.

**An action cannot both change and delete the same object.** Not two things in some order — a contradiction, and the order they happen to run in is not a specification. Refused at save time, where both rules are still on screen.

**A delete of a row that is not there is refused**, rather than treated as already-done: an action that reports success for a row it could not find is one nobody can tell from an action that deleted something.

**The editor got the fifth kind the same day.** It had been held out on the rule that an editor must not let somebody save an action which fails the first time it is clicked (§137), and the browser test asserts the *list* — so a kind offered without an executor turns it red.

Four mutations, all red. **901 API tests** (was 898), 95 browser.

`ontology.md` §5's rules row is ✅. What is left in that section is **one missing lookup, not five missing features**: creating, deleting or linking another type's object needs that type's source resolved in this project, and every one of those cases is refused at save time with a sentence naming it.
---

### 139. The missing lookup: creating another type's object (this session)

§135 and §138 both stopped at the same wall, and §138 named it: "one missing lookup, not five missing features". This is the lookup. A `create_object` rule can now name **any object type with a dataset mapped in this project**, and the row goes into that type's dataset.

**It is the first action to write two datasets**, which is the case decision 0008's `commit_versions` was written for and which nothing had exercised. A Ticket is modified and a Team is created; each dataset gets exactly one new version; both commit together or neither does. The acceptance test the decision listed as "an action touching two datasets commits both or neither" is now an *action-level* test rather than a service-level one — the Team key already exists, the second write refuses, and the Ticket's dataset is untouched.

**Validation moved to the type being created.** A rule's properties are checked against the object type it creates, not the one the action hangs off — the mutation that checks against the acting type instead lets through a rule that would write a column the target dataset has never heard of. The validator needed a workspace-wide property map for that, which is one query rather than one per referenced type.

**Two ways a target can fail to resolve, and they need different sentences.** No source in this project means nothing says where that type's rows live. *Several* sources means nothing says which of them a new object belongs to — and picking one would be a guess written into somebody's data. Both are refused; the message says which.

**A test outlived the restriction it was written against.** §128's "a rule kind this build cannot apply is refused not ignored" asserted a refusal that no longer exists, because all five kinds now execute. Rather than delete it, it became the same claim about what *can* still be unplaceable: a target type with no dataset here. The point it was making — a skipped rule reports success for an action that did half of what it says — is the same one.

**One self-inflicted detour.** My first edit replaced a slice of `actions.py` computed between two function names, and the slice spanned `check_criteria` — which vanished. The suite said so immediately (`module has no attribute 'check_criteria'`), and the fix was to restore from HEAD and redo the change with anchored replacements. Worth recording as the argument against index-based edits on a file this size.

Three mutations, all red. **904 API tests** (was 901).
---

### 140. An `object` parameter that resolves, and one plan per dataset (this session)

Migration 0044 gave parameters a type called `object` — p.25's "the object type parameter will take the value of a selected Ticket object" — and nothing had ever resolved one. A `delete_object` rule can now name an object through a parameter, which makes this the first action to act on an object it was not run against.

**The refactor is the interesting half.** The write phase had grown a shape it could not keep: the acted-on dataset was special-cased and everything else was "the others". A rule deleting a row from the *same* dataset the subject lives in would then stage that dataset twice — and the second staging collides with the version the first one just claimed, which is §134's staleness refusal firing on our own writes. So the executor now builds **one plan entry per dataset**, and every rule contributes updates, appends or deletes to whichever entry its object belongs to. One file per dataset, one version per dataset, whatever the rules were.

**Changing one object and deleting another is not §138's contradiction.** That refusal is about the *subject* — writing a property of a row and removing the same row. `deletes_the_subject` is now separate from `object_deletions` for exactly that reason, and the mutation that conflates them refuses a legitimate two-object action.

**A named object that is not there is refused**, not skipped, for the reason §138 gives about rows: success for an object nobody could find is indistinguishable from success for one that was deleted.

**I made the same mistake twice in one session, and the second time it cost less because of the first.** §139 records replacing a *slice* of a file computed between two markers, which swallowed a function. Editing the test file here, I did it again — the slice ran to end-of-file and took §139's fixtures with it. The suite said `fixture 'team_dataset' not found` within seconds, `git checkout` restored it, and the redo used a bounded slice with an explicit end marker. The lesson stands and is now written twice: **on a file this size, replace anchored text, not computed ranges.**

Three mutations, all red. **907 API tests** (was 904), 95 browser.

---

### 141. Changing an object a parameter names (this session)

The third and last of p.75's "some object other than the one I was run against" shapes. A `modify_object` rule with an `object` in its config means the object that parameter holds; everything else about the rule is unchanged, which is why it is the same rule kind rather than a fourth one. §5's "edit multiple objects in one transaction" row is now ✅ — an action can change, create and delete several objects of several types across as many datasets, and they commit together or not at all.

**Contexts are keyed by instance here, not by type**, and that is the one real difference from §139. A `create_object` can key on the type because a new row has no source yet and the type must have exactly one; a *named* object does have one, and two instances of a type can legitimately come from different sources with different column mappings — so "is this property stored anywhere" has to be asked of the instance's own source. Checking against the type would answer the wrong question and write a column that source has never heard of. The property, separately, is checked against the *type the rule changes*: the mutation that checks it against the acting type instead lets `status` through onto a Team.

**§138's contradiction, from the far side.** Two rules that name the same type and read the same parameter mean the same object, and changing and deleting it is the same contradiction as on the subject — visible in the definition rather than only at click time. Two *different* parameters name two different objects, and refusing that would refuse a definition that is fine; the mutation that writes the check as "any modify and any delete" is red on exactly that test. Two rules that happen to be handed the same instance at runtime are a coincidence, not a definition, and are left alone.

**`editable_properties` stayed what its name says.** It is derived from the rules and answers "which properties does this action write **on its own object**" for the change-impact report and the Workshop `run_action` editor. A named modify writes another object's property, so it is excluded — otherwise an effect citing `code` would be citing a property of a different row, and the impact report would claim this action writes the subject's type when it writes a parameter's.

Four mutations, all red. **914 API tests** (was 907), 95 browser. §139–§141 are API-only: the definition dialog still offers the subject-only shapes, so naming a second object is something the editing endpoint can express and the editor cannot yet.

---

### 142. Linking two named objects, from the end that holds no foreign key (this session)

The last shape `docs/parity/ontology.md` §5 was waiting on, and the one the earlier link work named as its own limit: "a link rule can only be set from the side that holds the join property, and this action's object type is the other one". That refusal is gone. A link rule written from the **to** side names the from-side object through a parameter and writes *its* join property.

**The value is not a parameter, which is the whole point.** A link here is derived (migration 0027): instances of the far type match on `to_property` equal to this instance's `from_property`. From the near side the rule sets its own row's foreign key, and *which object to link to* is the input. From the far side there is no row of its own to write — the input is *which object to link*, and the value is fixed: this object's `to_property`, because the link being created is a link to this object. So a far-side rule takes an `object` and no `target`, a near-side rule takes a `target` and no `object`, and each is refused with a sentence if it carries the other's field.

**The subject is read as this action leaves it.** `apply_rules` now runs before `object_modifications` and its writes are laid over the stored properties. An action that changes `status` and links a Team on `status` in one submit would otherwise write the value the ticket had *before* the submit — a link that stops holding the moment the action finishes. The mutation that reads the stored properties alone is red on exactly that test.

**A create with nothing to point at is refused.** If the subject has no value for the property the link joins on, writing the blank anyway would be a `delete_link` reporting itself as a create.

**A second test outlived its restriction, exactly as §139's did.** "A link rule from the wrong side is refused" asserted a refusal that this build lifts. Repointed rather than deleted, to what is still true: from that side the rule needs the parameter naming the object, and without one there is nothing it could mean.

**One mutation survived the first pass** — `changes_the_subject` skipping rules that name another object. §138's contradiction is about the subject, and nothing asserted that deleting the subject while changing *another* object is allowed. Fixed in the test, not the code: "close this ticket and update the team" is a definition somebody will write, and a check counting every modify would refuse it.

Left deliberately: a far-side `create_link` on an action that also deletes the subject is allowed. The other object ends up holding a value matching a row that no longer exists, which the derived-link model already handles — traversal finds nothing, exactly as it does for any value that matches nothing. Refusing it would be a rule nobody asked for.

Four mutations, all red. **921 API tests** (was 914), 95 browser. Still API-only: the definition dialog offers the subject-only shapes, so §139-§142 are things the editing endpoint can express and the editor cannot yet.

---

### 143. The dialog catches up with the endpoint (this session)

§139-§142 each ended with the same sentence: the editing endpoint can express this and the editor cannot. Four units of API with no way to reach them is a gap that grows, so this closes it before anything else is built on top.

**One control answers "which object", for both kinds that can name one.** A `modify_object` and a `delete_object` get an *On* picker - this object, or a type - and a *Which one* picker naming the parameter that holds it. `object_type` and `object` move together in both directions: an `object_type` left behind with no `object` names a *set*, which the server refuses, and an `object` left behind when somebody picks "this object" again would keep writing somewhere else while the dialog says otherwise. The mutation that keeps one of them is red.

**The property dropdown follows the rule, not the action.** `PropertySelect` is its own component keyed on the object type id, so each rule offers the properties of whatever type *it* writes and several rules on one type share a single fetch. The mutation that reads the action's own type everywhere is red on a rule setting a property the action's type does not have - which is the whole point of naming another object.

**Only `object` parameters are offered where an instance is wanted.** p.25's type is what holds one; a string parameter would carry a primary key, and the executor looks an instance up by id. Offering it would be offering a definition that fails on the first click, which is the same rule that kept `delete_object` out of the kind list until it ran.

**A link rule asks a different question at each end.** From the side that holds the join property: which object to point at (`target`). From the other side: which object to link (`object`), with the value coming from this object. Changing the link type clears both, because the answer to the old question is refused for a reason no longer on screen. The mutation that always shows the near-side field is red.

Four mutations, all red. **921 API tests**, **100 browser tests** (was 95).

---

### 144. Configured Object Views (this session)

`docs/parity/README.md` calls Object Views "the highest value per unit of work in the whole parity set", and the reason is in Foundry's own sentence: configured views are "fully customizable representations of an object **built using Workshop**" (`object-views` p.2). We have that engine, so the work was not building a view - it was deciding what a view *is*.

**A view is a pointer, not a document.** `object_type_views` (migration 0046) stores which module stands in for which object type, in which form factor, and which of the module's variables receives the object. Everything else a view needs - layout, variables, events, versions, publishing, revert, the changelog - is the module's, and a configured view that re-declared any of it would have been a second Workshop with one feature. Version management for configured views is ✅ in §4.2 for that reason and not because anything was built for it.

**The binding is one variable, and it is checked at save time.** A standard view is generated from the object type and takes no input; a configured one is a module, and a module takes input through its variables. `subject_variable` names the `single_object` variable that receives the object, validated against that module's own document - the same place and for the same reason an action rule's property is checked against its object type.

**Four refusals, each a screen somebody would otherwise reach before finding out**: an unknown form factor, a module this workspace cannot see, an **unpublished** module, and a subject variable that is not a `single_object` one. The unpublished refusal is the interesting one: an object view is read by whoever can read the object, and an unpublished module is readable only inside its own project - allowing it would configure a view that renders for its author and 404s for everybody else, which nobody reports as a permission problem.

**Nothing stored can hide the standard view.** p.2: standard views "remain accessible even after a configured Object View is built". That is a rule about the reader, so it is enforced by there being nothing that could express the opposite - no replace flag, no delete of the generated view - and by a control on the view itself that goes both ways.

**Reading the module reuses the published path.** A configured view renders through `published-canvas-apps`, the same workspace-wide, permission-checked read a published app uses. No new access path: an object view's audience is exactly the audience publishing already describes, and a second way to reach the same document would be a second thing to get wrong. A view that will not load falls back to the standard one with a sentence rather than showing an error where an object should be.

**The panel form factor is stored, not rendered.** p.4's Panel exists to be embedded and there is nothing here to embed it in yet; it is a separately addressable row so the two never collide, which the test asserts by setting both and clearing one.

Five mutations, all red - including the browser one that matters: seeding the subject variable with the primary key rather than the whole object. The fixture module reads `region` through an `object_property` derivation, so a view that renders without the object goes red rather than drawing an empty card, which a text widget with the answer typed into it would not have caught.

**One locator was ambiguous and Playwright said so rather than guessing.** The Ontology Manager mentions an object type in two tables - the types and the dataset mappings under them - so matching a row by name alone resolved to two. Filtered by the button the types table has instead, which is the same "match on what makes this row the one you mean" lesson §137 recorded about matching actions by `api_name`.

**934 API tests** (was 921), **106 browser tests** (was 100).

---

### 145. Previewing a linked object, and the visibility rule that had two copies (this session)

p.11's Linked objects component exists so a relationship is answerable **in place**: "which team owns this ticket, and what region is that team in" should not cost a hop you then have to come back from. Traversing was the only thing a link row did. Previewing is the other click, and they are deliberately separate controls rather than one that guesses.

**The unit found a leak, which is the more useful half.** The row summary read straight off `instance.properties` - no visibility rule anywhere near it - so a property somebody marked **hidden** (p.111) appeared next to every linked object that had one. The standard Object View honoured visibility from the day it existed and the Explorer honours it in its columns; this was the third surface, and having the rule written twice is exactly how a third copy ends up not existing at all.

So there is one copy now, in `components/object-properties.ts`, pure and unit-tested, and the standard view was repointed at it rather than keeping its own `partition`. Three mutations on it are red: keeping hidden properties, not leading with prominent, and reading the instance's keys instead of the type's declaration.

**The summary reads the type, not the instance.** Two consequences, both deliberate. Prominent leads, because prominent is the object type saying "this is what identifies one of these" (p.10) - which is exactly the question a one-line summary asks, and the old version answered with whichever three properties happened to be declared first. And a stored key the type no longer declares is ignored: an instance can carry one (§38 makes that possible, and the orphaned-keys note above says why they are left alone), and a summary that read the instance would show a property the ontology has never heard of.

**The trail is what proves nothing navigated.** A hop pushes a stop onto the breadcrumb trail, so the browser test asserts the properties arrived *and* the trail is still absent - which is the difference between an inline preview and a very fast round trip.

Four mutations, all red. **89 unit tests** (was 80), 934 API, **111 browser tests** (was 106).

---

### 146. Searching the ontology (this session)

`ontology-manager` p.28 puts a search bar in the header "to search across object types, properties, link types, action types, shared properties, interfaces, and functions". Four of those seven exist here; the other three are ○ in §1.2/§1.3, so there is nothing to search - named in the module docstring rather than silently skipped, because "found nothing" and "does not look there" read identically to whoever typed the query.

**Matched in Python, not in SQL, and the reason is p.28's own sentence**: "the search results highlight the specific field that matched your query". A database `LIKE` that returns rows tells you a row matched, not *why* - and four `ILIKE` clauses would each need their own opinion about case folding while still not answering the question. The tables are small; an ontology is tens of types.

**Which field matched is part of the answer, not something the browser re-derives.** A browser that re-derived it would be a second matcher, free to disagree with the one that decided the row belonged in the list - and the disagreement would surface as a highlight landing on the wrong word, or on none, which reads as the search being broken. The mutation that reports the first field for every hit is red on three tests.

**Ranked by how well the match reads, not by which table answered first**: exact api_name, then prefix, then substring, then description - the weakest signal last. A description mentioning the word is a hint; a name containing it is the thing.

**A link matches on its *side* names, not on its ends' type names.** `from_display_name` in the link row is the object type's name at that end, which is already findable as an object type - searching it here would report the same word twice under two kinds. What is worth searching is `from_side_name`/`to_side_name`, because that is what the relationship is *called* from each end (§123). I wired the wrong pair first and the test caught it, which is the argument for asserting the kind *and* the field rather than just that something came back.

**Two things the pure/vitest boundary decided.** `highlight` lives in its own `.ts` module rather than in the `.tsx` component, because vitest here runs pure functions only - the boundary `canvas/pure.ts` draws. And the mark is sliced out of the *value*, not out of the typed query: a highlight that rewrote "Status" as "status" would be editing the answer.

**A test asserted the wrong field and was right to fail.** The fixture's api_name and display_name both carried the search word, and `api_name` is searched first - so the reported field is `api_name`. Fixed in the test with the reason written down, because the ordering rule is precisely what decides what a reader sees highlighted.

Four mutations, all red. **96 unit tests** (was 89), **945 API tests** (was 934), **117 browser tests** (was 111).

---

### 147. Where time series and media live, and the media half built (this session)

`ontology.md` §7's build order item 5 says the two remaining property types "both need a storage decision first". **Decision 0009** makes both. They turned out not to be the same kind of problem.

**Time series: settled, not built.** A time series property is not a value, it is a table - one instance carries thousands of `(timestamp, value)` pairs. Everything this platform stores about an instance is *one document*, so putting points there means every list read pays for every point and every sync rewrites the whole history. The decision rejects a `time_series_points` table in Postgres too, and not for performance: it would be a second copy of data the dataset subsystem already versions, retains and traces, with its own retention policy, its own lineage story and its own answer to "what did this look like last Tuesday". So the property holds a series **id**, an `object_type_series` mapping on the object type source says which dataset and which key/timestamp/value columns, and points are read through the dataset engine on demand. The cost is named rather than discovered: freshness is sync-shaped, not streaming.

**Media: there is no media reference type, and that is the decision.** Foundry's points into a *media set* - `mimeType` plus a triple of media-set/view/item RIDs. We have no media sets, and building one is a product the size of Datasets that nothing in the five in-scope applications asks for. Adding the *shape* without the thing was rejected in stronger terms: two of the three RIDs would be permanently null, and the first person to branch on them would be writing dead code against a contract nobody honours.

What was actually missing was the **renderer**. An attachment holding a PNG already is a media reference in every sense this platform can honour - bytes, a MIME type, a URL that enforces the workspace boundary - and it drew a download link. So: no type, no table, no migration, and images, video and audio now render in place.

**Two collisions found on the way, both worth the time.**

*The download route refuses to serve anything inline*, and its docstring says why: the content type is the uploader's claim, and serving a claimed type inline is how a stored XSS happens. That refusal is right and was not weakened. Inline is now **earned** - asked for explicitly, only for a type on the route's *own* allowlist (never `image/svg+xml`, which is an image the browser executes script inside), always with `nosniff` so a file that is really HTML fails to decode as an image rather than running as a document. A caller naming a type off the list gets a download rather than an error, so a mislabelled file is a link and not a broken page.

*An `<img src>` cannot authenticate here.* Cookie auth requires the `X-Anchor-Session` header - the CSRF defence that makes accepting a cookie safe at all - and an element attribute cannot set headers, so the first version 401'd on every image. Exempting this one route would have put the hole back on the route that reads private bytes. Instead the bytes are fetched through the authenticated client and handed to the element as an object URL, revoked on unmount. Every existing rule stays intact and nothing new is trusted.

**A surviving mutation found a real gap.** Dropping the `disposition == "inline"` check passed everything: the only test guarding the default used a **PDF**, which is off the allowlist and so could never have gone inline either way - it could not tell "not asked" from "not allowed" apart. An image can go both ways, and the test that says which happens when nobody asked is the one that was missing. Fixed in the test.

Four mutations, all red. **102 unit tests** (was 96), **951 API tests** (was 945), **121 browser tests** (was 117).

---

### 148. Time series properties, built on the decision (this session)

Decision 0009 settled where the points live; this is that, built. A `time_series` property type, an `object_type_series` mapping (migration 0047) saying which dataset and which key/timestamp/value columns hold one property's points, and a read endpoint that queries them through the dataset engine.

**Nothing copies points anywhere**, which is the whole decision and is stated at the top of the module that would be the place to break it. The acceptance test is the plainest one in the file: readings uploaded as an ordinary CSV come back out of that dataset, filtered to one series, without ever having been written to Postgres.

**Declared on the *source*, not on the object type.** An object type is workspace-scoped; a dataset lives in a project. "Where are this type's rows in this project" is exactly what `object_type_sources` answers, and where its series live is the same question about the same project. A type mapped in two projects can point its series at two different datasets - which is already true of its properties, and would be surprising to lose here.

**Three refusals at declaration, each a chart somebody would otherwise open to find empty**: a property that is not declared `time_series` (points behind a string property are points nothing would ever draw), a column the points dataset does not have - checked against *the dataset's own schema*, read by the route and handed to the service, because the service does not touch Parquet - and three columns that are not distinct, since a series whose timestamp and value are the same column is a straight line.

**The SQL is a separate pure function and is tested without a Parquet file.** A wrong bucket, an unfiltered key or a missing cap all live in the shape of the query, and none of them need a dataset to see. The mutation that drops the series filter is red on five tests, three of which never open a file.

**The interval and aggregate vocabulary is now decided.** Decision 0009 deliberately left it open - "against a real widget rather than in advance" - and the widget is §4.1's chart. `INTERVALS` reuses `object_sets.TIME_INTERVALS`' names and adds `hour`, because a sensor reading every minute is unreadable at daily resolution. `AGGREGATES` includes `last`, because a series of readings is often a *level* rather than a rate and averaging a level across a day answers a question nobody asked.

**Two duplicated lists bit, exactly where duplicated lists do.** `PropertyIn.data_type` carried its own regex copy of the property types, so adding `time_series` to `ontology.PROPERTY_TYPES` left the one place a client could *declare* it behind - and the refusal named a pattern rather than a missing feature. Then `test_every_property_type_can_be_an_action_parameter` went red: `action_parameter_type` is a second enum overlapping `property_data_type`, and that test exists to catch precisely this drift. **Fixed in the code, not the test** - a time series property's value is a series id, an ordinary scalar, so re-pointing an instance at a different series is a normal edit and refusing it would be arbitrary. Both lists are now derived from `PROPERTY_TYPES` rather than retyped, and the enum is widened in the same migration that introduces the type.

Four mutations, all red. **971 API tests** (was 951), 102 unit, 121 browser.

---

### 149. The chart, and the last of §4.1's four renderings (this session)

p.11 gives the standard Object View four type-aware renderings. Geospatial and "everything else" landed with the view itself (§122); media landed once decision 0009 established there was nothing to store (§147); this is the fourth. A prominent `time_series` property now draws its line from the points in the dataset behind it - nothing copied, which is the decision, demonstrated on screen.

**A workspace-scoped read, keyed on the instance.** The project-scoped points endpoint from §148 is the one a *builder* uses; a *reader* is on the Object Explorer or the standard Object View, both of which are workspace-wide. Putting a series behind project membership would make one property readable and another not, on the same card, for no reason a reader could see - instance properties are already visible at this floor and a series is the value of one of them.

**The series id is not a parameter.** It is the instance's own value for that property, read server-side. A caller supplying one could ask for somebody else's series through an instance they can see, and the question this endpoint answers is "this object's readings" rather than "these readings". The mutation that reads the wrong property's value is red on three tests.

**The geometry is pure and its own module.** Where a point lands is a rule, and two of them are the kind that only show up in production: a **flat series** is `0/0` for every point - a sensor reading the same number all week is the most ordinary series there is - and a **single reading** is a fact that an empty chart would deny. Both sit in the middle rather than dividing by zero or being skipped.

**A test caught a real bug in its first run.** `Number(null)` is `0`, and so is `Number("")` - both finite, so a `Number.isFinite` guard alone plots a *missing* reading as a real zero. A gap in a line is honest; a zero is a reading that never happened. The emptiness check now comes first, and the comment says why.

**And a test of mine could not fail for its stated reason.** One claimed to cover "an object with no series id charts nothing" - but every synced instance in that fixture has one, so the assertion was true for the wrong reason. Replaced with what the fixture can actually distinguish: S2's chart is S2's, from the same dataset and the same mapping.

**The browser fixture needed the one thing `Module.object_type` cannot say**: the primary key column mapped to the series property *as well* as being the key. That is decision 0009's ordinary case - the series id is the instance's own key - and a mapping of `{column: same-named property}` has nowhere to express it. Built directly rather than by growing a parameter only one file needs.

Four mutations, all red. **976 API tests** (was 971), **111 unit tests** (was 102), **124 browser tests** (was 121).

---

### 150. Reading a value back out of a filter (this session)

`workshop.md` §3.2 calls object set filter variables "the single most load-bearing missing variable type", and p.444 says what one is for in two halves: filter state "can be **applied to object set variables**" *or* "**reused in widget configurations**". The first half has worked since `narrow_set` - a Filter List writes clauses, a derived set reads them. The second half had nothing, and it is the half that makes a filtered app readable: a heading that says which region you are looking at, a chart title that names it, an action whose default comes from what you already picked.

`filter_value` is that half. One input (the variable holding the clauses), one configured property, and the answer is what the viewer chose for it.

**A property nobody filtered on is `None`, not an error.** An untouched filter is the ordinary state of an app somebody has just opened, so a derivation that raised there would make the *first* render the broken one - the state every viewer sees before they have done anything. This is `filter_set`'s existing rule about unset values, one layer up, and the two now agree.

**A multi-select comes back whole.** An `in` clause holds several values because the viewer picked several, and returning `value[0]` would quietly answer a different question - "north" where the truth is "north and south". `is_empty` and `concat` both already handle a list, so a caller has what it needs without this function deciding for it. The mutation that collapses to the first value is red.

**Only the first clause for a property is read, deliberately.** Two clauses on one property is a Filter List expressing a range or a several-of - one filter with two halves, not two answers - and picking a half here would be this function inventing which half matters.

**Default filters needed nothing built, so nothing was built.** An `array` variable with a `default` *is* filter state applied on load: the default clauses are there before any widget writes, and `narrow_set` reads them like any others. The right response to a spec line that is already satisfied is a test that would go red if it stopped being satisfied, not a second mechanism - `test_a_filter_can_start_with_a_default_applied` is that test, and it asserts through the derivation rather than through the default it sets.

**The save-time check is the usual pair**, because a derivation that is wrong in the document should be refused where it is written rather than surfacing as an empty heading at render: exactly one input, and a property to read. The mutation that drops it is red.

Four mutations, all red. **984 API tests** (was 976), 111 unit, 124 browser.

What is still open in §3.2's row is the dedicated `object_set_filter` variable *kind*: filter state travels as an `array` of clauses rather than as its own type, so the panel cannot tell a filter apart from any other list and a widget cannot ask for "a filter" specifically. That is a typing improvement, not a capability - both of p.444's behaviours now work without it - so it waits for a widget that actually needs the distinction.

---

### 151. Time series set variables, and the chart that reads one (this session)

`ontology.md` named this as the last thing left after §148 and §149: the storage, the mapping and the points read exist, and Workshop could not ask for any of it. p.76 says what a time series set variable is, and the sentence is the whole design:

> "Time series set: Stores a time series property of **a single object**, optionally allowing the application of time series transforms to it."

**Of a single object - not of a set.** That is what makes this cheap rather than a fan-out: the object is already in hand as a `single_object` value, so a series variable is a *reference* built from it. `object_series` takes one object variable and a property, and resolves to `{object_type_id, instance_id, property, interval, aggregate}` - which is exactly what `seriesPoints` takes, so a widget consuming one adds no interpretation.

**It resolves to a question, never to points**, and that is the same rule object-set variables follow. `object_set` holds a definition rather than rows so one set can feed a table, a chart and a count without three notions of what the set is; a series is the sharper case, because decision 0009 keeps points in the dataset they arrived in and a variable holding points would be that copy - made once per viewing, per widget.

**The bucket and the summariser live on the variable, not on each widget** (p.76's "time series transforms"). Two charts reading one series then agree about what a point means, which is the difference between a variable and a shortcut for typing the same configuration twice. They are validated at *save*, against `time_series.INTERVALS` and `AGGREGATES` rather than a second copy of the list - an unknown aggregate would otherwise surface as a DuckDB parse error in front of a viewer, naming a function nobody typed.

**Two refusals worth the words.** A `time_series_set` with no derivation is refused: there is no static form of a series, so one would resolve to whatever `default` held, which for this kind is always a typo. And an object with no `id` or no `object_type_id` is refused rather than resolved to `None` - unlike a missing property value, that is not a state a viewer can be in, since every path that writes a `single_object` writes both. `None` would render as "no readings yet", a sentence about the data when the truth is about the wiring.

**The consumer is p.280's third Data input**, on the widget the spec puts it on rather than a new one - and forced to a line, because p.281 says "only the Line Chart option is supported" and because it is right: a bar per reading is a comb and a pie of readings answers nothing. The browser fixture asks for a **bar** chart on purpose; a fixture that agreed with the widget could not tell whether the rule was applied.

**`Number(null)` is `0`, again, one layer up.** §149 caught this inside `plot`; the same trap is here, because a reading that is missing arrives as `null` and `Number` makes it a finite zero - a measurement that never happened. Dropped rather than zeroed, and *said*, because a gap removed in silence is a chart that looks complete. **The first mutation of that filter survived**: no sensor in the fixture had a gap, so removing the guard changed nothing. A third sensor with one missing reading is what made the test able to fail.

**A second surviving mutation, same shape.** Deleting the "nothing picked yet" message left every assertion green, because the caption's absence before a click is guaranteed by the query being disabled rather than by the message. The test now asserts the sentence, not just the silence.

**Labels needed their own function.** `seriesLabel`'s narrowest bucket is a day, which is right for object counts; a series can be asked for by the hour or not bucketed at all, and a day-only label stacks a fortnight of readings onto fourteen labels - which a chart keyed on labels draws as fourteen points, silently losing the rest. `seriesPointLabel` is pure, carries seconds only where two readings can differ by them, and returns anything that is not a timestamp as itself rather than throwing `Invalid Date` from inside a chart.

Sixteen mutations, all red - six on the variable, four on the label, six on the widget. **994 API tests** (was 984), **116 unit tests** (was 111), **129 browser tests** (was 124).

Still open on §3.2's row: the other three consumers p.582 names (Map, Metric Card, Object Table) and p.583-584's time series *transforms* - cumulative, periodic and rolling aggregates, which are a computation over points rather than a variable, and belong with the points read rather than here.
---

### 152. Routing: the module's say in what a link carries (this session)

`workshop.md` §7 was ○ across the board, and it is the section that decides whether an app is *shareable*. p.195-199, built end to end.

**Two directions, two rules, two files - and that is the design.** p.198 ends with a sentence pointing the opposite way to everything above it: a query parameter matching an external ID seeds the variable "regardless of URL inclusion behavior configured". So inbound stays `seedFromQuery` (§116), ungated, and outbound is the new `routingParams`. Expressing them as one setting would have made a link somebody types by hand stop working against a module whose author never turned routing on.

**The routable kinds are stated positively, and the list is the *reading* end's vocabulary.** A kind may be in the URL exactly when `coerce` can parse it back: string, number, boolean, date, timestamp. Everything else is refused at save, because a builder who ticks "Always in URL" and gets nothing has no way to tell which end was wrong. That is wider than p.199 in one place and narrower in another, both named in the parity doc: `array` is refused (p.199 excludes filter variables, and our filter clauses are arrays - but so is an ordinary multi-select, and a list needs repeated parameters the reader does not handle), and `object_set`/`single_object` are refused outright where p.199 allows them by RID, because there is no by-RID rehydration to write a key against.

**Page IDs are author-set, not node ids.** A Craft.js node id is generated and changes when a page is recreated, so a link built from one would expire for a reason nobody could see. p.197's three "no page" cases - absent, never named, named but since deleted - all resolve to the default page, and the default page is read off the layout using `CanvasPage`'s own first-page rule rather than assumed, so the URL and the render cannot disagree about which page the reader is looking at.

**Routing found a real gap somewhere else, and it is the interesting part of this unit.** `when_visible` asks which variables a page's widgets bind - and `REFERENCE_PROPS` could not see the one widget whose entire purpose is to bind one. The Filter control declares its variable through `name` (`workshop_format.DECLARING_PROP`), which after the format-2 conversion holds a variable id like every other entry in that list, and it was never added. So a Filter bound to a deleted variable was neither refused nor reported - decision 0002's exact failure, on the widget the decision was written about. Fixed in both copies, with tests for the usage and the dangling reference. This is `subjectVariable` (§116) again, found the same way: by building something that had to enumerate bindings and noticing one missing.

**A test problem worth writing down.** `page.url` is Playwright's cached view of the main frame, refreshed by navigation events - and `router.replace` is a `history.replaceState`, which fires none. So an identical assertion passed whenever some other locator call happened to refresh the cache and failed when it did not. The query string is now read out of the browser with `page.evaluate("location.search")`. A test that is green for reasons unrelated to what it claims is the failure this repo keeps finding, and this is a new shape of it.

Twenty-two mutations, all red: eleven on the pure rules, five on the wiring, one on the reference-prop fix, and five on the server's refusals. **1005 API tests** (was 994), **137 unit tests** (was 116), **136 browser tests** (was 129).

Still ○ in §7: state saving (p.200-202), which is the third consumer of an external ID and belongs in §3.4's mechanism rather than beside this one.
---

### 153. State saving: a view somebody can name, keep and hand over (this session)

The last ○ block in `workshop.md` §7, and the third consumer of an external ID after embedding (p.163) and routing (p.198). `docs/parity/README.md` predicted this one: "it belongs in the existing mechanism … needing anything new would mean this was built wrong." The prediction held - no new naming mechanism - and what it did need was storage (db 0048) and one asymmetry worth writing down.

**A state is keyed by external ID, and that is the feature.** p.203:

> "Variable values are stored within a saved state via their external ID. As a result, modifying a variable's external ID after state saving has been configured may cause previously configured states to reload unsuccessfully."

The same page gives the upside: an Object Dropdown replaced by an Object Selection keeps its states "as long as the output object set from those widgets uses the same external ID". So a state survives the module being rebuilt around it, and a test rebuilds one with a different variable id and a different label to prove it.

**The asymmetry with routing.** Routing requires interface membership because the URL is read back by `seedFromQuery`, which only reads interface variables; state saving does not, because a state is read back by *this* module, by name. Two features on one key with two different requirements, which is why they are two functions rather than one - the temptation to unify them would have made a routed variable's rule apply to a saved one.

**What a state can hold is wider than what a link can, and that is not an inconsistency.** p.199 excludes arrays and object sets from the URL; p.205 includes them in a state. A query string has to be parsed back into a value and a jsonb document does not, so the list follows the medium. Derived variables are refused on both: a saved answer disagrees with its own question the moment the data moves, and saving the inputs restores both halves.

**Saving is a viewer's action.** p.200 calls this a feature for "module consumers", and a state writes nothing about the module - so requiring the editor role would put it behind exactly the permission its audience lacks. Saving over your own state updates it; over somebody else's it is refused, because the feature's second sentence is about sharing and a shared view replaced without a word is the failure that invites.

**A state that came back short says so.** Restoring what still applies beats refusing the whole state over one stale key, but only if the reader is told - otherwise they believe they are looking at what they saved. The open response carries the external IDs that no longer resolve, and the bar prints them.

**Foundry's location settings are refused rather than deferred** (p.204: "Add shortcut", "User home folder", "Any Compass location"). They configure where in Compass a state file is written; a state here belongs to its module, which is the only location this platform has, and a setting with one possible value is a control that teaches nothing.

**Two mutations survived first, and both were tests true for the wrong reason.**

- The unsavable-kind refusal was *unreachable*: `time_series_set` is the only kind a state cannot hold, and it is also always derived, so the derived check ran first and the kind check could never fire. Fixed by ordering, which makes both branches live - and the mutation is the only thing that could have found it, since the code read perfectly well.
- The `include_page` default was asserted through the `state_saving: true` shorthand, which takes the *dataclass* default rather than the block's - so flipping the block's default left the test green.

Nineteen mutations, all red: fourteen on the server, five on the browser. **1032 API tests** (was 1005), 137 unit, **142 browser** (was 136).

**§146's recovery recipe was incomplete and cost two failed attempts this session.** Migrations do not run as `platform_app` - that role has no CREATE on `public`. The line is `PLATFORM_APP_PASSWORD=devpass DATABASE_URL="postgresql://platform:devpass@localhost:5432/platform?sslmode=disable" .venv-api/bin/python packages/db/migrate.py`: the owner role, the plain `postgresql://` form rather than SQLAlchemy's `+psycopg`, and the password variable that `0006_rls.sql` needs. `docs/local-setup.md` had it right all along; the recovery note did not point at it.
---

### 154. Required properties, and a flag that meant nothing (this session)

`ontology.md` §1.2's TOC §15, and the first stage-3 item after the Workshop run. p.116:

> "Required properties are object type properties that must have a value. … This validation applies to data from the backing datasource and edits via actions."

**The column has existed since migration 0003.** The API accepted it, the Ontology Manager displayed it in two tables, and *no write path read it*. That is the shape of gap this repo's standard is written against: a flag that looks configured and enforces nothing is worse than an absent feature, because somebody will set it and believe it. Nothing here is new storage - the whole unit is making an existing switch do what its name says.

**Two enforcement points that behave differently, which is p.116's arrangement rather than a compromise.**

*Actions refuse.* "If you attempt to write a null or empty value to a property via an action, the action will fail to execute." Checked before anything is written, beside `check_criteria`, for that check's own reason: refused and refused-after-writing-half-of-it look the same to the caller and are very different in the dataset. **Only what the action writes is checked on an existing object** - a required property that was already empty is not this action's fault, and refusing there too would make an object that predates the rule uneditable by the one action that could fix it. A create is the exception, because there is no "already": every required property has to arrive with the object. Subject, created objects and named objects are each checked against their own type's list.

*Sync reports.* "The check for null values happens as backing datasources are indexed … the ontology modification itself will succeed if the column backing a required property contains null values." So the sync counts and returns; it does not refuse. Data that is already wrong is a fact about the data, and a sync that refused would leave an object type that will not load, no way to see why, and the fix out of reach upstream in the dataset. The counts reach the screen and the audit log - counted and not shown is the same as not counted.

**One predicate for "missing", shared by both ends.** Null, empty list, and the empty string. The third is ours and is the one that matters in practice: a form posts `""` for a box somebody cleared, so treating that as a value would let the one path a person actually uses walk straight past the rule. `0` and `false` are values - the classic false negative in a check written `if not value`, and a required numeric property whose only legal reading is zero is ordinary. A test asserts the two ends agree, because two opinions about `""` would mean a row the sync flagged and an action accepted.

**I wrote a migration for a column that already existed, and the migration runner caught it.** `ALTER TABLE … ADD COLUMN required` failed with "already exists" - it has been in 0003 since the beginning. Worth recording because the recovery was not free: I had already dropped and re-added the column to get a clean apply, which discarded the values in the dev database. In a real deployment that would have been data loss from a migration whose whole purpose was redundant. **Read the table definition before adding a column to it**, not just the recent migrations.

**A browser mutation that could not fail, for a reason worth writing down.** Mutating a *backend* source file and re-running the browser suite proves nothing: the API is a separate long-running process and does not reload. The mutation looked green and the rule was fine - the probe was inert. Confirmed by restarting the API with the mutation applied, where two tests went red immediately. Any backend mutation checked through `e2e/` needs `dev-up.sh` between the edit and the run; frontend ones are fine, because Next hot-reloads.

Nine mutations, all red: six on the rules, three on what reaches a person. **1056 API tests** (was 1032), 137 unit, **146 browser** (was 142).
---

### 155. Link traversal inside an object set definition (this session)

`ontology.md` §3's last ○, and the one `workshop.md` §3.1 names as the reason its "Object set definition" row is only partial. A set can now be the far side of a link: *"the orders belonging to these customers"*.

**A hop compiles to an `in` filter** over the near side's join values. That is the whole implementation, and it is why no store gained a new capability: `in` already means the same thing on Postgres and OpenSearch - which is precisely why it is in `OPERATORS` while the ordered operators are refused (§52's cross-store argument). A traversal that had invented its own join would have walked straight into the disagreement that list exists to avoid.

**The half that did need work is the primary key.** Migration 0027's join is "the *from* side holds the foreign key", so traversing towards the *to* side matches against that side's key rather than against a property - and a filter vocabulary that addressed only `properties.*` would have supported link traversal in one direction and refused the other. That is not a feature; it is half of one. Both stores now accept `$primary_key` as a filter target: a column on Postgres, a keyword field on OpenSearch, one sentinel shared with `ontology.PRIMARY_KEY_REF`, and a test that the two spellings agree. A second test checks an ordinary property still reaches `properties.*` on both, because a sentinel that swallowed every filter would make every set read the key.

**Three refusals, each of which would otherwise be an empty table somebody has to debug.**

*An empty base set is the empty answer, not an unfiltered read.* `join_filter` returns `None` rather than "no filter", and the caller stops. Returning an unfiltered set there would show **every** object of the far type - decision 0002's silent widening, in the one place where it would look most like a working feature.

*A link that does not touch the base type, and a traversal claiming to land where the link does not reach.* "Your definition is wrong" and "there are no matches" look identical in an empty table, so both are refused with a sentence naming what the link actually connects.

*Depth beyond three, and more than a thousand distinct join values.* Each hop is a full evaluation of the set below it, so depth costs a query rather than a clause; and a base set of a hundred thousand objects becomes a hundred thousand `in` terms on either store. Refused with the number rather than truncated - a set quietly missing its tail is the failure that looks like working software.

**The link decides which end is near**, read from the base set's own type (`links_for_type` returns a link once per end it occupies). So a definition cannot name the wrong direction: it does not name one at all. The same reasoning as `Traversal` holding a link type rather than a property pair - restating the join would be a second copy of it, free to disagree with the ontology the moment somebody edits a link.

Eleven mutations, all red. **1077 API tests** (was 1056), 137 unit, 146 browser.

**What is left is the builder.** The object-set editor offers a type and filters, so a traversal has to be written into the document by hand today. That is `workshop.md` §3.1's row, now ◑ for that reason rather than for the server one.

### 156. Drawing a link traversal (this session)

§155's other half, and the sentence that closed it: *"the object-set editor offers a type and filters, so a traversal has to be written into the document by hand today."* Now it does not have to be. `workshop.md` §3.1's row is ✅.

**A traversal is a set *transform*, not a third kind of set.** The panel's "This set" control already offered "Draws from an object type" and "Is another set, narrowed"; the hop is a third answer to the same question, "Follows a link from another set", and it lands on the machinery that was already there - `traverse_set` joins the transform list beside `narrow_set`, taking one input (the set to start from) and a config naming the link and where the hop lands. Nothing about cycles, usages or dangling references needed a special case, because a traversal *is* a derivation and those checks are about derivations.

**Both ends of the link are offered, named for the end you arrive at.** A link between two types can be followed either way and the two land somewhere different, so a link appears in the picker once per end it touches the base type from - twice for a self-link, on purpose. The label reads `<side name> → <far type>` and takes the side name of the end being travelled *to*, which is the reading `links_for_type` already established (p.192's own example: from a manager you follow "Direct reports"; from a report, "Manager"). Getting this backwards is a picker that is confidently wrong rather than broken, so a mutation checks it.

**The picker refuses to offer hops before it can know which exist.** Which links apply depends on the base set's *type*, and the base set is a variable reference - so until one is chosen there is no honest list, and the control is disabled with a sentence saying why rather than showing an empty dropdown. Changing the base clears the link for the same reason: keeping one would leave a hop the server refuses, saved by a control that looked fine.

**The saved config names both the link and the landing type**, which reads redundant and is not. The link says which ends exist; the landing type says which of them this hop took. §155's server refuses a pair that disagrees instead of following the link somewhere the definition did not say - and a builder that sent only the link would make that refusal unreachable from the one path people actually use.

**`from_side_name`/`to_side_name` were missing from the browser's `LinkType`.** The API has returned them since §146; the TypeScript type had not been told, so any UI reading a side name was reading `undefined` and silently falling back. Added, which is the sort of gap a shared types package exists to prevent and only closes when something tries to use the field.

**A fixture with the side names inverted, caught by the assertion rather than by the code.** My first draft named the sides from the wrong end and the test asserted the wrong string; both were wrong in the same direction, which is exactly the pair that passes. What actually decided it was `ontology.links_for_type` - there was already one reading in the codebase, and a second one invented in a test would have been a fork in the meaning of a stored field.

**And a browser test that was true only by luck.** Reading the picker's options the moment a base set is chosen counts an empty dropdown: the link types arrive from a request. The neighbouring test passed because `to_be_enabled()` waits, and mine did not - the same "the probe was inert" class as §154's backend mutation, from the other direction. Now it waits for the count, which also asserts the thing worth asserting: exactly one hop applies from a customer.

**One limit, named rather than hidden.** The picker can only offer hops when the base set's type is written down - so a base that is itself *narrowed* or *followed* shows the hint rather than a list, even though the server composes those fine (§155's `via` nests). Resolving the type through a chain of derivations is a walk the panel does not do yet; the hint says which kind of set to pick instead of showing an empty dropdown, which is the same rule as waiting for a base set at all.

**One survivor, and the claim it was hiding.** Copying the base set's filters onto the far side left every test green: my traversal test asserted what reached `via.base` and never looked at the hop's own `filters`. A customer's `region` filter applied to *orders* is a filter on a property they do not have - no rows, from a rule nobody wrote. The filters stay on the near side, and now something says so.

Twelve mutations, all red: six on the panel, six on the transform. **1082 API tests**, 137 unit, **149 browser** (was 146).


### 157. Value formatting (this session)

`ontology.md` §1.2's first ○, and stage 3's own headline - "property types and **formatting**". A property can now say how its value should be read: p.94's own two examples are a weight shown as "72.5 kg" and a value shown as "$100K".

**The stored value never changes, and that is the whole design.** Formatting on the way out of the API would make `"$100K"` the answer to a question that used to be answered `100000` - and every consumer that is not a screen would be wrong at once: filters, actions, aggregations, exports. p.100 settles it independently by offering *"the application user's current timezone"* as a legal choice, which is not something a server knows. So the formatter is stored beside the property, validated on the server, and applied in the browser.

**The server's contribution is refusals**, each of which is a page that would otherwise render wrongly or not at all:

* *A formatter that does not match the base type* (p.95). A number formatter on a string is not an error anybody sees - it is a setting that does nothing, forever.
* *The digit pairs `Intl.NumberFormat` throws on.* A minimum above its maximum is a `RangeError`, which in a browser is a blank cell and a console message nobody reads. Refused at save, where the answer can still be changed.
* *A style missing the thing that style is for* - a currency with no code, a unit with no unit, p.97's Prefix/Suffix with neither. The last is not a style at all; it is `plain` with extra steps, and saving it shows an editor a setting whose effect is nothing.
* *A misspelled option, refused rather than dropped.* Silently ignored, it is a setting somebody believes they turned on - and will believe again every time they reopen the editor and see it sitting there.
* *A timezone on a `date`.* p.100 scopes zones to timestamps, and it is right to: shifting a date by an offset moves it to a different day, which is a wrong answer rather than a differently-presented one.

**An absent timezone is deliberately not defaulted to UTC.** A stored `"UTC"` is an author's decision and an absent one is "wherever the reader is". Collapsing the two would take a choice away and look like tidying up.

**p.99's footnote is a rule, not a detail.** "Relative to now" only spans 24 hours; past that it renders short form **with the day of the week**. The weekday is what makes it its own branch rather than a fall-through to `datetime_short`, so a test renders the same instant both ways and holds them apart. Relative units are *truncated* rather than rounded, which is a decision the spec does not make: rounding turns 23h59m into "24 hours ago", a reading that names the very boundary the branch exists to stay inside.

**The vitest suite already ran in New York, and it earned its keep.** `vitest.config.ts` pins `TZ=America/New_York` for §151's reason - a UTC machine cannot tell a timezone option from a missing one. Three zones are asserted on one instant, including "no timezone means the reader's own", which is only checkable because that instant is still the previous day in New York.

**Two fallbacks, both so that a cell is never blank.** Properties are stored untyped, so a `float` column routinely holds `"n/a"` from a dataset nobody cleaned; `Intl` renders that as `NaN`, which reads like a computed answer rather than like the text that is actually stored. Same for an unparseable date and "Invalid Date". And if `Intl` refuses the options anyway, the plain number is still shown - a blank cell is the one outcome that tells a reader nothing.

**The raw value stays reachable in the tooltip.** p.94's readability is bought by hiding the number somebody has to type into a filter. Both, rather than a choice between them.

**The editor invents nothing, and its Apply button is not a trap.** The first version pre-filled `USD` and `kilogram` when you chose those styles - which is a guess that saves silently and renders every number in a currency nobody chose. Now the field starts blank, Apply is disabled while the draft is one the server would refuse, and the sentence saying why is on screen. The rules are the same list as `services/value_format.py`, checked in the one place where the answer can still be changed. p.96's live preview is the same `formatValue` the tables use, not an approximation of it.

**Two mutations survived, and both were tests true for the wrong reason.**

*The first was `to_have_count(0)` asserted before anything had rendered.* "A string property is offered no Format button" passed against a build where **every** property offered one, because an empty dialog also has zero of them. Presence before absence is the fix and this is the fifth time this repo has recorded that shape - the assertion was about the absence of a thing rather than about the rule that produces it.

*The second was hidden by the default I have just removed.* "Typing a unit lands it on the draft" passed with the unit input wired to nothing, because the style switch had already filled in `kilogram` - the test asserted a value it never set. Removing the invented default fixed the test and improved the editor, which is the good case: the mutation did not find a broken rule, it found a *convenience* that made a rule unobservable.

**And a wrong ✅ in the parity doc, found by reading the neighbouring page.** `ontology.md` §1.2 claimed **Conditional formatting** was done, citing §83 - which is the Object Table's columns, sort and paging. There is no conditional-formatting rule anywhere in the codebase. Both that row and `workshop.md`'s matching ◑ are now ○ with the correction stated, because a false ✅ in the specification-to-meet is worse than a ○: it is the one status nobody re-checks.

Thirty-six mutations, all red: thirteen on the validator, fourteen on the formatter, nine on the wiring and the editor. Two of those nine survived their first run - they are the two above, and they went red once the tests (and, in the second case, the editor) were fixed. **1104 API tests** (was 1082), **155 unit** (was 137), **154 browser** (was 149).


### 158. Conditional formatting (this session)

The row §157 corrected. `ontology.md` §1.2 claimed this was done, citing §83 — the Object Table's columns, sort and paging — and nothing of the sort existed. It exists now: `object-link-types` p.102-109, a property's values coloured by rules.

**An ordered list, and the order is the semantics.** p.105 describes an "Always true" rule used "as a fallback in case your other rules don't match", which only means anything if rules are tried in sequence and the first match wins. So a rule after an always-true one is unreachable, and unreachable is refused rather than allowed — a rule that is on screen looking configured and can never fire is worse than one that is missing.

**It composes with §157 rather than competing with it.** One property can carry a formatter *and* rules, and p.102's own example does. The rule compares the **raw stored value**; the formatter decides the text. Handed `"$100K"`, a threshold rule would never fire, because a string never was greater than anything. The browser test is the only place that claim can be made — it needs both settings on one property at once, which neither unit suite has — and it is the reason that test exists.

**This is not the ordered-comparison rule the stores refuse, and the distinction is worth stating** because it looks like a contradiction. `OPERATORS` excludes ordered operators (§52) because instance properties are stored untyped and Postgres and OpenSearch would disagree about whether "250" sorts before "40". Nothing here touches a store: the comparison happens in a browser, on a value already fetched, against a property the object type *declares* as numeric. The declaration is what makes it safe — which is exactly why a numeric comparison is allowed on a numeric property and refused on a string one (p.105 label C).

**A rule paints one property and may read another** (p.105-106: choose `Performance factor` in the logic, the colour still shows on `Type`). That is why validation needs the whole object type rather than the one property, and why the evaluator takes the whole instance rather than one value.

**The refusals, each a rule that would sit in an editor looking configured while doing nothing:** a comparison that does not fit the compared property's type; a rule naming a property the type does not declare; an unbounded numeric range, which is an always-true rule wearing a comparison; a boolean comparison whose value is the *string* `"true"`, which would never match the stored boolean; and a rule with no colour, no background and no alignment — the one outcome nobody can debug from a screen.

**Absence is not a match, and it is not a mismatch either.** The rule that took two attempts. "Is not exactly A320" is *true* of an object with no type at all, so an inverted rule evaluated-then-flipped would quietly colour every incomplete row — the rows it knows least about. The guard has to sit before the negation, not inside the comparison. `is_null` is the comparison for asking about absence, and it is the one that wants the empty value.

**Three mutations survived because no browser test ever saved a rule.** The editor tests stopped at "Apply is enabled", so dropping the rules on save, writing them nowhere, and failing to reset a stale comparison were all invisible. One test that builds a rule, applies it, saves the type and looks at an object killed all three — and it also carries §157's lesson forward by asserting that a *different* property's rules survived an edit that was about something else.

**Three more were tests too weak to tell two behaviours apart**, in the unit suite: `starts_with` and `ends_with` were indistinguishable from `contains` until a case put the substring somewhere the operator does not look, and an inclusive range was only ever asserted at one end. A fourth was a bad mutation of mine — JavaScript coerced the string back to a number, so the "compares as text" mutant was never comparing as text.

**And an assertion that waited thirty seconds for something that was never coming.** An unmatched value renders as bare text, deliberately: an unstyled wrapper around every cell of every table is a lot of DOM for nothing. So `assert colour != GREEN` was asking for the colour of an element that does not exist. The absence of the span *is* the evidence, and asserting it is both faster and more precise. Worth recording beside the `to_have_count(0)` lesson from §157, because it is the same mistake mirrored: there, absence was asserted where presence had not been established; here, presence was asserted where absence was the point.

Forty-three mutations, all red: eighteen on the validator, fifteen on the evaluator, ten on the wiring and the editor. **1128 API tests** (was 1104), **174 unit** (was 155), **159 browser** (was 154).


### 159. The Linked objects component's last two capabilities (this session)

`object-views` p.11 lists four things the component is for. Two were built — the groups (§18) and the inline property preview (§145). These are the other two, and `ontology.md` §4.1's row is ✅:

> "Open a subset of linked objects in a new tab for further exploration. Preview a selected linked object in the side panel of the standard Object View."

**The subset needed no new query, and the reason is migration 0027.** Links are *derived*, not stored: a link type names two properties, and the linked objects are the ones whose far property equals this object's near value. So "these linked objects" is already sayable in the Object Explorer's own vocabulary — `type` + `property` + `value` — and the whole feature is a URL. Even the awkward case is already handled: when the join lands on the primary key rather than a property, the explore route maps `$primary_key` to "the instance's key, not one of its properties", the same reading `find_by_property` and §155's set filters use. Passing the sentinel through untouched was the choice; a second spelling of a reserved name is a second thing to keep in step.

**A new tab, because p.11 says so and because the point is *further* exploration.** Taking the reader off the object they are standing on would make the two exclusive.

**Three controls per linked row, and they are three different intentions.** Traversal replaces where you are. The inline preview opens *under* a row and several can be open at once, because comparing two linked objects is the ordinary case. The side panel holds exactly **one**, beside everything, and survives scrolling through the other groups. A single control that guessed between them would make two of the three unreachable — the same argument §145 already made for splitting the first two.

**The panel clears itself on a hop.** A panel still showing something linked to where you *were* is the wrong-context bug the trail exists to prevent, and it would be silent: the object in it is real, its properties are real, and nothing on screen says it belongs to a different object now.

**A guard I wrote and then deleted.** The first draft refused to build a URL when the link type had no join. It cannot happen: the instance-links endpoint returns only traversable links, which is why `far_property` is a plain `string` rather than a nullable one — and TypeScript said so when the test tried to pass `null`. A branch no test can reach is this repo's own definition of a check that is not a check, so it went, with a note where it was.

**The claim the fixture carries.** One customer has two orders and the type has three. A "subset" link that opened *all* orders would be indistinguishable from a working one on any fixture where those numbers matched — so the counts are deliberately different, and the test asserts both that O1 is there and that O3 is not.

Eight mutations, all red — plus one that produced no test output at all, which was a malformed edit of mine rather than a survivor: it broke the parse, so the suite never ran. Worth noting because "no output" and "all green" look similar in a mutation log and mean opposite things. **1128 API tests**, **179 unit** (was 174), **163 browser** (was 159).

---

### 160. Edit-only properties, and a sync that was deleting them (this session)

`object-link-types` p.113: a property "not directly mapped to a column in the backing dataset of the object type". Useful for exactly what p.113 says - storing something alongside an object type without changing the dataset underneath it.

**The feature is one bit; the substance is what a sync must not do.** An edit-only value has no column to come back from, so the instance store is the only place it exists. The upsert was `properties = EXCLUDED.properties` - a wholesale replace - and a sync's row is built from `column_mappings` alone, so *every sync deleted every value that had no column*. Postgres now merges, with the dataset's values layered on top: a sync stays authoritative over exactly what it owns and no more.

**A stored flag, not "absent from every mapping".** The two are the same state and different intentions. A property nobody mapped might be a deliberate edit-only property, or a column somebody renamed upstream - and telling those apart is precisely what schema drift detection (0018) is for. Deriving the flag would make drift undetectable for every property it happened to describe. The existing `vip_note` fixture in `test_actions.py` is the other case, and it still gets refused, which is what keeps the exception as narrow as it claims.

**And the OpenSearch fixture server was lying about a merge.** Its bulk update did `{**existing, **doc}` - a *shallow* merge - while a real cluster's `_update` with a partial `doc` merges recursively. Every instance keeps its values under one nested `properties` object, so the shallow version replaced the whole thing: a partial update silently deleted every key it did not mention. That is the opposite of what a cluster does, so the fixture was making the gateway look wrong in a way no deployment would reproduce, and would equally have hidden a gateway that relied on the replacement. This is the first feature whose correctness *depends* on the merge, which is why it surfaced now and not in §16. The standing caveat still holds - the fixture cannot prove a real cluster agrees - but it now models the documented behaviour instead of contradicting it.

Two stores, then, and neither was right, for the same reason. The claim is written once and both answer it.

**The write-back exception is deliberately narrow, and the limits are the interesting part.** A `modify_object` rule on the action's own subject may write an edit-only property. Three things still refuse one:

* a **link** property, because a link is a join over stored data (0027) - a link with no column is one no sync could ever re-derive;
* **`create_object`**, because a creation's dataset row *is* how the object comes into existence, and an edit-only value has no column in that row and no instance yet to write to. Refused by name rather than dropped, which would be a value somebody supplied and never saw again;
* a property that is merely unmapped, per above.

**§154's sync report needed a subtraction.** p.116's missing-required count is computed from the rows a dataset produced, and an edit-only property is never in them - so a *required* edit-only property would have been counted missing on every row of every sync, for ever, saying nothing about the data. It comes out of that set. Actions still refuse to empty one, which is where the rule is actually enforceable, and that split is p.116's own.

Eight mutations, all red. One near-miss worth recording: the mutation harness backed up `src/services/actions.py` and `src/routes/actions.py` to the same scratch filename, so the second clobbered the first. The run aborted on a failed pre-check rather than restoring the wrong file over a source - every mutation asserts its target text is present before writing, and that guard turned a silent corruption into a stopped run.

**A flaky test of my own, found by this unit's full run and fixed here.** §156's "a traversal can be drawn" failed about one run in four with "still 3 after 20000ms" - the traversal never persisted. The test clicked Save and then called `settled`, which only proves the canvas *drew*, and it had already drawn: so the navigation that followed could start while the save was still in flight. It now waits on the definition response itself. Worth recording because the first four data points pointed at a regression in this unit - it failed twice with the change and passed once without - and only running it repeatedly showed the change had nothing to do with it. A test that fails a quarter of the time will frame whatever is in the diff.

**1135 API tests** (was 1128), 179 unit, 163 browser.

---

### 161. Derived properties: the question, not yet the answer (this session)

`object-link-types` p.143-148. A property "calculated at runtime based on values from linked objects" - a chain of up to three link types, an aggregation, and the property at the far end.

**This unit builds the declaration and its refusals. Nothing evaluates one yet**, and it is deliberately *not* exposed in the property editor: a property somebody could switch on and then watch render nothing would be worse than one that is absent. `ontology.md` §1.2's row is ◑ with that said plainly.

**A question, not a value.** Nothing is written under a derived property, and materialising one would create a second answer free to disagree with the first the moment a linked object changed.

**The direction of each hop is derived, not declared** - a link touches the type a chain has reached from exactly one end, so naming the direction as well would restate migration 0027's join and be free to disagree with it.

**And that is exactly where I got it wrong.** `one_to_many` is named from the `to` side: this repo puts the foreign key on the `from` side, so many `from` rows point at one `to` row - `works_in` is Person to Department with the department id on the person. The "many" is therefore reached travelling *inbound*, and I wrote it outbound. Three tests caught it, and the consequence would have been quiet: a department allowed to derive "employee salary" with no aggregation, which is one cell asked to hold every employee's salary.

**A test premise of mine was wrong too**, in the other direction. "Following the same link twice does not join up" is false - a department's employees' departments is a real walk - so demonstrating a chain that genuinely does not connect needed a fourth object type. Both cases are tested now, which is the point: the check and its counterexample.

**Four of p.145's nine aggregations are refused rather than answered, and the reasons are different.**

*`sum`, `avg`, `min`, `max`* need to know a property is a number, and instance properties are stored untyped. That is the blocker §52 named for ordered filters, §74 for numeric aggregations, §83 for property sorts and §86 for map area selection. **This is the fifth thing waiting behind it**, and it is worth saying that the queue is no longer an argument about convenience: p.143's own opening example is "a Department object type could have a derived property for Average employee salary", and that exact declaration is refused. The spec's headline illustration is what the missing type information costs.

*`approx_cardinality`* is refused for a sharper reason of its own. OpenSearch's cardinality aggregation is approximate and Postgres' `COUNT(DISTINCT)` is exact, so "approximate" would be a promise one store keeps and the other exceeds. `exact_cardinality` is the same question with an answer both can give, so that is the one offered.

**Refused on create rather than validated there.** A derived property follows link types *from this object type*, and a link type can only be created against types that already exist - so at create time there are none, and no chain named there could be a legal one. Not a limitation so much as a consequence, and the message says which.

Seventeen mutations, all red. **1159 API tests** (was 1135), 179 unit, 163 browser.

---

### 162. Derived properties, answered (this session)

§161's other half, and the one that makes the feature real: a derived property is now **evaluated when an object is read**.

**The chain is an object set rooted at the one object, so there is no traversal code here.** A derived property asks "follow these links from *me*, then reduce what you find", and §155 already expresses exactly that - a set of the starting type filtered to this instance's key, wrapped in one `Traversal` per hop, answered by `_resolve_traversal`. That is what filtering on `$primary_key` was for, and it is why a three-hop derivation cost nothing new. The pieces lining up like that is the strongest evidence so far that §155's shape was right.

**Two limits, and both are named rather than discovered.**

*Single reads only.* Each hop costs a query, so filling these in for a page of a table would be a silent N+1 on every list in the product. p.143's own examples are all object-shaped - "this department's average salary", "this project's lead engineer" - so the object view is where the answer is worth paying for. A derived *column* needs the aggregation pushed into the index, which is the same typed-index work §87 is blocked on.

*Four of nine aggregations still refused*, per §161.

**Each aggregation answers an empty chain with its own empty.** Written first with one shared sentinel, which produced a genuine inconsistency: an empty *base* answered `None` while an empty *far side* answered `[]` - the same question, two shapes, depending on which end of the chain ran out. Now `count` is 0, a collection is `[]`, a single value is `None`, and one function decides it.

**Three mutations survived, and all three were one fixture being too comfortable.** The first version reused the customers dataset as both types, so every customer had exactly one linked object - which made "count" and "count the first one", "limit 2" and "no limit", and "empty" and "one" all indistinguishable. The fixture is deliberately lopsided now: Ada has three orders and Grace has none. **A fixture where every case looks the same cannot fail for any of them**, which is the same lesson as §158's but arriving through the data rather than through the assertions.

**And the empty-chain path needed *two* hops to reach at all.** A single hop always has a base - the object being read - so "nothing found" there is just an empty far side, not a chain that ran out. It takes a second hop for the walk to stop partway, which is the only way into the short-circuit. p.147's multi-hop is what makes that branch reachable, and without a test for it the branch was three surviving mutants pretending to be covered.

Ten mutations, all red. **1163 API tests** (was 1159), 179 unit, 163 browser.

**Still not in the property editor**, so a derivation is set through the API. That was §163.

---

### 163. Drawing a derived property, and the view that could not show one (this session)

§161 declared, §162 answered, and this is somebody building one: a chain picked a hop at a time, each step offering only the links that exist from where the chain stands (p.145's own behaviour).

**The walk is a second copy of a server rule, and it is worth saying why that is not duplication for its own sake.** `services/derived_properties.py` decides what is *legal*; `lib/derived-property.ts` decides what to *offer*. Without the second one the editor would list every link in the workspace and let somebody build a chain the save then rejects - the trap the value-format and conditional-format editors both avoid. The server stays authoritative: nothing in the browser can widen what a save accepts, only narrow what a form suggests. It has its own unit tests for a specific reason - the one thing the server got wrong was the *direction* of a `one_to_many` hop, and that is exactly the mistake a rendering test cannot see.

**Two real defects, both found by the browser test rather than by reasoning.**

*The API could not accept its own output.* `parse` returns `far_type_id`, and `_FIELDS` did not include it - so an editor that reads a derivation, changes the aggregation and saves it got a 422 for sending back a field the server had just given it. Read-modify-write is the ordinary shape of editing anything, and it was impossible. It is accepted now and still checked rather than trusted: a declared landing type that disagrees with the chain is refused, the same refusal §156 makes for a traversal's link/landing pair.

*And the object view could not show a derived property at all.* §162 evaluates them on the **single-object** read, and I wrote that the object view is "where the answer is worth paying for" - but every caller of `ObjectView` hands it a row it already had, from a list. So the one surface the feature was built for rendered `∅` on every derived property. The view now fetches the instance by id **when the type has one**, with the handed-over row as the placeholder, so the ordinary object view costs exactly what it did. Worth recording because the design note was right and the wiring did not match it: "evaluated on the single-object read" and "reached by a single-object read" are different sentences, and I had only checked the first.

**The carry-through failure, for the third time** (§157, §160, here). The edit dialog rebuilds every property from the type, so any setting it forgets to carry is silently reset by somebody editing a description. The drawing test could not catch it - it draws and saves in one session - and only a *second* edit exercises it. That is now a test in three files, and the pattern has not varied once.

Ten mutations, all red. **1165 API tests**, **193 unit** (was 179), **167 browser** (was 163).

**The row stays ◑, and honestly so.** Four of p.145's nine aggregations are still refused, and one of them is p.143's own opening example. Drawing a derived property works; deriving an average does not, and will not until instance properties carry their declared types into the index.

### 164. One property definition, several object types (this session)

Shared properties (`ontology.md` §1.2; `object-link-types` p.178-191). p.178's example is `start date` on both `Employee` and `Contractor`, so that the metadata can be updated "in one place instead of on each object type" - and that sentence is the entire design constraint, because the obvious implementation satisfies half of it.

**A copy taken at attach time would pass every test that reads back what it wrote.** So the reference is a foreign key and the inherited fields are resolved when the object type is *read*, and the test that matters attaches two object types, edits the shared property once, and asks both. `resolve()` runs in both directions - on the way out so an edit shows through immediately, and on the way in so what gets stored is what was resolved - because two functions would be two chances to inherit a different set of fields.

**Attaching adopts; editing an attached property refuses.** p.187 and p.188 are two different moments and this is the line between them. Choosing a shared property *is* choosing its metadata, so a fresh attach takes the inherited fields whatever the request said - otherwise a client would have to read the shared property back and echo it just to point at it. Once attached, p.188 disables those fields, and a contradicting value is refused rather than discarded, because silently dropping somebody's edit is the failure this repo has now fixed in four other places.

**p.185 is one line of SQL and it is the one worth reading twice.** "When a shared property is deleted, all object types using this shared property will revert to regular properties" - so `ON DELETE SET NULL`, not cascade. A cascade would take two object types' properties, and their instances' values out of every application that reads them, as a side effect of tidying up an ontology. The property keeps its last inherited metadata, because the columns are written at save time as well as resolved at read time; that redundancy is also what keeps 0028's version snapshots honest, since a snapshot recording "see elsewhere" would change meaning when the shared property was later edited.

**One divergence, decided rather than inherited.** Foundry lists base type as editable on a shared property and does not say what happens to the object types using it. Cascading would retype every attached property silently, which is the precise change `type_impact` exists to make somebody acknowledge - so a base type change is refused while anything uses it, and the refusal names who is in the way. **Type classes and render hints are absent rather than stubbed**: nothing here reads a type class, and reindex tuning is not something this instance store exposes.

**A defect this unit did not introduce and should not leave unnamed:** `object_type_versions` snapshots only six fields per property, so **restoring an old version silently drops `visibility`, `value_format`, `conditional_format`, `edit_only`, `derivation` and now `shared_property_id`**. That is five already-shipped features losing their configuration to a restore, with no error. Found here, not fixed here - it is its own claim ("a restore restores the whole definition") and deserves its own tests. Next unit.

Thirteen mutations, all red - twelve in Python and one on the foreign key itself, since p.185's whole claim rests on `SET NULL` rather than on any line of code. **1187 API tests** (was 1165), 193 unit, 167 browser.

The row is ✅ for what Foundry documents this feature to be, with the two absences above named in `docs/parity/ontology.md` rather than hidden behind the mark. The **Ontology Manager surface** for it - p.180's shared property page, p.187's dropdown on a property, p.178's globe - is the next half.

### 165. The shared property page, and a cache that hid the whole point (this session)

§164's other half: p.180's page with p.181's creation modal, p.187's dropdown on a property, p.188's Detach, p.191's Usage, and p.178's globe.

**The one defect this unit found is worth more than the surface it was found in.** p.178's reason to exist is that editing a shared property updates every object type using it - and it did, on the server, and the browser showed the old metadata anyway. The object type *detail* is a separate React Query key per type (`["object-type", typeId]`), `staleTime` is 15 seconds, and the panel was only invalidating the summaries. So for fifteen seconds after the edit that was the entire point of the feature, the property editor showed what the property used to be. Nothing errored, and a reload fixed it, which is the shape of bug that survives a demo.

The test for it is the part worth copying: it **waits on the refetch** rather than asserting after it. Without the invalidation the dialog is served from cache and *no request is made at all*, so `expect_response` times out instead of racing - a check that fails for the right reason rather than a sleep that fails eventually.

**Only shared properties whose base type matches are offered** (p.181), the rule the derived-property editor follows about links. The ones that do not match are still counted in the hint, because "there are none" and "there are four and none is a date" are different situations and only one of them is somebody's mistake.

**The adoption rule is a pure module with its own tests** (`lib/shared-property.ts`), for the reason `lib/derived-property.ts` is: both ways of getting the inherited list wrong are silent. A field left out is one the server overwrites on save, so the form and the stored row simply disagree; a field added that Foundry does not share is one the server refuses on the *next* save, from a value the browser put there.

**And p.188's "disabled" is enforced twice on purpose.** The API refuses an edit to inherited metadata (§164); the row disables the two controls that could make one. Neither is redundant - the refusal is what makes the rule true, and the disabling is what stops somebody meeting it after typing.

Nine mutations, all red: five on the pure adoption rules, four on the browser claims (the globe, the two disabled controls, and the carry-through). **1187 API tests**, **200 unit** (was 193), **173 browser** (was 167).

### 166. A restore that was not one (this session)

**The defect §164 found, fixed.** `object_type_versions` recorded six fields per property. Every unit that added a seventh - visibility (§42), value formatting (§157), conditional formatting (§158), edit-only (§160), derived properties (§161) - added a column to `object_type_properties` and did not notice the snapshot. So rolling back to *any* earlier version erased all five, with no error and nothing in the history to say it had happened. §164's `shared_property_id` would have been the sixth; adding it is what made the pattern visible.

**Why nothing caught it for five units.** The failure is a *missing key*, and there is no general test for a missing key - only one per field, which is what this unit adds: seven tests, each configuring one setting, saving it away, rolling back, and asserting it returned. A suite that only covered the fields somebody had already forgotten would be a suite that missed the next one, so `required` gets a test too even though it was never lost.

The rule is now written where it can be seen: **a new column on `object_type_properties` is a new key in `_snapshot_version`**, said in that function's docstring, next to the list.

**Two references can go missing between a version and its restore, and they are treated differently.** A **shared property** that has since been deleted is *dropped* - p.185 already decided that ("all object types using this shared property will revert to regular properties"), and refusing would let a delete elsewhere permanently block a rollback here over a decision the delete had made. A **derivation** whose link types have gone is *refused*: nothing documents what a derived property becomes when its chain stops joining up, dropping it silently would put back something that is not the version, and keeping it would produce a column of blanks - which is exactly what `derived_properties.parse` exists to refuse. The asymmetry is the documentation, not a compromise.

**What cannot be fixed, and is recorded rather than papered over:** versions written before this change still hold six keys, so restoring one still clears the other six. The data was never captured.

Nine mutations, all red - including reverting the snapshot to its original six fields, which fails eight tests across two files. **1197 API tests** (was 1187), 200 unit, 173 browser.

**The sandbox rewound the checkout again mid-unit** (HEAD back at `16bed37`, `node_modules` intact, the database back at migration 0040). Third time; the recovery in the notes below worked unchanged. Nothing was lost because §164 and §165 were already merged - which is the argument for the merge-per-unit rhythm rather than a long-lived branch.

### 167. The search that could not find a shared property (this session)

`ontology-manager` p.28 lists seven kinds the header search covers. Four existed; §164 built the fifth and did not add it here, which §164 recorded as a gap rather than leaving the parity row's old sentence ("there is nothing to search") standing as a lie. This closes it.

**Worth doing before anything larger, for a reason specific to what a shared property is.** It is the thing somebody looks for by name *before* creating a second one that means the same. A search that could not find one was actively helping the ontology grow duplicates - the opposite of what the feature exists for.

**The one modelling decision: a shared property has no object type, and the hit says so rather than inventing one.** Every other kind answers "where does this live" with an owner - "status on Ticket" - and the search result carried `object_type_id` as a required field. A shared property belongs to no object type by definition (p.178), so its hit carries `null` and a **usage count** instead: "used by 3 properties" is the closest true answer, and it is the fact somebody deciding whether to open it actually wants. A borrowed owner would have sent whoever clicked it to a type with nothing to do with their query.

That made `object_type_id` nullable, which is the sort of change that quietly becomes null everywhere - so there is a test asserting the other four kinds still name their owner.

**A hit needs somewhere to go.** The search hands a shared property id up to the page, which passes it into the panel, which opens the editor. Resolved during render rather than in an effect, because the id can arrive before the list does and an effect keyed on the id alone would miss the case where the list is what arrives second.

Six mutations, all red: three on the server (not searching them at all - the original gap - a constant usage count, and a faked owner) and three on the browser (a hit that opens nothing, a missing count, a panel that ignores the id).

**One test fixed rather than papered over.** §165's delete test asserted `not_to_contain_text` on the shared properties table. That table *unmounts* when the last shared property goes, in favour of the empty state - so the assertion was failing for the wrong reason once the ordering changed. It now asserts the row is gone, which is the claim, and holds whether the table is empty or absent.

**1200 API tests** (was 1197), 200 unit, **174 browser** (was 173).

**One flake seen once and not reproduced, recorded rather than tidied away.** The first full browser run came back 172/2, both failures `to_contain_text` timeouts on the search results panel in `test_ontology_search.py`; the second run was 174/0, and both pass in isolation. The rendering path they exercise is unchanged by this unit - for a `property` hit the new ternary falls through to exactly the same markup - so the likely cause is timing: `search()` now makes one more query per request, and under a full-suite load that can push a response past Playwright's 5s default. Not fixed by raising the timeout, because a timeout raised to hide slowness is a check made harder to fail. If it recurs it should be visible.


### 168. Value types: a rule you can reuse (this session)

Value types (`ontology.md` §1.2; `object-link-types` p.222-234). p.222's own example is an `email` value type whose regex means every property using it "is explicitly understood to contain an email address".

**The constraint-sibling of shared properties, and the pairing is the design.** §164 shares *metadata* - what a property is called and how it is shown. This shares a *rule* - what a value is allowed to be. They attach independently and compose, which is why p.227 names both places one can go, and why a property inherits its shared property's value type when it has not chosen one of its own.

**p.229 splits a value type in half and the schema follows the split exactly.** Name and description are editable; base type and constraint are immutable, and changing a constraint appends a version. Two tables rather than one with an `updated_at`, because "what was this checking last March" is precisely the question somebody asks after finding data that was rejected. The current version is the highest-numbered one rather than a pointer column - p.230 makes propagation automatic, so there is one answer to "what is being enforced" and no second place for it to disagree.

**The deliberate divergence is enforcement.** p.227: a property with failing values makes the object type "fail to index" - which takes a whole type off every screen because one row is wrong. §154 already chose the other way for required properties, following p.116's own split, so this follows it: **the sync reports and the action refuses**. The report carries a count *and an example*, because "412 rows failed `email`" sends somebody to read 412 rows and "412 rows failed, e.g. 'n/a' does not match ...@..." tells them what their pipeline is putting there.

**Twenty-seven mutations, all red** - sixteen on the pure constraint module, eleven on the wiring. **One survived first and found a real bug**: the temporal tests used only zero-padded dates, so text and date ordering agreed and a text-comparing implementation passed them. Fixing the test exposed that the comparator *dropped* a timestamp's offset rather than converting it, making `2026-01-01T05:00+06:00` sort as 05:00 when the instant it names is 23:00 the day before. Two readings that both compare cleanly, only one right, and nothing raising either way - the exact shape of defect mutation testing exists to catch.

**1256 API tests** (was 1200).

The row is ◑: the constraints are enforced, the **Ontology Manager surface** is the remaining half, and p.233's `rid`, array and struct constraints are absent for reasons named in the parity doc rather than hidden.

### 169. The value type page, and a rule that says what it bounds (this session)

§168's other half: p.224's create form, p.227's dropdown on a property, p.229's version history, and the constraint editor that produces the rule.

**The constraint editor offers only what the base type can carry** (p.233 lists constraints *per* base type, not one menu mostly greyed out) - and it is the one piece worth a pure module of its own. `lib/value-type.ts` decides which kinds are offered and what a form may not save; `services/value_constraints.py` stays authoritative and enforces on every synced row. Nothing in the browser can widen what a save accepts, only stop the form proposing one that fails.

**A range says what it bounds.** For every type but `string` that is the value; for a string p.233 constrains the *length*. One word for two meanings is how somebody ends up believing they bounded the alphabet, so the label changes with the base type - and there is a browser test that fails if it stops.

**Changing a rule is a different button from changing a name**, which is p.229 rather than layout: metadata is editable and unversioned, the constraint is immutable and a change appends a version. One dialog for both would put a versioned change and an unversioned one behind the same Save and leave nobody sure which they had made. The version dialog lists the previous rules beside the new one, because that is the point of making them immutable.

**Inheritance is shown rather than hidden.** A property constrained through its shared property (p.227) shows `↑` where one that chose its own shows `•`, and the picker says which value type it is inheriting and from where. They are different states and only one of them is this property's own choice - which is also why the save sends `value_type_id` and never `effective_value_type_id`.

**The carry-through failure, for the sixth time** (§157, §160, §163, §164, §165, and here). The edit dialog rebuilds every property from the type, so a setting it forgets to carry is silently reset by somebody editing a description. The test that catches it needs a *second* edit; it is now in six files and the pattern has not varied once.

Eighteen mutations, all red: twelve on the pure module, six on the browser claims. **218 unit tests** (was 200), **180 browser** (was 174), 1256 API.

**And the full browser run found a real regression, which is what a full run is for.** Five ontology-search tests failed with the panel still reading "Searching…" - and unlike §167's flake, this reproduced in isolation. The endpoint was taking **over two minutes**: `ontology_search` called `list_properties` **once per object type**, and one dev workspace has 226 of them. That N+1 has been there since §146 and stayed survivable right up until §168 put a join through `value_type_versions` inside the N - a table whose row-level-security policy subqueries `value_types`, which has a policy of its own.

Fixed by giving search a single `list_properties_for_workspace` query that resolves shared metadata and deliberately **not** the value type: search matches on api_name, display_name and description, so the expensive half of `list_properties` was the half it never wanted. **Over 120s to 2.3s** on the same workspace.

Two things worth keeping. **A loop that issues a query is a loop whose cost is somebody else's to change** - the N+1 was not a bug until a later unit made the N expensive, and nothing warned. And **§167's two-test flake was probably this, early**: same file, same symptom, and the reading at the time ("one more query per request, under full-suite load") was directionally right and an underestimate. It was recorded rather than tidied away, which is why it was recognisable the second time.


### 170. Statuses, and the refusals that make one mean something (this session)

Ontology resource statuses (`ontology.md` §1.3; `object-link-types` p.253-259). All five of p.254's values on object types, properties and link types.

**A status column with nothing behind it would be `required` before §154** - displayed, accepted, enforcing nothing. p.253 says statuses exist so somebody editing the ontology knows what applications rely on, and knowing is not the same as being stopped. So: an `active` or `promoted` resource cannot be deleted (p.256), and the refusal names the way through, because "cannot delete" without "mark it deprecated first" is a dead end rather than a step.

**p.257's table is a cap, not a warning.** Foundry describes the invalid state as an error somebody *receives* - "an experimental object type cannot have an active link type". Storing the capped value instead makes that state unreachable: a link type is written at the lowest of its own declaration, its two object types, and the properties it joins on. Nothing to troubleshoot.

**Propagation lowers and never raises**, and p.258 is explicit that it should: applying `active` to every property is "the option to also apply", not a consequence. A field still being built on an otherwise finished type stays experimental rather than being declared production-ready by somebody finishing the type around it.

**The compatibility rule was the one that could have gone wrong quietly.** The type editor sends the whole definition on every save. `status` defaults to *unchanged* rather than to `experimental` - if it had defaulted to the documented default for a new resource, every save from a client predating statuses would silently demote a promoted object type, and demote its properties with it by p.256's own propagation. There is a test named after that.

**Twenty-three mutations, and four of them were worth the run.**

*One equivalent mutant, resolved by deleting code rather than adding a test.* A `CONTAGIOUS` list gated which statuses propagate - and `weakest` already refuses to raise, so adding `active` to that list changed nothing. Two spellings of one rule, and the redundant one was the one that could drift.

*Three survivors that were real test gaps*, and one needed a case I had not thought to construct. p.257 caps a link by its object types *and* by its join properties, and the two cannot be pulled apart from above - demoting a type demotes its properties. Isolating the object-type half needs a link joining on **`$primary_key`**: a sentinel rather than a property row (db 0027), so there is no far-side property status, leaving the type's own status as the only thing that can hold the link back.

**1303 API tests** (was 1256).

**Mandatory control properties are declined rather than deferred** (p.121-126), and recorded in the parity doc. They are row-level access controls enforced by markings and **restricted views** - p.124 says so directly - and this platform has neither. Building the flag without the mechanism would be a control that looks like access control and enforces nothing, which is worse than its absence because somebody would rely on it. Same reasoning as decision 0009's refusal of the media reference type.



**A second source gap, found and recorded rather than worked around.** I went looking for Interfaces first - it is the bigger stage-3 mechanism and shared properties are its foundation - and `docs/pal/` **has no Interfaces chapter**. `foundry_ontology.pdf` p.54 links back to "Interfaces / Metadata reference" and `foundry_functions.pdf` p.427 forward to "Interfaces / Overview"; neither page is in the export. What survives is the definition, the design guidance, and the rules a property must satisfy to implement one - enough to build *from*, not enough to build *to*, since the create/edit/metadata reference is the part that would decide the schema. The row is now marked `[?]` beside the Object Explorer gap the parity README already names, and value types were chosen instead because they have thirteen fully-sourced pages.



**What is left, and it is the half that makes this usable:** evaluating a derived property when an object is read, and an editor for it. The evaluation composes with what is already built - §155's `via` traversal expresses the chain, `aggregate_object_set` answers `count` and `count_distinct`, and a collection is the far set read with p.146's limit - so the shape is known; it is simply not written.


### 171. Telling somebody what a status change is about to do (this session)

The Ontology Manager surface for §170 (`ontology.md` §1.3; `object-link-types` p.253-259): p.256's dropdown, p.253's badge in the listing, p.254's deprecation note, and a Delete button that explains its own refusal.

**The one thing that needed a browser rather than a test client is the warning.** p.256's propagation is invisible until it has already run - demoting an object type demotes every property on it - so `propagationWarning` names the properties that are about to move, in the form, while the choice is still a choice. A response that reports the demotion afterwards is somebody discovering the change by re-reading a page they thought they understood.

**`experimental` draws no badge.** It is p.256's default, so badging it would put a label on every row of a new ontology and say nothing by being everywhere. That is a decision a test has to hold, because "shows nothing" and "is broken" look the same.

**Delete says why in the server's own words.** `deleteBlockedReason` returns the same sentence `check_deletable` raises, including the way through - "mark it deprecated or experimental first" - so somebody who reads the tooltip and somebody who reaches the refusal are not told two different things. The button is disabled rather than absent: a control that vanishes teaches nothing.

**Eight browser mutations, and two survived the first run** - both of them the same failure this repo keeps finding.

*The carry-through failure, for the seventh time* (§157, §160, §163, §164, §165, §169, and here). The edit dialog rebuilds every property from the type, so a setting it forgets to carry is silently reset by somebody changing a display name. There is no per-property status control on this screen, which is exactly what makes it dangerous: the value is one nothing on the page can see. The test sets a property to `deprecated` through the API, does an unrelated edit in the browser, and reads it back through the API.

*And a save that had to be asserted, not just observed.* Moving away from `deprecated` clears p.254's note. Hiding the fields while keeping the values would look identical on screen and then be refused by the server - a 422 nobody sees, because the dialog closes either way. §160's lesson, in a new place: the test waits on the PATCH and checks it was accepted.

**232 web unit tests** (was 218), **1303 API tests**, browser suite green.


### 172. Object type groups, and a rule about not looking (this session)

Groups (`ontology.md` §1.3; `object-link-types` p.261-263), server side. Create, rename, delete; both of p.261's directions for editing membership; p.262's three appearances - ontology search, a column on the object type listing, and a filter on it.

**Most of what a feature usually needs is absent here, and that is the finding rather than a shortcut.** A group carries no schema. Grouping an object type does not change it, deleting a group deletes only the classification, and nothing downstream was told anything by the grouping - so there is no validation about what may be grouped with what, and no refusal to delete one in use. Writing those tests would have been writing tests for nothing.

**The one rule with teeth is a rule about not looking.** p.263 records Foundry *changing* it: a group used to be non-discoverable when all its members were, and now "all groups will now be discoverable to any user that can view the ontology … to increase clarity and transparency in governance". So a group's visibility is a fact about the group, never derived from its members. That is one RLS policy on `workspace_id` with no join - and the natural implementation, listing groups by joining the membership table, silently reimplements the behaviour p.263 describes having removed. Its cheapest visible case is a group with no members, which is the state every group is in for the few seconds after somebody creates one: that version lets you create a group and then shows you nothing.

It also happens to be the shape this repo's own scar tissue argues for. **RLS policies that read another RLS-protected table** are a recorded bug class here (0008, 0009, 0015), so the membership row carries a denormalised `workspace_id` rather than reaching through to the group - pinned by composite foreign keys that make it impossible to get wrong and, as a side effect, **spell p.192's boundary in SQL**: a group cannot contain an object type from another workspace.

**Twenty-nine mutations over two rounds. The first fifteen all died, which was the reason to write the second fourteen** - a clean sheet is evidence about the mutants, not about the tests. Six of the second round survived, and every one was a real gap:

*Five were the same gap wearing different hats: the suite had one workspace.* `get_group`, `_check_types_exist` and the duplicate-name check could each drop their `workspace_id` clause and nothing noticed. The shared `Fixture` has a second *organisation*, which the permission middleware rejects before a query runs - so it proves the middleware and nothing about the SQL underneath it. What was missing is a second workspace **the same person can legitimately see**, where the path names one ontology and the id belongs to another and the only thing in the way is the query itself.

*One survived because a second check upstream covered it.* The delete route reads the group before deleting it, for the audit record's "how many object types stopped being classified" - so removing `delete_group`'s own existence check changes nothing observable through HTTP. Not an equivalent mutant, unlike §170's: the guard belongs to the service, and the route's read is there for metadata. The fix is one test that goes in through the service, which is also the first in this file to do so.

**A second finding, outside the unit.** `verify_schema.py`'s "no unexplained extra tables" check had drifted again - **seven tables** between 0040 and 0054, found while adding 0056's two. §88 fixed exactly this list and it went stale for exactly the reason it went stale the first time: the file needs a *fresh* database (its own `audit_log` fixture cannot be cleaned up, so a second run dies on a duplicate slug), which is the one thing a suite against the shared dev database cannot give it. Fixed and the reason recorded in the file, because the next person will be adding several rows at once too.

**1332 API tests** (was 1303).


### 173. The groups menu, and a write that must not happen (this session)

The Ontology Manager surface for §172 (`ontology.md` §1.3; `object-link-types` p.261-263): p.261's groups menu, p.261's "Edit groups" on the object type, and p.262's three appearances - chips on each row, a filter above the table, and the group kind in search.

**An empty group is drawn like any other, and it says "0 object types" rather than going quiet.** That is p.263's rule reaching the screen. Every group is empty for the seconds after somebody creates one, so a panel that hid it - or a count that rendered zero as blank - would fail on the very first use, and fail as an *absence* rather than an error.

**The interesting decision is a write that must not happen.** Membership is its own resource with its own verb (§172 made it one deliberately, so an object type's PATCH cannot carry it). But the edit dialog holds both, so it does two writes - and one that PUT the groups on every save would reintroduce the carry-through failure a layer up: open the dialog, a colleague files the type under a group, change a description, save, and their grouping is gone. **This is the eighth time this repo has met that shape** (§157, §160, §163, §164, §165, §169, §171), and the first answered by *not carrying the value* rather than by carrying it more carefully: the dialog sends nothing when nothing changed. `sameSelection` is therefore load-bearing and silent when wrong in either direction - always-true drops edits, always-false clobbers - so it is a pure function in `lib/object-type-groups.ts` with its own tests, not an inline `JSON.stringify`.

**A cache key that had to be different.** The page's object type query is now keyed by the filter, because six other components cache the *unfiltered* list under `["object-types", workspaceId]` - the group picker inside this very page most of all, since a picker offering only the group you were already filtered to could never move a type out of it. React Query matches by prefix, so the existing invalidations still reach it.

**An empty filter result is not an empty ontology.** Falling through to "The ontology starts here" because a group holds nothing would tell somebody with two hundred object types that they have none, and offer a Define button as the way out of a filter. Its own empty state, with a way back.

**Fifteen browser mutations, and the carry-through test needed two separate fixes before it could fail.** Both were races, at opposite ends of the same test, and each on its own left a green check that proved nothing.

*It raced its own setup.* The test attaches the group through the API *after* opening the dialog - that is the whole point, since the bug only exists when somebody changes the membership while the dialog is open. But the dialog's groups query was still in flight when the API call landed, so its answer already contained the colleague's group and even a dialog that PUT on every save sent the right value. The fix is a deterministic wait for evidence the read finished *and finished without the group*: an unticked checkbox for it.

*And then it raced the write it was checking.* The dialog issues two requests; the groups PUT is awaited **after** the PATCH resolves. A read taken on the PATCH's response therefore happens before a wrongly-issued PUT lands, and sees the membership still intact. `expect_response` had been the right tool in §171 and is the wrong one here, for a reason worth stating: **it waits for one request, and this dialog makes two.** The signal that there is nothing more coming is the dialog *closing*, since `onSuccess` runs only once both writes have finished.

The general lesson from both halves: a browser check on a multi-write save has to anchor on the completion of the whole save, not on any single response - and any setup that makes a client stale must first prove the client is past its read.

Two more survivors were ordinary gaps: the members dialog was never reopened, so "opens with nothing ticked" - which under a whole-membership PUT is the same bug as "empties the group" - went unseen; and the search hit was checked for being visible but never clicked, so a group hit that opened nothing looked fine. The fourth was **a leftover-state artifact**: this module reuses a workspace, so a group with members left by an earlier run kept the listing on screen when the mutant would otherwise have emptied it. The claim is about a workspace whose only group is a new empty one, so the test now builds that workspace rather than hoping for it.

**246 web unit tests** (was 232).


### 174. Action type statuses, and a cascade that walked around p.256 (this session)

The last fully-sourced row on this stage (`ontology.md` §1.3). p.253 names actions among the kinds that carry a status - "every object type, property, link type, **action**, or interface in the Ontology has a status" - and §170 added the column and then enforced nothing with it. All four values (p.255 excludes `promoted` from action types by name), p.256's delete refusal, p.254's note, and §170's "omitted means unchanged" on the one endpoint that writes a status.

**The interesting part is not the column; it is the hole the column made visible.** `action_types.object_type_id` is `ON DELETE CASCADE` (db 0013), so deleting an object type deletes its actions whatever their status. p.256 says an `active` resource cannot be deleted - and a cascade deleted one without ever demoting it, with nothing anywhere saying an action somebody relied on had gone. Deleting an object type now refuses while an `active` action hangs off it, naming every one in the way.

**Link types were already safe from the identical hole, and for a reason that does not transfer.** §170 caps a link at the weakest status of its two object types (p.257), so an `active` link on an experimental object type is a state the ontology cannot hold. Actions are *not* capped, because p.257's table is about link types and its own explanation is specific to them - a foreign key may be in production "while the link type and its backing datasource are still in development". Extending the cap to actions would have been inventing a rule and would silently demote actions nobody asked to demote. **So the decision not to invent a rule is exactly what created the need for the refusal**, and both halves have tests named after them.

**Seventeen mutations, one survivor, and it was the cheapest kind of gap**: nothing asserted the status *badge* was drawn on the row - only that the value was stored. p.253 says statuses exist so that somebody reading the ontology knows what is relied on, which is a claim about the listing rather than about the database.

**A rule already satisfied, worth recording rather than building.** p.256 also says "the API name of an active resource cannot be changed. Changing an API name is only possible for those marked as `experimental`." Every api_name in this platform is immutable on every resource - object types, shared properties, value types, groups, actions - which is strictly stronger than p.256 asks, so there is nothing to add.

**1345 API tests** (was 1332).


### 175. Who may promote, and a role this platform already had (this session)

p.255's other two sentences, the ones §170 read past while taking its `promoted`-scope rule.

**"There is no ontology-level role here" was wrong, and I had said it repeatedly.** `workspace_role` is an enum of admin/editor/viewer (db 0001), ranked in `permissions.py`, and a workspace *is* this platform's ontology (db 0003) - the same equivalence shared properties, value types and groups all lean on. So p.255's "Ontology Owner role on the ontology level" is a **floor on an existing role**, not a permission system that needed inventing.

**And the source says not to invent one.** Foundry's Ontology-roles chapter (`ontology-manager` p.43) opens by marking itself legacy: "no longer the most up-to-date method for ontology resource permissioning. Ontology resources can now be permissioned using the **Compass filesystem**" - their project/folder ACLs, which is structurally what this platform's workspace and project roles already are. A per-resource `ontology_resource_roles` table would have been replicating the model Palantir is migrating *off*, on the strength of a chapter that says so, while the platform already had the shape they moved *to*. The divergence worth naming: our admin is workspace-wide where theirs is per resource - stricter, not looser.

**The gate is on the transition, not the value, and that is the whole design.** The type editor sends the whole definition on every save, so an editor pressing Save on an already-promoted type sends `promoted` without asking for anything. Refusing that would lock every editor out of every promoted type - p.255's protection turned into a rule that makes the most important object types uneditable by the people who build them. The same trap has a second face in the browser: a dropdown that hid `promoted` from an editor would leave the select with no entry matching its own value, which renders blank and demotes the type on the next save. Both have tests named after them.

**p.255's visibility sentence, which needed a column.** "Setting an object type's status to `promoted` will automatically set its visibility to `prominent`." An object type had no visibility of its own - `property_visibility` had existed since 0003 but only ever on properties - so db 0057 adds one, reusing the enum rather than declaring a second holding the same three values. It **raises and never lowers**: p.255 says what promoting does and nothing about demoting undoing it, so a type somebody deliberately made prominent stays that way.

**Seventeen mutations, all killed on the first run** (12 server, 5 UI) - and the browser file is the first here to sign in as *two* people at once, because an option hidden from the wrong person is a feature and an option hidden from the right person is the feature switched off, and one session cannot tell those apart.

**What is deliberately not built** is p.255's second sentence: "Other users must submit a proposal for review and approval by an Ontology Owner." That needs a review surface for ontology changes. §52's proposals and §53's blocking checks are the right machinery and are built around repository change sets rather than ontology edits, so wiring the two together is a feature and plausibly its own stage - not something this refusal should pretend to be.

**1359 API tests** (was 1345), **251 web unit tests** (was 246).


### 176. A cap that was only a validation (this session)

**§170 shipped a defect and this repo's own parity note asserted the opposite.** Found while reading p.258 for the next unit, by asking a question the previous four units had not: p.257 says a link type "**will automatically be changed**" when one of its object types is - that is an *event*, and §170 implemented a *validation*.

The cap was computed in `set_link_join`, so it held for every link somebody edited and for no other. Demoting an object type left an `active` link hanging off an `experimental` one: precisely the state p.257's troubleshooting section says cannot exist (`ConflictBetweenLinkTypeStatusAndObjectTypeStatus`), and precisely what `docs/parity/ontology.md` claimed was "unreachable rather than detected". **It was reachable in two API calls**, and a three-line probe showed it in about a minute once the question was asked the right way round.

`recap_link_types` now re-applies p.257 to every link touching a type whose status or join columns just changed, run *after* the property rows are written because a link is capped by its join columns too and propagation may just have lowered them.

**It lowers only, and the stored status is the declaration.** A link's row already holds the capped value rather than what was asked for, so re-capping from it can only go down - which is p.257's own asymmetry, stated for the neighbouring case: a foreign key may be in production "while the link type and its backing datasource are still in development". A dependency recovering does not restore the link, because the link's own readiness is not a fact its object types know.

**Seven mutations. One survivor and one skip, both the same shape:** a rule that names two symmetric things - `from` and `to` - and a test exercising only one of them. The far join column had no test, and the mutant that stopped reading it passed. Worth generalising: whenever a rule reads both ends of a relationship, one test per end, because the code that reads half of it looks exactly like the code that reads all of it.

**The lesson about the parity doc is the bigger one.** A row saying a state is unreachable is a claim, and claims in that file are load-bearing - four later units read it and built on top. It is now corrected in place rather than quietly patched.

**1364 API tests** (was 1359).


### 177. Bulk status editing, and a bulk edit as a way round the rules (this session)

p.258's three sentences, which finish `ontology.md` §1.3 apart from p.255's proposal path.

**A bulk edit is a way round every rule it forgets**, so the interesting work was not the loop. `set_type_statuses` runs the same pure functions the single-type path does - p.255's promotion role, p.255's visibility, p.256's propagation into properties, §176's link re-cap, and a version per type - and most of the tests are one per rule, asserting the new path did not become a back door. Mutation testing was the right tool for exactly this: every "bulk skips rule X" mutant is a plausible thing to have written.

**p.258's option is an option, and that is the whole of §170's asymmetry.** "When changing an object type from `experimental` to `active`, there is the option to also apply the `active` status to all properties." A parameter rather than a consequence, unticked by default - and the test that matters is the one that *does not* tick it, because a version that always raised would pass every test that does.

**Bulk property statuses are capped at the object type's own status**, which is the decision in this unit. p.256's propagation runs on every save of the type, so a property raised above it would be silently demoted by the next unrelated edit - a change somebody made, gone later, with nothing to say why. That is the carry-through failure in a new place, and capping refuses to create the state rather than letting it exist until something tidies it away.

**All or nothing.** One refusal fails the whole request: a half-applied bulk edit leaves somebody to work out which half, and the caller chose those types together.

**A comment that claimed something false, removed rather than kept.** The bulk route's first docstring said its declaration order mattered because FastAPI would otherwise read `bulk-status` as a `{type_id}`. Checking rather than asserting showed both `{type_id}` POST routes have extra path segments, so no collision is possible. §176's lesson one level down: a confident comment is a claim, and an unchecked one is worse than none.

**Twenty-two mutations, all killed** (15 server, 7 UI).

**1381 API tests** (was 1364).


### 178. Variables-first, and a refactor deliberately left half done (this session)

The Widget setup tab, organised the way p.65 describes it (`workshop.md` §2).

**p.65's order is the order somebody has to think in.** The Object Set that populates the widget, then the options that set makes answerable, then what the widget produces for others to read. The panel was a flat list of whatever each widget's author wrote first, which puts three different kinds of decision on the same footing.

**The only *behaviour* in the row is p.66's progressive disclosure**, and it is the reason this is more than a layout change: "This configuration option is revealed in more detail once the Object Set is populated". Wrong in either direction is silent - revealed too early is a panel of empty dropdowns asking questions nothing can answer, revealed too late is a widget that looks unfinishable. So `configReady` is pure and tested, and the panel says *which* input it is waiting on rather than "configure this widget first", because a widget with three inputs would otherwise leave somebody guessing.

**Deliberately not finished, and that is the notable decision.** Eighteen of the twenty-one settings panels bind variables. Converting all of them is mechanical but is roughly 4,700 lines of restructuring in one file, which is a change nobody could review and a large blast radius for a presentational refactor. Three are converted - Filter List (p.65-67's own worked example), Search, Time Series - and the parity row says exactly which, and that the rest still render flat. A half-converted panel set is a real cost, and naming it is better than a row that claims more than it did.

**Eleven mutations, and two "survivors" that were the script's fault rather than the tests'.** `configReady` lives in a pure module covered by vitest; the mutation script ran only the browser file, which exercises one required input with a null value - so "an unset select counts as bound" and "one bound input reveals everything" both passed. The tests that kill them already existed. **A mutation run measures the suite you point it at**, and pointing it at one layer of a two-layer feature reports gaps that are not there - which is the same error as trusting a green suite, one level up.

**256 web unit tests** (was 251).

---


### 179. Four more panels, and the rule the first three did not need (this session)

Continuing §178's conversion rather than leaving it half done, because a half-converted panel set was the cost §178 named and leaving it while starting something new is what would have made that decision a bad one. **Object table, Card list, Pivot table, Metric card** - seven of eighteen now. (The denominator is corrected to fifteen in §181; six panels bind no variable at all.)

**It was not the mechanical chunk it looked like.** Every object-set widget is populated *either* by a bound object set variable *or* by an object type picked directly, and `configReady` was all-of. Waiting for both would wait for something nobody is meant to supply: the configuration would never appear and the widget would look permanently unfinishable. So `requires` now takes a **choice** - a nested array meaning "any one of these" - and the waiting message reads as a choice too, because naming only the first would send somebody to fill in a field they do not need and leave the one they do.

§178 converted three widgets that happen to have a single input. The rule they did not need is exactly the rule the fourth one is built on, which is a decent argument for converting a *family* rather than the three easiest.

**Two panels earned their reordering rather than just receiving it.** The Pivot table is the one that shows why there are three sections and not two - its drill-down variable is p.65's "the data that is then produced and output by the widget". The Metric card is the one where p.65's order does real work: its **label describes a number the widget cannot produce until a set is chosen**, so asking for the label first asks somebody to name a thing they have not picked. That reordering is asserted as *containment* rather than position - the claim is that the set is an input and the label is configuration, not that one is drawn above the other.

**An equivalent mutant, resolved by deleting code.** The empty-alternative guard read `requirement.length > 0 && requirement.some(...)` - and `some` on an empty array is already false, so the guard changed no behaviour at all. §170's pattern exactly: two spellings of one rule, and the redundant one is the one that can drift. The test that pins the behaviour stays; the code that duplicated it is gone.

**The mutation script runs both layers this time**, which is §178's own lesson applied rather than repeated: that unit reported two survivors that existing vitest tests already killed, because the script only ran the browser file.

**270 web unit tests** (was 256).

---

### 180. The three widgets that are not populated by an object set (this session)

**Parameter control, Dataset table, Action form** — ten of eighteen. (Corrected to fifteen in §181.) §179 converted a *family*: four widgets that all read an object set, all shaped the same way. These three are the argument for not stopping there, because each one bends p.65's shape somewhere different and a rule fitted to the object-set family gets each of them wrong.

**The Parameter control has no input at all.** It produces the value everything else reads — its parameter name is what every table and chart references — so the panel opens on Outputs, and its configuration waits for nothing. That is not an omission: the widget has an *optional* dataset the dropdown's options can come from, and a `requires` naming it would make configuration wait for something nobody is obliged to supply, leaving the widget permanently unconfigurable. §179's choice-rule does not help here; what is needed is no requirement at all. The mutant that adds one is killed by the browser suite, which is the only place "the panel is stuck" is visible.

**The Action form's two dropdowns look alike and are not.** Action type and "Edits" are both `<select>`s over a list, drawn one after the other in the original flat panel. The action type is the input — until one is chosen there is no form, so *which variable does it edit* is a question about nothing. But leaving the second unset is a **real answer** ("whatever the viewer picks from a list"), not an unfinished one, so it is configuration rather than a second input. Requiring both would mean the configuration never appears for the perfectly ordinary form that lets the viewer choose. Two mutants cover the two ways to get this wrong — requiring the subject variable, and calling Edits an input — and both die.

**The Dataset table is the only straightforward one**: p.66's disclosure with a dataset in the object set's place, since the filter-column picker reads the dataset's schema. Binding the dataset also clears the column beside it, which is the same reason the disclosure exists.

**Map and Chart are not a wrap, and that is why they are not here.** Both have a `source` toggle — `"objects"` vs `"dataset"` for the Map, three alternatives for the Chart — with inputs and configuration *interleaved inside each branch*, and the Chart's drill-down output sitting between two of them. Converting them means restructuring the branches so each one contributes to three sections, not adding a wrapper around a flat list. Recorded rather than attempted: they are a unit of their own, and doing them badly inside a mechanical conversion is how a "mechanical" change stops being reviewable.

Seven mutations, all red, across **both layers** — §179's lesson kept rather than re-learned. **219 browser tests** (was 216); web unit unchanged at 270, since the change is entirely in the panels rather than in the pure module they share.

---

### 181. The last three panels, and a denominator that was wrong the whole time (this session)

**Embedded module, Loop, Button** — and with them the conversion is finished except for Map and Chart.

**The count was wrong from §178 onwards.** "Eighteen variable-bearing panels" was never checked; it was twenty-one settings panels minus a guess. Classifying them properly gives **fifteen**: Container, Text, Section, Header, Page and **Overlay** have no variable-bound control at all. Overlay is the one that matters, because it had been sitting on the to-convert list for three units — it has a Title and a "Shows as", both pure display options, so there is nothing for p.65's three sections to separate. §178's own rule already answers it: a widget with nothing to output draws no Outputs heading, because an empty heading promises a control that does not exist. A lone "Configuration" heading over the only content in the panel is that same heading, one section over. So Overlay is declined rather than pending, and the remaining work is two panels, not eight.

**The Embedded module is the one Foundry documents the disclosure for.** p.127: "Once a child module is selected, the module interface for the child module will be shown in the widget **configuration panel**" — which settles both halves at once, the *when* and the *which section*. The mapping already disappeared before a module was chosen, by rendering `null`; that is the silent version of p.66's rule, and the difference between the two is a person wondering whether the widget is broken.

**The Loop is the first widget that needs `requires` in its original all-of form.** §179 taught it a *choice* for the Object table — a set **or** a type — and this is the mirror case: a set to loop through **and** a module to repeat, where neither alone leaves anything to configure. It turned up a real gap in the pure module's tests: the existing all-of test asserted only that both names appeared in the message, and "a set **or** a module" contains both names too. The mutant that swaps the conjunction was the one mutant of the seven killed by the **unit** layer rather than the browser — the clearest argument yet for running both.

Two dead conditions fell out of the same change. `{moduleId && (...)}` guarded the item picker, and the configuration section now only renders once `requires` is satisfied, of which a module is half — so the guard could no longer be false. §170's precedent again: two spellings of one rule, delete the redundant one.

**The Button is p.65 read literally.** The sentence is "the input and output variables of a widget … **as well as** any additional configuration and display options" — so label, icon and style are display options by the page's own words, and the variable the button reads to decide whether it is pressable is an input, and goes first. No `requires`: "Always" is a real answer, the Parameter control's reason from §180.

Seven mutations, all red, across both layers. **222 browser tests** (was 219), **271 web unit** (was 270).

---

### 182. The restructure, and four controls that could never be enabled (this session)

**Map and Chart** — the two panels §180 recorded as "not a wrap", and the Widget setup row is now ✅ across **all fifteen** variable-bearing panels.

**The Map is the first panel whose `requires` is not a literal.** Every conversion before it had one fixed set of inputs; a Map has two, chosen by a `Points from` toggle sitting above them, so the rule is computed from the toggle. A fixed rule is unrecoverable in one of the two branches: a map pointed at a dataset would sit waiting for an object type nobody is going to pick. The toggle itself went into Inputs rather than above the sections — it is not a variable, but it asks the first half of p.65's "what populates this widget".

**The Chart is where p.280's three "Data input" options land as one choice.** §179 built the alternative for the Object table's two; this is the same rule with a third arm. Its drill-down variable became the Outputs section, present only when there is a set to narrow — a dataset-backed or series-backed chart has no set, so a clause would have nothing to mean.

**Four controls were disabled with their options already in the DOM.** Found by reading the panels closely enough to restructure them, and confirmed in a browser before a line was changed:

* the Map's `Label property` and `Filter property` guarded on `objectTypeId`, which a map bound to an **object set variable** never has, because the set names its own type. `Location property`, sitting between them and reading the same loaded type, guarded on `effectiveTypeId` and worked. Three siblings, one query, two asking the wrong question — and it is the *inconsistency* that proves it was a mistake rather than a decision;
* the Chart's `Category`, `Of column` and `Filter column` guarded on `dataset` while being populated from `columns`, which is computed a few lines above to be *either* the set's properties or the dataset's columns.

The generalisable form: **guard a control on the options it offers, not on one of the several ways those options can arrive.** Both fixes are that sentence.

**A message that had only ever been exercised at two.** The Chart's three-way choice came out as "a time series set **or** an object set **or** a dataset" — the choice arm joined with a plain `" or "`, which reads fine at two and badly at three, while the all-of arm three lines below had the comma form all along. One `joined(names, conjunction)` helper now serves both, so they cannot drift apart again. This was caught by a browser assertion failing on the exact string rather than on containment, which is the same lesson §181 recorded one unit earlier.

Nine mutations, all red; two of them died at the **unit** layer. **226 browser tests** (was 222), **273 web unit** (was 271).

---

### 183. The rest of p.193's sentence (this session)

§132 built the Changelog panel and stopped one sentence short, naming what it had skipped rather than implying it was done: "You can inspect **JSON diffs** to see the exact modifications and review a **visual hierarchy** to understand how changes relate to nested components." Both are here now, and the row is ✅.

**The JSON diff is leaf by leaf, not line by line.** "JSON diffs" reads like two pretty-printed blocks with a gutter, and that is the wrong tool for this job: a key inserted earlier in an object shifts every line beneath it, and re-indenting a nested object rewrites lines whose values are identical, so a line diff reports work nobody did. `fieldChanges` walks both values and names the smallest thing that actually differs — `props.columns[1]`, `text`, `set.filters[0].op` — which is the modification itself and is the same answer however the documents happen to be serialised. A change of *shape* (an object replaced by a string) is one change at that path rather than a removal per leaf followed by an addition, because "this became a string" is what happened.

**A move reports its position.** Its props are identical by definition — that is what makes it a move rather than a change — so a detail computed from props would be empty, and an empty detail on an entry that clearly changed reads as a panel that failed to load one. `changeDetail` compares the parent and sibling index instead, which is the only thing that happened to it.

**The hierarchy is the layout tree, pruned to branches that contain a change.** Both unpruned extremes are wrong in the same way: the full tree is the whole module, and a changelog that redraws the module buries the four things that moved; a flat list of only the changed nodes loses the nesting p.193 is asking about. An ancestor with no change of its own is drawn without a chip — labelling it would claim a change nobody made. And deleted nodes are grafted back at the position they held in the older version, since building from the newest document alone would drop the one kind of change that has no node left to hang off, which is also the kind somebody most wants placed.

**Two survivors, both real gaps rather than equivalent mutants.** Walking arrays to `Math.min` of the two lengths passed every array test, because they all compared arrays of equal length — and a column added to a table is the most ordinary edit this panel has to describe. And the check that an unchanged ancestor carries no chip was written as `data-change="context"`, an attribute the mutant did not touch; scoping a chip count to the node's *direct* children is what actually asserts it, since the changed node underneath does have one. Twelve mutations, ten red on the first pass, twelve after the tests were fixed.

**289 web unit** (was 273), **230 browser** (was 226).

---

### 184. The style block, and the one rule inside it (this session)

`workshop.md` §1.5 (p.57-62) was seven ○ rows and the largest untouched block left in Workshop — "unglamorous, and most of the distance between 'a canvas' and 'looks like Workshop'". Five of the seven are now done.

**It is values, which is exactly why it is a tested pure module rather than three settings panels.** The numbers are p.62's own: Compact 16, **Regular 24 top/bottom and 48 left/right**, Large 40 and 62. Regular and Large are not square, and one-number-per-option is the shape that quietly loses that. A control using 20px where the page says 24 looks plausible and nothing else in the system objects — there is no failing request, no error, nothing to notice.

**The per-level asymmetry is p.57-62's own.** Backgrounds are offered at all three levels (p.58); border styles "can be configured on sections and widgets" (p.60); padding is "for pages and sections" (p.62). Offering all four everywhere would have been less code and would have put a padding control on a widget with nothing to pad.

**One rule, and it is the item worth the work.** p.59-60: "widgets within that section automatically switch between light and dark mode based on the brightness of the background". Two decisions inside it:

* **The threshold is WCAG's own crossover**, `√(1.05 × 0.05) − 0.05` ≈ 0.179, derived from its contrast formula rather than picked. A round 0.5 is the obvious answer and is far too high — it puts white text on a mid-grey that black text reads better on. And the luminance is weighted rather than averaged: a saturated blue and a saturated yellow have the same naive channel average and could not be less alike to read against.
* **It applies as one `data-scheme` attribute** that redefines the ink and line tokens beneath it. Every widget already reads `--ink` and `--line`, so the rule reaches widgets written years before it existed — including ones nobody thought to check. Colouring widgets individually would mean touching each, and the one missed would be invisible until somebody picked a dark background.

**A compatibility trap, caught while writing it.** The Container's `background` has been free-text CSS since the first canvas. The tidy version of `resolveBackground` validates and returns `null` for anything that is not a preset or a hex — which would blank `red` and `var(--panel)` on every module in the corpus that set one. It passes unrecognised values through instead, and `isDarkBackground` refuses to guess at a colour it cannot parse rather than flipping a section's text on a value nothing read.

**One survivor, and it is the "passes for a reason it did not state" shape again.** The check that a widget gets no padding control selected the *Text* widget — which has no style block at all, so its panel lacks every one of these controls whatever the rule says. The assertion could not fail. The Container is the widget that does carry the block, and is the only one that can tell a correct per-level rule from a missing one. Sixteen mutations, fifteen red on the first pass, sixteen after.

**Two rows deliberately left ○.** Section header formatting (p.58) is blocked on a feature that does not exist — p.58 says those options "can be added when the header is enabled on a section", and sections here have no header. And p.62's inner-section-style inheritance names a list of "pre-defined section styles" that does not survive extraction from the PDF, so there is nothing to be faithful to yet. Both are recorded as their own rows rather than folded in and half-built.

**310 web unit** (was 289), **236 browser** (was 230).

---

### 185. Collapsible sections, and a gotcha implemented rather than noted (this session)

p.55's collapsible sections and p.82's three events — Expand, Collapse, Toggle — with the sentence that follows them built in rather than carried as a comment:

> "If the specified section has a Boolean variable backing the collapse state, **the value of this variable will not be updated** as a result of one of these events."

**The rule p.82 does not state, and something has to.** A section can be told two different things at once: what its backing variable says, and what an event last said. p.82 is explicit that the two may disagree, and silent about which is on screen — and getting it wrong is invisible, either a Toggle that appears to do nothing or a variable that appears not to be read. The reading here is **the most recent instruction wins**: an event overrides the variable and stays in force until the variable's own value *changes*, at which point the variable is the newer instruction. The two simpler rules each break one of p.82's own sentences. "The variable always wins" makes Expand and Collapse do nothing on exactly the sections the page says they are available for. "The event always wins" makes the word *backing* false after the first click — the variable would drive the section once and never again. Both are mutants, and both are red.

**Toggle is resolved against what is on screen**, not against the variable, and that distinction is a mutant of its own: computing it from the variable looks like the feature working right up until an event and a variable disagree, which p.82 says they are allowed to.

**The server refuses an effect aimed at a section that cannot collapse.** p.82 offers its three "for each collapsible section", and a section with no collapse state has nothing for them to change — so saving one would save a button that does nothing, which is the one outcome nobody can debug from the outside. Checking mere layout membership would have accepted a Toggle aimed at a *button*; that is a separate test.

**Three survivors, and all three were instructive.**

* Two were **false**: the harness mutated `widgets.tsx` and ran the browser layer before Next had rebuilt, so the tests ran against the previous bundle. §178's stale-dev-server lesson, one layer over — the harness now settles before the browser layer, and both mutants died immediately. Worth knowing because the symptom is a *surviving* mutant, which reads as a missing test rather than a missing wait.
* One was **real, and it was the gotcha itself**. The test clicked, waited for the section to open, and asserted the variable still read `true` — which passes trivially, because a write to that variable would take a debounce plus a server round trip to show up and the assertion ran long before that. **A negative assertion needs a clock.** The click now also sets a marker variable, and the test waits for the marker to land; by then a write to the backing variable would have landed too. Asserted as one string, so the two cannot be read apart.

**A silent-CSS failure, found by a red test rather than by reading.** The section's body is hidden with the `hidden` attribute — chosen so a table inside a collapsed section does not refetch every time somebody opens it. The UA stylesheet's `[hidden] { display: none }` is one attribute selector and lost on specificity to `.canvas-section-parts { display: flex }`: the DOM read as hidden and the section stayed on screen. Third time this repo has been caught by CSS that is silently nothing.

Fourteen mutations across **three** layers — API, unit, browser — all red. **321 web unit** (was 310), **242 browser** (was 236), **1389 API tests** (was 1381).

---

### 186. What the flake was actually measuring (this session)

§185 ended with a browser test failing for reasons it did not cause, and a note saying the ontology search took 4.5 seconds against a 5-second assertion. This is the follow-through. **The endpoint is now 0.37s** — twelve times faster — and the cause was not what the note guessed.

**The note blamed the row count. It was row-level security, evaluated once per row.** The measurement that settled it: a bare `SELECT id FROM object_types WHERE workspace_id = $1` returning 425 rows took **237ms** as the application role and **5ms** as the owner, who bypasses RLS. The plan put every millisecond in one line — `Filter: rls_can_access_workspace(workspace_id)` — at 0.56ms per row.

**Why, and why "add an index" would have been the wrong answer.** The tables are small and correctly indexed; the cost is the *calling*. `rls_can_access_workspace` is STABLE, so Postgres may hoist it — but only when its argument is a constant. `object_types.workspace_id` is a column, so the planner treats it as varying and calls a four-CTE function 425 times, even though the WHERE clause has already pinned that column to one value.

**The fix is the standard idiom**: `rls_workspace_ids()` takes **no arguments**, which is the entire point — a zero-argument STABLE function is a constant expression, so it is evaluated once per query and the per-row work becomes an array containment test. Postgres then does better than hoisting: the predicate moves into the *index condition* rather than staying a post-filter.

**Two migrations, because the same mistake had two shapes.** 0058 did the eleven policies whose predicate was exactly `rls_can_access_workspace(workspace_id)`, and got 4.5s → 1.9s. Measuring again showed the remainder was the same call one join further out: `object_type_properties` has no `workspace_id`, so its policy asks through its parent, and it fires once per *property* rather than once per type — 815ms of the 912ms still left. 0059 did those eight. **Measuring between the two is what found the second shape**; stopping at "the policies I could grep for" would have banked less than half of it.

**Three policies are deliberately untouched.** `canvas_apps`, `connections` and `resources` mix a workspace predicate with a project one in a single CASE or OR, and `rls_can_access_project` has the identical problem across **26 policies** in several shapes. Converting half a mixed expression would leave the row cost unchanged while making the rest harder to find. That is the next unit, and the pattern is now established.

**Equivalence is what these tests are about, not speed.** This is the security backstop: a faster predicate that admits one extra row is a data leak, not an optimisation. `test_rls_workspace_ids.py` compares the two predicates over **real rows**, sampled per access route — direct membership, group membership, org owner/admin, and a cross-organisation control — and asserts that every route except the control actually granted something. That last assertion is the one that matters: the first version of the check ran 3,600 *uniformly random* pairs, agreed on all of them, and granted access in none, which proves only that the two agree about strangers.

**A NULL that is not a bug.** `rls_can_access_workspace` returns NULL rather than false on an ordinary denial — `current_setting('app.service', true)` is NULL when unset, and `NULL = 'worker'` is NULL. A policy reads NULL as "no row", so the two are equivalent *as policies*; comparing them as values without a COALESCE reports every denial as a mismatch, which is what the first run did.

**Ten mutants on the function itself**, applied with `CREATE OR REPLACE` against the live database rather than by editing a file, since an applied migration is immutable. Four widen the set (every workspace visible; org membership without the admin role; a deactivated admin; a worker seeing everything), five narrow it, and all nine died on the equivalence tests. The tenth — dropping the `WHERE id IS NOT NULL` guard — survived, and was worth the argument: the NULL only appears when `app.service = 'worker'` is set and `app.workspace_id` is not, a half-configured worker connection no test created. Both spellings deny, so nothing could see the difference through the API; what the guard protects is the function's answer being a *total boolean* for anything composing it. A test for that misconfiguration kills it.

**Making things faster unmasked a latent test race**, which is worth writing down because the failure looks nothing like its cause. Three browser tests began failing on Playwright *strict mode* — `get_by_role("heading", name="Value types")` resolving to two elements. Both headings had always been on the page: these fixtures name their project after the section they look for, so the page carries `<h2 class="project-name">Value types 706e06</h2>` beside `<h2>Value types</h2>`, and `name=` matches by substring. The assertion used to succeed the instant *one* of them appeared, before the other arrived. §186 made the page fast enough that both land together. The race was always there and was always the test's; `exact=True` is the fix, and a slow page was the only thing hiding it.

**1396 API tests** (was 1389), 1 skipped, and **242 browser** green.

---

### 187. The project half: correct, proven, and reverted (this session)

**The unit that did not ship, and the reason is worth more than the code.** `rls_project_ids()` is written, equivalent, mutation-tested and *not in use*. Migration 0060 put it into twenty-five policies; migration 0061 took it back out.

**The rule was the hard part and it came out right.** `effective_project_role` has five outcomes and two are revocations. As a set: the worker's own workspace; an active org owner/admin of the organisation; `inherited` mode plus workspace access; `custom` mode with a **direct** entry that is not `none`; or `custom` mode with no direct entry and some group entry granting a real role. The order between the last two *is* the rule — a direct entry always wins, including a revocation — which is a `NOT EXISTS` in the group branch rather than a plain union.

**Three mutants survived the first pass, all rules the sample could not reach.** A direct grant in a workspace the user has lost (every real grant sits in a workspace its user is also in); the org-admin branch dropped entirely (an admin reaches inherited projects through the workspace gate anyway, so the branch is load-bearing only for a `custom` project with no entry for them); and `u.status = 'active'` removed (this database has no deactivated admins, and "a disabled account keeps full access" stays true for a long time unnoticed). Each got a constructed case. Thirteen mutants, ten red first pass, thirteen after.

**Then the browser suite said no.** It ran for **1h33m** instead of ~30 minutes, with nine failures that had nothing to do with what they check. The cause was one endpoint:

| | `GET /workspaces/{id}/projects` |
| --- | --- |
| before 0060 | **4.4s** |
| with 0060 | **22.1s** |

**The mistake was a cost model, not a rule.** The set idiom replaces a per-*row* cost with a per-*statement* one — a win exactly when the statement is paid once, a loss when something upstream already loops. `v_user_projects` resolves `effective_project_role` **per project**, and that endpoint joins it, so a workspace holding 881 projects ran the resolution 881 times and each one built an 881-element array of its own. Quadratic, from a change whose whole purpose was to remove a multiplication.

**Why the workspace half is safe and stays.** `rls_workspace_ids()` returns a handful of ids, and nothing in the application loops per workspace. The difference between §186 and §187 is not the idiom — it is what the idiom gets multiplied by. That is the sentence to remember before applying this pattern anywhere else.

**What was kept, and why it is not dead code.** The function and its tests stay. The equivalence is the expensive part to establish — real rows per access route, four constructed cases the corpus cannot supply, thirteen mutants — and deleting it would mean re-deriving and re-proving all of it later. **Fixing `v_user_projects` is the actual prerequisite**, and it is its own unit; the 4.4s baseline is not acceptable either, it was simply not made worse.

**A process note.** The API suite was green at 1410 and the equivalence suite was exhaustive, and both were satisfied by a change that made the product five times slower on a core endpoint. The browser suite is the only check that runs the real thing end to end, and it is the one that caught this. That is the second unit running where it earned its cost.

**1410 API tests**, 1 skipped, green with the revert in place.

---

### 188. One missing keyword (this session)

§187 named `v_user_projects` as the prerequisite and left it. This is that unit, and it turned out to be **two `ALTER FUNCTION` statements**.

**Every permission helper in this schema resolves as the owner except the two that do the work.** `rls_can_access_workspace`, `rls_can_access_project`, `rls_is_org_admin`, `rls_app_shared_with_user` and seven more are all `SECURITY DEFINER`. `effective_workspace_role` and `effective_project_role` were `SECURITY INVOKER` — and they are the ones that read `users`, `workspaces`, `workspace_members`, `group_members`, `projects` and `project_members`, every one of which carries a policy. So resolving a single role ran the whole isolation layer several times over.

| `GET /workspaces/{id}/projects`, 178 projects | |
| --- | --- |
| `v_user_projects` as invoker | **1319ms** |
| as definer | **23ms** |
| the same query as the owner | **27ms** |

The owner column is the tell. The work itself is ~27ms; the other 1.3 seconds were policy evaluation inside the function whose entire job is to decide policy. End to end the endpoint went **0.9s → 0.03s**.

**Why this was invisible.** `rls_can_access_*` already call these two *as definer*, because those wrappers are definer — so definer-mode behaviour was already the behaviour on the path RLS takes. Only a **direct** call ran them as invoker, and `v_user_projects` is the only place in the codebase that makes one.

**The correctness half, which matters more than the speed.** A permission function filtered by the permissions it is resolving can only under-report: if a policy hides a `workspace_members` row, the resolver says you have no role. Today that never bites, because the policy on that table lets a user see their own memberships — the answer comes out right because two rules happen to agree, not because anything guarantees it. Compared over 300 real (user, project) pairs across direct membership, group membership, org admin and cross-organisation denial, with 221 grants: **zero answers change**. A speedup that also closes a way for the schema to become wrong later.

**Three things §187 tried and this did not need.** No new function, no rewritten policies, no query rewrite — with the resolvers fixed, the existing view at 23ms beats the LATERAL rewrite I had measured at 34ms, so `v_user_projects` is left exactly as it was. §187's whole apparatus was aimed one level above the actual cost.

**The test is a property, not a behaviour**, which is why it needs its own file: `SECURITY INVOKER` here errors nothing and changes no answer on this data. `test_permission_function_security.py` asserts that every resolver is definer and pins a `search_path` — a definer function without one is a worse hole than the one being fixed — and that the list of exempt setting-only helpers is still exempt, by checking their bodies read no table. A last assertion requires the two lists to *exhaust* the helpers, so a function added later cannot quietly go unchecked. Six mutants, all red, including "a new helper is added and left as invoker" and "a setting-only helper starts reading a table".

**A harness bug worth more than the mutants, and it cost a full suite run to find.** Two of the six mutants altered functions that migration 0062 does not own — `rls_can_access_project` and `rls_current_user_id` — and the restore only re-applied 0062. So the harness exited leaving both mutated, and the next full API run came back **214 failed, 375 errors**: not a regression, a poisoned database. The lesson generalises past this repo: **a mutation harness whose restore is narrower than its mutants is worse than no harness**, because its damage outlives it and lands on whatever runs next. The restore now names every function any mutant touches.

**And then the browser suite failed twice, which took longer to explain than the change did to write.** `test_widget_config_tabs.py` lost two tests: one measuring a table 68px tall that should have been 377, one counting two header cells that should have been three. Both read as the object table rendering nothing — but the API returned byte-identical responses under both settings, and the same fixture drove a table with all thirty rows when a probe waited four seconds.

A timeline settled it. The object table is visible long before it has data: it draws its frame, asks for the workspace's object types, and only when *that* answers does it evaluate the object set. `settled()` returns at the frame. Under definer the tree-row click lands at **0.99s** and the height is read at **1.03s** — the evaluate request is not fired until **1.14s**. Under invoker, `GET /projects` was still in flight until **1.87s**, and the click could not happen until the Layout panel it renders had drawn, by which time the evaluate had answered at 1.13s.

**A slow request nobody was waiting on was holding the test's hand.** The race has been in those two tests since they were written, on every machine, and it passed every time because an unrelated 1.1-second query covered it. §188 did not break them; it stopped paying for their guard. The fix is in `select_widget`, which now waits for `ROWS` table rows before returning — and it belongs there rather than in each test, because `header_count` and `bounding_box` are equally happy to read the loading state and believe it. **This is the third time this session** an equivalence-preserving change has surfaced a latent Playwright race (§186's `exact=True`, twice), and the pattern is now specific enough to name: *making something faster removes an accidental barrier, and every test that was relying on that barrier fails at once.*

Two mutants against the wait. Deleting it fails both tests, which is the point. The second — wait for a header cell instead of for the rows — **survived, and is equivalent rather than a gap**: sampling the gap every 10ms shows the table go straight from no `<table>` at all to three headers and thirty rows in one paint, so there is no state a header wait could return in that a row wait would not. Checked rather than assumed, because "my mutant survived, it must be equivalent" is the excuse that hides real holes; the sample is the difference between knowing and hoping. It also explains the original error text — `header_count` read **0**, not 2, so the test was waiting for −1 columns and reporting the 2 it kept seeing.

**1434 API tests** (was 1410), 1 skipped; **242 browser tests**, all passing.

---

### 189. The page a variable is looking at (this session)

p.81's Variable-Based Page Selection, which §185 named as the next one and correctly called "p.82's sentence with a page id where the boolean was". `components/canvas/page-selection.ts` is `collapse.ts` one row up, on the same rule — **the most recent instruction wins**: a Switch-to-Page event overrides the backing variable and stays in force until the variable's own value *changes*. The argument for that rule is §185's and is not repeated; what follows is only the two things a page has that a boolean does not.

**The variable holds a page ID, not a node.** A boolean says everything there is to say about a collapse state, but a page has to be *identified*, and there are two identifiers available. The author-set `pageId` is the right one for p.197's reason: a Craft.js node id is generated, means nothing to whoever types the value, and changes when a page is recreated — so picking it would make a variable set from a transform or a URL silently stop working after an edit nobody would connect to it. The side effect is worth having: the link and the variable name the same page in the same words. The event keeps the *node*, which is how it can still reach a page nobody has named.

**A string can name a page that is not there.** A boolean cannot be wrong; a page ID can be a typo, or belong to a page since deleted. p.197 already answers this for the URL — "users will be returned to the module's default page" — and the same answer is right here, because the alternative to falling back is a blank module with no way out. Blanking is the one outcome that leaves a reader stuck.

**Where the server stops.** It refuses a `page_selection` that names a variable which is absent or is not a string, and deliberately does **not** check the *value* against the pages. The asymmetry is the usual split — the server owns what is legal, the browser owns what to render — and here it has teeth: a kind that is wrong can never work, while a value matching nothing today might match tomorrow, so a value check would make a valid module stop saving because somebody renamed a page.

**Twelve mutants, and the two that survived the first pass were both worth more than the ten that did not.**

The first was `if (now === null) return defaultNode;`. Deleting it changes no behaviour at all — the `nodeForPageId` callback happens to tolerate a null and returns the default anyway — so every test still passed and the line read as something to delete. It is `tsc` that refuses it: without the guard, `now` is `string | null` where a `string` is wanted. So the guard is load-bearing for the *contract* rather than for the arithmetic, and the honest response was to **add a types layer to the harness** rather than to write a test that could not tell the difference. A repo that mutation-tests only behaviour will quietly delete every line whose job is to make a type check out.

The second was the interesting one, and it was a test bug of a shape this repo has not recorded before. Making a Switch-to-Page event record no memory of the variable's value should be trivially fatal, and it was not. Instrumenting the mutant at 250ms intervals:

```
before    visible: ['p1']  texts: ['PAGE= MARK=']
t+250ms   visible: ['p3']  texts: ['PAGE=overview MARK=yes']
t+500ms   visible: ['p1']  texts: ['PAGE=overview MARK=yes']
```

The mutant *is* observably wrong — it shows the right page for a quarter of a second and then sends the reader home — and the whole test had run and passed inside that window. **`to_be_visible` retries until it sees what it wants and then stops looking**; a wrong first frame is forgiven, and a wrong *last* frame is never examined. The cause is that variables resolve on the server, so for the first few hundred milliseconds `resolved` is empty and the backing variable reads as *absent*, which is precisely the one state in which an event wins unconditionally.

The fix is a `readout()` helper and an ordering rule: **every `showing()` in the file is preceded by a wait for the header to say what the variable is.** One of them earns its place twice over — the test that a mistyped page ID opens the default page would otherwise pass against a build that never read the variable at all, since an unresolved variable also opens the default page.

Both survivors generalise past this unit and are now rough edges: an assertion that can be satisfied by a transient state is not an assertion, and a mutation harness that runs only behavioural layers cannot see a type contract.

**1441 API tests** (was 1434), 1 skipped; **248 browser tests**; 12 mutants, all killed.

---

### 190. The tabs that were pages (this session)

§189's parity row named tabs as the remaining third of variable-backed layouts and said they were "not more of the same", because p.84 reverses p.81's rule: a Switch-to-tab event *does* write its backing variable. Building it turned up something bigger first.

**A row that said ✅ on a substitution.** §1.3 listed Tabs as done, meaning the Tabs *widget*, and `CanvasSection`'s own comment defended it: "a tabbed section is the Tabs widget over pages, which is the same idea one level up." p.54 says otherwise in one sentence — "**Tabs**: adds tabs to the top of a **section**" — and the difference is not cosmetic. A module has exactly one set of pages, so two independent tab groups side by side on a page, which p.54 treats as ordinary, could not be expressed at all. p.84's Variable-Based Tab Selection had nothing to attach to, which is why the row below it had stayed ○ without anyone noticing the row above was the reason.

So §190 is the Tabs *section*: `direction: "tabs"` on `CanvasSection`, one child per tab, a tab holding several widgets being a child that is itself a section — p.54's own "a layout, which itself may contain one or more sections". Tab names are a comma-separated list in the same idiom as `weights`, so a Tabs section is configured the way a Columns section already is. Unnamed entries become "Tab 3" rather than the child widget's name, because a tab bar reading "Section" over a section says nothing, and duplicates are numbered because **a tab name is an address**: p.84's event and the backing variable both use it, so two tabs called "Details" leave both with no answer.

**The reversal, and the thing it might have talked me out of building.** p.84's write-back makes it tempting to let the variable be the only state — the event writes it, so why hold an override? Because the write needs a debounce and a server round trip, and the tab has to move *now*. For those few hundred milliseconds the event and the variable disagree in exactly the way p.81's do, and without the override the section would snap back on every click and settle a moment later. So `tab-selection.ts` is the same arithmetic as `collapse.ts` and `page-selection.ts` — the most recent instruction wins — and p.84's difference is entirely in the wiring. `collapse.ts` and `page-selection.ts` describe a disagreement that persists; this describes one that heals.

**Fifteen mutants, all killed, and the fifteenth was the interesting one.** Making the tab choice global instead of per-section survived the first pass, and the reason is worth keeping. My two-groups test gave the groups different tab names — `L1/L2` and `R1/R2` — so when the shared state handed the right-hand group the left-hand group's choice, `activeTab`'s staleness guard discarded it as naming no tab this section has, and the right-hand group fell back to its first tab. **The right answer, for the wrong reason.** Two panes each offering "Chart" and "Table" is the ordinary case and the only one where shared state actually shows; with the names made identical the mutant dies. The lesson is narrower than §189's and worth having beside it: *a test whose fixtures are gratuitously distinguishable can be passed by a component that is not distinguishing them at all.*

**And the harness gained a no-op check**, prompted by §189 rather than by anything here: a mutation whose regex matches nothing is reported as a survivor, which reads as a hole in the tests and is really a typo. §189 cost two by-hand investigations to that; `mut190.sh` fingerprints every file before and after each mutation and reports NO-OP rather than SURVIVOR. It fired zero times, which is the outcome you want and not the reason to leave it out.

**1453 API tests** (was 1441), 1 skipped; **257 browser tests**; **357 unit tests**; 15 mutants, all killed across four layers.

---

### 191. Two props that named a variable and nobody knew (this session)

Found while scoping copy-and-paste, which needs a definitive answer to "which props hold a variable id". `REFERENCE_PROPS` is that answer: it decides what counts as a *usage*, which decides whether a variable can be deleted and whether a binding to a missing one is refused. **Two entries were never added to it** — `collapsedWhen` (§185) and `tabVariable` (§190) — and the omission was silent in both directions.

```
collapsedWhen    -> ACCEPTED a reference to a variable that does not exist
tabVariable      -> refused (§190's own check, which is about the kind)
visibleWhen      -> refused: this layout binds to v_x, which the module does not declare
```

And the other way round, asking for a variable's usages when a section binds both its visibility and its collapse to it:

```
{'v_b': [{'node': 'sec', 'prop': 'visibleWhen'}], 'v_s': []}
```

`v_b`'s collapse binding is invisible; `v_s` backs a Tabs section and has **no usages at all**. So the Variables panel would report it as used by nothing and offer to delete it — and §190's check, which only asks whether it *resolves* at save time, would then refuse the next save, blaming an edit made earlier. A refusal arriving one step late and pointing at the wrong thing is worse than no refusal.

**There was already a guard, and it could not have caught this.** `test_the_reference_prop_list_agrees_with_the_browser_s_copy` asserts the API's copy and the browser's match — and they did, identically wrong. A check that compares two copies is blind to anything missing from both, which is a general shape worth naming: *mirroring is not completeness.*

So the new guard checks the list against the **builder**. Every prop a settings panel reads (`node.data.props.X` in `widgets.tsx`) whose name ends in `Variable`, `Parameter` or `When` must be a known reference or a named exception. Eleven props match today; ten are references and one is exempt — a Loop layout's `itemVariable` holds the **child module's** external ID (p.135), so it names something in a different document. The exemption is a named constant rather than a pattern, because an exemption nobody can see is how the next one gets added quietly.

It is a naming convention, and asserting it is what makes it one: a prop holding a variable id and called `foo` still slips through, and the failure message says the answer is to call it `fooVariable`. The guard carries its own vacuity assertion — a completeness check that finds nothing passes, which is the third time that shape has come up this session.

**Eight mutants, all killed, and one of them had to be rewritten to mean anything.** "The completeness guard exempts the two props it was written for" survived, and correctly: exempting a prop that is *present* in the list changes no behaviour, so the mutant tested nothing. The version that matters removes the two props **and** exempts them at once — the guard is then genuinely blind, and the kill has to come from the usage tests. It does, which is what proves those tests stand on their own rather than being decoration around the guard.

**A process note, paid for in lost work.** The sandbox rewound mid-unit and took this unit's first draft with it, because it was still uncommitted after half an hour. §188–§190 were untouched, being merged. The rule that follows is cheap: **commit and push as soon as a unit's tests are green, before the mutation harness runs**, not after the record is written. The harness is the longest phase and the one most likely to be interrupted, and a commit costs nothing to amend.

**1457 API tests** (was 1453), 1 skipped; 8 mutants, all killed.

---

### 192. Copy, paste, and the question p.55 asks twice (this session)

The unit §191 was scoped for. p.55 offers cut, copy and paste for sections and widgets, and — the part that makes it more than an editor convenience — **two** pastes: "Paste with same input variable" reuses the copied thing's variables, "Paste with duplicate input variables" mints new ones matching them. Everything else is a subtree walk, fresh ids, and rewriting the references that point inside what moved.

**One transform over the serialised layout.** Craft.js has a node-tree API, but the layout *is* the serialised map (decision 0002) and the builder already deserialises one on load, so `clipboard.ts` transforms the map and hands it back to `actions.deserialize`. Cut is then one atomic edit rather than a copy followed by a delete that could land without it — and the whole thing is testable without a browser, which matters more here than usual: *a paste that rewrote one reference too few is invisible* until somebody edits the copy and watches the original move.

What travels: the subtree through both `nodes` and `linkedNodes`; the definitions of every variable it references; and every event triggered from inside it, with node ids remapped where the target came along and left alone where it did not. p.55 says nothing about events, and leaving them behind would have been defensible — but a copied Button that has lost its on-click does less than the thing it copied, silently.

What does not travel: a duplicated variable's **derivation inputs**. p.55's "input variables" are the widget's own, not the whole graph behind them, and duplicating the graph would clone the object set a filter narrows — precisely the thing an author duplicating a filter wants to keep shared. The other reading is defensible and produces a different feature, so the judgement is stated in the module and asserted in a test rather than left to be inferred. A duplicate also drops the **external ID**: it is what a URL and an embedding module address, the server refuses two variables that share one, and carrying it would make the paste unsaveable for a reason pointing at the wrong variable.

**Twenty-two mutants, all killed** — and unusually, none survived. That is worth a note rather than a celebration: the reason is that the interesting behaviour is all in a pure function with a fixture that names every node, so a wrong remap changes a value a test already reads. The three units before this one each had a survivor, and each survivor lived in *wiring* rather than arithmetic.

**Three false starts in the browser test, all the same shape: the fixture was not asking the question.**

1. The first bound its widget with `{{v_word}}` in the text. An interpolation is **not** a reference prop, so nothing in this system counts it as a usage — not the server, not the Variables panel, not the clipboard — and the clipping carried no variables at all. Three tests failed for a reason with nothing to do with pasting.
2. The second counted `get_by_text("COPY ME")` unscoped and got four where it expected two, because the Layout panel shows a Text widget's `text` prop as the row's detail. Every widget was counted twice — once drawn, once listed.
3. The third read the Variables panel's usage counts straight after a paste and saw the duplicate as "unused". The panel counts usages against the **saved** definition, so before a save it is answering a question about the previous document.

The third is the one that improved the test: it now saves and reloads before reading the counts, which turns "did the paste repoint the props" into a question about the *document* rather than about the editor's memory. And the counts are a better readout than anything on the canvas, because they name both sides at once — a build that minted the variable and forgot to repoint the props shows "Show" used twice and "Show copy" used by nothing.

**Named and not built**: p.68's *Unused widgets* area, the holding pen a Cmd+V lands in when there is nowhere to put a widget yet. It needs a place in the document for nodes outside the layout tree, which is a format change rather than a control.

**1457 API tests**, 1 skipped; **263 browser tests**; **383 unit tests**; 22 mutants, all killed.

---

### 193. The effects an author can actually reach (this session)

p.85's **Reset {variable} value**, and the gap that turned up while adding it.

**`switch_tab` was legal and unreachable.** §190 added it to the server's `EFFECTS` and never to the builder's catalogue, so it could be saved and could not be created — a feature reachable only by hand-editing the raw JSON. Nothing noticed, because the two lists are in different languages and neither is derived from the other. This is §191's shape exactly, one list over: *mirroring is not completeness, and neither is having only one copy checked.* So the entry comes with the guard — the panel's catalogue must cover exactly what the server accepts minus what it refuses with a reason. Offering a refused effect is a choice that fails on save; not offering an accepted one is the gap above.

**Reset is a deletion, and that is the whole design.** p.85 says "its default value, which is the value configured in the variable definition", and the obvious implementation writes that default. Writing it is wrong for a variable an embedding module has mapped, whose definition is the *parent's* (p.128) — a value the child does not have. Deleting the viewer's value is right in both cases at once:

- an unbound static variable resolves as `values.get(vid, variable.default)`, so forgetting the local value **is** "back to the definition";
- a mapped one resolves as the host's value with the child's definition skipped entirely (p.127), so forgetting the local override **is** "back to the parent's definition".

One operation, and p.128's rule falls out of the existing evaluator instead of needing a case. The reset also deliberately **never forwards to the host**, unlike `set`, which does: forwarding would have a child's Reset button edit its parent's state.

p.85 offers Reset "for static variables", so the server refuses it on a derived variable and on an object set with its own definition — neither has a stored value to put back. And `recompute` joins `PLANNED_EFFECTS` beside `export`: every derived variable here recomputes on every resolve, so until §3.5's other two recompute behaviours exist there is nothing for it to trigger, and saving one would save a click that does nothing.

**`events.ts` had no unit tests, and could not have had any.** It imports `context.tsx`, and a `.tsx` anywhere in the import graph is a file vitest cannot parse — so `run`, which exists to enforce p.80's ordering, was reachable only through a browser. The pure half moved to `event-run.ts` and everything is re-exported, so no call site changed; the ordering rules now have ten unit tests. The case that motivated the split is the one this unit created: a Set and a Reset of the same variable are applied through *different* capabilities at the end of a run — one a write, one a deletion — so whichever came last has to win, and nothing about the code's shape makes that automatic.

**Fifteen mutants: fourteen killed, one equivalent.** Writing `next[name] = undefined` instead of `delete next[name]` survives, and this time the equivalence was established rather than assumed: the only consumer of the map's *shape* is `JSON.stringify(values)` — the bridge's resolve dependency and its request body — and `JSON.stringify({a: undefined, b: 1})` is `{"b":1}`, identical to the deleted case. Every other reader accesses by key, where absent and `undefined` are the same. `delete` stays because a map that accumulates undefined keys across resets is untidy, not because anything can tell.

One mutant was withdrawn rather than fixed: "make the catalogue guard compare the server's list to itself" is neutering an assertion, which any test permits and which proves nothing. Replaced by the failure that can genuinely happen — the scan quietly ceasing to match the panel's format after a reformat — which the guard's label assertion kills.

**And the full browser run found a fourth instance of the same latent flake**, in a file this unit did not touch. `test_action_statuses.py` waits for a heading named "Actions"; `get_by_role(name=…)` matches by case-insensitive *substring*; and that file's fixture names its project **"ActionStatuses …"**, whose first seven letters are "actions". Two matching headings on the page, so a strict-mode violation the moment both have rendered — and it passed for as long as the assertion happened to resolve before the project name arrived. `exact=True`, the same one-word fix as §186's two. The tell is worth repeating because it is unmistakable once seen: a failure that says **"resolved to 2 elements"**, never "not found".

**1463 API tests** (was 1457), 1 skipped; **266 browser tests**; **393 unit tests**; 15 mutants, 14 killed and 1 equivalent.

### 194. Variables that hold their value, and the event that lets go (this session)

p.76's two non-automatic recompute behaviours, and p.85's **Recompute {variable}** that fires them. **Only when triggered by an event** has no value until one does; **On module load, and when triggered by an event** computes once at load and then holds.

**The server computes and the browser remembers**, because those are the only two places the state can live. Derived values resolve on the server — one implementation of the transforms, not two — and the server has no memory between requests, so "do not recompute this time" can only arrive from the caller. The browser keeps what each holding variable last computed and sends it back; the evaluator uses it *as the input to everything downstream*, which is the part that could not be done by freezing a number on screen. Freezing locally would leave a variable showing one figure while its dependants recomputed from a fresh copy of it — two answers to one question on one page, the silent-disagreement class this repo keeps deleting.

**The browser test found the hole it was written for, and it was in the design.** The wire carried one field, `held`, and a recompute was expressed by *dropping* the entry, on the reasoning that the server computes whatever it is not given. That works for **On module load** and cannot work for **Only when triggered by an event**: p.76 gives that one no value until an event fires, so "nothing held" is already its state on a fresh page. The request a click produced was byte-identical to the request a page load produced, and the server answered both with `None`. **The event did nothing, forever, with no error.**

The general shape is worth the name: **an absence cannot carry a request when absence is already a meaningful state.** Both unit suites were green — the browser's bookkeeping was right about what it remembered, the evaluator was right about what to do with what it was given — because the bug lived in neither half but in what the two agreed the wire meant. Only the round trip could see it. That is also exactly the argument the browser test's docstring had made for existing, written before it was known to be true.

So the ask travels as an ask: `recompute_now` beside `held`, and the ask wins over the held value — which means the browser no longer has to drop its memory to make an event land, the thing it could not do unambiguously. `recompute.ts` swapped `forget` for a pending set: `request` records a click, `requested` puts it on the wire, `settled` clears **only the asks the returning resolve actually carried**, so an event fired mid-request is not swallowed by the answer to the previous one.

**Two survivors, and both were the test's fault, not the code's.** `remember`'s "carries a held value rather than re-reading the echo" passed the same string as all three arguments, so it held whichever way round the two branches went — §188's lesson again, in a test written to guard a race. And the evaluator's `derivation is not None` guard had nothing behind it: `parse` refuses the state it protects against, so the only way to reach it is to build a `Variable` by hand — which is a real contract of a public function, and without the guard a static variable marked this way resolves to `None` instead of what somebody typed. Both fixed in the tests.

**37 mutants, 0 survivors, 0 no-ops. 1488 API tests** (was 1463), 1 skipped; **271 browser tests** (was 266); **417 unit tests** (was 393).

### 195. The layout template picker, and a preview that made it unclickable (this session)

p.52's picker at the bottom of a page, its hover preview, and p.53's "the page layout will update to the one you selected".

**The design question p.53 does not answer is what happens to the widgets already there.** "The page layout will update" is a sentence about layout, and the picker is documented on a page created moments earlier, so the intended use is plainly a starting point — but the control is always on screen and somebody will click it on a page they spent an hour arranging. So applying a template never loses a widget: the sections are replaced, their contents carried into the new ones positionally, and anything past the new count lands in the last section rather than nowhere. The case that is handled rather than solved — narrowing three sections to two — piles the surplus into the last, which is visible, undoable, and not a deletion.

**The bug the browser test found is one CSS rule, and the symptom had no error anywhere.** The hover preview was an ordinary sibling above the icon strip, so opening it pushed the strip *down*: the icon slid out from under the pointer that was hovering it, `mouseup` landed on empty space, and the browser never synthesised a `click` at all. The button did nothing, silently. The trace is the tell and is worth keeping — **`pointerdown` and `mousedown` arrived and `mouseup` did not**, which says the element moved rather than that the handler was wrong. Floated now, so opening a preview moves nothing.

**And a correction to my own first diagnosis, which the harness caught.** The first hypothesis was Craft's drag connector eating the press, and a `stopPropagation` went in to stop it. The mutant that *removes* that handler survived — every browser test still passed without it — so it was never load-bearing, and a confident comment explaining why it was essential would have been a false explanation of a real bug. Removed. The rule: when a mutant that deletes a fix survives, the fix was not the fix.

**Three other survivors, all real holes in the tests.** The direction assertion only ever checked a template whose direction was the default, so a build that hard-coded `columns` passed while the Rows and Toolbar templates would have laid down something that looked nothing like the icon clicked. `pageGroups` walks `linkedNodes` as well as `nodes` — Craft hangs an `<Element canvas>`'s children off the former, and `clipboard.ts` carries the same warning — but every fixture used `nodes`, so the walk was untested. And nothing opened the module as a *reader*, so a picker rendered unconditionally would have passed the whole file and shipped a layout-rewriting control into the published app.

**25 mutants, 0 survivors, 0 no-ops. 447 unit tests** (was 417); **277 browser tests** (was 271).

### 196. Conditional-visibility indicators in the Layout panel (this session)

p.55's icons and tooltips marking which sections have conditional visibility, which closes the open half of a ◑ row.

**The second half of p.55's sentence is the requirement.** "…making it easier to identify and manage conditionally visible sections **even when they are currently hidden in the module view**." That is not a note about the feature's benefit, it is a constraint on what the indicator may read: a marker driven by the condition's *current value* would go out exactly when the sentence says it should be useful. So it reads the document — does this node carry a condition — and never the resolved values.

Which puts two markers on screen that deliberately disagree. The canvas already writes "hidden unless <label>" on a node whose condition is false, and that one **is** value-driven, because it answers "what is happening now". The panel answers "what is configured". A browser test asserts both are present at once on the same section, which is the only place that distinction is visible.

**The split in `conditions.ts` is a bug fix wearing the clothes of a refactor.** The first version computed the whole marker — icon, verb, and the variable's *label* — inside the tree walk. That walk runs inside Craft's node-map selector, which re-runs when the node map changes and not when the variable list does, so renaming a variable left the tooltip reading the old name until something unrelated touched the layout. Now the walk reads only which conditions a node carries, and the label is looked up at render.

Worth noting how close that came to shipping: every unit test passed either way, because the bug is not in either function but in **which React hook re-runs when**. The mutant that reverts the split is the one this unit's harness exists for, and the browser test kills it — so the fix is verified rather than asserted, which is the standard §195 set when a deleted fix turned out not to have been the fix.

**16 mutants, 0 survivors, 0 no-ops. 464 unit tests** (was 447); **282 browser tests** (was 277).

### 197. Where a parked widget lives (this session)

p.68's *Unused widgets* area — a widget that is in the module but on no page. The last `○` on the Workshop layout rows, and the first thing this session to touch the saved format, so it got a decision record (`docs/decisions/0010-unused-widgets.md`) before any code.

**The decision turns on one function, and the two candidate homes are not equivalent.** `usages()` decides whether a variable may be deleted, and it *iterates the node map* rather than walking the tree. So parked widgets kept in the map are counted for free, and parked widgets kept in a sibling key on the document are not. Under the sibling key: park a Filter List bound to `v_region` → the Variables panel reports `v_region` unused → an author deletes it → the server allows it → the widget comes back bound to nothing. **No error at any step.**

That is the same shape §190, §191 and §193 were each caught by — a list that had to be complete with nothing checking it against the thing it described. The sibling key could be made correct by scanning both places, and that is precisely the second scan that keeps not getting written. So the design removes the possibility instead: parked widgets are children of a `CanvasUnused` node under ROOT.

Two properties the record names as the ones this design will lose first, both now held by a mutant:

- **`CanvasUnused` renders nothing, in both modes.** A version that drew its children would put parked widgets on the page for every reader, and nothing in the builder tests would notice. The guard is a browser test that opens the module as a *reader*.
- **Placing is a move, not a copy.** Ids survive, so bindings and the events triggered from the widget come along. A version that minted new ids would look identical on screen and be wrong the moment a variable changed.

**All three survivors were real holes, and the first looked equivalent.** `move: ROOT may be moved` passed with the guard deleted, because in a well-formed document everything descends from ROOT and `isDescendant` already refuses it — the explicit clause never fires. Only a *detached* target separates the two, and this module explicitly reads documents that can arrive from anywhere. The other two: `isCanvas` on the minted holder was unasserted (Craft re-derives it, so a document written without it works today and is wrong the moment anything reads the map directly), and nothing checked that a parked widget had *left the layout tree* — the panel comment said a widget in both places reads as two widgets, and no test said so.

**22 mutants, 0 survivors, 0 no-ops. 491 unit tests** (was 464); **289 browser tests** (was 282).

### 198. Loops over arrays, and a console check that had never worked (this session)

p.132-133's loop over an array. The parity doc had recorded the blocker exactly — the `array` kind had no element type, so p.134's "a variable typed to the array type" could not be expressed or checked.

**p.134's sentence is ambiguous and p.134 settles it.** It could mean the child receives the whole array; two sentences later it says the struct-typed interface variable renders the fields of each struct *entry*, so the child receives one entry and its variable is typed like an entry. `Embed` carries `item_kind`, computed from what is being looped. An argued reading with no test is a comment, so the mutant implementing the other reading is the one that harness exists for.

**§191's drift guard fired on new work for the first time.** `arrayVariable` names a variable and was not in `REFERENCE_PROPS`; the save was refused before this could ship with a variable deletable out from under a configured loop. That check had been archaeology since §191.

**And the finding that outlives the unit: the browser suite's console-error assertion had never worked.** A mutant keying loop copies by *value* makes React log "Encountered two children with the same key"; the test asserted no console errors and passed. `DEV_SERVER_NOISE` contained `hot-reloader-client`, added to silence one benign Next prefetch message that *names that file as its source* — and React's own `console.error` routes through the same client in dev, so **every React error in the whole suite was filtered out**. The fixture's docstring says the check "is not decoration". It was.

Removing it unmasked a second bug, in a test §192 wrote: `settled()` waits for the canvas and the Layout panel paints after it, so a baseline read **0** and `n == before * 2` became `n == 0`. It passed on luck until §196 and §197 each added work to the panel's first paint.

**26 mutants, 25 caught, 0 survivors, 1 withdrawn as equivalent. 1510 API tests** (was 1488), 1 skipped; **507 unit tests** (was 491); **297 browser tests** (was 289).

### 199. Finding a variable (this session)

p.72's search, filter and partitions — the three controls that exist because a module with forty variables has a Variables panel nobody can read.

**p.72 says "search by name or unique ID" and this system has two things that could be called one**: the opaque generated `id` and the author-chosen `external_id`. Picking either would be right half the time and silently wrong the other half, so the search matches all three fields.

**A partition is an ordering, not a filter.** Everything stays in the list and the relevant ones come first under a heading; hiding the rest would make the panel lie about what the module contains, and p.72's word is "find", not "restrict". A partition with nothing in it still draws its heading, which is the answer to the question rather than the absence of one.

**A divergence, stated rather than papered over.** p.72's page partition is "variables used in the active page", and our builder draws every page at once — so "the active page" has no answer the way p.72 assumes. The page an author is working in is the one holding their selection.

Two things caught before they shipped, both by writing the test first. A unit test found a distinction I had not drawn — `pageNodes: null` is "the caller does not know" and `[]` is "the page is empty", which are different answers, and there the code was right and the test was wrong. And the first render emitted both partition headings in a block above the whole list rather than interleaving them, which `listEntries` now makes impossible by building headings and rows as one sequence.

**28 mutants, 0 survivors, 0 no-ops, first run.** Every browser assertion names the variables it expects rather than counting rows, because three controls that each narrow a list all look like they work if you only assert "fewer than before" — the mutants are chosen to keep counts right while changing which variables survive.

**533 unit tests** (was 507); **306 browser tests** (was 297).

### 200. The variable lineage graph (this session)

p.77–78's lineage graph — the row §199 deliberately left open, because a view of how variables feed each other is a different kind of thing from a way of shortening a list.

**One sentence in p.77 is the whole design**: "trace which widgets **read or write** a variable". A widget that reads a variable is downstream of it; a widget that writes one is upstream. So every prop in `REFERENCE_PROPS` carries a direction, and getting one backwards points an arrow the wrong way in the one view whose entire purpose is being trusted while debugging. Four of the thirteen are writes — a Filter's `name`, a Filter List's `filterParameter`, a Search's `searchParameter`, a chart's `drilldownVariable` — and they are exactly p.69's "output variables… data passed out of a given widget".

That is the **fourth instance** of the shape §190, §191 and §193 were each caught by: a list that must stay complete with nothing checking it against its subject. This one is guarded on the way in and in both directions — and by the end of the unit the completeness half is not a test at all but a **type**: `PROP_DIRECTION` is keyed by `REFERENCE_PROPS` itself, so an unclassified prop does not compile.

**A divergence, stated in the file and in the parity doc.** p.78 puts the chevrons "on the top and bottom edges", which is a vertical graph. This draws left to right, because `pipeline-graph.tsx` already draws the dataset lineage graph that way — two directions for two dependency graphs in one product is a worse divergence than one direction that differs from Foundry's.

---

**The harness found six survivors, and five of them were the same mistake in five places: a rule stated in a comment and checked at one point.**

- The direction table had three spot checks over thirteen props, so **ten entries could be flipped silently**. The fix is a hand-written expectation per prop — written out separately rather than derived from `PROP_DIRECTION`, because a test that reads its expectation out of the thing under test agrees with whatever that thing says.
- `expand` returning only the *first* missing neighbour survived: no case had a node with two. That failure is invisible on screen — the chevron stays, so it reads as a node with more behind it rather than one whose expansion dropped something.
- `collapse` dropping the node it was asked about survived, because no node was ever its own neighbour. `layers` already carries a cycle guard whose comment says a document can arrive with a loop in it; the test now builds that loop. **Same shape as §197's ROOT survivor** — a guard that looks unreachable until you ask what document could reach it.
- Reading an explicit `selected: null` as "no opinion" survived. Clear is what makes `undefined` and `null` different answers: under `??` the selection outlives the graph, and the next node to take that id lights up as selected.
- In the browser, a collapse chevron drawn where it would do nothing survived — the test asserted the *expand* arrows were absent and said nothing about their inverses.

**The sixth was not a hole but dead code.** `PROP_DIRECTION[prop] ?? "read"` survived being changed to `?? "write"` because the loop iterates `REFERENCE_PROPS` and every entry is classified, so the branch cannot be reached. Rather than withdraw it as equivalent, the branch is gone and the type replaces it: **a branch nothing can reach is a branch no test can hold**, and the honest response to one is to remove the possibility, not to record an exception.

One assertion written while closing those holes was wrong and the panel was right: a Filter whose only child is the variable somebody expanded *from* still offers to fold it away, because collapse asks whether another visible node is holding the neighbour, not which node reached it first.

**And a rough edge paid for in full: the harness restores from `git show HEAD:`, so running it over uncommitted source silently reverts that source.** The re-run of the six survivors was started with the fixes on disk and unpushed; the first `restore()` put the file back to HEAD, and killing the run left a planted mutant behind on top of it. Nothing was lost — the fixes were still in context and the two test files were outside the restore set — but the rule is now explicit: **commit before re-running, every time.** It is the same rule as §197's "restore inside the exception handler", seen from the other end.

**42 mutants, 42 caught, 0 survivors, 0 no-ops** after the fixes.

**578 unit tests** (was 533); **314 browser tests** (was 306); 1510 API tests, 1 skipped, unchanged — this unit adds nothing to the server.

`workshop.md` §3.3's lineage row goes ○ → ◑. The remaining half is p.78's per-node detail — "the pages and overlays where a variable is used and the time at which a variable was computed" — which needs the evaluator to report a computation time it does not currently record.

### 201. What a copy of a variable cannot carry (this session)

p.73's two creation actions, and the last two ○ rows in `workshop.md` §3.3. Small buttons; the interesting part is what they are not allowed to do.

**A duplicate is not `{ ...variable, id: newId }`.** Three things on a variable are unique within the module — the id, the label, and the **external ID** — and the third one is not a matter of taste: `_refuse_duplicate_external_ids` rejects two variables sharing one. So the copy cannot have it, and **dropping it cascades**, because the external ID is §3.4's one mechanism behind three features. A routed variable without one is refused (p.198, "the URL addresses a variable by its external ID"); interface membership without one is refused; a saved state without one has no key (p.203). A copy that kept those three flags is a copy the module cannot save — and the 422 would name a variable the author never edited.

So `duplicate` returns **what it had to drop** and the panel says so. That line is the feature, not a courtesy: it is three checkboxes' worth of difference between two rows that otherwise look identical, and an author who is not told spends an afternoon on a saved state that never appears.

`legacy_name` goes with them, and it is the one that could be argued either way. It records what this variable was called when the app was a v1 document with string-keyed parameters — a fact about one variable's history. A copy made today was never that parameter, and a second variable claiming to be it makes the conversion record ambiguous in the one direction it exists to keep clear.

**The contrast with the button beside it is the point of the pair.** p.73's New-variable-from-current "takes the current object set as its input… while **maintaining a reference to the source variable**" — a reference, not a copy. The new set gets a `filter_set` derivation with the source in the first slot and no object set definition of its own, so changing the source's filters moves it too. It lands half configured on purpose: the value to filter on is the author's next decision, the same state the panel's own "Is another set, narrowed" option produces. Guessing a property to make it savable on the click would invent a filter nobody asked for, and the browser test asserts the *refusal* rather than a save.

Offered on object sets only, and **absent rather than disabled** elsewhere — p.73's "object set variables only" is a fact about the kind, not a condition that will pass later.

**The one assertion the unit tests could not make** is that the server accepts what the panel produces. A duplicate carrying the external ID passes everything that does not think to look. So one browser test saves and reads the document back from the API — which needed a `Module.definition()` helper, because reading the panel back only ever confirms the panel. Its first version read straight after the click and reported "the copy was never made" when what had happened was that the read was early; `save()` now waits for the header's "· saved".

**32 mutants, 32 caught, 0 survivors, 0 no-ops.** The single survivor of the first run was **not a hole and not a mutant**: `return null` → `return null as never` is a type assertion, compiled away, with the same runtime value. A runtime suite cannot catch a change that has no runtime. Replaced with one that deletes the guard outright, which the same test catches. The rule for writing these: **mutate behaviour, not types.**

**609 unit tests** (was 578); **322 browser tests** (was 314); 1510 API tests, 1 skipped, unchanged — like §200, this unit adds nothing to the server, and both of its refusals were already there.

With these two, `workshop.md` §3.3 has no ○ rows left.

### 202. Splitting the input widgets, and one sentence that settles it (this session)

Top of `workshop.md`'s widget build order, and a decision that had been sitting in the spec unanswered: split the generic parameter control into Foundry's named input widgets, or keep it and accept the divergence. Five rows of the filtering table read `◑ via generic CanvasParameterControl`.

**Decision 0011: split.** The argument for keeping one control is real — the five share a label, an output variable, and a value the viewer edits, and a `control` prop switching costumes is not a hack. It loses on what p.459–468 actually specifies. Read past the category overview and the five diverge in *configuration*: String Selector has static-or-dynamic options, three display modes and per-mode placeholders; Text Input has a format with a whole rich-text mode behind it; Date and Time Picker has time precision and timezone handling. A shared control would grow a union of roughly twenty props of which each mode reads a quarter, and a panel showing "time precision" beside "show grouping" is a panel nobody can read.

**One sentence settles it on its own.** p.468: "If the percent sign is selected, the output variable of the widget will be the user-entered value divided by 100." That is not a display option. It changes the relationship between what the viewer types and what the variable holds, for one suffix value, on one of the five. A shared control would carry that rule permanently and apply it never.

The record also fixes what happens to `CanvasParameterControl`: **it stays.** Craft resolves a node by `resolvedName`, so deleting the component does not degrade an existing module — it stops the module rendering at all. And it cannot be silently converted either: `control: "select"` fed by a dataset column does what no named widget does, since p.461's options come from a static list or a string array variable and never from a query. Named widgets land beside it; its palette entry goes when all four exist. No migration, for decision 0002's reason — a document that changes when you open it is a document whose history stops meaning anything.

**Numeric Input is the first**, chosen because the percent rule makes it the one that proves the split was necessary rather than cosmetic. `number-input.ts` holds what the viewer types and what the variable holds in one place, because the percent case makes them different numbers and the drift is silent: a field showing `8.2` over a variable holding `0.082` looks correct from either side alone.

Three things it gets right that `Number(text)` does not. Empty is `null`, not `0` — different answers. A half-typed entry is `undefined`, a **third** answer: `null` clears the variable, `undefined` writes nothing yet, and collapsing them makes the field clear itself on the keystroke between `1` and `1.5`. And dividing by 100 is not exact in binary, so both directions round to fixed significant digits and the round trip is asserted as a property.

In the widget, the field is **uncontrolled while it is being typed into**, which is not laziness: driving `value` from the variable on every keystroke reformats the text mid-entry, and with grouping on the caret jumps as a comma appears under it.

---

**Seven survivors, splitting three ways — and the split is the useful part.**

**Two were dead code.** `group()` guarded against a minus sign being grouped with the digits and against exponent form being grouped, and neither can fire: `\B` is a *non-word* boundary, so the position between `-` and the first digit **is** a boundary and no comma goes there; and JavaScript renders exponent form only with one digit before the point, so there are no thousands to separate. Both checked against the runtime rather than argued. §200's rule applied — the branches are gone and the reasoning is in the comment.

**Two were real holes, and they were the two guards that *do* fire** — each survived because its neighbour covered every case I had written down. The shape check exists for the literals `Number` accepts and a numeric field should not: `Number("0x10")` is `16`, quite finitely, so `isFinite` lets it through. The finite check exists for `1e999`, which passes the shape check and becomes `Infinity`. **A redundant-looking guard beside a real one is worth a mutant precisely because the tests that cover one usually cover the other.**

**Two were real holes in the browser tests**, both about the half of the binding typing cannot reach: nothing exercised the field following a variable changed from *elsewhere*, and a field that only ever wrote would sit showing a number nothing holds any more.

And one of those was **an assertion against a moment rather than a clock**. The half-typed test claimed nothing happened, but `expect` passes on its first successful poll — so "still 5" was satisfied before a mutant's write would have landed. It now waits on a marker variable set by the same click, the idiom `test_collapsible_sections.py` established. *The way to check that nothing happened is to find a point after which it definitely would have.*

The seventh survivor was mine and was not a mutant: `void text;` beside a state declaration changes nothing. Same class as §201's `as never`, one turn later, which is how a rule earns a second entry rather than a first.

**37 mutants, 37 caught, 0 survivors, 0 no-ops** after the fixes.

**685 unit tests** (was 609); **335 browser tests** (was 322); 1510 API tests, 1 skipped, unchanged — `name` was already in `REFERENCE_PROPS` and classified `write` in `PROP_DIRECTION`, so the new widget's output variable is refused for deletion and drawn upstream in the lineage graph with no new server code at all.

`workshop.md` §10 goes from 13 of ~52 widgets to 14.

### 203. The Text Input, and the trigger the enter key needed (this session)

Decision 0011's second named input widget, and the first thing on this platform to fire a `submit` event.

**p.465 states an asymmetry and does not explain it**, and the explanation is the design. "Event on enter" is listed under Single line; "initial height" under Text area. The reason is that in a text area the enter key *inserts a newline* — so a widget that also fired an event on it would be fighting the person typing. `text-input.ts` therefore carries a catalogue of what each format has, the settings panel renders from it, and the widget's keydown handler asks it rather than comparing against `"line"` at the call site. A second place that knows which formats submit is a second place to get it wrong when Markdown lands.

**`submit` joins the server's trigger vocabulary**, next to `click`, `row_select` and `change`. Named for the act rather than the key, following the rule already written beside that tuple: a viewer pressing enter is *committing what they typed*, and a trigger called `enter` would need renaming the first time anything else commits an entry. It is distinct from `change` because `change` fires per keystroke and this fires once — which is the whole reason p.465 offers it.

**Markdown is absent, deliberately.** p.466 describes "a rich text editing experience powered by the same editor used in Notepad", with a formatting toolbar and a raw/rich toggle. That is an editor, not a format flag. A third dropdown option that drew a plain textarea is precisely what every catalogue in this codebase exists to prevent, so the row stays ◑ and the format stays out of the list.

Height is in **rows rather than pixels**, stated as a divergence: p.465 names no unit, and a pixel height set by an author is wrong the moment a viewer's font size differs from theirs.

---

**And a §202 gap, found while adding the catalogue entry rather than by the harness.** `CanvasNumericInput` fires `change` but was never added to the events panel's `change` widget list — so an author could not wire the event the widget was already announcing. That is §194's shape seen from the other side: there an offer nothing fired, here a firing nothing could offer. **Both are invisible from inside one half**, which is why the browser test now asserts the panel offers exactly "Changed" and "Submitted" on a text input.

**Two bugs caught by writing the unit tests first**, both in code that reads fine:

- `Number(null)` and `Number("")` are `0`, which is finite — so `rowsOf` coerced before deciding absence and read "not set" as "no rows at all", clamping it to the minimum instead of defaulting.
- `"constructor" in TEXT_FORMATS` is true for a plain object, so a document naming it resolved to a "format" that is a function, and the widget would read `.multiline` off it and get `undefined`. `Object.hasOwn` now.

---

**Two survivors, and both were the same mistake in shapes I did not recognise as the same one** — §201's lesson arriving twice more.

**The fallback format was compared to its own constant.** Every assertion said `formatOf(x)` equals `DEFAULT_FORMAT`, so moving the constant to `"area"` moved the expectation with it. The fallback matters *as a single line*: a document naming a format this build does not know gets the narrower of the two, so a module does not silently acquire paragraph fields where it had one-line ones.

**The clock and the marker were the same variable.** The test for "enter does not fire in a text area" pressed Enter, then clicked a button whose effect set the *same* `v_mark` — so the assertion passed because the click had erased the evidence, not because nothing wrote it. A mutant firing submit in every format sailed through.

That is a sharper version of §202's rule than §202 stated it. §202 said: to assert that nothing happened, find a point after which it definitely would have. §203 adds the other half — **the clock must not be able to overwrite the thing being checked.** A second observable is the fix; the *same* observable is a test that cannot fail.

**35 mutants, 35 caught, 0 survivors, 0 no-ops** after the fixes. Four layers this time, since the trigger vocabulary is server-side.

**1512 API tests** (was 1510), 1 skipped; **711 unit tests** (was 685); **348 browser tests** (was 335).

`workshop.md` §10 goes from 14 of ~52 widgets to 15.

### 204. The String Selector, and a test that could not see through a correction (this session)

Decision 0011's third named input widget, and the biggest of the four: p.459–461 is not one widget with options but a **two-by-two matrix**, and both axes have consequences.

**The selection changes what the variable holds.** p.461: "If the selection is set to Single, the output variable will be a string variable. If the selection is set to Multiple, the output variable will be a string array variable." That is the *second* setting in this family to do that, after §202's percent suffix — and two of four is no longer a coincidence but the clearest evidence yet that decision 0011 was right. A binding made under one selection is **invalid** under the other, so changing the selection clears it.

**The display axis is not free either.** Radio buttons exist only under Single, checkboxes only under Multiple. So `display` is a setting *within* a selection, and one click in the panel leaves a document naming a pair p.461 does not have. Every read goes through `displayOf`, which resolves it; trusting it draws radio buttons over a variable holding a list.

Three smaller decisions, each with the reason in the file. **Empty is `null` for single and `[]` for multiple** — an `array` variable with no value is an empty list, and a derivation reading it breaks on `null` where it handles `[]` fine. **Blank options are dropped and duplicates collapse** — two identical options are one choice drawn twice, indistinguishable in a `<select>`, and as radio buttons they share a name and fight over which is checked. **`chosenOf` returns a list for both selections**, so the checkbox arm cannot drift from the radio arm.

p.444's *Checkbox* row closes here rather than as its own widget, because p.461 shows what it is.

---

**The finding that outlives the unit: a test cannot see through a normalising read.**

Two mutants survived, each deleting one of the two corrections the panel makes when the selection changes — the variable clear and the display reset. Both had tests. Both tests were incapable of failing.

The widget defends itself by **correcting on read**. The variable picker lists only variables of the selection's kind, so a `<select>` still bound to a string variable renders with value `""` the moment the options no longer contain it — identical to having been cleared. The display select's value goes through `displayOf`, so it reads `dropdown` whether or not the prop was reset. **The render shows the corrected value; the prop keeps the stale one; and the prop is what gets saved.**

The defences are right and stay. What was wrong is where the tests looked. Both now save and read the document back from the server, the way §201's duplicate test does. The rule: **where code defends itself by normalising what it reads, a test has to look at what was written.** It is the mirror of §203's clock — there the test could not see a change because something erased it; here it could not see one because something corrected it.

A third survivor is **withdrawn as equivalent**, with the reasoning recorded in the model rather than in a note nobody will find: `chosenOf` always allocates, so `pick`'s copy is never the caller's array and mutating it is unobservable.

**§191's drift guard fired on new work for the second time.** `optionsVariable` holds a variable id — p.461's dynamic option generation — and was in neither copy of `REFERENCE_PROPS`, so the option list could have been deleted out from under a configured selector. It is the same widget family as §198's `arrayVariable`, and for the same reason: a widget whose *options* come from a variable is exactly the shape that gets missed, because the obvious reference is the output one. `PROP_DIRECTION` being keyed by `REFERENCE_PROPS` since §200 then refused to compile until the direction was stated too — the guard-as-a-type doing its job one layer down.

**43 mutants, 43 caught, 0 survivors, 0 no-ops, 1 withdrawn.**

**756 unit tests** (was 711); **365 browser tests** (was 348); 1512 API tests, 1 skipped, unchanged.

`workshop.md` §10 goes from 15 of ~52 widgets to 16, and only the Date and Time Picker is left before the generic control's palette entry can go.

### 215. The Object Selector, and a widget documented in one line (this session)

p.444: "Object Selector: Allow the user to select multiple objects from a list of objects." That
sentence is the **whole specification** — alone among the filtering widgets it has no page of its
own — and what to do about that is the unit's only real decision.

**The temptation with a one-line spec is to fill the gap with your own design and call it
parity.** A multi-select "obviously" wants select-all, invert, a chip row of what is chosen,
maybe a maximum. Foundry documents none of those, and building them would have produced a widget
that looks like Workshop's and is not. So the Selector is the Object Dropdown with a different
selection: the same model file, the same p.458 search rules, the same property lines, the same
clause output carrying several keys instead of one. Nothing was added to its settings panel that
p.455-458 does not already give the Dropdown, and one thing was *removed* — p.457's Allow no
selection, which is meaningless for a widget whose resting state is already none.

Three behaviours differ, and each follows from the word "multiple" rather than from taste:

* **No auto-selection.** p.457's setting exists because a single dropdown with nothing chosen
  starves every downstream widget. Pre-ticking one row of many would be a filter nobody applied.
* **The list stays open while ticking**, the whole point being to choose several.
* **The empty selection is still stated** — `in []` on load — for §207's reason: a variable
  nothing has written means *no narrowing*, so downstream would receive the whole set rather
  than none of it.

The one new function is `selectionSummary`, and its middle case is why it is a function at all:
none is a prompt, several is a count, and **one is the object's own title** — a reader who has
picked one can see which, and showing "1 selected" there would withhold an answer the widget
already has.

---

**A test that passed for free, because a rule two units old was right.**

The thing multiple selection gets wrong most often is losing what is already ticked when the list
is filtered: a reader narrowing to find their second object loses their first. That test passed
on the first run, and the reason is §207's decision that **the variable is the source of truth,
not a copy in component state**. Ticks live in the clause list; the search filters what is drawn;
the two never touch. A widget holding its own `Set` of keys would have had to remember to survive
re-filtering, and would have looked correct until somebody typed.

Worth recording as the positive case: the entries in this file are mostly bugs a rule would have
prevented, and this is a rule preventing one two units after it was written, in a widget that did
not exist when it was made.

---

**Four widget survivors, and three of them were the same mistake.**

Every selection test in this file reads the *downstream table*, which is the right instinct — the
clauses are what the module acts on, and a widget can draw the right ticks while writing the
wrong ones. But it left the mirror uncovered: a selector whose boxes **never tick**, or tick
**all at once**, passes every one of those tests, because the clicks still write the right
clauses. Both mutants survived, in the same run. Nothing exercised a non-default search mode
either, so `searchMode` could have been hardcoded and the whole file would still be green.

The lesson is not "assert the checkbox too". It is that **choosing the strongest observable can
leave the obvious one untested.** The downstream table was picked deliberately, because it is
harder to fake; the reader's own feedback then went unasserted precisely *because* it looked too
simple to be worth a test. A widget with no visible state is unusable whatever it writes.

The fourth was the tick's position — a class no rule matches passes every check that is not a
measurement (§211), so it is measured: the box's right edge left of the title's left edge, and
their tops within a line of each other.

---

**A CSS class name that already meant something else, and the bug it was hiding.**

The last survivor was the tick's layout rule, and it took three rounds to understand — each one
worth writing down, because they are three different mistakes.

**First: the rule was dead.** `.canvas-selector-option` has meant the String Selector's option
grid since §204, and that rule comes *later* in the file, so it won. The Object Selector's rows
were being styled by a widget they have nothing to do with. Nothing looked wrong, because that
rule is also a flex row — and either widget could have broken the other from then on. This is
§211's import collision in a namespace with **no compiler to catch it**: two modules exporting the
same name at least fail to typecheck sometimes, while two rules claiming the same class silently
resolve by source order. Renamed to `canvas-object-tick`.

**Second: the renamed rule was still untestable**, because the mutant that swapped the class back
kept passing. Measuring rather than reasoning (§209) settled it in one run: the row was
`display: flex`, height 31.75 — **one line**. `align-items: start` and `center` cannot differ on a
row one line tall, so no assertion about the tick's position could separate the two rules.

**Third: the reason it was one line was a real defect.** p.457 says a property is displayed
*beneath* the object title. `.canvas-dropdown-option`'s grid stacks its **direct** children, and
in the Selector the title and its details sit one element deeper inside a wrapper — so they ran
inline after the title. Every existing test passed, because they **counted** the detail lines
rather than measuring where they were. The wrapper stacks now, and a test measures that the first
detail's top is below the title's bottom.

So a collision hid a dead rule, the dead rule hid a flat layout, and the flat layout hid a
mis-rendered widget — and the thing that broke the chain open was a mutant nobody could kill.

---

**5 new model mutants (40 on the shared file) and 22 widget mutants, 0 survivors, 0 no-ops**
after the fixes.

**1081 unit tests** (was 1076); **509 browser tests** (was 491); 1521 API tests, 2 skipped,
unchanged.

`workshop.md` §10 goes from 25 of ~52 rows to 26, counted from the table. **Build-order item 6's
two pickers are done**; what is left of it — Inline Action depth — is blocked on `ontology.md`
item 4, action parameters and rules, which is designed (decision 0007) and unbuilt.

---
---
---
---

### 214. The Object Dropdown, and a setting the platform refuses (this session)

p.455-458's widget: p.457's Label, Input object set, Selected object output and Allow no
selection; the property lines under each title; p.458's Hide null properties, Sort items by and
all three Search items by modes.

---

**Most of this widget is other widgets, and that is the finding.**

p.457's output is "a single object set of the currently selected object" — which is exactly what
the Object Table's p.224 Active object is, down to the shape: a list of *clauses* that a
`narrow_set` derivation resolves against the widget's own set, so a selection keeps meaning what
it means when the set changes underneath it. And p.457's **Allow no selection** turned out to be
p.224's **Disable active object auto-selection** with the sign flipped: off means pick the first
object so downstream widgets have something on load. Two settings, on two pages, of two widgets
in two different categories of Foundry's documentation — one question about one variable shape.
`autoSelectKey` took `enabled: !allowNone` and nothing else was needed.

The property lines under each title are the Property List's `visibleProperties`, applied once per
row rather than once, and p.458's "hidden on a **per object** basis" falls out of that for free.

This is §213's finding with the sign flipped too. There, a rule restated one level up was deleted
because the level below already enforced it. Here, two specifications describing one mechanism
were **joined** rather than implemented twice. The tell is the same in both cases — a rule you can
point at somewhere else — and what differs is only whether the other copy is above you or beside
you.

---

**p.458 asks for a sort this platform deliberately refuses.**

"Sort items by: Specify the order in which objects are sorted." `object_sets.parse_sort` takes
four sorts and refuses every property name in a sentence: instance properties are stored untyped,
so Postgres and OpenSearch would order 250 and 40 differently, and text orders differently again
(decision 0006). A property picker here would have produced a 422 where a list should be, on a
setting that looked like it worked in the panel.

Three ways to handle that, and only one is honest. Faking it client-side would sort *the loaded
page* and claim to have sorted the set. Leaving the control out entirely would lose the sorts the
language does have. What is built offers those four, and — the part worth keeping — **reads a
property name a document holds back to the default** rather than sending it on. A module written
against p.458's wording then loses its ordering instead of losing its list.

The rule: when a specification asks for something the platform refuses on purpose, the widget's
job is to **fail soft on the document and say why in the panel**, not to approximate the feature
and not to pretend the setting does not exist.

The same shape governs the search. p.458's "all searchable properties in the object set" is an
*or* across properties, and every clause the object-set language takes is an *and* — so search
runs over a loaded page of 200, and the widget **says so on screen** when the set is bigger. A
search box that answers about part of a set looks exactly like one that answered about all of it.

---

**One survivor, and it was about a property called `null`.**

`titleOf` guards `!titleProperty || !values`; the harness removed the first half and nothing
noticed, because `values[null]` is `values["null"]` and no fixture has a property by that name.
`null` matches the api-name pattern `^[a-z][a-z0-9_]{0,99}$`, so it is a legal one — and without
the guard, "this type has no title property" would have depended on whether some property happened
to be called that. The input is exotic; the confusion is not, and one line of test pins it.

**The server caught a fixture error the browser could not have.** The selection variable was
declared as an `object_set`, and the save came back with "variable 'The selection' is an object
set but names no object type to draw from" — it is an `array`, because what the widget writes is
clauses and the *set* is what `narrow_set` makes of them. A refusal in a sentence, at the point of
the mistake, instead of a widget that renders and quietly narrows nothing.

---

**Two widget survivors, and both were tests that could not fail.**

The blank-label test used `""`. That is falsy whether or not it has been read through the model,
so it asked nothing — the case that separates them is `"   "`, which is truthy and would have
drawn a row of nothing above the widget. And the other half of the same test used Playwright's
`to_have_text`, which **normalises whitespace**: `"  Site  "` and `"Site"` compare equal to it, so
the trim was invisible from both directions at once. It reads `text_content` now.

The second was the option list floating. Nothing measured it, and the mutant that puts the panel
back in flow broke nothing — every option was still clickable, just with the rest of the page
shoved down as it opened. It is measured on the widget *below* the dropdown, because the toggle
sits above the panel and would not move even in flow: the control that reflows is not always the
one that moves.

---

**35 model mutants and 26 widget mutants, 0 survivors, 0 no-ops** after the fixes.

**1076 unit tests** (was 1046); **491 browser tests** (was 473); 1521 API tests, 2 skipped,
unchanged.

`workshop.md` §10 goes from 24 of ~52 rows to 25, counted from the table.

---
---
---
---

### 213. The Object View widget, and a guard that was already there (this session)

p.259-263's widget: the input object set, p.261's Object View Mode with the reader's toggle,
p.262's Hide header and Empty state message. It finishes `workshop.md`'s build-order item 5.

**It renders the platform's own `ObjectView`** — the one the Object Explorer and the traversal
dialog render — rather than a Workshop copy of it. A second renderer would be a second place for
a configured view, a prominent geopoint's map and a derived property to drift, which is the
mistake `object-properties.ts` exists to record. That decision is also what made the unit small:
almost everything p.259-263 asks for was already built somewhere a reader could reach it.

The import goes through `next/dynamic`, because `object-view.tsx` imports `CANVAS_RESOLVER`
from `widgets.tsx` — a configured view *is* a module, and rendering one needs the widget table.
A static import back would close the cycle, and which half ends up `undefined` then depends on
which module the bundler reaches first: a blank widget with no error.

---

**The build order was wrong about this item four times, in three different ways.**

§210 and §211 needed no ontology work at all. §212's traversal existed and the widget still
needed a new endpoint, because a builder configures before there is data — "does the data layer
support this" and "can this be configured" are separate questions. §213 is the one the item had
always said would need the Object Views work, and it did: it renders one. **The work had been
finished for eleven units by the time anybody checked.**

That is a different failure from the other three, and the one worth naming: a build order records
what was true when it was written, and nothing in it ever goes back to ask whether it still is.
Three entries in that item now say so.

---

**A comment that said "there is no setting that could express this" was falsified by this unit.**

`object-view.tsx` opened with the claim that the standard view "cannot be turned off, because the
rule is about the reader rather than about configuration — there is no setting that could express
'hide it'". Workshop p.261 **is** that setting. The claim was true about the platform's own
surfaces and was written as though it were true about the code, and nothing pointed at it when
that stopped being so. The same sentence had been copied into `ontology.md` §4.2's table. Both
now say what actually holds: every caller that is not a configured widget takes the defaults, and
the widget's toggle defaults to on, so withholding the standard view takes a deliberate act about
one widget in one module.

---

**The harness deleted code rather than finding a missing test.**

The widget asked the server whether the bound object type had a configured view and fed the
answer into two model functions — `startsStandard` and `showsToggle` — so that a stale
"configured" preference would fall back and a switch with nowhere to go would be withheld. Both
are correct rules. Replacing that answer with a constant `true` **changed nothing on screen**,
and the mutant survived.

It survived because `ObjectView` already does both, one level down, and is tested there. The
widget's copy could never be observed, whatever it said. Two functions, one query and eight unit
tests went; the browser test that covers the behaviour stayed, because it was always testing the
level that decides.

**The tell is a survivor whose code is a rule you can point at somewhere else.** §195's version
of this was a fix that fixed nothing; this is a guard that guards nothing, and it is harder to
see, because the behaviour is right either way and the duplicate reads like defensiveness. The
question to ask a surviving guard is not "which test is missing" but "who else already refuses
this" — and if somebody does, the missing test is not missing.

One further mutant is recorded as **equivalent** in the model: `viewModeOf(mode) === "standard"`
and `mode === "standard"` cannot differ while `VIEW_MODES` has two keys. The read stays anyway,
because the two stop agreeing the moment p.261 grows a third mode and the raw comparison would
then treat it as configured — silently.

---

**Two header tests could not fail, and the signal to fix them was already there.**

`standard-object-view` is on the element in all three of its states — loading, error and ready —
and the component says why in a comment: without it, "failed to load" and "failed to render"
look identical from outside. So `expect(view).to_be_visible()` followed by
`expect(".sov-head").to_have_count(0)` asks about an absence while the view is still *loading*,
where everything is absent. Both header mutants sailed through; the test asserting the header
can be hidden passed against a build that never hid it.

The fix was one locator: `[data-state='ready']`. **The clock (§202) was already provided, with a
comment explaining what it was for, and the test did not use it.** That is worth more than
another entry about waiting: an affordance nobody reaches for is not much better than one that
does not exist, and the place to look for it is the component's own reason for existing.

---

**§211's aliasing rule fired again, and the compiler caught it this time.** `emptyMessageOf`
already meant the Object Table's, which takes two arguments, so the duplicate import failed to
typecheck instead of quietly resolving to the wrong function. That is luck, not a safety net —
§211's collision was two numbers and typechecked perfectly. The rule does not depend on whether
`tsc` happens to notice.

---

**16 model mutants and 16 widget mutants, 0 survivors, 0 no-ops** after the fixes, plus one
withdrawn as equivalent and one withdrawn as not a mutant at all (it inlined a function's own
body — §201's rule with the sign flipped).

**1046 unit tests** (was 1038 — eight were *removed* with the guard they tested and nine added);
**473 browser tests** (was 463); 1521 API tests, 2 skipped, unchanged.

`workshop.md` §10 goes from 23 of ~52 rows to 24, counted from the table.

---
---
---
---

### 212. The Links widget, and a fixture that never crossed its own boundary (this session)

p.268-272's widget: the input object set, p.270's "All link types" against "Specify link types",
p.272's link selection and label override, and p.271's Default link expand. It is the third of
`workshop.md`'s build-order item 5, and the third time that item's "depends on ontology work"
has been wrong — from a new direction, which is the part worth keeping.

---

**A link is identified by its type *and* its direction.**

`links_for_type` returns a link type once per end it occupies, so a self-link — Person manages
Person — comes back **twice** on purpose: "my manager" and "my direct reports" are different
questions carrying the same `link_type_id`. Every selection, override and expansion in this
widget is keyed on `${link_type_id}:${direction}`. Keyed on the id, ticking one end would tick
both, an override meant for one would rename both, and **nothing on screen would look wrong** —
which is why the browser fixture gives Ada eleven reports and no manager, so her two ends of the
one link carry different counts and no single row can stand in for both.

The row's label is the **side name**, not the link type's display name, because a link called
"manages" reads backwards on the inbound side.

---

**The new endpoint is the interesting part of "no ontology work needed".**

Traversal has existed since §155, and the widget still needed something new:
`GET /object-types/{id}/links`, which lists a type's links with no object in hand. p.272's
dropdown is a question a builder asks *before* there is data to traverse, and answering it from
the instance endpoint would have made the set of configurable links depend on whether the bound
object set happened to be empty — a widget configurable on a Monday and not on a Tuesday.

So the build order's premise was wrong a third time, but not in the way the first two were:
**"does the data layer support this" and "can this be configured" are separate questions**, and
only the first had been asked. That is now written down beside the item.

---

**p.271's expansion is seeded, not derived.**

Recomputing which sections are open on every render would reopen a section the moment anything
else on the page refetched, and the reader would be clicking the same triangle with no idea why.
The seed follows the object *and the configuration*, so an author who swaps which link the widget
draws sees the new section open rather than a fully folded widget and a setting that looks broken.

---

**The survivors, and the one worth remembering.**

The model gave one: `chosenOf` asked only whether a key was *present*, and a numeric key is
truthy. It resolves against no link — `linkKey` builds a string — but the settings panel lists
what `chosenOf` returns, so an author would have been shown a row nothing could fill.

The widget layer gave five, and four are ordinary: nothing measured that the header is the
full-width control; nothing opened the settings panel under "All link types" to find the link
picker absent; every `defaultExpand` in the fixture was already legal, so reading the prop raw
and reading it through the model were the same; and nothing changed the configuration after
mount, so the expansion seed never had to follow it.

The fifth is the family again. **The header reports the link's `total`; the section under it
lists the first page, which the traversal caps at ten.** The fixture gave Ada two reports, so
`total` and `items.length` were both 2 and a header that counted its own list passed every
assertion — it would have been wrong by exactly the amount nobody could see. The tell is a
fixture sized *under* a limit the code is written against: a boundary the data never crosses is a
boundary no test can hold. Ada now has eleven reports, and the widget says "11" over a list of
ten.

---

**33 model mutants, 27 widget mutants and 7 API mutants, 0 survivors, 0 no-ops** after the fixes.

**1038 unit tests** (was 1013); **463 browser tests** (was 444); **1521 API tests**, 2 skipped
(was 1515).

`workshop.md` §10 goes from 22 of ~52 rows to 23 — **counted from the table this time.** The
number written at the top of that section said 17, and the running total in these entries said
20; neither matches what the rows actually say, because both were carried forward by hand. The
header now states how it was arrived at, so the next person can check it in one command instead
of trusting it.

---
---
---
---

### 211. The Property List, and two column limits that were not the same (this session)

p.265-266's widget: the input object set (first object only), p.265's Layout, p.266's property
selection with a column count, and Hide null properties. Like §210 it needed no ontology work —
only the object set variables and property renderer that already existed. **That is twice the
build order's "depend on ontology work" has been wrong about this group**, which is now written
down in `workshop.md` before it is wrong about the third.

---

**The bug worth the unit is one word long.**

`MIN_COLUMNS` and `MAX_COLUMNS` already meant **2 and 8** in `widgets.tsx`, imported from the
String Selector's option grid. p.266's are **1 and 6**. Imported without aliasing, the number
input in the panel would have offered a minimum of two columns for a widget whose model clamps
to one — and it *typechecks*, because both modules export a number under that name. The
settings panel and the model would have disagreed about the legal range with nothing to say so.
Both are renamed at the import, with the reason beside them.

**Two rules carried forward.** A blank value counts as null, because a CSV column that was empty
arrives as `""` rather than `null` and hiding one while keeping the other looks arbitrary to
somebody who cannot see which the store holds. And nulls hide only once there is something to
judge — every value is `undefined` while the instance resolves, so hiding then would empty the
widget on load and fill it a moment later, which is §210's rule about whether a widget renders
at all, one level down.

---

**Two survivors, and both were tests that could not fail.**

The browser tests read labels with `count()` and `text_content()`, neither of which retries, so
calling them straight after `settled()` asks the page a question before it has the answer and
gets `[]`. **Three of the four label assertions had been passing on timing luck**; the fourth
failed and was the only reason it came to light. They now wait on the count first — the clock
again (§202).

They also read `text_content` rather than `inner_text`. The stylesheet upper-cases these labels,
so an assertion on the *rendered* text would have passed just as happily if the display names
had been replaced by the api names in caps — which is precisely the mutant the label test
exists to catch.

And the model's "does not mutate the list it was given" used `hideNull: true`. That path
**filters**, and `filter` allocates whether or not anything was copied, so the assertion held
against a version that handed back the caller's own array. The copy only matters where the list
is returned directly, and there the alternative is returning the object type's property array —
which a caller sorting for display would reorder for everything else reading it.

One widget mutant is recorded as **equivalent**: `rows?.[0]` and `rows?.[length - 1]` cannot
differ, because the widget fetches one row. p.265's "only the first object will be displayed" is
kept by the *page size* rather than by the index, and a widget that fetched more to make the
index testable would be spending a round trip on a test.

**19 model mutants and 12 widget mutants, 0 survivors, 0 no-ops** after the fixes.

**1013 unit tests** (was 997); **444 browser tests** (was 435); 1515 API tests, 2 skipped.
`workshop.md` §10 goes from 19 of ~52 widgets to 20.

---
---
---
---

### 210. The Object Set Title, and a widget whose job is to be absent

p.274's widget, and the first of `workshop.md`'s build-order item 5 — which turned out not to
depend on ontology work at all, only on the object set variables and title properties that
already existed. The input object set, Contains single object, Show icon, Title override, and
Render widget when the object set is empty with its placeholder object type.

**Three rules worth naming, and each is a place the obvious implementation is wrong.**

p.274 says the override is "only available when Contains single object is disabled".
*Available* is a statement about the panel. One click flips the toggle and leaves the override
sitting in the document, so the rule has to hold on the **value** as well — otherwise a
leftover override quietly renames somebody's object and reads as deliberate.

**A single-object title never falls back to the type name.** "Site" where "Site 14" was meant
is not a degraded answer, it is a wrong one that looks right: nothing on screen distinguishes
it from an object genuinely called that. The fallback is the empty string.

**Unresolved is not empty.** A set whose definition has not come back has an unknown count, and
reading that as zero would make every module carrying this widget flash a gap on load and then
fill it — §81's rule for `visibleWhen`, arrived at from the other direction.

**Two divergences, both stated.** Show icon draws a mark in the object type's *colour* carrying
the icon **name** as its accessible label, because the `icon` field holds a name like `cube` and
this platform has no icon set to draw one from. And on the *canvas* a hidden widget says why it
would be absent rather than going blank: p.274's rule is about the module view, and a builder
who cannot see the widget cannot select it to turn the setting back off. **Enable drag** is ○ —
p.274 makes it conditional on a data bank service that does not exist here, and a drag source no
drop zone accepts promises something nothing will do.

---

**The harness found the same shape §205 did, in the tests rather than the code.**

Both placeholder assertions used the module's **own object type** as the placeholder. So "used
the placeholder" and "ignored it" produced the same string, and the two mutants that gut the
feature — never consult the placeholder, consult it always — both sailed through. The control
value coincided with what it was being contrasted against. They now declare a second type with
a different display name, and there is a new test for the half p.274 states and nothing checked:
a placeholder applies *"if the inputted object set is empty"*, so one that stood in always would
rename every non-empty set to whatever an author once picked as the stand-in.

One survivor in the model is recorded as **equivalent rather than a hole**: `single` is provably
`false` where `overrideFor` is called, because the branch above returns unconditionally, so
swapping it for `false` cannot differ. The argument stays — the early return is the thing most
likely to move, and this is what would still be right if it did.

**17 model mutants and 16 widget mutants, 0 survivors, 0 no-ops** after the fixes.

**997 unit tests** (was 980); **435 browser tests** (was 423); 1515 API tests, 2 skipped.
`workshop.md` §10 goes from 18 of ~52 widgets to 19.

---
---
---
---

### 209. The browser suite tidies up after itself

Not a parity item. §208's verification run went red on a test that had nothing to do with it,
and chasing that properly turned up three things stacked on each other.

**The suite had never cleaned up.** Every test file creates object types in one shared dev
workspace and none removed any; after a session of runs there were about **1,400**. The
Ontology Manager's listing fetches and renders every type in the workspace, so opening its Edit
dialog took **7.2 seconds**, and a test leaning on Playwright's 5-second default failed — with
nothing wrong in the product and nothing wrong in the diff. The suite had aged into failing on
its own leftovers.

The recording lives in `Api.call` rather than in each test, because that is the one funnel every
write goes through: a per-test list would be right for the tests that remembered and silently
wrong for the rest. It stores the **delete path built from the create path**, so it needs no
workspace id of its own and cannot disagree with the one that created the type. Teardown is
best effort and reports rather than asserts — the API refuses to delete an `active` or
`promoted` object type (p.256), and those are exactly the types the suite creates to prove the
refusal works, so a cleanup that insisted would fail on them. It runs after the last assertion,
where an exception would turn a green suite red for tidying up.

Verified rather than assumed: 18 tests across two files, **29 object types before and 29
after**. Across a full browser run the residue is **7** — the `active` and `promoted` types the
API refuses to delete, one per test that proves the refusal — so the workspace went 29 → 36 for
423 tests rather than growing by hundreds. Not zero, and worth saying so: at seven a run this
takes two hundred runs to reach where one session got, which is a different problem rather than
no problem.

The previously red test passes three runs out of three, in 3.5s rather than timing out at 10 —
and the whole suite got **seven minutes faster** (25 minutes to 18), because every test that
touched an ontology page had been paying for those 1,400 rows.

**The defect underneath is still open and is now written down**: `ontology.list_types` has no
`LIMIT`, so the listing is O(every type in the workspace). Fixing it properly means the type
*pickers* — eight call sites — become searchable rather than exhaustive, since a dropdown that
silently truncates is worse than a slow one. That is its own unit and it is recorded in
`docs/parity/ontology.md` rather than half-done here.

**And a correction.** The first version of §208's note asserted a mechanism I had not measured —
that past ~1,200 types the dialog "stops producing the checkbox". It does not; it produces it
after 7.2s. The rough-edge rule now records *that* mistake rather than repeating the guess.

---
---
---
---

### 208. The Object Table's display options, and a grid that never scrolled

p.224-225's Display & formatting block: lines per row, value wrapping, frozen columns, the
empty state message, a custom "No value" display, fit columns horizontally, narrow headers,
and conditional formatting colouring the whole cell. On paper a list of CSS one-liners.

---

**The grid has never scrolled sideways, and nothing had noticed.**

`.canvas-frame-area` is a grid item, and a grid item's default `min-width: auto` lets it grow
to fit its content — so a table wider than the page pushed the *whole module* out instead of
scrolling inside its own `.data-grid`, which has carried `overflow: auto` since the day it was
written and never once got to use it. The bug predates this unit and applies to every wide
table; frozen columns are only the feature that made it impossible to ignore, because a column
pinned against a grid that cannot scroll has nothing to stay put against.

**A control test is what found it.** "The frozen column did not move" passes perfectly against
a table that cannot move at all, so the test beside it asks whether an *unfrozen* column
scrolls away. That one failed. The frozen one had been green the whole time, for the wrong
reason — the same shape as §207's container off-by-one, and the second unit running where a
passing assertion was the one to distrust.

**One more thing only a browser could settle**: `display: -webkit-box` stops a `<td>` being a
table cell at all, taking the column widths with it, so the line clamp lives on an inner
element. That is an implementation which passes every unit test there is and is visibly wrong
on screen, which is what the browser layer is for.

**And one thing the harness took back.** The row height uses a cell's `height` rather than
`min-height`, and the comment beside it claimed a table cell *ignores* `min-height` — so the
choice read as a bug the browser had caught. It had not: the harness planted the swap and it
survived, because Chromium honours `min-height` on a table cell even though the property is
undefined there. `height` stays, since the defined behaviour is the one to rely on, but it is a
difference that would only show in another engine and this suite cannot see it. The claim was
corrected and the mutant dropped rather than left standing as a permanent false survivor.

**And the clamp was clipping rather than widening.** A clamped, overflow-hidden box does not
report the width its content needs, so an unwrapped value inside one was cut off where it
should have widened its column and let the grid scroll. The clamp now applies only when
wrapping is on — the only time it has anything to do.

---

**The harness's two survivors are §203 read backwards.**

`linesOf` and `frozenOf` each guarded against `null`/`""` before coercing, and deleting both
guards changed nothing. §203's `rowsOf` needed exactly that guard, because `Number(null)` is a
finite `0` and zero rows was a genuinely different answer from "not set". Here it is not: the
default is the clamp floor in both, so a coerced `0` lands on precisely the answer absence
gives. **Same coercion fact, opposite conclusion, and what decides it is whether the default
coincides with the clamp.** Both guards are gone rather than excused.

**Two divergences, both stated.** `∅` becomes p.224's "No value" **in this widget only** —
`PropertyValue` grew an optional `emptyText` so a page about one widget does not restyle the
rest of the platform. And Fit columns defaults **on**, against p.225's wording, because every
table this platform has drawn is full-width and a new setting must not change how documents
that predate it are drawn.

**28 model mutants and 18 widget mutants, 0 survivors, 0 no-ops** after the fixes (one
mutant removed as equivalent in Chromium, verified rather than assumed).

**980 unit tests** (was 958); **423 browser tests** (was 408); 1515 API tests, 2 skipped.

**One browser test is red and it is not this unit's.** `test_required_properties.py`'s Ontology
Manager test fails against `origin/main` in this environment exactly as it does here, and it
passed earlier in the same session with no code change in between.

**The first version of this note asserted a mechanism I had not measured** — that past ~1,200
object types the Objects page's Edit dialog "stops producing the checkbox". It does not. The
dialog opens in 0.3s and the checkbox appears **7.2 seconds** after that; Playwright's default
`expect` timeout is 5s, so the test times out on a page that was going to answer. The same test
with a 30s timeout passes 3 runs out of 3, and with the default fails 3 out of 3.

The slowness is real and its cause is `ontology.list_types`, which has **no `LIMIT`** — the
Objects page renders every object type in the workspace, and the shared `operations` workspace
had accumulated about 1,400 of them because the browser suite created object types and never
removed any. So fixture debris was the *trigger*, an unbounded list endpoint is the *defect*,
and the test's reliance on a default timeout is what turned it into a red suite. Raising the
timeout would have hidden all three. **§209 fixed the trigger**; the unbounded endpoint is
still there and is written down in `docs/parity/ontology.md`.

---
---
---
---

### 207. The Object Table's selection outputs, and a set that could not be empty

p.224's Selection block, and the fourth item of `workshop.md`'s library build order started:
the **Active object** output, auto-selection of the first row with p.224's setting to disable
it, **Enable multi-select**, and the **Selected objects** output.

**The widget writes clauses, not a finished set definition.** A clause list is what
`narrow_set` consumes — the Pivot Table's drill-down already works this way — so a selection
means whatever it means *against the table's current set*. Storing a definition would be
closer to p.224's wording and would freeze the base set at the moment of the click: filter the
table afterwards and the selection variable would go on describing rows that are no longer
there.

---

**Building it honestly found something the platform could not say.**

p.224 wants "an empty active object at load time" when auto-selection is disabled, and there
was no value for it. A variable nothing has written holds no clauses; no clauses means *no
narrowing*; so every downstream widget would have received the whole table — three objects
selected because none was. `object_sets.parse` refused `in []`, and that refusal sat directly
beside the one for a missing value and looked like the same rule.

**It is not the same rule, and the difference is direction.** A missing value must not
*widen* a set: that is decision 0002's failure, where an unset parameter made a map show more
rows than it should. `in []` narrows — to nothing — which is the safe direction and the only
honest reading of "is a member of no values". Keeping the refusal *caused* the bug it was
written against. Both stores already agreed (`= ANY(ARRAY[])`, `terms: []`, and the reference
`matches` all find nothing), so the change is one refusal and a cross-store case.

That forced a second distinction into the model, and it is the one worth remembering:
**"nothing is selected" and "nobody has said" are different values, and only one of them is
safe to hand downstream.** `keysOf` cannot tell them apart — both are no keys — so there is a
separate `hasSelection`, and the widget *states* emptiness on load rather than leaving the
variable alone.

**p.224's "auto-selection only triggers when the widget is visible" is also not free.** A
collapsed section keeps its children mounted — deliberately, so a table inside one does not
refetch every time somebody folds it away — so the table is running, has its rows, and would
select one for a viewer who cannot see it, opening the drawer p.224 describes on a row nobody
chose. An `IntersectionObserver` answers it, and answers the hidden tab and the closed overlay
with it; a walk up the Craft tree looking for a collapsed ancestor would have needed a case
for each.

`activeVariable` and `selectedVariable` went into all four reference lists as **writes** — the
first entries added there that a widget produces rather than reads — and `PRIMARY_KEY` is
pinned to the server's constant by a test, because a clause naming anything else filters on a
property that does not exist, which narrows to nothing and is indistinguishable from an empty
selection on both stores.

---

**The harness found the same two shapes it keeps finding.**

Two survivors in `keysOf`, and they were a pair: dropping the operator check changed nothing
because the test clause had a scalar value and the *shape* check refused it anyway, and
dropping the shape check changed nothing because no test ever handed it a key clause whose
value was not a list. **Each guard was covered only through the other** — §202's shape, third
time. Both are reachable: an `array` variable holds whatever a `set_variable` effect put
there, and the server's refusal comes at resolve time, long after the checkboxes have been
drawn. The second is the worse one, since `"S1".map` is a TypeError and a widget that throws
during render takes the module with it.

And the browser tests had a **false pass that was hiding an off-by-one across the whole
file**. `CanvasObjectTable` renders a `.canvas-block`; so does the ROOT `CanvasContainer`. So
`.canvas-block` index 0 was the container, and "exactly one row is active" passed against it —
the container holds every row on the page, so the assertion was true whichever table the row
was in. It passed while every other assertion in the file read the wrong table. The fix is a
child combinator (`:has(> .data-grid)`); the lesson is that the one assertion that passed was
the one to distrust.

The widget layer found two more of the same kind. **Nothing asserted the active row was
actually *coloured***, only that it carried the class and the ARIA state — both of which pass
against a stylesheet where that class does nothing. And **`multiSelect &&` was never doing any
work**, because every test bound the Selected objects output and enabled multi-select together;
an author turning the toggle off with the output still bound is one click away, and p.224 says
that variable is only in use when the toggle is on.

**20 model mutants and 19 widget mutants, 0 survivors, 0 no-ops** after the fixes.

**958 unit tests** (was 933); **408 browser tests** (was 394); **1515 API tests**, 2 skipped
(both environmental).

---
---
---
---

### 206. Markdown, and a safety measure that was working backwards

p.314-319's widget, and the third item of `workshop.md`'s library build order — which called it
"trivially cheap" and was wrong. p.318's syntax table is the cheap half: fourteen syntaxes,
enumerated, read as the specification it is and used as one, each row a case in the unit test.

**The parser is hand-rolled, and safety is the argument rather than the absence of a library.**
Every off-the-shelf Markdown renderer emits an HTML *string*, which then has to be sanitised and
injected with `dangerouslySetInnerHTML` — so the platform would sit one sanitiser
misconfiguration away from executing whatever an app author typed, and an app author is not
somebody the whole workspace has chosen to trust. This parses to a **tree of plain objects** that
the widget renders as React elements. There is no markup string anywhere in the path, so raw HTML
in the source is text because text is all the parser produces, and the browser suite asserts it
both ways: the `<script>` an author typed is *present as characters* and *absent as an element*.

p.317's two precedence rules are functions in the model rather than conditionals in the JSX,
because they are rules the page states and somebody will eventually ask whether we follow them:
code blocks stay left-aligned whatever the widget says, and a table column that names its own
alignment keeps it while one that does not takes the widget's — which is why `alignOf` returns
`null` for an unmarked column rather than defaulting it to left. The browser suite caught the
first of those being computed and discarded: the `<pre>` carried no style, so it read as `start`
and was left-aligned only by inheritance.

`{{v_id}}` is expanded in typed text, as `CanvasText` has always done, and deliberately **not** in
text arriving from a variable. That text is data — a row out of a dataset, whatever a derivation
put there — and data that can name variables is data that reads them.

`textVariable` went into all four reference lists on the way in, as `timezoneVariable` did in
§205.

---

**Ten survivors on the first run, and four of them were on `safeHref` — the one function whose
entire job is safety.**

Deleting its control-character strip changed no test. The strip was there for `java\nscript:`,
the standard defence against a *denylist* that checks `startsWith("javascript:")`. This is an
**allowlist**, which refuses `javascript:` for the ordinary reason that it is not on the list,
broken up or not — so all three tests that named the strip were watching the allowlist do the
work and crediting it to the strip.

Worse than useless: under an allowlist, stripping can only ever *add* accepted strings.
`ht\ntps://evil.test` was becoming an accepted `https://evil.test` that nobody had typed. **The
measure was running backwards, and every test of it passed.** A control character now refuses the
URL rather than being deleted from it.

The general rule is the one the other six survivors are also instances of: **a defence can only be
tested on an input the other defences would let through.** Case folding tested with `javascript:`
tests the allowlist. Case folding tested with `HTTPS://X.test` tests the fold.

The rest, briefly: the text-merge test never crossed a flush, so it passed whether or not anything
merged; the line-ending test asserted a block count both outcomes share; `&& !UNORDERED.test(line)`
was dead, since one regex wants a digit where the other wants `-`, `*` or `+`; `cells`' fallback
was unreachable, and looked reachable only because the table rule accepted an alignment row the
row rule would not; and `--`, which is how people type a dash, had nothing saying it is not a
horizontal rule.

The widget layer found two more of the same shape. **The heading test rendered one level-1
heading**, so a widget emitting `h1` for everything passed it — the level is read in the model and
handed to `createElement`, and only a browser can say which tag came out. And **the word-wrap test
asserted only the "off" side**, which a rule that does nothing in either direction satisfies
perfectly.

The third widget survivor is worth recording as *not* a hole: `item.done !== undefined && (…)`
mutated to `item.done === undefined || (…)` survives because React renders `true` and `false`
alike as nothing, so the two expressions are the same program. Planting the mutant that really
does give every item a checkbox confirmed the assertion catches it. **An equivalent mutant is a
fact about the language, not a gap** — and telling the two apart takes one more experiment, which
is cheaper than the test nobody needed.

**49 model mutants and 23 widget mutants, 0 real survivors, 0 no-ops** after the fixes (one
equivalent mutant, verified as such).

**933 unit tests** (was 862); **394 browser tests** (was 379); 1511 API tests, 2 skipped
(both environmental — no MySQL server, and no group-membership rows in a fresh database).

`workshop.md` §10 goes from 17 of ~52 widgets to 18.

**Deferred, and named rather than approximated**: p.319's inline `:objectreference[…]{…}`
extension with p.316's Inline reference toggle, p.315's annotation objects, and p.317's
user-text-selection outputs. The first two need ontology plumbing and an output object set; a
renderer that showed their syntax as literal text would be worse than one that says it does not
do them.

---
---
---
---

### 205. The Date and Time Picker, and the rule that runs the other way

p.463–464's widget, decision 0011's fourth — and with it the generic parameter control's **palette entry is gone**, as that record said it would be. The component stays in the resolver: Craft maps a node's `resolvedName` to a component, and a document naming one it lacks does not degrade, it fails to render.

**The timezone is p.468's percent rule inverted, and the inversion is the whole argument for the split.** Percent *changes what the variable holds* — type 25, store 0.25. The timezone must **not**: a `timestamp` variable holds one instant, and the zone only decides how it is written down and how a typed wall clock is read back. Two settings in the same widget family pulling in opposite directions is the strongest evidence decision 0011 could have had, and neither rule would have survived in a shared control without being applied in the wrong place.

Three things worth naming. **Reading a wall clock back needs two passes**, because the offset depends on the instant and the instant is what is being solved for — one pass is wrong for exactly the hour either side of a DST change, which is the hour somebody will pick the day it happens. **Precision truncates the stored instant**, not just the display, and truncates with `Math.floor` because a remainder subtraction rounds *up* before 1970. **An unknown zone falls back to the viewer's own** rather than throwing: the zone can come from a variable, a variable holds whatever a derivation put in it, and `Intl` throwing inside a render is a blank module rather than a wrong time.

No timezone library. `Intl.DateTimeFormat` already knows every offset and every DST rule; what this adds is the arithmetic to get an offset *out* of it.

**`timezoneVariable` went into all four reference lists on the way in.** §191's guard caught a missing one in §198 and again in §204, both times on a widget whose *configuration* came from a variable rather than its output. Third time, stated before the check had to say it.

---

**Four survivors, and three of them were the same instinct: write the obvious precondition, then find the general check already covered it.**

The parse validation compared six fields, of which the day comparison could never fail alone — any day overflow also rolls the month. `asInstant` special-cased `null`, `undefined` and `""`, and `new Date` makes an Invalid Date of all three. `partsIn` corrected midnight rendered as hour 24. Each is gone rather than excused: the six comparisons became one string comparison with nothing unreachable in it, and `hourCycle: "h23"` replaces `hour12: false` so a 24 is impossible by construction rather than patched afterwards.

**The fourth is a new shape, and a sharp one.** `vitest.config.ts` deliberately runs the suite in `America/New_York` — there is a note there explaining that on a UTC container a test of UTC formatting proves nothing. My `zoneOf` fallback test then used `America/New_York` as the zone that should *not* come back. It is the suite's own local zone, so the fallback and the wrong answer were the same string, and a mutant returning the fixed zone in local mode sailed through.

**A test whose "wrong" value is the environment's default cannot fail.** The fix computes a zone the suite is provably not running in rather than naming one, so it stays true if the config's `TZ` changes. And it is the fifth member of a family these units keep finding: an expectation derived from its own subject (§201), a guard tested only by its neighbour (§202), a clock that erases its own evidence (§203), a read that corrects what it is asked about (§204), and now a control value that coincides with the environment's default. **In each, two things that had to differ were the same thing.**

**41 mutants, 41 caught, 0 survivors, 0 no-ops** after the fixes.

**862 unit tests** (was 756); **379 browser tests** (was 365); 1512 API tests, 1 skipped, unchanged.

`workshop.md` §10 goes from 16 of ~52 widgets to 17, and decision 0011 is complete.

---
---
---
---

### 198. Loops over arrays, and a console check that had never worked (this session)

p.132–133's loop over an array. `workshop.md` had recorded the blocker exactly — the `array` kind had no element type, so p.134's "a variable typed to the array type" could not be expressed or checked — so the unit is the element type first, then the loop arm.

**p.134's sentence is ambiguous and p.134 settles it.** "A variable typed to the array type" could mean the child receives the whole array. Two sentences later it says the struct-typed interface variable "renders the fields of each struct **entry**" — so the child receives one entry, and its variable is typed like an entry. Handing every copy the whole array would not be a loop. `Embed` carries `item_kind`, computed from what is being looped, and the cross-module check compares against that rather than a hardcoded `single_object`. The mutant implementing the *other* reading is the one the harness exists for: an argued reading with no test is a comment.

**§191's guard fired on new work for the first time.** `arrayVariable` names a variable and was not in `REFERENCE_PROPS`; the save was refused before the feature could ship with a variable deletable out from under a configured loop. That check has been archaeology since §191 and this is the first time it caught something on the way in.

---

**But the finding that outlives the unit is in `e2e/conftest.py`.** A mutant keying loop copies by *value* instead of position makes React log "Encountered two children with the same key"; the test asserted no console errors and passed anyway.

`DEV_SERVER_NOISE` contained `hot-reloader-client`. It went in to silence one benign Next prefetch message that *names that file as its source* — and in Next's dev build React's own `console.error` is routed through the same client, so **every React error in the whole browser suite carried the string and was filtered out**. The fixture's docstring says the check "is not decoration". It was, for as long as that line existed.

The rule: **match a noise filter to the message, never to its source.** A source is shared with the things worth failing on. The comment beside that list had already warned that matching too broadly "would swallow a real API call that did not come back", and the next line did exactly that in a different way.

**Removing it unmasked a second bug**, in a test §192 wrote. `settled()` waits for the *canvas*; the Layout panel paints after it, so `before = tree_rows(page).count()` read **0**, turning `n == before * 2` into `n == 0` — an assertion nothing can satisfy once a paste adds rows. It passed on luck until §196 and §197 each added work to the panel's first paint. **The failure blamed the wrong half**: "still 4" reads as the paste producing the wrong number, when the paste was right and the baseline was zero. A probe with identical steps printed 2 and 4; only printing `before` itself found it.

**Four survivors, none of them what they looked like.** Two were harness scoping (`test_canvas.py` covers the cross-module check and the api layer did not run it). One was mutating dead code (`craft.props` supersedes a component's parameter default, so the default never fires for a saved document). One was the real hole above. A fifth mutant is **withdrawn as equivalent**, with the reasoning recorded: `validate_module` returns 422 before `_check_embeds` is reached, one call site, unconditionally preceded — checked for a reachable path the way §197's ROOT survivor turned out to have one, and this does not.

**26 mutants, 25 caught, 0 survivors, 0 no-ops, 1 withdrawn. 1510 API tests** (was 1488); **507 unit tests** (was 491); **296 browser tests** (was 289).

---
---
---
---

---
---
---
---

---
---
---
---

---
---
---
---

**The sandbox rewound the checkout twice more this session** - HEAD back at a commit from PR #50, `docs/parity/` gone, Postgres down, `node_modules` pruned, the database missing six migrations. Nothing was lost either time because every unit was already pushed and merged. The recovery is mechanical and worth having written down: `git fetch origin main && git checkout -B <branch> origin/main`, then `scripts/dev-up.sh`, then `npm ci` **at the repo root** (§132's lesson - never in `apps/web`), then the migrations, then a full API run to prove the restore before touching anything. The migration line is the part that is easy to get wrong and is spelled out in §153: it runs as the **owner** role, not `platform_app`, with the plain `postgresql://` DSN and `PLATFORM_APP_PASSWORD` set.
---

## What's not started

- **Code** — all four items are done (§45–§47). What is left in the pillar is optional and named rather than assumed: the git *mirror* to a remote the customer owns (§45's extension point — a git server is explicitly not on the list), and branch-to-environment mapping, which §47 declined because this platform has neither branches nor environments and inventing both to satisfy a phrase would be the tail wagging the dog
- **`code_repos`** (migration 0003, spec §16) — a table with no writer and, since §45, no future one. Left in place because the schema verifier asserts the spec's tables and dropping it is a claim about the spec rather than about a feature; the project nav no longer counts it (§46). Drop it if the spec is ever revised to match the decision
- **Canvas widget palette** (see §15, §40, §41, §42, §43): Container, Text, Filter, Dataset table, Object table, Chart, Map, Action form. No configurable tile source for the map (§43 ships country outlines in the bundle and names this as the extension point), and no cross-widget interactivity beyond parameters (e.g. a table row selection driving another widget's detail view — `MapCanvas` already takes an `onSelect` nothing passes yet) — both additions to the same resolver/widget pattern, just not built yet. Reordering placed widgets is done (§44), by buttons as well as by drag
- **Sharing an app outside the platform** (a public or token-scoped link) — `ROADMAP.md` Canvas item 7, explicitly a stretch: it needs an auth model for an unauthenticated or token-authenticated viewer, which is a bigger question than any widget. §44's viewer route is the in-platform half and stops at the workspace boundary
- **Canvas apps don't appear on the workspace-wide "published apps" nav anywhere yet** — the `GET .../published-canvas-apps` read path exists and is tested (§15) but no frontend page lists it; today a workspace member reaches a published app only if handed its direct URL
- **Object instance sync gained scheduling, still full-snapshot by design** — §16 added a cron schedule and a 2M-row worker cap, but §14's cursor-based incremental mode is deliberately connection-sync-only: an object-type-source's input dataset is a wholesale-replaced snapshot with no cursor to hold, so full-snapshot mark-and-sweep is the correct approach here, not a gap (see §16 for the reasoning)
- **The OpenSearch instance store has never run against a real cluster** — §35 wired it in and tests it over real HTTP against a fixture implementing the REST subset it uses, which proves its requests and parsing but not that OpenSearch agrees (no analyzers, no mapping enforcement, no refresh semantics in a fixture). A deployment reaching for it is the last verification step; until one has, `OPENSEARCH_ENDPOINT` unset leaves every environment on the Postgres store, which is fully tested. **§37 raised what this gap can cost**: link traversal depends on the index's *mapping* — a `keyword` subfield must exist on string properties for an equality query to match — and mapping is precisely what a fixture with no analyzers cannot check; the fixture treats `properties.x` and `properties.x.keyword` as the same value and says so in its own docstring. The mapping is declared explicitly in `_ensure_index` rather than inherited from dynamic defaults, so the guarantee is ours rather than the cluster default's, but verifying it is still the first real cluster's job — and "links traverse to nothing on OpenSearch while working on Postgres" is the shape that failure would take
- **Object type edits do not clean up the instances they orphan** — §38 lets a property be removed; a stored instance keeps a `properties` key the type no longer declares until the next sync rewrites the row without it. Deliberate: the browse UI reads the type's declared properties so an undeclared key simply does not render, and deleting data across a store the API may not own (instances can live in OpenSearch, §35) would be a destructive side effect of an administrative edit. Worth knowing if you query the instance store directly and find keys the ontology has never heard of
- **Attachment files are never garbage-collected** (§39). Replacing an attachment leaves the previous object in storage, and an upload that is never referenced leaves one too — the upload happens while a form is being filled in, before anyone has decided which instance it belongs to. Deleting on replacement would mean deleting bytes any prior dataset version still refers to, and there is no reference counting to make that safe; a sweep over "keys under `attachments/` that no current instance references" is the shape of the fix, and it needs the instance store to be enumerable per workspace, which OpenSearch makes possible but nothing does yet
- **`property_values.py` is the fifth mirrored file** and one more than this list says should exist before someone builds a shared package (§39). The mitigation is that it is pure standard-library Python, so `test_property_types.py` asserts the two copies' SHA-256 match rather than asserting behaviour — mechanical, unlike the connector registries. **If you need a sixth mirror, build the package instead**: it means moving both service images to a repo-root Docker build context, which `apps/web/Dockerfile` already requires
- **Links through a join object are not supported** — §37's traversal is a single property-to-property equality, so a many-to-many relationship expressed as A → join table → B cannot be described as one link type. `many_to_many` cardinality still works when both sides hold a shared key; what is missing is the two-hop case, which needs a third object type in the middle and is a different data model, not an extra parameter. Nor are computed join keys (`upper(a) = trim(b)`) — a derived join column belongs in the dataset feeding the type, where the model layer can already produce it
- **Canvas filters build SQL in the browser** (§40). The value is escaped and the column comes from a schema-populated picker, and the endpoint it posts to already accepts arbitrary SQL at the same viewer floor — so this is a correctness and taste issue, not a privilege one. The better shape is structured filters (`{column, operator, value}`) on the preview/query endpoint so the server builds the SQL; worth doing when item 2's charts need the same predicate, rather than twice
- **Write-through to external connection sources** — Actions write back to this platform's own dataset copy only (see §12); connectors don't support write operations yet
- **Control-plane and build/deploy pipeline** — no Dockerfile exists for `apps/control-plane` yet, and nothing in the repo invokes `docker build`/`cdk deploy` automatically — §17's deploy was run entirely by hand from a local machine. **The test side of this is now closed** (§107): `.github/workflows/ci.yml` runs the API suite, `tsc` and the browser suite through `scripts/check.sh`. The *build and deploy* side is not, and the workflow itself has never executed — there is no way to run GitHub Actions from this environment, so its first run on a real PR is what proves the wiring

---

## Known rough edges worth knowing about

- **A migration that adds an enum value cannot be cleanly re-applied after editing** - Postgres has no way to drop an enum label, so the usual "reset an already-applied migration" recipe (drop what it created, delete its `schema_migrations` row, re-run) leaves the label behind and the re-run fails with `enum label "x" already exists`. Hit while fixing 0025 mid-session. `ADD VALUE IF NOT EXISTS` makes the file idempotent and is now used there; any future migration adding an enum value should do the same, because the alternative on a shared dev database is recreating the type and everything that references it.

- The local dev Postgres instance (this sandbox only) needs manual restarting periodically - not a real issue, just a sandbox quirk, documented in the restart command used throughout this session.
- `apps/api/requirements.txt` was missing `duckdb`, `pytz` (DuckDB's own timestamp dependency), and `python-multipart` (needed by FastAPI for file-upload endpoints) - all three are genuine runtime dependencies of code that already existed, not new to this session's work, and the gap would have surfaced as a broken Docker image. Fixed in this session; a `requirements-dev.txt` was added alongside it for the test-only extras (`pytest`, `httpx`).
- Upload/sync/model size caps (50 MB / 200 MB / 5M rows) are conservative day-one limits, each flagged in code comments as the point where the Athena/worker path takes over.
- A handful of spec-silent decisions were made conservatively and flagged in-code with `# Flagged for review` - e.g. who can create a workspace (org admin), who can create a project (workspace editor+), object counts being workspace- vs. project-scoped for `object_types`, the objects/instances/actions role floors described above, and the Actions write-back scope decision (this platform's own dataset copy, not the external source).
- The API and worker use **different env var names for the same local-dev concept**: the API's storage gateway reads `STORAGE_ROOT` (default `/tmp/anchor-storage`), the worker's reads `LOCAL_STORAGE_ROOT` (default `/tmp/anchor-worker-storage`) - harmless once you know it (each service is independently deployable and has always had its own env), but worth knowing before pointing both at the same directory for a manual end-to-end check, as this session had to work out by tracing a `FileNotFoundError` back to the mismatch.
- `apps/web/.env.local` was committed at the wrong path (`apps/web/src/.env.local`) since at least the initial commit - Next.js only loads `.env.local` from the app's own root, so the documented dev sign-in flow (`dev_server.py`'s instructions) silently never worked from a fresh clone until this session moved it. Fixed; see §14.
- **The residue is large enough to be a clock, and it caught `test_ontology_search.py` in §185.** Every browser run's `Module.object_type()` creates an object type and nothing cleans up, by design - and this sandbox's shared database has reached **6,281 object types and 13,634 properties**, 425 of them in the dev workspace the browser suite uses. `GET /ontology-search` measured **4.5 seconds** there by authenticated `curl`, against a Playwright assertion whose default timeout is 5, so two of that file's tests failed on "Searching…" with nothing wrong in the diff. **§186 found what that was actually measuring** - not the row count but row-level security, evaluated once per row - and fixed it: the endpoint is **0.37s**, the tests pass with thirteen times the headroom they had, and the 5-second default is now correct rather than marginal. Left as it is on purpose: raising it would only hide the next regression. The residue itself is unchanged and still worth knowing about, because it is what made a per-row cost visible at all.

- Dev/test Postgres accumulates residue across sessions: worker and API test suites create real orgs/workspaces/connections/models in the shared local dev database and don't clean them up afterward (by design - matches the existing `test_cleanup.py`/discovery-function pattern of not needing per-test teardown, since most discovery queries naturally stop matching once a schedule advances past "due"). This session hit one case where that assumption didn't hold: leftover cron models and scheduled syncs from earlier, interrupted test runs had never advanced past their `next_run_at`/`sync_next_run_at`, so a later manual worker invocation picked them up and failed against long-deleted tmp-directory files. Not a product bug - the two real bugs it surfaced (per-connection error isolation, empty-cursor VARCHAR mismatch, both in §14) were - but worth knowing if a stray "failed" run shows up against an unfamiliar workspace slug in this sandbox's Postgres.
- **A scheduled-sync test that leaves its schedule behind poisons every later run** - found the hard way in §22. The worker reschedules a connection after every run (the tests use `* * * * *`), so a test connection left in the database is *permanently due*: the next suite run rediscovers it and tries to sync it against a source that no longer exists - a dropped MySQL database, a `moto.server` on a port nothing is listening on, a `tmp_path` storage root long since deleted. Nothing fails (the job's per-candidate isolation records it and moves on), it just gets slower, and it compounds - 81 stale connections had accumulated by the time it was noticed, taking the worker suite from 16 seconds to over ten minutes, since each dead source costs a connect timeout and boto3 retries three times before giving up. Both worker `workspace` fixtures now clear `sync_schedule`/`sync_next_run_at` on teardown (`test_sync_configs.py` for connections, `test_instance_syncs.py` for object-type sources) and the suite is back to ~16s. Any new fixture that schedules something must do the same - this is the shared dev-database residue problem below, in its one form that actually bites.
- **The API's and worker's connector registries are two files that must be kept in step** (`apps/api/src/services/connectors.py` and `apps/worker/src/anchor_worker/connectors.py`) - duplicated deliberately, for the same reason `dataset_engine.py`/`storage.py` already are (independently deployable images, no shared Python package in this build), but with a nastier failure mode than those two: a source type registered in the API but missing from the worker syncs fine interactively and then silently fails on its schedule, per connection. `apps/worker/tests/test_mysql_sync_configs.py` asserts the registries agree; extend that assertion when a third source type lands, and treat "did the worker get it too?" as part of adding any connector. A shared package would remove the class of bug entirely and is worth doing if a third or fourth connector arrives - it means moving both service images to a repo-root Docker build context, which `apps/web/Dockerfile` already requires (§17 bug 1), so the precedent exists. **§29 raised the stakes on this**: the expectations evaluator is now mirrored too (a fourth thing to keep in step, with its own parity test in `test_model_runs.py`), and its drift mode is worse than the connectors' - a rule the API can store but the worker cannot evaluate would make a gated run's verdict silently disagree with the dataset's own health badge. Whoever adds the fifth mirror should build the shared package instead.
- **Worker jobs' per-candidate `except` tuples are the single most repeated bug in this codebase** - §14 (twice, `sync_configs.py`), §16 (`instance_syncs.py`, `StorageKeyError`), and §21 (`sync_configs.py` again, the *same* `StorageKeyError` gap §16 fixed one file over). Every occurrence has the same shape: a job calls something that raises an exception type the isolation tuple doesn't name, so one bad candidate crashes the whole batch instead of failing alone. When adding or editing a scheduled job, enumerate every exception type on the call path rather than the ones a first test run happens to exercise - and when fixing one job, check its siblings for the identical gap.
- **RLS policies that read another RLS-protected table are a recurring bug class in this codebase** - 0008 (users), 0009 (canvas_apps↔canvas_app_shares), and now 0015 (canvas_apps↔projects) all hit the same shape: a policy's `USING` clause subqueries a table whose own policy can legitimately hide the exact row the first policy needs, so the check silently fails closed instead of erroring loudly. Worth a systematic pass if another cross-table RLS policy gets added - the fix is always the same (`SECURITY DEFINER` helper resolving just the needed column, bypassing RLS internally) but nothing currently catches the pattern except noticing a feature silently doesn't work.
- **`npm run build` while `next dev` is running corrupts the dev server.** Both write `apps/web/.next`, so a production build under a running dev server leaves it serving 500s with `Cannot find module './vendor-chunks/@tanstack.js'` on every route - which reads as a broken page rather than a broken cache, and cost a debugging detour in §47. Recovery: stop the dev server, `rm -rf apps/web/.next`, restart. Run the two in sequence, never concurrently.
- **An applied migration is immutable, and that includes its comments.** `migrate.py` checksums the file, so editing one - even to fix prose that is actively wrong - makes every database that already applied it refuse to migrate at all. Hit in §92: §90's docstring correction to `0034` blocked `0036` from applying, and would have blocked it in production too. Corrections to a migration's *prose* go in `packages/db/migrations/ERRATA.md`; the runner ignores `.md`. There is no escape hatch and there should not be one - the guard cannot tell a comment from a statement from a hash, and a runner that tried would be a runner that sometimes let a changed statement through.

- **`scripts/dev-up.sh` used to hang any caller without a terminal, and the fix is one word: `setsid --fork`.** A script runs with job control off, so a backgrounded command stays in the shell's process group and is therefore *not* a process-group leader - and `setsid` only forks when its caller is one. Without a fork it `exec`s in place, so the dev server kept the pid of the script's own child and the script sat in `wait` for a process that never exits. Interactively nobody notices: the prompt comes back. Piped, `dev-up.sh | tail` printed **nothing at all** until the pipe closed, and the pipe could not close while a child held it - a 20-hour-old `dev-up.sh` was still parked in `do_wait` when this was found, and every agent or CI run that had to start a server had been paying minutes for it. With the fork, a piped run that starts the API returns in **3.6 seconds**; without it, the same run produces no output and is still going at 30. Both servers also take `< /dev/null` now, for the same reason one level down.

- **A stale dev API shows up as a browser suite that gets *slower*, not one that fails.** The dev API does not hot-reload, and the failure mode when you forget is worse than a broken page: every affected request 500s, every Playwright assertion waits out its full 30-second timeout, and the run keeps going. Found in §172 - a one-line SQL fix landed after the last restart, and the suite that normally takes 17 minutes was still going at 30 with no output at all, because `pytest -q | tail` shows nothing until it finishes. Both diagnostic instincts point the wrong way: the API answers `/health` instantly and `pg_stat_activity` shows no slow query, because the requests are failing fast and the *browser* is doing the waiting. **The check that actually answers it** is one authenticated `curl` against the endpoint you changed - it either returns the new shape or it does not. Restart after every source edit, and re-smoke before a long run rather than after it.

- **This sandbox loses state without warning, and the two shapes it takes both read as application bugs.** The dev **database** can come back several migrations behind: the symptom is a 500 from an ordinary write naming a column that does not exist (`auto_publish_on_save`, in §132), not anything that says "unmigrated". Re-run `packages/db/migrate.py`; it is idempotent. And `apps/web/node_modules` can come back pruned to a fraction of itself while the running dev server carries on serving from its loaded modules, so the first sign is a test runner that cannot find `vitest/config`. **Reinstall from the repo root** (`npm ci` at the top level) - this is an npm workspace, and `npm ci` inside `apps/web` replaces the correct hoisted tree with a standalone partial one that shadows it.

- **A migration that drops a column makes the previous API version fail, for as long as it is still running.** Migration 0044 drops `action_types.editable_properties`, and the control plane applies migrations as part of a version update - so between "migrated" and "new image serving", every request through `list_action_types` is a 500. Hit locally the moment 0044 landed: the dev API had been up since the previous day and every Workshop save returned 500 with `column at.editable_properties does not exist`, which reads as a broken feature rather than a stale process. Restarting the API fixed it. Nothing in this build needs zero-downtime yet, and the honest note is that when it does, a drop has to be its own later migration - write the new tables, deploy the code that reads them, *then* drop - rather than one migration doing both.

- **`verify_schema.py` needs a fresh database; it cannot be run twice against the same one.** It creates a fixture organisation, and `audit_log`'s append-only `DELETE` rule (migration 0004) *silently* discards deletes — `DELETE 0`, row still present, even as superuser with `row_security = off` — so the fixture can never be cleaned up and the second run dies on a duplicate slug before checking anything. Found in §88, and it is the reason the verifier's "no unexplained extra tables" check had been failing unnoticed for sixteen migrations.
- **Four features are waiting on one missing capability: the instance index does not honour declared property types.** **Decided in `docs/decisions/0006-typed-instance-properties.md` (§104), not built** — one index per object type, text ordering refused permanently, the map's box as a `geo_bounding_box`, and what the OpenSearch fixture needs before the build is checkable at all. Ordered filters (`gt`/`lt`), numeric aggregations (`sum`/`avg`/`min`/`max`, §74), sorting a table by a property (§83) and selecting an area on a map (§86) are each refused for the same reason — properties are stored untyped, so a comparison means one thing on Postgres and another on OpenSearch. Every refusal says so in a sentence. **It cannot be built in this sandbox**: the OpenSearch side is tested against `tests/opensearch_fixture_server.py`, which has no mapping enforcement by design, and there is no Docker daemon and no reachable OpenSearch artifact host here, so the cross-store agreement — the entire point — cannot be demonstrated. It needs a real cluster, not more code.
- **Two sources feeding one object type produce two instances for the same primary key** (found in §83). Instance identity is `(source_id, primary_key)` — `instance_store._doc_id` — so pointing a second dataset at an object type that already has one duplicates every overlapping key instead of updating it, and a set over that type returns each duplicated object twice. Nothing errors. Multi-source object types are a legitimate Foundry pattern (a union of feeds into one type), so the honest fix is to make identity `(object_type_id, primary_key)` and decide what happens when two sources disagree about the same object's properties — an ontology decision with a backfill behind it. Until then, one source per object type.
- **Reading a Playwright locator as `count()` then `nth(i)` is a torn read, and it fails as a 30-second hang rather than a wrong answer.** The obvious way to snapshot a column - `{cells.nth(i).inner_text() for i in range(cells.count())}` - is two or more round trips to the browser. A re-render landing between them (a filter change is exactly that) leaves it asking for a row that no longer exists, and `nth(i).inner_text()` then *blocks for the full timeout* instead of returning something stale that a polling helper could reject and retry. Found in the resource-filter browser check: the run took 48s instead of 20s and failed only on the first run after a source edit, which read convincingly as "the dev server was recompiling" for several rounds. Use `all_inner_texts()` (or `all_text_contents()`), which is one call and one snapshot. This matters most inside `eventually`, where the whole design assumes a cheap read that can be retried.

- **Making the server faster breaks browser tests, and the tests were always wrong.** A slow request is an accidental barrier: while it is in flight the page cannot finish rendering, so an assertion written with no wait gets one for free. Remove the slowness and every test leaning on that barrier fails in the same run, which looks exactly like the change broke the feature. Two of these landed in one session. §186 dropped `/ontology-search` from 4.5s to 0.37s and two headings that had always arrived one at a time started arriving together, making a non-`exact` `get_by_role` locator ambiguous. §188 dropped `/projects` from 1.1s to 30ms and two `test_widget_config_tabs.py` tests began reading an object table's height and header count in the ~150ms between "the widget's frame is visible" and "its rows have arrived" — a gap `settled()` does not close, because it waits for a `.canvas-block` and the frame *is* one. **The tell is that the API answers are identical**: diff the responses under both settings first, and when they match, stop looking for a permissions or data bug and get a timeline of requests versus assertions instead. The fix is always a wait for the thing actually being measured, placed in the shared helper rather than in the test that happened to fail.

- **A Playwright assertion that can be satisfied by a transient state is not an assertion.** `to_be_visible` retries until it sees what it wants and then stops looking: a wrong *first* frame is forgiven, and a wrong *last* frame is never examined. §189 found a mutant that showed the correct page for 250ms and then went somewhere else, with the whole test file having run and passed inside that window. The pattern to watch for is a page whose state depends on something arriving asynchronously — a resolved variable, a fetched row — because before it arrives the state is often *legitimately* the one the test is checking for. The fix is an ordering rule rather than a longer timeout: wait for evidence the async thing has landed (a marker variable, a value drawn on screen), and only then assert the thing under test. A related trap in the same family: if the not-yet-loaded state happens to equal the expected answer, the check passes against a build that never implemented the feature at all.

- **When a browser test fails, ask whether the fixture is posing the question before asking whether the code is wrong.** §192 lost three rounds to fixtures rather than to the feature: a widget bound by `{{...}}` interpolation, which nothing in this system counts as a variable usage; a `get_by_text` that also matched the Layout panel's row detail and so counted every widget twice; and a read of the Variables panel's usage counts *before* a save, when that panel is computed from the saved definition and is still describing the previous document. All three read as "the feature is broken". The tell is a failure whose number is wrong in a way the feature could not produce — four copies where the paste ran once, a variable "unused" that is visibly on screen.

- **A vitest unit test cannot reach any module whose import graph touches a `.tsx`.** The parse fails on the JSX, so the failure is "cannot parse", not "module not found", and it points at a file you did not write a test for. §193 hit it on `events.ts`, which had no unit tests at all for that reason — the ordering rules it exists to enforce were only ever checked through a browser. The fix is a split: pure logic into a `.ts` with no React imports, the hook left behind in a file that re-exports it, so no call site changes. Worth doing the moment a module has arithmetic worth testing, rather than after months of browser-only coverage.

- **A mutation harness that edits Python is testing the running server's *old* code.** The dev API does not hot-reload (already known, already written down for ordinary work) — and §194's harness walked straight into it: two route mutants reported SURVIVOR having never actually run, because the browser layer was talking to a server started before the mutation. The tell is a mutant that lands cleanly (no NO-OP) and that no layer catches even though the thing it breaks is obviously load-bearing. The fix is to restart the API before **every** browser layer, unconditionally, rather than tracking which files a mutant touched: the server can also be left dirty by the *previous* mutant, and getting that bookkeeping subtly wrong reintroduces exactly the false negative the restart exists to remove. A harness that cannot verify its own mutations reached the code under test proves nothing — the same argument as the fingerprint check, one layer down.

  The corollary bit immediately: **never run the harness while a full suite is in flight.** §194 did, to save wall-clock time, and got 1 failure and 9 errors in two files it had not touched — the harness's `restore()` rewrites files (triggering a Next rebuild) and its browser layer restarts the API underneath whatever else is running. Every one of the ten passed on a clean re-run. The tell is `ApiError` in files unrelated to the unit; the cost is fifteen minutes and a moment of believing a real regression had appeared. The two are the same shared mutable environment, so they have to be serialised.

- **An absence cannot carry a request when absence is already a meaningful state.** §194 encoded "recompute this variable" as *dropping* it from the map of held values, which reads as obviously equivalent to asking. It is not, whenever some variable's legitimate resting state is also "nothing held" — there, the ask and the initial condition produce identical requests and the receiver cannot answer both correctly. What makes this dangerous is that it can be **half**-working: the behaviour whose answer to the ambiguous state happens to be the right one for both readings passes every test, and hides the one that does not. Worth checking any protocol where a field's absence means "do the default": if two different callers' situations can both produce that absence and want different answers, the second one needs its own field.

- **A control that reflows on hover cannot be clicked, and nothing reports it.** §195's preview panel opened as a sibling above the icon strip, pushing the strip down — so the icon moved out from under the pointer hovering it, and the browser never synthesised a `click`. No error, no warning, a button that simply did nothing. The diagnostic that settles it in one run is to log every pointer event on the element: **`pointerdown` and `mousedown` arriving with no `mouseup` means the element moved**, not that the handler is wrong, and that distinction is the difference between fixing a stylesheet and rewriting a component. Any hover-triggered panel that shares a normal-flow parent with its trigger has this shape; float it.

- **The harness restores from `HEAD`, so any edit it prompts you to make is undone by its own cleanup.** §195 deleted a dead fix the harness had just exposed, re-ran the harness, and got the dead code back — `restore()` writes `git show HEAD:<path>`, and HEAD still had it. `git status` then showed the file as unmodified, which is exactly what a successful deletion and a silently reverted one both look like. Any change made in response to a harness finding has to be **committed before the next run**, or re-applied after it; checking `git status` afterwards is not enough, because the file matching HEAD is the failure, not the proof.

- **When a mutant that deletes a fix survives, the fix was not the fix.** §195 first blamed Craft's drag connector for eating the press and added a `stopPropagation` to stop it. The real cause was the reflow above, and the harness proved it: removing the handler broke nothing. It would have stayed in the tree forever as dead code carrying a confident comment that explained a real bug incorrectly — worse than no comment, because the next person to hit something similar would trust it. Mutating your *own* recent fixes is worth doing for exactly this reason.

- **A value read inside a framework's selector is only as fresh as what that selector watches.** §196 computed a tooltip inside Craft's node-map selector using data from a React prop; the selector re-runs on node-map changes, so renaming a variable left the tooltip showing the old name until something unrelated touched the layout. No unit test can see this — both functions were correct, and the bug was in *which hook re-runs when*. The rule that falls out: inside a selector, read only what the selector subscribes to, and do every other lookup at render. The tell is a value that is right on first paint and stale after an edit somewhere else on the page.

- **A mutant can be caught by a *hang*, and a harness that treats that as a crash loses the run and leaves the bug on disk.** §197's cycle-guard mutant makes `isParked` loop forever, so vitest spun rather than failed; `subprocess.run(timeout=…)` raised, the exception escaped, and the run died at mutant 6 of 22 — **skipping the `restore()` at the end**, so a planted bug sat in the working tree afterwards. A hang is a suite that did not pass, which is what "caught" means: catch `TimeoutExpired` and return False. And restore inside an exception handler as well as at the end, because the failure mode of not doing so is a mutation-testing harness turning into the thing it was written to catch.

- **The harness's `restore()` reads `git show HEAD:`, so running it over uncommitted source reverts that source — silently, on the first mutant.** §200 fixed six survivors, then started the re-run with the fixes on disk and unpushed. `restore()` put the file back to HEAD before the first mutation went in; killing the run left a planted mutant on top of the reverted file, so `git status` showed one small unexpected diff and gave no hint that the real work had gone. Nothing was lost only because two of the three edited files were outside the restore set and the third was still in context. The rule is one line — **commit before every run, including a re-run** — and it is §197's "restore inside the exception handler" seen from the other end: a harness that guarantees a clean tree guarantees it against *you* as well. The tell is a `git status` after a killed run that is shorter than it should be.

- **Mutate behaviour, not types — a mutant with no runtime cannot be caught by a runtime suite, and its survival means nothing.** §201 wrote `return null` → `return null as never` and duly got a survivor. The assertion compiles away; the value is the same `null`; there was nothing for vitest to see. It reads exactly like a real hole in the report, which is the cost: an hour spent looking for the missing test. The tell is a mutant whose diff is entirely inside a type annotation, an `as`, a generic parameter, or an `interface`. If the change would vanish under `tsc`'s emit, it is not a mutant — and §200's opposite case is the pair to it: a branch nothing can reach is a branch no test can hold, so remove the branch rather than record an exception.

- **A guard that looks redundant beside a real one is exactly where a hole hides, because the tests covering one usually cover the other.** §202's `toStored` checks the *shape* of the text and then that the result is *finite*, and each survived being deleted. Every "not a number" case written down — `abc`, `1.2.3`, `Infinity` — is caught by both, so neither guard was load-bearing for the suite. They separate on two inputs nobody thinks of: `Number("0x10")` is `16`, quite finitely, so only the shape check refuses it; and `1e999` is digits-e-digits, so only the finite check refuses that. The tell is two adjacent validations whose test cases are the same list — and the fix is to find the input each one alone rejects, which is also the fastest way to discover one of them really is dead.

- **To assert that nothing happened, find a point after which it definitely would have.** §202's half-typed-entry test claimed a variable kept its value, and passed against a mutant that cleared it: Playwright's `expect` succeeds on its *first* matching poll, so "still 5" was read before the write landed. A timeout is the wrong fix — it is slow and it is tuned to one machine. The right one is a second observable changed by the same action, so waiting for that proves the first had its chance: §202 clicks a button that also sets a marker variable and asserts both in one string. `test_collapsible_sections.py` had already invented this and called it "the clock".

- **The clock must not be able to overwrite the thing it is timing.** §202 established that asserting "nothing happened" needs a point after which it definitely would have, and §203 promptly built one wrong: the button that proved a cycle had completed set the *same* variable the event under test would have set, so "did not fire" passed because the click had erased the evidence. The mutant it was written to catch sailed through. The clock has to be a **second, independent** observable — and the tell that it is not is a test where the waiting step writes anything the assertion reads. This and the two entries above are one family: an expectation derived from its own subject, a guard tested only by its neighbour, a clock that clears its own evidence. In each, the test and the thing it checks are not actually two.

- **A test cannot see through a normalising read: where code corrects on the way out, assert on what was written.** §204's panel resets two props when the selection changes, and both resets had tests that could not fail. The variable picker lists only variables of the selection's kind, so a `<select>` still bound to a stale one renders `""` — identical to cleared. The display select's value goes through the resolver, so it reads the legal value whether or not the prop was fixed. **The render shows the corrected value; the prop keeps the stale one; the prop is what gets saved.** The defence is right and the assertion was in the wrong place — read the document back from the server instead. The tell is a control whose displayed value is computed rather than stored, which is exactly the controls worth defending, so this will keep happening. It completes the family two entries up: §203's clock could not see a change because something *erased* it; this one could not because something *corrected* it.

- **A test whose "wrong" value is the environment's default cannot fail.** §205's `zoneOf` fallback test asserted that a bad configuration falls back to the viewer's own timezone, using `America/New_York` as the zone that should *not* come back — and `vitest.config.ts` deliberately runs the suite in `America/New_York`. The fallback and the wrong answer were the same string. Worse, the config's own comment explains it chose a non-UTC zone precisely so UTC assumptions would show up, which is exactly the trap it then set for anything naming that zone as a contrast. The fix is to **compute** a value the environment provably is not using rather than naming one, so it survives the config changing. The tell is a constant in a test that also appears in a config, a fixture, or a default — and this is the same family as the four entries above: two things that had to differ turning out to be the same thing.

- **"Not caused by my diff" is one finding; *why* it fails is a second, and the second one has to be measured.** §208's verification run went red on an Ontology Manager test that had passed hours earlier. Reproducing it on `main` established the first half honestly. Then I wrote down a mechanism — "past ~1,200 object types the Edit dialog stops producing the checkbox" — that sounded right, fitted the evidence, and was **wrong**: the dialog produces it after 7.2s, and Playwright's default `expect` timeout is 5s. The real chain is an unbounded `list_types` (no `LIMIT`) rendering ~1,400 rows, fixture debris supplying the rows, and a test leaning on a default timeout. Three separate things, and the plausible single story I recorded named none of them. A diagnosis that has not been instrumented is a guess, and writing a guess into `STATUS.md` in the confident voice of the entries around it is worse than leaving the failure undescribed.

- **Two modules exporting the same constant name are one import away from a control that typechecks and lies.** §211's Property List clamps its column count to 1–6; the String Selector's option grid clamps to 2–8, and `widgets.tsx` already imported `MIN_COLUMNS` and `MAX_COLUMNS` from the second. The new panel's number input picked those up silently — the types match, both are numbers — and would have refused a one-column layout the model considers legal, with nothing anywhere reporting a disagreement. The tell is a shared, generic constant name (`MIN_*`, `MAX_*`, `DEFAULT_*`) in a file that already imports one from somewhere else; the fix is to alias at the import so the two cannot be confused by reading.

- **A default that coincides with a clamp makes the guard in front of it unreachable.** §208's `linesOf` and `frozenOf` both checked for `null`/`""` before coercing, and deleting both changed no test. §203 needed exactly that guard — `Number(null)` is a finite `0`, and zero rows was a different answer from "not set" — but here the default *is* the clamp floor, so a coerced `0` already lands on the answer absence gives. Same coercion fact, opposite conclusion. The tell is a defensive check whose two branches return the same value for every input that reaches it; the question to ask is not "is this input possible" but "does this guard change the answer".

- **A container that shares a class with the things inside it makes index 0 a trap, and the assertion that passes is the one to distrust.** §207's browser tests located widgets as `.canvas-block` by index — and the ROOT `CanvasContainer` renders a `.canvas-block` too, so index 0 was the container and every index after it was off by one. What made it expensive was which assertion survived: "exactly one row is active" *passed*, because the container contains every row on the page, so it was true whichever table the row was actually in. One green assertion vouched for a locator that was wrong everywhere else, and the failures it caused looked like a broken feature rather than a broken selector. The tell is a positional locator over a class an ancestor also carries; the fix is a child combinator (`:has(> .data-grid)`). This is the family again — the passing check and the thing it was meant to check were not actually two.

- **A defence can only be tested on an input the other defences would let through.** §206's `safeHref` had three tests naming three mechanisms — an allowlist, a case fold, and a control-character strip — and all three used `javascript:` as the input. The allowlist refuses that on its own, so the other two tests confirmed the allowlist and learnt nothing about themselves; the harness found all three at once, because deleting the mechanism each one named changed no result. What made it more than a coverage gap is *why* the strip was there: it is the standard defence against a **denylist** `startsWith("javascript:")` being split by a newline, and under an **allowlist** it can only ever add accepted strings — `ht\ntps://evil.test` was becoming an accepted `https://evil.test` that nobody typed. The measure was running backwards and every test of it passed. The tell is a negative test whose input would be rejected with the mechanism removed: pick an input the *other* checks accept, or the test is about them.

- **Two CSS rules claiming the same class resolve silently by source order — §211's collision, in a namespace with no compiler.** §215 gave the Object Selector's row `.canvas-selector-option`, which has meant the String Selector's option grid since §204 and is defined later in the file. The new rule was dead from the moment it was written; the rows were styled by an unrelated widget, looked fine because that rule is also a flex row, and either widget could have restyled the other from then on. Two modules exporting one name at least fail to typecheck sometimes; two rules claiming one class never do. **Before adding a class, grep for it** — and the tell that you did not is a stylesheet mutant that changes nothing.

  It went three layers deep, and the layers are three separate mistakes. The renamed rule was *still* untestable, because the mutant swapping the class back kept passing — measuring rather than reasoning (§209) showed the row was one line tall, and `align-items: start` cannot differ from `center` on one line. **And the reason it was one line was a real defect**: p.457's property lines were running *inline* after the title instead of beneath it, because `.canvas-dropdown-option`'s grid stacks its direct children and the Selector's sit one element deeper. Every test passed, because they **counted** the detail lines rather than measuring where they were. A collision hid a dead rule, the dead rule hid a flat layout, and the flat layout hid a mis-rendered widget — and what broke it open was a mutant nobody could kill. **A stylesheet mutant that survives is not a missing CSS test; it is a question about whether the rule does anything.**

- **Choosing the strongest observable can leave the obvious one untested.** §215's Object Selector tests all read the *downstream table* its clauses narrow to, which is the right instinct: a widget can draw the right ticks while writing the wrong clauses, and the clauses are what the module acts on. But a selector whose checkboxes never tick — or tick all at once — passes every one of those tests, because the clicks still write correctly. Both mutants survived in the same run. The reader's own feedback went unasserted *because* it looked too simple to be worth a test, next to an assertion that was chosen for being hard to fake. A widget with no visible state is unusable whatever it writes. The tell is a test file where every assertion is one hop away from the widget: at least one has to be about what the person operating it can see.

- **Playwright's `to_have_text` normalises whitespace, so it cannot see a trim.** §214's label test asserted `to_have_text("Site")` against a widget rendering `"  Site  "` and passed — the matcher collapses leading, trailing and repeated whitespace before comparing, which is usually what you want and is exactly wrong when the trim *is* the behaviour under test. The mutant that removed the read sailed through. Anything asserting normalisation — trimming, collapsing, padding — has to read `text_content` (after a `to_be_visible` wait, since it does not retry) and compare exactly. The other half of the same test had the paired fault: it used `""` for "no label", and the empty string is falsy whether or not it has been read through the model, so the case that separates them is `"   "`. Two ways to write a test about whitespace that cannot see whitespace, in one test.

- **When a specification asks for something the platform refuses on purpose, fail soft on the document — do not approximate the feature, and do not drop the control.** §214's Object Dropdown has p.458's "Sort items by"; `object_sets.parse_sort` refuses per-property sorts in a sentence, because instance properties are stored untyped and the two stores order 250 and 40 differently (decision 0006). A property picker in the panel would have looked like it worked and produced a 422 where a list should be. Sorting the *loaded page* client-side would have been worse: it would have claimed to sort the set. What works is to offer what the language does have, **read a value the document holds but the platform refuses back to the default**, and say why in the panel — so a module written against the spec's wording loses its ordering rather than its list. The same shape covers the search: "all searchable properties in the object set" is an `or` across properties and every clause the set language takes is an `and`, so search runs over a bounded page and the widget says on screen when the set is bigger. The tell is a setting whose value has to be sent somewhere that validates it; the question is what a stale or unsupported value should cost, and the answer is never "the whole widget".

- **A guard duplicated one level up is invisible to every test, because the level below is still right.** §213's Object View widget asked whether the bound type had a configured view and used the answer to fall back and to withhold a switch that led nowhere. Both rules are correct; both were already enforced by `ObjectView`, which the widget renders. Replacing the widget's answer with a constant changed nothing on screen, so the mutant survived — and the survivor was not a missing test but two functions, a query and eight unit tests that could never have been observed. §195's version of this was a fix that fixed nothing; this is subtler, because a duplicated guard reads like ordinary defensiveness and the behaviour is right either way. **The question to ask a surviving guard is not "which test is missing" but "who else already refuses this"** — and when somebody does, delete rather than test. The tell is a survivor whose code restates a rule you can point at in another file.

- **A comment that says "nothing could express this" is a claim with a shelf life, and nothing points at it when it expires.** §213 added Workshop p.261's Object View Mode. `object-view.tsx` had opened with "the standard view … cannot be turned off, because … there is no setting that could express 'hide it'" — a sentence that was true about the platform's surfaces, written as though it were true about the code, and copied into `ontology.md`'s parity table where it read as a guarantee. Nothing in the build flagged it: the new setting typechecked, every test passed, and the file went on asserting the opposite of what it now did. The same shape sits in build orders — §213's item had named a dependency that had been satisfied eleven units earlier, because a build order records what was true when written and nothing re-asks. **When a change makes something newly expressible, grep for the words that said it was not**: "cannot", "no way to", "nothing that could", "depends on", plus the noun. It is thirty seconds, and the alternative is a confident sentence that will be believed.

- **A fixture that never crosses the limit the code is written against cannot see the limit.** §212's Links widget header reports a link's `total`; the section under it lists the first page, which the traversal caps at ten. The fixture gave the object two linked rows, so `total` and `items.length` were both 2 — and a header that counted its own list passed every assertion while being wrong by exactly the amount nobody could observe. This is the "two things that had to differ were the same thing" family once more, but with a tell of its own: a **fixture sized under a boundary the code claims to handle**. Any pagination, truncation, clamp or preview limit has one, and the fixture has to cross it or the branch on the far side is untested. The fix is a number, not a test: eleven reports instead of two, and the widget now says "11" over a list of ten.

- **A stop hook that checks `git status` cannot tell your work from a harness's in-flight mutation, and "commit and push" is the wrong answer during a run.** §197 hit this three times; one of the prompts landed on the mutant that makes `CanvasUnused` render its children, which is the exact failure its decision record exists to prevent — committing it would have shipped parked widgets onto the page for every reader. A mutation harness works *by* dirtying `git status`, so during a run the only safe responses are to verify against the running process and wait, or `git checkout --` the file. The check to run is `ps aux | grep <harness>` plus `git diff`: a one-line change reverting a guard, with the harness alive, is never yours.

- **Match a noise filter to the message, never to its source.** §198 found `hot-reloader-client` in the browser suite's `DEV_SERVER_NOISE`, added to silence one benign Next prefetch message that names that file. React's `console.error` is routed through the same client in dev, so *every* React error was being filtered out and the console assertion had never once worked. A source is shared with the things worth failing on; a message is not. The tell is an assertion that has never failed in the whole life of a test suite — and the way to check one is to make it fail on purpose, which is what a mutation harness is.

- **A baseline captured with no wait is an assertion against zero, and its failure blames the wrong half.** §192's clipboard test read `before = tree_rows(page).count()` after `settled()`, which waits for the canvas rather than the Layout panel — so `before` was 0 and `n == before * 2` could never match. It passed on luck for four units. What makes this worth a rule is the *message*: "still 4" points at the value being compared, not at the thing it is compared against, so the obvious reading is that the operation misbehaved. When a comparison against a captured baseline fails, print the baseline before investigating the operation.

- **Match a noise filter to the message, never to its source.** §198's harness produced a survivor that should have been impossible, and the cause was one entry in the browser suite's `DEV_SERVER_NOISE`: `hot-reloader-client`, added because a benign Next prefetch message names that file. React's `console.error` routes through the same client in dev, so the filter had been discarding **every React error in the whole suite** since the day it was written — an assertion whose own docstring insists it "is not decoration". A source is shared with the things worth failing on; the message is not. The comment beside that list had already warned that matching too broadly "would swallow a real API call that did not come back", and the next line did exactly that in a different way.

- **A baseline captured with no wait is an assertion against zero, and its failure blames the wrong half.** §198's console fix unmasked a clipboard test failing on "still 4". That reads as the paste producing the wrong number; the paste was right, and `before` was **0** because `settled()` waits for the canvas while the Layout panel paints after it — turning `n == before * 2` into `n == 0`. It passed on luck for four units until §196 and §197 each added work to the panel's first paint. A probe with identical steps printed 2 and 4 and looked fine; only printing `before` found it. Capture a baseline through a wait, and when a comparison fails, check *both* sides before believing the one the message names.

- **Not every mutant is worth killing — some are sabotage rather than a plausible mistake.** §193 wrote one that rewrites a guard's comparison to read the server's own list, making the test a tautology. It survived, and the right response was to withdraw it: any assertion can be neutered, and proving so says nothing about the code. The useful version is the failure that happens by accident — a scan that quietly stops matching after a reformat — which a vacuity assertion does kill. When a mutant survives, ask whether a maintainer could have written it by mistake before treating it as a hole.

- **A check that compares two copies is blind to anything missing from both.** §191's `REFERENCE_PROPS` had a drift guard asserting the API's list and the browser's matched — and they did, identically wrong, for two props across two units. Mirroring is not completeness. When a list has to be exhaustive, at least one check has to compare it against the *thing it describes* rather than against another copy of itself: here, against the props the builder's settings panels actually read. The same reasoning applies to any pair of mirrored files this repo keeps in step.

- **A mutation harness needs to check that its mutations landed.** A regex that matches nothing produces a run of the unmutated code, which the harness reports as a survivor — indistinguishable from a real hole in the tests, and the natural response is to go looking for the missing assertion rather than the missing backslash. §189 spent two by-hand investigations on this before §190's harness started fingerprinting every file before and after each mutation and reporting NO-OP instead. It costs four lines and it fires exactly when you would otherwise be misled.

- **Fixtures that are gratuitously distinguishable hide the bugs that come from not distinguishing them.** §190's two-tab-groups test gave each group its own tab names, so a mutant that shared one tab choice across the whole module still passed: the second group discarded the first group's choice as naming no tab it had, and fell back to the right answer for the wrong reason. Whenever a test is about *keying* — per section, per row, per widget — the fixtures have to collide on everything except the key, or the component can be ignoring the key entirely and still look correct.

- **A mutation harness that runs only behavioural layers will tell you to delete your type contracts.** §189 had a line whose removal changed no behaviour — a null guard the callee happened to tolerate — so every test passed and it read as dead code. `tsc` was what refused it. Any repo that mutation-tests TypeScript needs a types layer in the harness alongside the test layers, or the discipline quietly argues for deleting every line whose job is to make a type check out.

- **Craft.js gives a canvas widget its children as one Fragment, not a list.** `React.Children.toArray(children)` therefore returns a one-element array however many widgets the node contains, and nothing errors — §78's sections all rendered as a single column until this was found. Any canvas widget that needs to treat its children individually (a section, a grid, anything positional) must go through `childList()` in `widgets.tsx` rather than `React.Children` directly.
- **An undefined CSS custom property is silently nothing, not an error.** `background: var(--surface)` in a repo whose variable is `--panel` renders transparent, and a structural browser check will pass straight through it — this bit twice (§78's overlay panel, and `.repo-preview-table th` before it). A check on something that must be *visible* should assert a computed colour, not just the element's presence.
- ~~Native HTML5 drag-and-drop (what Craft.js's toolbox uses to create new widgets) can't be reliably driven by Playwright automation - `dragTo()` and manual mouse event sequences both no-op against it.~~ **Corrected in §78**: Craft.js's `connectors.create` listens for *pointer* events, not the HTML5 drag API, so `dragTo()` fails but a `mouse.down` → `mouse.move(..., steps=N)` → `mouse.up` sequence drives it fine — the `steps` argument is the part that matters, since a single jump gives Craft no intermediate move to compute a drop target from. Dropping a widget into a section is verified by automation on that basis.
- **`TEST_ADMIN_DSN` must contain a literal `?` (e.g. `...devpass@localhost:5432/platform?sslmode=disable`), not just `.../platform`** - `tests/test_connections.py`'s source-database fixture builds its isolated test database's DSN via `ADMIN_DSN.replace("/platform?", f"/{SOURCE_DB}?")`; if `ADMIN_DSN` has no `?` suffix the `.replace()` silently no-ops and every statement meant for the fixture's own throwaway `conn_source_test` database (a `public.orders` table, a `public.recent_orders` view, a blanket `GRANT ALL ON ALL TABLES` to a scratch login role) runs against the real shared `platform` database instead. This session hit it directly: a malformed DSN during this session's final regression run polluted the shared dev Postgres with exactly those objects and grants, breaking every other suite's fixtures with `DependentObjectsStillExist` on an unrelated `DROP ROLE`. Fixed by using a correctly-suffixed DSN and manually reverting the pollution (`REVOKE`/`DROP VIEW`/`DROP TABLE`/`DROP ROLE`) - not a product bug, but worth getting right the first time since the failure mode is silent until a much later, unrelated test trips over it.
- **Worker jobs' discovery functions are global across every workspace by design** (§14, §16 - RLS-blind on purpose, since a scoped connection can't discover work in workspaces it doesn't know about), which means running the worker test suite's `run_due_object_source_syncs`/`run_due_sync_configs`/etc. against the *real* dev `platform` database (rather than a disposable one) will also pick up and act on any real, non-test source/connection that happens to be due at that moment - including one left over from manual browser verification in this same session, whose `LOCAL_STORAGE_ROOT` differed between the manual run and the pytest run and so failed with a stale storage-path error the next time discovery found it due. Point `WORKER_DATABASE_URL` at a disposable database for routine worker test runs where possible; if it must be the shared dev database, expect real dev-sandbox rows to occasionally get touched by test runs and vice versa.
- **A failed `cdk deploy` (CREATE_FAILED) can leave the automatic rollback stuck in `DELETE_FAILED`**, found live re-deploying the §17 dry-run stack after a bad build. Two independent causes, both structural to how CloudFormation handles these resource types, not bugs in this repo's code: (1) RDS `deletionProtection: true` blocks CloudFormation from deleting the DB instance during *any* CFN-driven deletion, including its own automatic rollback of a botched CREATE - not just a deliberate `delete-stack` on an established stack - because CFN checks the template's declared property, not the live value, so this triggers even on a stack that was never touched out-of-band; (2) a VPC-joined OpenSearch domain that's still mid-creation when something else fails can get cancelled without CloudFormation ever actually issuing it a `DeleteDomain` call, leaving it (and its ENI) alive and blocking every security group/subnet that depends on it - confirmed via `describe-domain` reporting `Processing: false, Deleted: false` on a domain that had, in fact, finished creating. Recovery (documented as a runbook the first two times, since there's no clean prevention for the OpenSearch half): disable + directly delete the RDS instance, directly `delete-domain` the OpenSearch domain if `describe-domain` shows it was never told to, then retry `delete-stack`. For the RDS half specifically, `data-stores.ts`'s `deletionProtection` prop (default `true`, unchanged for real deploys) is now overridable via `-c deletionProtection=false` for exactly this kind of dry-run stack that expects to be torn down repeatedly - the control plane's own deploys never pass this key, so real customer stacks keep the safe default.

---

## Running it locally

```
scripts/setup.sh
```

From a fresh checkout to a stack you can sign into. It asks before anything slow, is safe to re-run, and finishes by printing the URL and a token. `--defaults` takes every default and asks nothing.

**`docs/local-setup.md` is the guide** — the same steps by hand, what each one is for, how to seed a test client or user, and the failures worth recognising by sight (the DSN form `migrate.py` refuses, the `PLATFORM_APP_PASSWORD` the schema needs, why a token stops working when the API restarts).

Underneath: `scripts/dev-up.sh` starts Postgres, the API on 8300 and Next on 3100, seeding a dev org with four users at each role level and writing their tokens to `/tmp/anchor-dev-tokens.json`; `apps/api/dev_server.py --extra-user` adds your own; `scripts/dev-down.sh` stops the two servers again and leaves Postgres alone, because it is not this repo's to stop. `scripts/check.sh` runs every check the repo has.
