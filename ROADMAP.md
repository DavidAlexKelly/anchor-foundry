# Anchor — Roadmap phase 2: Foundry-shaped applications

_Phase 1 built six pillars and is complete: it lives in `docs/roadmap-phase-1-pillars.md`, and `STATUS.md` §21–§55 is the detail. **Cross-references elsewhere in the repo of the form "ROADMAP.md section N item M" mean that document, not this one.**_

_This document is the plan for a different thing: making Anchor's surfaces work the way Palantir Foundry's do. It is written to be started from, so each item carries what Foundry actually does, what exists here today, what to build, and how you would know it worked._

---

## What is actually being asked for

Phase 1 produced a competent web app with six tabs. Foundry is not shaped like that, and the difference is not cosmetic:

> **In Foundry, a project is a folder of resources, and every resource opens its own full-screen application.** A dataset opens Dataset Preview. A Workshop module opens Workshop. A repository opens Code Repositories. The project view is a *file browser*; the application is where the work happens.

Anchor today inverts this. `/[workspace]/[project]/datasets` is a page listing datasets, and a dataset is a row that expands. The pillar is the destination and the resource is a detail of it. Foundry's pillars are not destinations at all — they are resource *types*.

Three shifts follow, and they are the whole of this roadmap:

1. **Resources become first-class and open as applications** — their own route, their own full-viewport UI, their own tab. This is the structural precondition for the other two.
2. **Code stops being a `<textarea>` and becomes an IDE.** Today `code/page.tsx:407` and `models/page.tsx:330` are literally plain textareas holding SQL. Foundry's equivalent is a browser IDE with a file tree, multi-file repositories, branches, pull requests, checks, and a preview that runs your transform on a sample before you commit.
3. **Canvas becomes Workshop.** Today: eight Craft.js widgets on one page, each holding its configuration inline. Workshop: a typed **variable** system, an **event** system, a **layout** system (header, pages, sections, overlays, tabs), and a widget library several times the size — with widgets wired to each other through variables rather than configured in isolation.

### Parity map

| Anchor today | Foundry equivalent | Honest gap |
|---|---|---|
| `/project/datasets` list + row detail | **Dataset Preview** app (Preview, Details/Schema, History, Time Travel tabs) | No dedicated app; profiling and lineage exist but are scattered across pillar pages |
| `/project/models` + SQL textarea | **Pipeline Builder** (visual) and **Code Repositories** (code) | No editor worth the name; single-statement transforms only |
| `/project/code` change sets, proposals, reviews | **Code Repositories** | Review workflow exists and is good; the *repository* underneath it is one file per model version |
| `/project/objects` + `/objects/[typeId]` | **Ontology Manager** + **Object Explorer** | Closest to parity of anything here |
| `/project/canvas/[appId]` — 8 widgets | **Workshop** | No variables, no events, no layout system, no view/edit separation |
| `/project/pipeline` DAG | **Data Lineage** app | Exists; needs to become a destination rather than a tab |
| Project overview with pillar cards | **Project resource browser** | The core inversion described above |

---

## Section 0 — The precondition: resources, and applications that open them

**Nothing else in this roadmap can be built first.** Both Workshop and Code Repositories are full-viewport applications; there is currently no way to *be* one. Sequenced first for that reason alone, and it is the smallest section.

### ~~0.1 A resource registry with stable resource IDs~~ — **done, `STATUS.md` §53**

**What Foundry does.** Every resource has an RID (`ri.foundry.main.dataset.<uuid>`) that is stable for life, survives renames and moves, and is what every link, permission and lineage edge points at. The resource type is *in* the identifier, so a link can be resolved to an application without knowing where it came from.

**What exists today.** Six unrelated tables with their own UUID primary keys (`datasets`, `models`, `object_types`, `canvas_apps`, `connections`, plus `code_change_sets`). Nothing enumerates "everything in this project" — `resource_counts` in the project detail endpoint is six separate `COUNT(*)`s, which is why the first-run checklist needed the project-scoped fix in `STATUS.md` §44.

**Build.**
- Migration `0032_resources.sql`: a `resources` table — `id`, `workspace_id`, `project_id`, `kind` (enum: `dataset`, `model`, `object_type`, `workshop_module`, `code_repo`, `connection`), `name`, `description`, `created_by`, `created_at`, `updated_at`, `trashed_at`. Existing tables gain `resource_id` (FK, unique, not null) and **backfill in the same migration** — a resource with no registry row is invisible to the browser, so partial adoption is worse than none.
- Keep the per-kind tables. This is a registry, not a rewrite: `datasets` still holds dataset-specific columns. The registry owns identity, naming, location and lifecycle; the kind table owns everything else.
- RLS policies on `resources` mirroring the project-scoped ones (`rls_can_access_project`), and the kind tables keep theirs — belt and braces here is correct because a leak in the registry leaks *names across projects*, which is the metadata Foundry treats as sensitive.
- `GET /api/workspaces/{ws}/projects/{p}/resources` with kind filter, search, sort, pagination.

**Prove it.** Rename a dataset, confirm every link still resolves. Move a resource between projects, confirm permissions follow the new project and not the old one. Trash a resource, confirm it leaves the browser but lineage edges pointing at it still render (as trashed) rather than 404.

**Watch for.** The temptation to make `resources` the *only* table and hang JSON off it. That trades six well-typed schemas for one untyped one, and the schema verifier that has caught real bugs (`STATUS.md` §7) has nothing left to verify.

### ~~0.2 The project resource browser~~ — **done, `STATUS.md` §54**

**What Foundry does.** The project page is a file browser: name, type icon, last modified, owner; sortable, filterable by type, searchable. It is deliberately dull, because it is a *directory*, not a dashboard.

**What exists today.** `page.tsx` renders six pillar cards with counts and a first-run checklist.

**Build.** Replace the pillar cards with the resource table. Keep the first-run checklist — it is genuinely good for an empty project and Foundry has no equivalent worth copying. Type filter chips, a New button per creatable kind, breadcrumbs.

**Decision to make deliberately:** whether the pillar tabs survive at all. Recommendation: **keep them as filtered views of the browser** (`?kind=dataset`), not as separate pages. Deleting them outright loses discoverability for people who do not yet know what a resource is; keeping them as separate implementations guarantees they drift.

**Depends on** 0.1.

### ~~0.3 The application shell and `/r/{id}` routing~~ — **done, `STATUS.md` §54**

**What Foundry does.** A resource URL resolves to whichever application handles that type, full-viewport, with a thin top bar (breadcrumb back to the project, resource name, sharing, save state) and no platform chrome.

**Build.**
- Route `/(app)/r/[resourceId]` outside the `(platform)` group so it does not inherit the sidebar.
- A server-side lookup of `kind` → dynamic import of that kind's application. Unknown or trashed → a real "this resource no longer exists" page, not a 404 shell.
- A shared `<ApplicationShell>`: breadcrumb, title (rename in place), save/dirty state, share, and a slot for app-specific toolbar items.
- Clicking a row in the browser opens `/r/{id}` **in a new tab** (`target="_blank"` with `rel="noopener"`), which is the specific behaviour asked for. Cmd-click and middle-click must keep working — that means a real `<a href>`, not an onClick handler calling `window.open`.

**Prove it.** Open five resources of different kinds in five tabs; each has the right app, the right title, and a working back-to-project breadcrumb. Refreshing any tab lands in the same place.

**Depends on** 0.1.

### 0.4 Deep links into application state — **S**

**What Foundry does.** A Workshop URL carries the page and the variable state; a Dataset Preview URL carries the tab. You can send someone a link to what you are looking at.

**Build.** Per-app URL state (query params), a "copy link" affordance in the shell, and restore-from-URL on load. Do this **while** each app is built rather than after — retrofitting URL state means unpicking component state that has already been written to assume it owns everything.

---

## Section 1 — Workshop (replacing Canvas)

The largest section. Workshop is a real application-building product; treating this as "more widgets" is how it ends up as a dashboard tool with a widget menu.

The three things that make Workshop *Workshop* — and that Canvas has none of — are **variables**, **events** and **layouts**. Build them before widget number nine.

### 1.1 Design spike: the module definition document — **M, and blocking**

**The problem.** Canvas stores its definition as Craft.js node props: each widget holds its own configuration inline (`CanvasChart` holds its dataset id, dimension, measure, aggregate). Workshop widgets do not work that way. A widget takes an **input variable** and writes an **output variable**; the filter list does not know the object table exists, and the object table does not know where its object set came from. The wiring is a graph that lives *beside* the layout tree, and Craft.js does not model it.

**Decide, and write it up as `docs/decisions/0002-workshop-module-format.md`:**
- The module definition is one document with three top-level parts: `layout` (the tree), `variables` (id → declaration), `events` (id → declaration). Widgets reference variables by id.
- Whether Craft.js stays. Recommendation: **keep it for the layout tree** — it is working, the drag/drop and selection model is non-trivial, and `STATUS.md` §37's hard-won pan fix lives in that world — but stop using node props as the system of record for anything but layout and per-widget display options.
- Variable *values* are runtime state and are never persisted with the module. This is the same rule the canvas already follows (`context.tsx`), and it is the rule that keeps a saved app from being a saved *session*.
- Migration path for the existing apps. There are few enough that a one-shot migration in SQL is honest; a compatibility layer for a format nobody outside this repo uses is not.

**Prove it.** Round-trip an existing canvas app through the new format and render it unchanged.

### 1.2 Variables — **L**

**What Foundry does.** Typed variables are the wiring. Types: **object set**, **single object**, string, numeric, boolean, date/timestamp, array (of boolean, date, numeric, geopoint, geoshape, string, timestamp or struct), and object-set-filter variables. Object set variables are initialised from an object type or another object set, then optionally filtered by property values or Filter variables, or **pivoted to linked objects via a Search Around**. Variables also support **transformations**: string concatenation, if/else, casting between primitives, `is empty`/`is not empty`, `object property` (a property of a single object), and `object set aggregation` (an aggregate over a property of a set) — and transformations chain, referencing earlier ones.

**What exists today.** `context.tsx` holds a flat map of parameter values, untyped, set by the Filter widget and read by whatever asks. No object sets, no derivation, no chaining.

**Build.**
- A typed variable model in `packages/types`, shared by API and web.
- A variables panel in the builder: create, rename, retype, see usages (and **refuse to delete a variable a widget is bound to** — the alternative is a widget silently reading undefined).
- Evaluation: derived variables recompute when their inputs change; cycles are refused at save time. The cycle refusal already has a precedent to copy — Models item 7 (`STATUS.md` §30) does exactly this for the transform DAG.
- Object set variables are the hard part and where the value is: they need server-side evaluation against the instance store (OpenSearch, `STATUS.md` §31), because "filter this set and aggregate it" cannot be done client-side over a 200-row page. **This is the item that decides whether Workshop parity is real.**

**Prove it.** A filter list narrowing an object set that an object table and a chart both read, live, with a metric card showing an aggregation over the same set. Change the filter; all three update; no page reload.

**Depends on** 1.1.

### 1.3 Events — **M**

**What Foundry does.** Events trigger behaviour when a user acts. They fire from many widgets — Button Group, Object Table on row selection, String Dropdown on select/deselect, Tabs. A button's **On click** can trigger an action, trigger a set of events, open a URL, or begin an export; when it triggers an action you can additionally fire events at points in the action lifecycle (on submission start, on successful completion). Events execute **sequentially in configured order**, but do not wait for the downstream computation of previous events. Setting a variable copies the value immediately, so the next event sees it.

**Build.** An event model (trigger → ordered list of effects), effects for: set variable, navigate to page/overlay, open URL, run action, export. Sequential execution with the copy-immediately semantics above — worth matching exactly, because the alternative (awaiting each effect) produces different results for the same configuration and is the kind of difference that is invisible until someone's app misbehaves.

**Depends on** 1.2.

### 1.4 Layouts — **L**

**What Foundry does.** A module has a **header** (persistent toolbar for module-wide title, tabs and buttons), **pages**, **sections**, and **overlays**. A default page starts as two vertically divided sections. Sections subdivide a page and can be configured as columns, rows, tabs or toolbars, each containing widgets or further layout. Overlays are contextual layers over a page — modals and drawers — for content that should not navigate you away. A **Tabs widget** triggers events to navigate between pages and overlays. Layout elements are edited from a Layout sidebar panel or by selecting them in the module view.

**What exists today.** One page, free-form drag-and-drop, no header, no sections, no overlays.

**Build.** The layout tree from 1.1 with those node types; the Layout sidebar; drag-to-resize sections; the Tabs widget wired to the event system. Responsive rules per section type.

**Watch for.** This is the item where "as close to Workshop's UI as possible" costs the most and pays the most — a Workshop user opening Anchor recognises the three-panel shell (Layout/Variables sidebar, canvas, widget configuration) before they recognise any individual widget.

**Depends on** 1.1, and the Tabs widget depends on 1.3.

### 1.5 The widget library — **XL, and incremental**

Anchor has eight: Container, Text, Filter, Dataset table, Object table, Map, Chart, Action form.

Build toward Foundry's set, in the order below (roughly descending value per unit of work):

| Priority | Widget | Notes |
|---|---|---|
| 1 | **Filter List** | The canonical Workshop widget. Property-aware filters over an object set, emitting an object set variable. Anchor's Filter emits a scalar — this is a rewrite, not an extension |
| 1 | **Object Table** (upgrade) | Row selection emitting single-object and object-set variables; column config; sorting; server-side paging |
| 1 | **Button Group** | The event system's primary trigger surface |
| 1 | **Metric Card** | A configurable card highlighting a key metric; the natural consumer of object-set aggregation |
| 2 | **Tabs** | Navigation between pages and overlays |
| 2 | **Charts** (upgrade) | Object-set input rather than dataset-only; drill-down emitting a filtered set |
| 2 | **Map** (upgrade) | Object-set input; selection emitting a set. The clustering and pan work (`STATUS.md` §37) carries over |
| 2 | **Inline Action Form** | Editing objects from inside the app; upgrade of the existing Action form |
| 3 | **Object List / Card List** | Card-shaped alternative to the table |
| 3 | **Pivot Table** | Cross-tab over an object set |
| 3 | **Search / Prominent Terms Filter** | Foundry's example apps lean on these |
| 3 | **Time Series / Timeline** | |
| 4 | **Embedded module** | One module inside another — needs 1.4 first |
| 4 | **Comments / Notepad** | |

**Rule for every widget:** it consumes input variables and emits output variables. A widget that reaches directly for a dataset id is a widget that cannot be wired to anything, which is the flaw in the current eight.

### 1.6 The builder shell — **M**

Three panels: left (Layout tree / Variables / Events, tabbed), centre (the module), right (configuration for the selection). Plus **Edit and View modes** — Workshop's edit/preview split is not a nicety, it is how you check an app before publishing it. Anchor's viewer route (`/[workspace]/apps/[appId]`, `STATUS.md` §44) is the seed of View mode.

**Depends on** 1.4.

### 1.7 Publishing, sharing and permissions — **M**

Published modules with a version pointer, so editing a live app does not change what users see until you publish. Per-module sharing. Widget-level visibility conditions driven by variables (a section that appears only when a set is non-empty — `is empty`/`is not empty` from 1.2 exist precisely for this).

### 1.8 Migrating the existing canvas apps — **S**

One-shot SQL migration to the new format, run against real saved apps, with the old definitions retained in the migration's audit trail. **A record of what an app was must not change when the format does** — the same principle that shaped the dataset/version work in phase 1.

---

## Section 2 — Code Repositories

**What Foundry does.** Code Repositories is a web IDE for production code: authoring support (IntelliSense, linting, error checking, rich help dialogs), version control, change management and CI, and it is the intended place for pull request review and repository management. **Transforms repositories** author data transformation logic in Python, Java or SQL, with features for previewing and debugging transforms — a **Preview** that runs your code on a limited sample of the input datasets without committing. Pull requests support description templates. (Foundry also has **Code Workspaces** — hosted JupyterLab, RStudio and VS Code — for exploratory data science. That is a *separate product* from Code Repositories, and conflating them is the main risk in this section. See "what this does not include".)

**What exists today, and it is more than it looks.** `docs/decisions/0001-where-code-lives.md` already decided the hard architectural question: **no git server; the system of record is Postgres; git federation is an optional outbound mirror.** On top of that sit change sets, proposals, reviews and a review gate (`STATUS.md` §45–§47) — the *governance* half of Code Repositories, already built and tested. What is missing is the *repository* and the *editor*: today a "repository" is one SQL string per model version, edited in a textarea.

### 2.1 Design spike: multi-file repositories on Postgres — **M, and blocking**

The decision in `0001` covers a single file per model. It does not cover: multiple files, directories, branches, merge, or what a commit *is* when there is no git.

**Decide, and write up as `docs/decisions/0003-repository-storage.md`:**
- Content-addressed blobs (`sha256` → content) plus trees plus commits, i.e. git's data model without git — or a simpler snapshot-per-commit. Recommendation: **the git model**, because branches and diffs fall out of it for free and the alternative reimplements them worse.
- Branch semantics: what a branch is, what merge does, whether fast-forward-only (recommended — three-way merge in a browser IDE is a product in itself).
- How a repository relates to the datasets it produces. In Foundry a transform *declares* its outputs; that declaration is what lineage is built from. Anchor derives lineage from model definitions today, so this is a change to how the DAG is computed.
- What happens to `model_versions`. It cannot simply be dropped — rollback (`STATUS.md` §29) depends on it.

### 2.2 A real editor — **M**

**Monaco**, self-hosted. Not a CDN import: the deployed stack has a strict egress posture and the onboarding page's CSP experience is the precedent. Bundle it, lazy-load it, and pin the version.

Python and SQL syntax first; language-server-grade IntelliSense is 2.9, not this item. Ship: syntax highlighting, bracket matching, multi-cursor, find/replace, a keybinding set people recognise.

### 2.3 File tree and multi-file editing — **M**

Tree, create/rename/delete/move, tabbed editors, unsaved-state indicators, and a working-set concept so a half-finished edit survives navigating away. **Depends on** 2.1.

### 2.4 Branches — **L**

Create from a branch, switch, list, delete. Commit to a branch. A diff view (the existing `services/code.py` diff logic already handles the trailing-newline case correctly — `STATUS.md` §46 — and should be reused, not rewritten). Fast-forward merge. **Depends on** 2.1.

### 2.5 Transforms authoring — **L**

The point of the whole section: code in a repository that declares the dataset it produces, and a build that runs it. Python transforms executing in the worker; the existing DuckDB execution path is the target, and the sandboxing question (running customer Python) is a real security design item, not an implementation detail — **flag it early, do not discover it at build time**.

SQL transforms are the cheaper first step and should ship first, because they are what exists today, just relocated into a repository.

### 2.6 Preview — **M**

Run the transform against a limited sample of its inputs, without committing, and show the resulting rows and schema. Foundry's Preview is the feature that makes the IDE usable rather than ceremonial; it is also the natural place to catch the schema drift the connectors already detect (`STATUS.md` §26).

### 2.7 Pull request review UI — **M**

Anchor already has proposals, reviews, blockers and the review gate. What it lacks is the *review surface*: side-by-side diffs, inline comments anchored to lines, per-file resolution, a description template. Build the UI onto the existing service rather than a second workflow beside it.

### 2.8 Checks — **M**

Lint and schema-compatibility checks that run on a proposal and block merge. Reuse the existing quality-gate machinery from Models item 3 where it fits.

### 2.9 Code assistance — **L, and optional**

Foundry's Code Repositories offers inline AI assistance over a highlighted snippet — Explain, Find bugs, Ask a question. Genuinely useful, entirely separable, and it depends on a model provider decision that this platform has not made. **Do not let it block anything.**

---

## Section 3 — The Dataset application

**What Foundry does.** Dataset Preview shows metadata, build history, health and more, across tabs: **Preview** (a sample of the data), **Details** (technical information and administrative operations, including Schema — full column specifications, editable where applicable), **History** (dataset change history), and **Time Travel** (an interactive view of how the dataset changed across committed versions).

**What exists today.** All of the substance and none of the shape: column profiling (`STATUS.md` §22), lineage (§27), forking (§28), schema policy and drift detection (§26). It is spread across pillar pages and row expanders.

### 3.1 The dataset application — **M**

Full-page app at `/r/{id}` with tabs Preview / Schema / Details / History / Lineage. Mostly a re-presentation of endpoints that already exist, which makes it the **best first application to build after Section 0** — it proves the shell against something already working, rather than co-developing an app and its backend.

### 3.2 Column detail — **S**

Profiling per column (min/max/null rate/distinct) surfaced in the Schema tab, where it belongs.

### 3.3 Time travel — **M**

Browse a dataset at a previous version. Needs a decision on retention, and it is the one item here that has a storage bill attached — say so in the item rather than in the invoice.

---

## Section 4 — Ontology applications

Closest to parity already. Two applications, both mostly re-presentation:

### 4.1 Object Explorer — **M**
Workspace-wide search, type filtering, saved searches, link traversal. The explorer (`STATUS.md` §32) and traversal (§33) exist; this is the full-page app around them.

### 4.2 Ontology Manager — **M**
Type and link management, property types, change history (§34, §35) as a proper application rather than a settings page.

---

## Cross-cutting

- ~~**Session storage.**~~ Done (`STATUS.md` §55): the browser session is an httpOnly cookie brokered by the API, which is what made opening every resource in its own tab workable at all.
- **Permissions per resource.** `resources` is the natural place for resource-level sharing. Today permissions are project-scoped; Foundry's are per-resource. Decide before Workshop publishing (1.7) needs it.
- **Testing standard is unchanged**: real Postgres, real OpenSearch, real dev servers, real browser. Two of the four defects found this week were invisible to the API tests and obvious in a browser (`STATUS.md` §52) — Workshop is far more interactive than anything built so far, and Playwright coverage of the builder is not optional.
- **Performance.** Object set evaluation (1.2) is the first thing here that can be slow in a way users notice. Budget for server-side evaluation and paging from the start.
- **The Cognito first-login blocker is still open** and still blocks a real deployment being usable. None of this roadmap matters on a real stack until that is fixed.

---

## Suggested order

1. **Section 0** (0.1 → 0.2 → 0.3). Nothing else can start.
2. **Section 3.1** — the dataset application, as the first thing through the new shell. Low risk, proves the pattern, immediately better than a row expander.
3. **Section 1.1** — the Workshop format spike. Do this early even though building against it comes later; it is the decision most expensive to get wrong.
4. **Section 1.2 → 1.4** — variables, events, layouts. The point of no return: after this Canvas is Workshop-shaped even with eight widgets.
5. **Section 2.1 → 2.4** — repository storage, editor, files, branches. Independent of Workshop; a second person could run this in parallel from here.
6. **Section 1.5** — widgets, continuously, priority order.
7. **Sections 2.5–2.8, 3.2–3.3, 4** — as capacity allows.

**On scale, plainly:** Workshop and Code Repositories are each a product, not a feature. Section 0 is a few weeks. Section 1 to genuine parity is months. The order above is chosen so that something is better after every step rather than after all of them — if this stalls at step 4, Anchor still has resource-centric navigation, a real dataset app, and a Workshop-shaped canvas with a small widget library, which is a coherent product. Stalling at step 6 leaves nothing half-built.

---

## What this deliberately does not include

- **Code Workspaces** (hosted JupyterLab/RStudio/VS Code containers). Foundry ships these *alongside* Code Repositories for exploratory work; they are per-user compute environments with a large infrastructure and security surface. The ask was "VS Code-like code workspaces", and Section 2 delivers the *editor experience* — the browser IDE — which is where that value is. Hosted per-user containers are a separate decision with a separate bill; naming it here rather than smuggling it into Section 2.
- **A git server.** Already decided in `docs/decisions/0001`. Section 2.1 extends that decision; it does not reopen it.
- **AIP.** Foundry's AI surfaces run through it. Not modelled here.
- **Slate.** Foundry's older app builder. Workshop is the current one; building toward the deprecated product would be strange.
- **Three-way merge** in the browser IDE. Fast-forward only until somebody has a concrete need.

---

## Sources

Foundry behaviour above is drawn from Palantir's public documentation:
[Workshop widgets](https://www.palantir.com/docs/foundry/workshop/concepts-widgets) ·
[Workshop variables](https://www.palantir.com/docs/foundry/workshop/concepts-variables) ·
[Variable transformations](https://www.palantir.com/docs/foundry/workshop/variable-transformations) ·
[Workshop layouts](https://www.palantir.com/docs/foundry/workshop/concepts-layouts) ·
[Workshop events](https://www.palantir.com/docs/foundry/workshop/concepts-events) ·
[Button Group](https://www.palantir.com/docs/foundry/workshop/widgets-button-group) ·
[Object Table](https://www.palantir.com/docs/foundry/workshop/widgets-object-table) ·
[Filter List](https://www.palantir.com/docs/foundry/workshop/widgets-filter-list) ·
[Pivot Table](https://www.palantir.com/docs/foundry/workshop/widgets-pivot-table) ·
[Code Repositories](https://www.palantir.com/docs/foundry/code-repositories/overview) ·
[Code Workspaces](https://www.palantir.com/docs/foundry/code-workspaces/overview) ·
[Product comparison](https://www.palantir.com/docs/foundry/code-workbook/code-products-comparison) ·
[Dataset Preview](https://www.palantir.com/docs/foundry/dataset-preview/overview) ·
[Datasets](https://www.palantir.com/docs/foundry/data-integration/datasets)
