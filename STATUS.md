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
- Dev/test Postgres accumulates residue across sessions: worker and API test suites create real orgs/workspaces/connections/models in the shared local dev database and don't clean them up afterward (by design - matches the existing `test_cleanup.py`/discovery-function pattern of not needing per-test teardown, since most discovery queries naturally stop matching once a schedule advances past "due"). This session hit one case where that assumption didn't hold: leftover cron models and scheduled syncs from earlier, interrupted test runs had never advanced past their `next_run_at`/`sync_next_run_at`, so a later manual worker invocation picked them up and failed against long-deleted tmp-directory files. Not a product bug - the two real bugs it surfaced (per-connection error isolation, empty-cursor VARCHAR mismatch, both in §14) were - but worth knowing if a stray "failed" run shows up against an unfamiliar workspace slug in this sandbox's Postgres.
- **A scheduled-sync test that leaves its schedule behind poisons every later run** - found the hard way in §22. The worker reschedules a connection after every run (the tests use `* * * * *`), so a test connection left in the database is *permanently due*: the next suite run rediscovers it and tries to sync it against a source that no longer exists - a dropped MySQL database, a `moto.server` on a port nothing is listening on, a `tmp_path` storage root long since deleted. Nothing fails (the job's per-candidate isolation records it and moves on), it just gets slower, and it compounds - 81 stale connections had accumulated by the time it was noticed, taking the worker suite from 16 seconds to over ten minutes, since each dead source costs a connect timeout and boto3 retries three times before giving up. Both worker `workspace` fixtures now clear `sync_schedule`/`sync_next_run_at` on teardown (`test_sync_configs.py` for connections, `test_instance_syncs.py` for object-type sources) and the suite is back to ~16s. Any new fixture that schedules something must do the same - this is the shared dev-database residue problem below, in its one form that actually bites.
- **The API's and worker's connector registries are two files that must be kept in step** (`apps/api/src/services/connectors.py` and `apps/worker/src/anchor_worker/connectors.py`) - duplicated deliberately, for the same reason `dataset_engine.py`/`storage.py` already are (independently deployable images, no shared Python package in this build), but with a nastier failure mode than those two: a source type registered in the API but missing from the worker syncs fine interactively and then silently fails on its schedule, per connection. `apps/worker/tests/test_mysql_sync_configs.py` asserts the registries agree; extend that assertion when a third source type lands, and treat "did the worker get it too?" as part of adding any connector. A shared package would remove the class of bug entirely and is worth doing if a third or fourth connector arrives - it means moving both service images to a repo-root Docker build context, which `apps/web/Dockerfile` already requires (§17 bug 1), so the precedent exists. **§29 raised the stakes on this**: the expectations evaluator is now mirrored too (a fourth thing to keep in step, with its own parity test in `test_model_runs.py`), and its drift mode is worse than the connectors' - a rule the API can store but the worker cannot evaluate would make a gated run's verdict silently disagree with the dataset's own health badge. Whoever adds the fifth mirror should build the shared package instead.
- **Worker jobs' per-candidate `except` tuples are the single most repeated bug in this codebase** - §14 (twice, `sync_configs.py`), §16 (`instance_syncs.py`, `StorageKeyError`), and §21 (`sync_configs.py` again, the *same* `StorageKeyError` gap §16 fixed one file over). Every occurrence has the same shape: a job calls something that raises an exception type the isolation tuple doesn't name, so one bad candidate crashes the whole batch instead of failing alone. When adding or editing a scheduled job, enumerate every exception type on the call path rather than the ones a first test run happens to exercise - and when fixing one job, check its siblings for the identical gap.
- **RLS policies that read another RLS-protected table are a recurring bug class in this codebase** - 0008 (users), 0009 (canvas_apps↔canvas_app_shares), and now 0015 (canvas_apps↔projects) all hit the same shape: a policy's `USING` clause subqueries a table whose own policy can legitimately hide the exact row the first policy needs, so the check silently fails closed instead of erroring loudly. Worth a systematic pass if another cross-table RLS policy gets added - the fix is always the same (`SECURITY DEFINER` helper resolving just the needed column, bypassing RLS internally) but nothing currently catches the pattern except noticing a feature silently doesn't work.
- **`npm run build` while `next dev` is running corrupts the dev server.** Both write `apps/web/.next`, so a production build under a running dev server leaves it serving 500s with `Cannot find module './vendor-chunks/@tanstack.js'` on every route - which reads as a broken page rather than a broken cache, and cost a debugging detour in §47. Recovery: stop the dev server, `rm -rf apps/web/.next`, restart. Run the two in sequence, never concurrently.
- **An applied migration is immutable, and that includes its comments.** `migrate.py` checksums the file, so editing one - even to fix prose that is actively wrong - makes every database that already applied it refuse to migrate at all. Hit in §92: §90's docstring correction to `0034` blocked `0036` from applying, and would have blocked it in production too. Corrections to a migration's *prose* go in `packages/db/migrations/ERRATA.md`; the runner ignores `.md`. There is no escape hatch and there should not be one - the guard cannot tell a comment from a statement from a hash, and a runner that tried would be a runner that sometimes let a changed statement through.

- **`verify_schema.py` needs a fresh database; it cannot be run twice against the same one.** It creates a fixture organisation, and `audit_log`'s append-only `DELETE` rule (migration 0004) *silently* discards deletes — `DELETE 0`, row still present, even as superuser with `row_security = off` — so the fixture can never be cleaned up and the second run dies on a duplicate slug before checking anything. Found in §88, and it is the reason the verifier's "no unexplained extra tables" check had been failing unnoticed for sixteen migrations.
- **Four features are waiting on one missing capability: the instance index does not honour declared property types.** **Decided in `docs/decisions/0006-typed-instance-properties.md` (§104), not built** — one index per object type, text ordering refused permanently, the map's box as a `geo_bounding_box`, and what the OpenSearch fixture needs before the build is checkable at all. Ordered filters (`gt`/`lt`), numeric aggregations (`sum`/`avg`/`min`/`max`, §74), sorting a table by a property (§83) and selecting an area on a map (§86) are each refused for the same reason — properties are stored untyped, so a comparison means one thing on Postgres and another on OpenSearch. Every refusal says so in a sentence. **It cannot be built in this sandbox**: the OpenSearch side is tested against `tests/opensearch_fixture_server.py`, which has no mapping enforcement by design, and there is no Docker daemon and no reachable OpenSearch artifact host here, so the cross-store agreement — the entire point — cannot be demonstrated. It needs a real cluster, not more code.
- **Two sources feeding one object type produce two instances for the same primary key** (found in §83). Instance identity is `(source_id, primary_key)` — `instance_store._doc_id` — so pointing a second dataset at an object type that already has one duplicates every overlapping key instead of updating it, and a set over that type returns each duplicated object twice. Nothing errors. Multi-source object types are a legitimate Foundry pattern (a union of feeds into one type), so the honest fix is to make identity `(object_type_id, primary_key)` and decide what happens when two sources disagree about the same object's properties — an ontology decision with a backfill behind it. Until then, one source per object type.
- **Reading a Playwright locator as `count()` then `nth(i)` is a torn read, and it fails as a 30-second hang rather than a wrong answer.** The obvious way to snapshot a column - `{cells.nth(i).inner_text() for i in range(cells.count())}` - is two or more round trips to the browser. A re-render landing between them (a filter change is exactly that) leaves it asking for a row that no longer exists, and `nth(i).inner_text()` then *blocks for the full timeout* instead of returning something stale that a polling helper could reject and retry. Found in the resource-filter browser check: the run took 48s instead of 20s and failed only on the first run after a source edit, which read convincingly as "the dev server was recompiling" for several rounds. Use `all_inner_texts()` (or `all_text_contents()`), which is one call and one snapshot. This matters most inside `eventually`, where the whole design assumes a cheap read that can be retried.

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
