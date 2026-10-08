# Roadmap phase 3 — fidelity, and the road to production

_Phase 1 built six pillars (`docs/roadmap-phase-1-pillars.md`). Phase 2 reshaped them into Foundry-shaped applications (`ROADMAP.md`) and is essentially complete: sections 0, 3 and 4 are done, 1 and 2 are done but for named remainders._

_This document exists because "done" and "right" turned out to be different things. Phase 2 asked whether each surface **existed**. This one asks whether it is **the thing Foundry users would recognise**, and what else stands between here and a system worth putting in front of a paying customer._

---

## Sources, and how to read the citations

Every claim about Foundry in this document is cited to the Palantir documentation PDFs in `docs/pal/`, by file and page. The citation format is **(`code-repositories` p.13)**, meaning `docs/pal/foundry_code-repositories.pdf`, page 13. Page numbers are those of the PDF, which match the extracted page markers.

This replaces an earlier draft that was written from search-engine summaries because `palantir.com` is blocked by this environment's egress proxy. That draft got the broad shape right and several specifics wrong — the widget configuration tabs, the number of helper panels, and the entire existence of Global Branching. **Where this document contradicts the previous one, this one is correct**, and the differences are called out where they change a recommendation.

One limit remains and it is worth stating plainly: these are the docs, not the product. Claims about what Foundry *has* are now well-sourced. Claims about **how it feels to use** still are not — nobody in this loop has used Foundry, and a feature list is not an experience. Where a judgement rests on feel, this document says so.

---

## What is actually being asked for

Three complaints, and they are all correct:

1. **"Code is a very simple model runner. I want a full integrated VS Code like in Foundry."**
2. **"Canvas should work exactly like Foundry Workshop from a UI perspective."**
3. **"When you are in a project the navigation is fine, but it should simply be the navigation. When going to stuff like edit a canvas or a code repo this should be a new screen."**

The third is the cheapest to fix and the one that makes the other two feel different immediately, so it goes first.

---

## Two findings that reframe the rest

### 1. The good version usually already exists, beside a worse one that people actually hit

Verified in the working tree at `16bed37`:

| The good thing | Where it is | The worse thing beside it |
|---|---|---|
| Monaco, file tree, branches, PRs, checks, preview | `components/applications/repository-app.tsx`, 1173 lines, full-screen at `/r/{id}` | `app/(platform)/[workspace]/[project]/code/page.tsx:332` — `<textarea className="code-editor">`, 463 lines |
| Full-viewport application shell, no platform chrome | `app/(app)/layout.tsx` + `application-shell.tsx`, used by three resource kinds | the Workshop builder renders *inside* `ProjectLayout`'s sidebar |
| Typed variables, events, layouts, 16 content widgets | `components/canvas/` | `models/page.tsx:330` — SQL and Python in `<textarea className="sql-box">` |

`app/(app)/r/[resourceId]/page.tsx:32` excludes `dataset`, `code_repo` and `object_type` from its stub table because those three have real applications; `canvas_app` is still in the stub table at line 40. So complaint 1 is not "the code editor is bad" — **there are two code editors and the pillar page ships the old one**. Complaint 3 is not "canvas needs a new screen" — the screen exists and canvas is not on it.

### 2. Foundry's governance model is cross-application, and we have no equivalent

This is the finding the previous draft missed completely.

**Global Branching** (previously "Foundry Branching") lets a developer "make modifications across multiple applications on a single branch, test those changes end-to-end without disrupting the production environment, and merge those changes with a single click" (`foundry-branching` p.2). The worked example is exactly our architecture: change a pipeline's logic and output schema on a branch, "see these changes in Ontology Manager on that same branch, and modify the object type definition as a result" (`foundry-branching` p.3). Reviewers are added per resource "depending on each resource's approval policy" (`foundry-branching` p.3).

This is not a niche feature. It is the reason Foundry's branch model feels coherent: **a branch is a property of the workspace, not of a repository.** Workshop modules branch and rebase (`workshop` p.193). Object Views branch (`object-views` p.1, §6). Code repositories branch. All of them can participate in one global branch.

We have branches on repositories only. Our ontology has change history (§85) but no branch; our Workshop modules have versions (§88) but no branch. Every piece of that is individually defensible and collectively it means we cannot offer the workflow above.

**Recommendation:** do not build Global Branching. It is enormous. But **stop treating repository branches as the general answer to "how do changes get reviewed"**, because Foundry doesn't, and design the ontology and Workshop review paths to be joinable later rather than accidentally incompatible.

---

## Section A — Navigation: make the project page *only* navigation

**Size: S. Highest leverage in this document.**

### What Foundry does

The sidebar "is your constant companion in the platform and the starting point for navigation", opened and collapsed with `Cmd+O` / `Ctrl+O`, with **five primary sections** (`getting-started` p.27–28):

1. Home, Search (Quicksearch, `Cmd+J`), Notifications, What's New
2. **Recent**, **Files**, **Applications**
3. Applications (favorited)
4. Files (favorited)
5. AIP Assist, Support, Account, Other Workspaces

**Files, powered by Compass**, is "the landing page for the Project folder structure, where you can access top-level Portfolios, Projects, Your files, and Shared with you shortcuts" (`getting-started` p.31–32). A resource "is analogous to a file in a traditional system"; each has "a unique identifier called a resource identifier, or RID, which is standardized across applications", and **"each resource type opens in a different platform application"** (`getting-started` p.37). Projects are permission boundaries with Viewer, Editor, Owner roles (`getting-started` p.38).

That last quote is the whole of complaint 3, in Palantir's own words.

### A.1 Move the Workshop builder to `/r/{id}` — **S**

**Today.** `app/(platform)/[workspace]/[project]/canvas/[appId]/page.tsx` (507 lines) sits in the `(platform)` route group and inherits the project sidebar. Meanwhile `canvas_app` sits in the `APPLICATIONS` stub table at `r/[resourceId]/page.tsx:40`.

**Build.** A `WorkshopApplication` in `components/applications/` wrapping the existing builder — a move, not a rewrite; the Craft.js `<Editor>`, the three panels and the viewer all stay. Register `canvas_app` in the dispatch, delete its stub entry, and make the old URL a permanent redirect (**not** a deletion — links exist in the e2e suite and in `STATUS.md`).

**Watch for.** The builder reads `useParams<{workspace, project, appId}>`. Under `/r/{id}` it has only a resource id; `resolve()` already returns both slugs, so the shell should pass them as props rather than have the builder re-fetch.

### A.2 Delete the second code editor — **S, mostly deletion**

Point the code pillar page at the resource browser filtered to `kind=code_repo`. **Watch for:** that page is where review-required proposals are created today — confirm the proposal flow reaches the same place from the application first, or governance loses its entry point.

### A.3 Pillar pages become filtered views — **S**

Phase 2 §0.2 recommended this and it was half-taken: the browser exists and six pillar pages exist beside it. Two implementations of one list is the condition under which they drift, and they have.

### A.4 Applications portal, Recent, Favorites — **S each**

Foundry's Applications portal shows platform apps plus "trusted custom apps that admins promote", and promotion carries required metadata: name (which "can be different than the resource name"), icon, description, application owner, thumbnail, and **collections and tags** — "collections are required, while tags are optional" (`app-building` p.30–32). Promoted apps get "the purple checkmark for trusted content". The promotion UI appears "both in Applications Portal and in edit mode of Workshop" (`app-building` p.33).

Recent "lists the last 20 resources you have opened or interacted with" (`getting-started` p.31). Favorites are star-marked shortcuts to applications, resources, and **individual object instances** (`getting-started` p.32–34).

We have a published-apps nav page (§25). The gap is promotion-as-a-concept — a curated, owned, described thing distinct from the underlying resource. Cheap, and it is what makes a platform feel like a platform.

---

## Section B — Code Repositories: from a repository surface to an IDE

**Size: L overall, and genuinely incremental.**

### What Foundry does

Code Repositories "provides a web-based integrated development environment (IDE) for writing and collaborating on production-ready code", with all common Git tasks through the web UI, integrated pull-request review, and "IntelliSense, code linting and error checking, and rich help dialogs" (`code-repositories` p.2).

**Five tabs: Code, Branches, Pull requests, Checks, Settings** (`code-repositories` p.10). The Code tab has six labelled regions: In-App Help, Branch Options, Code Editor Options, File Editor, **Helper Panels**, and a **Status bar** (`code-repositories` p.10–11).

**The helper panels are nine, not four** — the previous draft undercounted badly (`code-repositories` p.13–15):

| Panel | What it does |
|---|---|
| Foundry Explorer | file navigation; select a dataset and "Open" to view the full dataset |
| Problems | issues detected in code; click an issue to open the problematic code |
| Debugger | examine transform behaviour while it runs |
| Preview | run code on a limited sample "without committing your changes" |
| Tests | run unit tests and display results |
| File Changes | uncommitted changes to the current file, and comparison with previous versions |
| Build | trigger dataset builds and view progress |
| Docs | language references |
| SQL Scratchpad | test SQL queries, with favourites and history tabs |

The **status bar** reports Code Assist state — "essential for detecting problems in your code and running previews" — plus Problems, Checks status, and file-saving status (`code-repositories` p.15).

Two branch facts we do not implement and should: **"To edit code in your repository, you must work in a sandbox branch — protected branches cannot be directly edited"** (`code-repositories` p.12), and the Branches tab also manages **tags**, "like immutable branches", with optional regex name validation via `repoSettings.json` (`code-repositories` p.17).

The Settings tab is where "code authors can configure their personal editor preferences and repository administrators can control the repository's behavior and policies" (`code-repositories` p.20).

### Where we actually are

| Foundry | Anchor today | |
|---|---|---|
| Code tab, Monaco-class editor | Monaco, self-hosted | have |
| File tree | `FilesTab` | have |
| Branches tab | create, list, delete, fast-forward, merge | have |
| Preview without committing | SQL only | partial |
| Pull requests tab | exists as *proposals*, not as a repository tab | partial |
| Checks tab | checks run and block, no tab | partial |
| Protected branches / sandbox rule | — | none |
| Tags | — | none |
| Settings tab | — | none |
| Problems, Debugger, Tests, File Changes, Build, Docs, SQL Scratchpad, Explorer | — | none |
| Status bar | — | none |
| IntelliSense beyond Monaco built-ins | — | none |
| Multi-file editor tabs | one file at a time | none |
| Code Workspaces | — | none |

### B.1 One editor, one repository model — **M**

The awkward part is `models`. A model today is a SQL or Python string in a textarea; in Foundry the transform is a file in a repository. Until a model *is* a file, there will always be a second editor. Keep the model row as the *declaration* (inputs, output, trigger, schedule) and move the *body* into the repo — §94's publish path already connects a repository file to a model.

**Watch for.** A model mid-edit when the migration runs. Write it as copy-in, read-from-repo, drop-the-column-later, not a single cutover.

### B.2 Multi-file editing with tabs — **M**

One open file at a time is the single biggest thing that makes the editor feel unlike an IDE.

**Watch for.** Uncommitted edits live in `useState` keyed by path (`repository-app.tsx:206`) with no persistence. That survives switching files but not a reload — so a five-tab editor is five ways to lose work at once. Persist to `localStorage` keyed by repository and branch **before** adding tabs; tabs are what make the loss expensive.

### B.3 The five tabs, and the sandbox rule — **M**

Re-home proposals into a Pull requests tab and check runs into a Checks tab, and add Settings. Ours are Files, History, Branches, Publish; History belongs in a panel and Publish belongs on the branch.

Add the **protected-branch rule** here rather than later: editing `main` directly is currently possible, and Foundry's model — protected branches are not editable, work happens on a sandbox branch — is both safer and the thing that makes the Pull requests tab load-bearing rather than optional.

### B.4 Helper panels — **M each, independently useful**

Take them in this order, which is roughly value per unit of work:

1. **Problems** — `ruff` for Python in the transform runner; DuckDB's parser for SQL, which preview already runs.
2. **File Changes** — diff the working draft against the committed version. The diff machinery exists for commits (§60); point it at uncommitted state.
3. **Tests** — the runner already executes customer Python in an isolated container with an empty task role (`docs/decisions/0004-running-customer-code.md`). A test job is the same mechanism with a different entrypoint.
4. **Foundry Explorer equivalent** — browse datasets and object types from inside the editor and insert a reference. Small, and disproportionately makes the editor feel connected to the platform.
5. **SQL Scratchpad** — we have most of this in preview already; what is missing is the persistent history and favourites.

Defer Debugger and Build; Build in particular assumes Foundry's build orchestration, which is a different thing from our worker.

### B.5 Language intelligence — **L**

Monaco gives basic completion free. Real IntelliSense over *your* datasets needs a language server with platform context. Defer until B.1–B.4 are in use, then decide with evidence about what people reach for.

### B.6 Code Workspaces — **XL, and a separate product decision**

Code Workspaces brings "JupyterLab®, RStudio® Workbench, and VS Code third-party IDEs" as managed containers, and critically: **"Code Workspaces are backed by the Code Repositories infrastructure, which provides industry-standard version control features like branching, merging, and commit history"** (`code-workspaces` p.2–3).

That sentence is the argument against starting here. The container IDE is layered *on* the browser IDE, not instead of it. Its own docs also say that for large-scale pipelines and data connections, "other Foundry tools have more functionality than Code Workspaces" (`code-workspaces` p.3).

**Recommendation: do not start here.** B.1–B.4 close most of the felt gap at a fraction of the cost and are prerequisites either way.

And the "extensions and a terminal" caveat turns out to be the whole of it. Foundry's feature comparison across its three code surfaces (`vs-code` p.7–8) shows Code Repositories answering **No** to exactly three things — shell terminal, keybinding customization, public extensions — while answering **Yes** to Python preview, debugger, and unit tests, and being the *only* one of the three that can do Java transforms, SQL integration and TypeScript function preview. The docs then state the division of labour outright: Code Repositories "is the intended platform tool for pull request reviews and repository management" (`vs-code` p.14).

So VS Code does not replace the browser IDE in Foundry; it sits beside it and hands users back for review. That is a much stronger argument for finishing the browser IDE first than this section originally made, and it is written up as a scope boundary in [`parity/code-repositories.md` §11](parity/code-repositories.md).

---

## Section C — Workshop: UI fidelity

**Size: L, almost entirely additive — the model underneath is sound.**

Phase 2 built the hard part. Variables are typed with derivations, cycle refusal and usage-aware deletion; events are trigger → ordered effects with Foundry's sequential copy-immediately semantics, which the docs confirm precisely: "the source variable value is copied to the target variable value immediately… downstream variables that depend on the target variable will not be up-to-date before the next configured event executes" (`workshop` p.80). Layouts have pages, sections, overlays, tabs and a header.

### C.1 The widget configuration panel — **M**

**The previous draft got this wrong.** It claimed the tabs were Widget setup / Display / Actions. They are **Widget setup, Metadata, Display** (`workshop` p.65–68):

- **Widget setup** — "where a module builder will configure the input and output variables of a widget… as well as any additional configuration and display options" (p.65)
- **Metadata** — rename the widget, and view or edit **the widget's raw JSON configuration** (p.67–68)
- **Display** — sizing only: **Auto (max)**, **Absolute**, **Flex** (p.68)

Events are configured *on the widget's own controls* — for a Button Group, "at the bottom of a button's configuration pane… choosing the Event option from the On click dropdown menu" (`workshop` p.83) — not in a separate Actions tab.

Our `SettingsPanel.tsx` shows a flat prop list, so variable wiring reads as one field among many rather than as the primary thing a widget is. Restructure into those three tabs. The Metadata tab's raw-JSON editor is worth copying exactly: we store `format: 2` documents already, and exposing them is a few hours' work that makes every unsupported configuration survivable.

### C.2 The vertical header — **S**

Foundry's header can be horizontal or vertical, and the vertical one has real depth: configurable width, **collapsibility with a collapsed-by-default option**, a custom image for the collapsed state, and defined collapse behaviour — "the Button Group and Tabs widgets will also have collapsed states that will only show the icons… All other widgets will be hidden when a module header is collapsed" (`workshop` p.47–49).

We have horizontal only (§80). Small, visible, characteristic.

### C.3 Section layouts — **S–M, and we are missing four of six**

Foundry's section layouts are **Columns, Rows, Tabs, Flow, Toolbar, Loop** (`workshop` p.54). We have columns, rows and tabs. Missing:

- **Flow** — "turns the current section into a vertically scrolling container… widgets that stretch beyond the displayed interface"
- **Toolbar** — "optimized for smaller widgets like Button Groups or Metric Cards"
- **Loop** — "loop over an object set or array, displaying an embedded module for each object in the set"

Flow and Toolbar are small and remove a class of "I can't lay this out" complaints. Loop depends on C.4.

Also worth noting: sections support **conditional visibility** with layout-panel icons indicating which sections are conditionally hidden (`workshop` p.55), and **drop zones** for cross-application drag payloads (p.55).

### C.4 The module interface — **M, and it is the same feature as three others**

This is the most useful thing the doc review turned up.

"The module interface is the set of variables that are able to be mapped to variables from a parent module when embedded, **and initialized from the URL**. You can think of the module interface as the API for a Workshop module." The mechanism: "navigate to the Settings panel for a variable, add an **external ID**, and make sure the toggle for module interface is enabled" (`workshop` p.163).

State saving uses the same key: "select a variable and then navigate to the settings tab and add an external ID" — and "variable values are stored within a saved state via their external ID", so changing an external ID breaks previously saved states (`workshop` p.202–203).

So in Foundry, **one concept — an external ID on a variable — powers embedding, URL deep-links, and state saving.** We built deep links separately (§99) and deferred embed mapping (§114). Those are not two features; they are one feature we implemented half of, twice.

**Build.** External IDs on variables, with the interface toggle. Embed mapping and state saving then both fall out. Save-time refusals: mapping a variable not in the interface, a type mismatch between host and interface variable, a required interface variable left unmapped, and — from the docs' own warning — a rename of an external ID that has saved states pointing at it.

**Watch for.** "When an interface variable is mapped between a parent and an embedded child module, Workshop uses the **parent module's** variable definition and ignores the embedded module's own" (`workshop` p.164). That precedence rule is not obvious and getting it backwards would be subtly wrong rather than visibly broken.

### C.5 The versions dialog and the changelog panel — **S + M**

The Versions dialog lists saved versions with "a timestamp, editor, and description if available", each offering **Publish this version**, **View this version** (with "a warning banner… when viewing a non-published version"), and **Revert to this version** (`workshop` p.191–192). Two settings live there: **Automatically publish when saving**, and **Always prompt to add a version description when saving**.

Our semantics are already right — §88 pinned publishing to a version so saving no longer moves viewers. What is missing is the dialog. **S.**

Separately, the **Changelog panel** visualises differences between versions, by range or against the previous version, highlighting "additions, deletions, changes, moves, and newly unused elements", with inspectable JSON diffs and a visual hierarchy (`workshop` p.193). That is **M**, and it is also the UI Foundry reuses for module rebasing and conflict resolution — so it is the cheapest step toward module branching if that is ever wanted.

A routing detail worth stealing: changing `/latest/` to `/dev/` in a module URL "will redirect to the last saved version… instead of the last published version" (`workshop` p.166). One route, and the save-versus-publish distinction becomes testable by a human in a browser.

### C.6 The widget library

Now that the inventory is authoritative, here is the real gap. Ours: 16 content widgets plus 5 layout primitives (`components/canvas/widgets.tsx`).

**Filtering** (`workshop` p.444) — Foundry has 13: Filter List, Object Dropdown, Object Selector, String Selector, Checkbox, Date and Time Picker, Date Input, Text Input, Numeric Input, Exploration Filter Pills, Exploration Search Bar, Prominent Terms, User Select.
We have Filter List and a generic `CanvasParameterControl`. **Text Input, Date Input, Numeric Input and String Selector** are the four that make a filter bar feel complete, and all four are small.

**Core display** (`workshop` p.220) — Object Table ✅, Object List ✅ (our Card list), Object View ❌, Property List ❌, Links ❌, Object Set Title ❌, Header text ❌.
**Object View as a widget** is the interesting one — it "renders Object Explorer's object view for a single object", which ties directly to Section D.

**Visualization** (`workshop` p.276) — 20 widgets. We have Chart XY, Map, Metric Card, Pivot Table, Time Series (≈ Time Series Analysis). Missing: Pie, Vega, Free-form Analysis, Gantt, Image Annotation, Linked Compass Resources, Markdown, Media Preview, PDF Viewer, Resource List, Status Tracker, Stepper, Timeline, Waterfall, Action Log Timeline.

**Event-trigger & navigational** (`workshop` p.480) — Button Group ✅, Tabs ✅, Inline Action ❌, Comments ❌, Media Uploader ❌.

**Priority if pursued:** Text/Date/Numeric Input and String Selector → Markdown (trivially cheap, disproportionately useful) → Inline Action → Object View widget → Property List → Timeline → the rest on demand.

### C.7 Edit and view are already separate

Recorded so it is not re-litigated: Preview exists in the builder, the viewer route exists, and §114 keeps the embedded editor disabled in both. Nothing to do.

---

## Section D — What is missing entirely

| Foundry | What the docs say | Recommendation |
|---|---|---|
| **Object Views** | Two kinds: **standard**, which Foundry "automatically creates" from the object type's configuration, spotlighting prominent properties with type-aware rendering — media viewers, time-series charts, geospatial on a Map — plus a Linked objects component for traversal (`object-views` p.9–11); and **configured**, which are "fully customizable representations **built using Workshop**" and become the default view once created (`object-views` p.2). Two form factors, full and panel. | **The best value in this table, and cheaper than the previous draft claimed.** Configured views are Workshop modules bound to one object — we have that engine. Standard views are generated from the object type, which we already model. **M**, not M–L, and it makes the ontology navigable rather than tabular. |
| **Pipeline Builder** | "Foundry's primary application for data integration"; graph and form interfaces with "join keys and column casting suggestions"; strongly typed functions that "flag errors immediately instead of at build time"; strict output checks that prevent builds; automatic pruning of transform paths not connected to outputs. Outputs are "an object type, link type, or dataset" (`pipeline-builder` p.2–4). | **The largest genuine product gap.** Ours is a read-only DAG *view*. Note the output list: theirs writes the ontology directly. **XL**; spike before committing. |
| **Functions** | Server-side logic "executed in an isolated environment", with "first-class support for authoring logic based on the Ontology" — reading properties, traversing links, making edits. Used for Workshop object sets and variables, function-backed table columns, chart aggregations, and function-backed actions (`functions` p.2). | **L.** Our actions are declarative only. This is the prerequisite for actions getting materially richer, and it shares infrastructure with the transform runner. |
| **Global Branching** | Cross-application branches with per-resource reviewers and single-click merge (`foundry-branching` p.2–3). | **Do not build.** But see finding 2 — design the ontology and Workshop review paths so they could join later. |
| **Carbon workspaces** | Curated multi-application workspaces (`getting-started` p.36). | Skip. |

---

## Section E — Production readiness, which is not the same as fidelity

**None of the above makes this production-ready.** Unchanged from the previous draft, because none of it depends on Foundry's documentation.

**E.1 — CI. ~~Never executed.~~ Done, and it found a real bug.** This item said the workflow had never run, which was true when written. It first ran on PR #50 and was **red for nineteen consecutive runs**, on one cause: `0006_rls.sql` creates `platform_app` with a placeholder password, `migrate.py` reconciles it from `PLATFORM_APP_PASSWORD`, and only `scripts/setup.sh` — which CI has no reason to run — was setting that variable. So the role kept `change_me_in_secrets_manager` while everything connected as it with `devpass`. Migrations applied, the Migrate step went green, and then every Postgres-touching job was refused.

The tell was visible in the job list the whole time: `types and unit tests` is the only job that never touches Postgres, and it was the only one passing. Fixed in PR #52; all three jobs green.

Two things worth keeping from this. **The docstring on `sync_app_password` was the bug** — it said local dev and CI don't set the variable, "so this is a no-op there", which reads as fine on paper and is wrong in exactly the way only a run exposes. And nineteen red runs sat there while the same suites passed on every developer machine, which is the entire argument for stage 0 going first.

**E.2 — Decision 0006 is unproven against a real cluster. M.** *Found in §805: deployed stacks set `OPENSEARCH_ENDPOINT` but never `OPENSEARCH_SECRET_ARN`, and the API needs both, so every deployment reads its objects from Postgres today. Turning OpenSearch on needed more than the secret: the worker's scheduled sync wrote only Postgres, so tables past the 20,000-row interactive limit would never have reached the index. Since §811 it writes the index when one is configured, by the API's document ids and mapping; §810 made the fixture take arrays and 404 a sweep of a missing index, which found the API's sync failing on an empty first sync. §813 gave `backfill()` a command that pages, and §814 an opt-in, `-c objectStore=opensearch`, that hands both services the domain's secret. What is left is one deployment taken through `docs/deploying.md`'s cutover.* Typed instance properties are tested against a fixture that now enforces mappings and has 17 tests of its own fidelity (§112). As that work said: this narrows the unproven claim from "does any of this work" to "does OpenSearch behave like the mapping it was given". One deployment closes it.

**E.3 — Observability: ~~there is none~~. Done in both halves (§802, §815), M.** ~~No error tracking, no structured logging worth querying, no metrics, no alerting. The first incident will be diagnosed by SSH and guesswork.~~ The API now gives every response an `X-Request-ID`, writes one JSON line per request (by route template, so nothing an id or a token lives in), records an unhandled error's traceback under the id its 500 quotes, and serves Prometheus metrics at `/api/metrics` (`apps/api/src/lib/observability.py`; `docs/deploying.md` has the variables). ~~**Still open, and the deployment's rather than the process's:** shipping those lines to a store, scraping the metrics, and alerting on them.~~ The lines already went to CloudWatch Logs, and §815 counts them there with metric filters instead of scraping. Eight alarms report to an SNS topic: 5xx rate, unhandled errors, p95 latency, no running API or worker task, unhealthy targets, and database storage and CPU (`infra/cdk/src/constructs/monitoring.ts`). `-c alarmEmail=` subscribes an address. The filters name the formatter's fields, and `test_observability.py` runs each one against lines the API really wrote, so a renamed field fails a test instead of silencing an alarm. **Not verified:** that a real CloudWatch evaluates the patterns as the test's reader does. The reader implements only the syntax the patterns use, and refuses anything else.

**E.4 — Scale ~~is entirely unmeasured~~. Measured at a million rows (§804, §805), M.** ~~Every test runs against tens of rows. Not "it will be slow" — **unknown**, which is worse, because it cannot be planned around.~~ `apps/api/bench/scale.py` drives the real routes in-process against Postgres and local storage: upload a million-row file, preview, profile and query it, sync it into objects, then list, count and sum them. On a 4-CPU machine, after the fixes below:

| At 1,000,000 rows | p50 | p95 |
|---|---|---|
| **Dataset preview** (the number this item asked for) | **23 ms** | **26 ms** |
| Dataset profile, cached (first: 0.18 s) | 11 ms | 15 ms |
| Grouped query over the dataset | 98 ms | 109 ms |
| Objects: first page with its total | 301 ms | 336 ms |
| Objects: count | 292 ms | 332 ms |
| Objects: sum a property | 864 ms | 970 ms |
| Objects: sync (the worker's scheduled sync) | 42 s, once | |

**§899: a regression in the sync, found by re-measuring.** At a hundred thousand rows the worker's sync took 39 s, ten times the per-row cost measured above. 0158's trigger (§817), which stamps each object with its type's workspace, read the type under `object_types`' row policies, evaluated afresh for every row: 371 ms of a 427 ms statement of a thousand objects. Migration 0167 makes it `SECURITY DEFINER`. That is a key lookup, 8 ms for the same thousand, and the policy still refuses every object it refused. The sync of a hundred thousand rows is 5.05 s again.

**What measuring found, and fixed.** At 10,000 objects a first page took 0.9 s and a count 0.5 s. Freshly synced rows made the planner check row-level security row by row, calling the SECURITY DEFINER `rls_workspace_ids()` twice per row; migration 0155 makes all 25 policies that call it compute it once per statement. At a million, the first page took 2.9 s at p95 because one sync gives every object the same `updated_at`, and the `primary_key` tie-break sorted every row; migration 0156 puts the key in the index (0.09 ms to read the page). Migration 0157 asks "is this a kiosk?" once per statement in the six policies that ask it per row. The API's interactive sync wrote one statement per object (16 s for 10,000); it now writes a thousand per statement (0.55 s). The worker's sync, the only one for a table past 20,000 rows, did the same per-row writes and also **overwrote edit-only property values on every run** (§805): it merges and batches now.

~~**What is still slow, and why.** A count or a sum reads every row. The count pays about 0.3 µs a row for the policy checks (39 ms without RLS), and the sum also parses each row's `jsonb`. That is the Postgres store's floor without a structural change, such as putting `workspace_id` on `object_instances` so the policy needs no join; OpenSearch would aggregate natively.~~ **§817 made that structural change, and its first measurement showed the change alone did nothing.** The count's cost was reading every row from the table, not the join. Even the owner role with no policies took 269 ms on a cold cache. The change only paid with an index holding `(object_type_id, workspace_id)`: both policies then read only indexed columns, so a count is answered from the index alone. It also needed `ANALYZE` after a large sync. With a second index on the type, the stale statistics a sync leaves behind sent the first page to a full sort, 507 ms, until autovacuum caught up. Migration 0158, at a million objects (p50):

| | Before | After, right after the sync | After, once autovacuum has run |
|---|---|---|---|
| First page with its total | 263 ms (228 ms once autovacuum has run) | 197 ms | **60 ms** |
| Count | 243 ms (217 ms) | 173 ms | **56 ms** |
| Sum a property | 822 ms (866 ms) | 707 ms | 781 ms |
| Sync, by the worker | 33.8 s | 39.6 s | |

The sync pays for it: the trigger, one more index and the `ANALYZE` add about 17%. A sum still reads and parses every row's `jsonb`, so its time barely moved. That is the remaining floor for the Postgres store, and OpenSearch would aggregate natively. `bench/scale.py` now reports reads both ways, because the two differ by up to 4×. **§824 found the rest of the policy cost on the development database's own shape.** That is 9,974 projects and 21,372 usage rows in one workspace, measured through the API on a copy of it. Thirteen policies written after 0058 still called `rls_can_access_workspace(...)` per row. Migration 0159 rewrote them to the once-per-statement set. The ontology cleanup page went from 5.0 s to 0.16 s, and the published apps list from 1.3 s to 0.5 s; small reads were unchanged. The same rewrite for `rls_can_access_project`, the step 0060 tried and 0061 reverted, was measured again with 0155's hoisting and still lost. It did not speed up any slow endpoint, and small reads slowed from 8 to 60 ms, because an org owner's project set is every project in the organisation, built once per statement. It is recorded in 0159's docstring so it is not tried a third time blind. **§825 took the projects list and the cleanup page the rest of the way.** Migration 0160 gives the `projects` policy a shortcut ahead of the per-row check: an inherited-mode project in one of the caller's workspaces is visible, which the per-row check would grant anyway. The project grid now reads `projects` directly and resolves each returned row's role once, where `v_user_projects` resolved it twice for every project. A page of the grid went from 0.7–1.6 s to under 20 ms. The cleanup page's 0.16 s did not hold. On a later copy, the planner estimated one object type and ran the usage sum and four source probes once per type, which took 4.8 s for 814 types. Each is now aggregated once for the workspace's types: 0.14 s. `tests/test_rls_project_ids.py` checks that the policy admits exactly the users who have a role, for each access route. **§826 found the same shape one table over.** `canvas_apps` had no workspace of its own, so the published-apps gallery filtered with `rls_project_workspace_id(project_id) = :wid`. That function is not leakproof, so the row policy ran first, on all 12,473 apps of every tenant, to return 11. Migration 0161 adds the column as 0158 did for objects: a trigger sets it from the project, a project may no longer change workspace, and the column is indexed. The gallery went from 0.5 s to 0.03 s; an action type's usages, an object type's related artifacts and an object view's module lookup read the column too. The trigger is named to fire before `register_resource`, which reads the same column for the resources registry. **§827 indexed the other end of every reference.** Postgres indexes the referenced side of a foreign key, never the referencing one. Forty-seven references to resources had no usable index, so deleting a dataset read `models`, `action_runs`, `link_types` and the rest in full, and so did every lineage read that follows a reference backwards. Migration 0162 indexes them all. The pipeline graph's runs statement went from 665 ms to 2 ms and its datasets statement from 93 ms to 12 ms. Deleting a dataset went from 43 ms to 9 ms. References to users and workspaces are exempt, and `tests/test_foreign_key_indexes.py` fails on any new reference without an index. **§829 hoisted the last per-row lookup a crawl of every page found.** `users_same_org` and `groups_same_org` called `rls_user_org_id()`, which is SECURITY DEFINER and cannot be inlined, once per row. On a database holding 68,974 users of many tenants, the pipeline's *View as* picker took 180 ms to list four people, and notification recipients took as long. Migration 0163 makes the call an InitPlan. The listings also name the caller's organisation, which the policy already restricts them to, so an index finds those people first. Both responses are now under 10 ms. A crawl of every GET route on the copy now finds three over 100 ms: the unpaged project list and the ontology export, which return megabytes, and the workspace-wide object list at 134 ms. **§830 turned to writes.** Creating, renaming and deleting projects, apps and object types all take 11–50 ms on the copy. Saving a module took 118 ms even when it was empty. To validate it, the save loaded every action type in the workspace (362, with their parameters, rules and criteria) and the properties of all 815 object types. Validation only ever looks these up by an id the document itself contains, so the save now loads just the ids it mentions: 18 ms. The action-type save has the same shape, but its validator also follows links and the action's own type to ids its body does not name. At 19 ms it was left alone, because narrowing it could not be shown exact. **§831: evaluate, which a viewer's filter calls on every keystroke, spent half its 105 ms building every property's full description to keep two columns.** It now reads the name and declared type, resolved through shared properties as before, and takes about 33 ms. It is not narrowed to the document's ids as the save was. Evaluation also meets types through request values and objects read back from the store. **Not measured:** OpenSearch at this size (E.2), and anything past one machine.

**E.5 — Dependency advisories. ~~S~~ Done (§806, §807): `npm audit --omit=dev` finds 0 vulnerabilities.** ~~Two in the Next 14.2.5 tree. Pre-existing and known; still an answer somebody will want.~~ 14.2.5 had a critical `next` and a high `postcss`. §806 took the 14.x patch line to its end (14.2.35) and switched the image optimizer off (`images.unoptimized`; nothing uses `next/image`, and its endpoint was where the unpatched remote-code-execution advisory lived). That still left 23 advisories fixed only in Next 15.5. **§807 moves to Next 15.5.27 with React 19.3.0.** That needed React Query 5.104 (5.51 declared React 18 only), a single deduplicated React (the first install left React 18 hoisted for the libraries), `outputFileTracingRoot` moved out of `experimental`, and an npm `overrides` entry, because Next pins its own `postcss` at 8.4.31 and 8.5.28 carries the fixes. No page needed changing for asynchronous `params`: every route reads them through `useParams()` in a client component, and only the root page and layout are server components. Keeping it at zero means running the audit now and then. It is deliberately not a CI gate: an advisory published overnight would turn unrelated PRs red. **§837: the Python half had never been audited.** `pip-audit` found 48 advisories in the API's runtime pins, 3 in the worker's and 25 in the control plane's. The serious ones were the JWT library that verifies every sign-in (PyJWT 2.9.0), Starlette under FastAPI 0.111, the multipart parser, and the control plane's `cryptography` 43. The pins moved: FastAPI 0.142.2 with Starlette 1.7.0 pinned beside it, pydantic 2.13, PyJWT 2.15.1, python-multipart 0.0.32, dagster 1.13.25, cryptography 50.0.1, and pytest 9.1 (which the worker runs at runtime for code tests). Every requirements file in the repo now audits clean. Two things moved underneath. FastAPI now includes routers lazily, so a matched route no longer carries the include's `/api` prefix, and the access log and metrics restore it (`observability.route_template`). The control plane had used `EmailStr` without declaring `email-validator`, which old FastAPI had installed for it. Run `pip-audit -r` on each file, as with `npm audit`, now and then. **§838: the infrastructure's packages had never been audited either.** `infra/cdk` has its own lockfile, outside the workspace `npm audit` ran in. aws-cdk-lib 2.150.0 carried six high advisories in its own constructs and more in what it bundles. It moves to 2.272.0, with constructs 10.8.1 and the CDK command line 2.1144.0. Two deprecated calls went to their replacements (`containerInsightsV2`, which synthesizes the same cluster setting, and `addResourceDependency`), and the three construct checks pass. One advisory remains: a `brace-expansion` bundled inside aws-cdk-lib itself, which no override reaches. It runs only when a stack is synthesized, on the operator's machine. **§905: an advisory published after §807 (`source-map-js` 1.2.1, an event-loop denial of service, under postcss) moved the override to postcss 8.5.29, which requires the fixed 1.2.2.** `apps/web/package-lock.json` went with it: npm reads a workspace member's lockfile nowhere, the image builds from the root's, and the stale copy, last touched in §424, was what a scanner would have read.

**E.6 — The `export` effect. ~~S~~ Done (§459, §787).** ~~Refused with its reason (§76) because it needs a download surface the viewer route lacks. Foundry's Button Group treats export as a first-class `On click` target alongside actions, events and URLs (`workshop` p.482) — so this is not an exotic ask.~~ The file is built in the browser, which removed §76's reason: `docs/parity/workshop.md`'s Export row is ✅, with p.489's Excel workbook (`apps/web/src/lib/xlsx.ts`), the clipboard, a file name and a choice of properties, and §775's function-backed export.

**E.7 — Backup and restore ~~has never been rehearsed~~. Rehearsed locally (§803), M.** ~~An untested backup is a hope.~~ `scripts/rehearse-restore.sh` dumps the database, restores it beside itself and runs `python -m src.services.restore_check`, which says what the restored database disagrees with: files storage no longer holds, and object types whose index does not match their datasets, with the sources to re-sync. `docs/deploying.md` ("Backup and restore") has the RDS point-in-time steps and the numbers from the rehearsal. Building it found that **every OpenSearch total stopped counting at 10,000** - the object counts, a set's total, and the auto-refresh watcher's count, which would have missed a delete in any type past that size. They are exact now. **Still open:** rehearsing it against a deployed stack's RDS and bucket, which needs one.

**E.8 — Request bodies were unbounded. Done (§832), S.** Not one of the original seven: an audit found it. Nothing capped a request body: not the load balancer, not the API. A JSON body is read whole into memory before a route sees it, and a file upload was spooled whole before any route could check its size. The attachment route then read the entire file again and refused it past 25 MB only afterwards. So any signed-in client could make an API task hold as much as it liked. `apps/api/src/lib/body_limit.py` now bounds every body before anything reads it. A file upload may be up to 51 MB, the dataset cap plus room for the form; any other body up to 16 MB, four times the largest the API takes (a test run's working set). A declared length over the limit is refused unread. A chunked body is counted as it arrives and refused once it passes the limit. Both get a 413 that has a request id and an access line, like any other response.

**E.9 — A query could outlive its request. Done (§833), S.** Also found by audit. The API set no `statement_timeout`. CloudFront stops waiting for an origin after 30 seconds, but a slow query kept running after the client had gone and held one of the task's thirty pooled connections. A handful of those at once would stall every request on the task. Every pooled connection now starts with `statement_timeout` set (`STATEMENT_TIMEOUT_MS`, default 30 s, set as a connection option so it costs no round trip). A cancelled statement is answered with a 503 saying so, not a 500, and the connection goes back to the pool usable. The cutover and restore-check commands share the engine but read a whole deployment, so each runs without the limit unless told otherwise. There is deliberately no idle-in-transaction timeout: some requests hold a transaction open while waiting on a webhook or a function, and a limit there would cut them off.

**E.10 — One task was the whole API. Done (§841), S.** Also found by audit. Every service ran exactly one Fargate task with no scaling. A crash, an out-of-memory kill or a lost host was an outage until ECS started a replacement, and a busy hour had nowhere to go. The API now runs two to six tasks and the web server two to four, scaling on CPU at 60%. Two keep serving while one is replaced. The API's ceiling is set by the database: six tasks at 30 connections each is 180, under half of what a t4g.medium allows. The worker stays at exactly one, because it runs the Dagster daemon and a second would fire every schedule twice. Before scaling out, the API was checked for anything a second process would disagree about. It runs no background jobs, the OIDC signing key comes from configuration, and the only in-process cache is a 30-second identity cache. `infra/cdk/src/checks/scaling-check.ts` holds all of this, including the connection budget, which it re-derives if the database class changes.

**E.11 — The hop from CloudFront to the services is plain HTTP, and the load balancer is open to the internet. Open; proposed in decision 0025 (§842), M.** Viewers reach CloudFront over HTTPS, but CloudFront reaches the load balancer over HTTP, and that listener admits anyone on port 80. So the session cookie and bearer tokens cross the origin hop unencrypted, and anyone with the load balancer's DNS name can skip CloudFront entirely. The construct comments say the control plane adds a certificate and an HTTPS listener after issuing a customer subdomain, but nothing in this repository does. Decision 0025 recommends an internal load balancer behind a CloudFront VPC origin. It is not built here because it replaces a deployed load balancer, and only a deployed stack can show that the replacement keeps serving. §850 found that it also decides whether a listener's ingress allowlist can work. Through CloudFront, the address the allowlist can trust is CloudFront's, so a deployed stack's allowlists refuse every sender. The fix is two proxy hops, which is safe only once the load balancer is internal. The decision says so, and a check holds the two together. **§909: option B is built, behind `-c originAccess=vpc`.** The load balancer is internal and admits only the VPC, the distribution reaches it through a CloudFront VPC origin, and a listener trusts two hops. Without the flag the template is byte-for-byte what it was. What is left is one stack deployed with it, by `docs/deploying.md`'s procedure, before it becomes the default.

**E.12 — The deployed worker stored its data on its own disk. Done (§844), S.** Found by comparing every environment variable the apps read against what the stack sets. The worker chose S3 when `DATA_BUCKET` was set, but the stack sets `S3_DATA_BUCKET`, the name the API reads. So every deployed worker fell back to local storage inside its own container. Its scheduled syncs, model outputs, listener archives and exports went where the API, reading S3, could never find them, and were lost with the task. The worker now reads `S3_DATA_BUCKET`. A test reads the name out of the construct's `commonEnv`, so the two cannot drift apart again. Both apps now refuse to start on ECS without the bucket rather than falling back to development storage: the worker's local disk, and the API's in-memory connection secrets, which a second API task (§841) would not share. `deploying.md` lists the bucket and the two optional settings the stack does not set (`PLATFORM_PUBLIC_URL`, and the OIDC issuer and key). The reverse comparison found the stack paying for an ElastiCache node that nothing reads. §845 removed it (decision 0026). Reading the task roles against the code found worse: the roles allowed secrets under `platform/connections/*`, but every connection's secret is created as `anchor/connections/<id>`. So a deployed stack refused every connection's credentials, on save in the API and on read in the worker. §846 points the roles at the prefix the code writes, scoped to the stack's own region and account, holds the two together in a test, and drops an Athena grant on a workgroup that never existed.

---

**E.13 — The web ACL refused the platform's own requests. Done (§847), S.** Found by reading the stack's WAF against what the API accepts. AWS's Common Rule Set blocks every request body over 8 KB (`SizeRestrictions_BODY`). So a deployed stack answered every upload, attachment, listener push and large save with the WAF's 403, long before §832's limits applied. Five more of its rules refuse what this platform's requests legitimately carry. Query strings over 2 KB are a picker reading back about fifty chosen types. URLs with IP addresses, `../` paths and markup in a body are a connection to an internal host, a code file, a Markdown widget. A request without a `User-Agent` is a system pushing to a listener. Those six rules now count instead of blocking (`infra/cdk/src/constructs/waf.ts` says why each), so matches still show in the WAF's metrics and nothing is refused for them. Every other rule in both managed sets still blocks, including the metadata-address SSRF rule. `src/checks/waf-check.ts` holds the six to names the set has, the rest to blocking, and the API to bounding bodies itself. **Not verified:** a request through a deployed WAF.

**E.14 — A fresh stack could not migrate its database. Done (§848), S.** Found by reading what the migration Lambda's package holds against what the migrations import. Every deploy runs the migrations from a Lambda whose package is built from `packages/db` alone. Migration 0034 imports the Workshop converter from `apps/api`; its comment says the two share a container, which stopped being true when the Lambda replaced the manual step. So a new customer stack's migration stopped at 0034 with `No module named 'src'`, and the stack rolled back. Nothing had run the migrations from the package: local runs, CI and every fresh-database test run `migrate.py` from the checkout, where the import finds the API by walking up the tree. Migrations are immutable, so 0034 stays as written. `packages/db/bundle.sh` now builds the package, with a copy of the converter under `lambda_vendor/`, and both the bundling container and `test_migration_bundle.py` run it. The test migrates an empty database from the package with nothing else on the path, and holds the copy byte-identical to the API's. **Not verified:** a deploy, since bundling needs Docker.

**E.15 — A deployed stack sent sign-in back to an address that did not serve it. Done (§849), S.** Found by following the platform's address from the control plane to the browser. The web app asks the hosted UI to send a viewer back to its own origin, the distribution's `https://<id>.cloudfront.net`. The app client allowed only the `platformUrl` context. A control-plane deploy filled that with a placeholder, `https://<slug>.platform.example.com`, and later deploys with the stored bare domain, no scheme. So the hosted UI could not complete a sign-in on any deployed stack, which may be ROADMAP's unexplained first-login blocker. The stack now allows the distribution's own address, with `platformUrl` an optional further one. It also hands that address to the API as `PLATFORM_PUBLIC_URL` and reports it as the `PlatformUrl` output, which the control plane stores. The API had built a listener's endpoint from the request. Behind the load balancer that is plain HTTP, so the endpoint it handed out sent its token in clear, to an address CloudFront answers with a redirect. Outbound applications, refused on every stack for want of `PLATFORM_PUBLIC_URL`, now have it. `src/checks/stack-check.ts` synthesizes the whole customer stack, with bundling skipped, and checks the four places the address goes. **Not verified:** a sign-in on a deployed stack.

**E.16 — A deployed sign-in page had no hosted UI to send anyone to. Done (§851), S.** The web app read the hosted UI's address and the app client from `NEXT_PUBLIC_COGNITO_*`, which Next writes into the bundle at build time. One web image serves every customer's stack, each with its own pool, and the documented builds pass neither. So a deployed page said sign-in was not configured, unless someone rebuilt the image for that one stack after deploying it (STATUS.md §20 did). The stack now gives the API `COGNITO_DOMAIN`, and the API answers `GET /api/auth/config` with the domain and client to anyone, since neither is a secret. The page asks it first and keeps the build's values for development. `stack-check.ts` holds the API's variables to this stack's pool, and `e2e/test_sign_in_config.py` follows the page from the API's answer to the hosted UI's authorize request. **Not verified:** a sign-in on a deployed stack.

**E.17 — Nothing deleted from the data bucket was ever gone. Done (§852), S.** The data bucket is versioned (§10) and had no lifecycle rule. So every previous version of every file was kept for the life of the stack: a deleted dataset, every replaced file, and every upload abandoned part-way. All of it was billed, and "delete" never removed customer data. A previous version now lasts 30 days and an abandoned upload a week. Thirty is the database's 14 days of backups plus two weeks, because the restore runbook repairs a file deleted since the restore point from its previous version. `stack-check.ts` holds the bucket's window past the backups', and refuses any rule that expires current files.

**E.18 — Overlapping worker passes did the same work twice. Done (§853, §854), S.** The worker's schedules fire every minute or five, and Dagster launches each tick as its own run. A pass still working when the next tick comes overlaps it, and during a deploy the old and new worker both pass. Each step read its row, decided, and wrote later with nothing held between. So a model run that outlasted a minute could be executed again by the next pass, writing a second output version, and a due cron model could be enqueued twice. A model run, a due cron model and an upstream model are each now claimed under a row lock: `FOR UPDATE SKIP LOCKED`, re-checking the condition that made them due. The pass holding the lock acts; the others skip the row, and find it handled once that pass commits. `test_model_run_claims.py` runs a second pass inside the first one's claim, and runs passes against rows another pass holds. **§854 did the same for the five-minute schedules.** A connection's sync, an object source's sync and a scheduled export each moved their next run on only when the work ended. So a sync that outlasted five minutes was due again for the next tick, which synced the same source alongside it, and an export wrote a second copy. Each now claims its row first (`jobs/claims.py`): under a brief lock, it re-checks that the row is still due and moves the next run on. The lock is not held for the work, so an edit from the platform never waits on a sync. With every scheduled step claimed this way, two workers overlapping during a deploy are safe too, and the rolling deployment stays as it is.

**E.19 — A deployed session ended every fifteen minutes. Done (§859), S.** The session cookie carried only Cognito's access token, which the stack issues for fifteen minutes. The 30-day refresh token Cognito returns with it was thrown away. So fifteen minutes into any session the next request was a 401, and the client answered every 401 by sending the page through sign-in, with an unsaved module or half-filled form going with it. The refresh token now goes to the API with the access token and into a cookie of its own: httpOnly, SameSite=Strict, and sent only to `POST /api/auth/refresh`. That route asks the hosted UI's token endpoint for a new access token and sets a new session. The client renews once on a 401, for all the requests waiting at once, and asks again; a renewal Cognito refuses drops the cookie, and the page goes to sign-in as before. Signing out drops both cookies. `test_session_refresh.py` covers the route and the exchange against a local token endpoint, and `e2e/test_session_renewal.py` covers the client. **Not verified:** a renewal against a real pool.

**E.20 — Two writers of one dataset could swap each other's bytes. Done (§861), S.** Found by following §853's question into the API. Every writer of a dataset version reads `current_version`, writes the parquet to `v{n+1}/data.parquet`, and records the version. None of them locked the dataset when reading. So two writers landing together both took the same number, and both wrote the same key, before either committed. Writers include an action, an upload, a sync, a model run and a listener archive. Whichever wrote second replaced the first's committed file, leaving a version row that described one write and held the other's bytes. The API's refusal of a stale staged version came after the overwrite, and the worker's unique violation came after it too. Each of the seven writers now reads the number with `FOR UPDATE` in the transaction that writes the file and records it. A second writer waits, reads the next number and writes its own key. Readers are never blocked. An action that versions several datasets locks all of them first, in id order (`lock_for_writing`), so two such writes that meet in opposite orders queue rather than deadlock. `test_version_staging.py` has two writers race through staging and commit, and `test_model_run_claims.py` holds a dataset and checks that a run's output waits.

**E.21 — A lost race was answered as a server fault. Done (§862), S.** Two requests changing one thing at once mostly ended with one of them failing in the database. Examples: two saves of a module both taking its next version number, two edits of a code file, and §861's two multi-dataset writes in opposite orders. Uncaught, each reached the 500 handler. The person was told the server was broken, when the same request a moment later would succeed, and the 5xx alarm counted it as an outage. A unique violation, a deadlock and a serialization failure are now a 409 that says what happened and to try again; a unique violation names its constraint, because it can also be a plain duplicate a service did not check for. Every other database error is still a 500.

**E.22 — A deleted workspace's files were never deleted. Done (§864), S.** Found while checking §852's lifecycle rule against what the platform deletes. A workspace's deletion removed its rows and, by its own comment, left the schema and the storage prefix to "an async worker job". The job dropped the schema only. Every file the workspace held stayed in the bucket as a current object for the life of the stack, out of reach of even §852's rule for previous versions. A project's deletion did the same to its datasets' files. A deletion now leaves a tombstone naming the prefix, written by a trigger in the deleting transaction, because a cascade is not a route (db 0164). The nightly cleanup deletes what each tombstone names, and forgets a tombstone only once its prefix is gone. A prefix must be a whole workspace's or one dataset's, or the bucket is not touched. Deleted files' previous versions then expire under §852's rule. **And its object indices (§876):** where objects live in OpenSearch, a workspace's types each had an index, and the cascade that deleted the types never deleted them. The nightly cleanup lists the domain's workspace indices, asks the database which search prefixes no workspace owns (db 0166), and deletes those indices by name. It is an orphan sweep like the schemas', so it also finds what every workspace deleted before it left.

**E.23 — The fifty-first invitation of a day was a server fault. Done (§866), S.** A stack's user pool sent invitations through Cognito's own email, which AWS limits to 50 messages a day per account, and nothing said so. The 51st invitation of a day reached the 500 handler with no hint that waiting, or SES, would fix it. Cognito's other refusals reached it too: an address it would not send to, and an email already in the pool. `-c inviteFromEmail=` now sends through SES from a verified address. Cognito's refusals are translated: the daily limit is a 503 that names its cause and its fix, an existing address a 409, and an address Cognito will not send to a 422 in Cognito's words. Any other code is still a fault.

**E.24 — Every read from S3 left a copy on the task's disk. Done (§869), S.** DuckDB reads a file, so on S3 `local_path` downloaded the object to a new temporary file on every call. That covers every query, preview, object-set read, sync and export. Nothing ever removed one. A task that ran long enough would fill its 20 GB of ephemeral disk, after which every read failed until ECS replaced it; the more a stack was used, the sooner. Both apps now keep one copy per object and ETag, so a repeat read costs a HEAD rather than a download, and an object that changed is fetched again. A download lands whole or not at all. Past `STORAGE_CACHE_MAX_BYTES` (4 GiB), copies idle for fifteen minutes are deleted, least recently used first. The two apps share no code, so the cache is written in each and `test_storage_cache_parity.py` holds them identical.

**E.25 — A run a stopped worker left behind stayed "running" for good. Done (§870), S.** A model run, a code test or a code preview is marked running before its work starts, so the claim is visible (§853). A deploy that replaced the worker's task, an out-of-memory kill or a lost host left that row "running" for ever. A model set to react to new upstream data was then never enqueued again, because its rule is "nothing queued or running", and the run's page said it was still going. Every minute, the model-run pass now fails any run still "running" well past what any run could take: an hour for a model run, which waits at most fifteen minutes on a dispatched transform, and thirty minutes for a test or preview, limited to five. The error says the worker stopped and to run it again (db 0165). An action run the API opened and never closed, because its task was stopped mid-request, is failed after thirty minutes the same way; until then the action's metrics counted it as running for ever. A run that was in fact alive still writes its real outcome over that.

**E.26 — No deployed stack could issue an OpenID Connect token. Done (§871), S.** A source configured for OIDC (§599) trusts tokens the platform signs, instead of the platform holding its credentials. That needs an issuer URL and an RSA signing key shared by every task. The stack set neither, and CloudFormation can generate a password but not an RSA key, so every deployed stack refused every such source. The stack now sets the issuer to its distribution's address and names a secret under the prefix its roles manage. The first API task to need a key generates one and stores it there; a task that loses the race to create it reads the winner's. The worker only reads, so the published key set and every token agree. `test_oidc_stored_key.py` runs this against moto: the key is made once, a cold task reads the same one, and a worker's token verifies against the API's key set.

**E.27 — How much memory DuckDB takes on a deployed task. Done (§875), M; one measurement on a stack remains.** Every dataset operation opens its own in-memory DuckDB, which by default may use 80% of the memory it can see. A user's query is held to 512 MB (`QUERY_MEMORY_LIMIT`). The other connections are not: 21 of the API's 24, for ingest, profiling, preview, export and merging, and most of the worker's. A Fargate task runs in a VM about its own size, so on the API's 1 GB task each of those may take about 800 MB. Two at once, beside the API's own few hundred, would be killed by the kernel, and every request on the task with it. Each fix has a cost that wants a measurement: a limit on every connection, with a temporary directory to spill to, makes the largest operations slower or refused; a shared DuckDB instance shares a catalog its callers' temporary views would collide in; a 2 GB task doubles that line of the bill. It needs `apps/api/bench/scale.py` run on a deployed task, watching memory, before choosing. **One measurement so far (§872):** the bench at a million rows peaked at 938 MB resident in one process on a 16 GB machine, where DuckDB saw 12.5 GB to use. The file was 4.5 MB of parquet, so most of that was the object sync, which on a stack runs in the worker's 2 GB task. That is half the worker's task for a narrow table, and a wider one would scale it. **§875 measured locally and chose.** At three million rows of ten columns (570 MB of CSV), an unbounded connection reached 2.8 GB resident for an ingest, a profile and a join in turn. The profile alone was 1.3 GB, because it counted every column's distinct values in one aggregate, which holds all of them at once. Counting one column per query took the same time and 400 MB, so it now does that. Each connection, in both apps, opens through one `connect()` that takes `DUCKDB_MEMORY_LIMIT` and `DUCKDB_THREADS` from the task and spills past the limit to local disk. The limit is 512 MiB and two threads: the join refused to run under 384 MiB at two threads and passed at it, at about 1.5 times the limit resident. The API task went from 1 GB to 2 GB, which fits two such operations at once plus 512 MiB for the process. Memory is the cheap line of a Fargate bill: about $3 a month per task. `scaling-check.ts` holds the sizes to that sum. **Still to do on a stack:** run `apps/api/bench/scale.py` on a deployed task and confirm that resident memory stays under the task's memory. **§907: the worker counted its output twice.** Model runs, syncs and listener archives wrote their parquet to a temporary file and then read it whole into memory to store it, so a run held its output's size on top of DuckDB's limit, and on S3 an output past 5 GB, the limit of a single PUT, could not be stored at all. They now store from the file: `put_file` copies it locally and uploads it to S3 in 8 MiB parts, four in flight. **§911: the API sized itself for two DuckDB operations and allowed forty.** Each runs on one of anyio's worker threads, and nothing else bounded them. `DUCKDB_SLOTS=2` on the API task does now: an operation past it waits up to a minute for a slot, then gets a 503 with `Retry-After`. A slot belongs to a thread, so a sandbox and its writer hold one between them. **§912: a REST source's answer was read whole.** A page of records, or a token endpoint's answer, went into memory at whatever size the API sent, so one broken or hostile API could take the API task with a preview, or the worker with a schedule. Each is now read to a cap, 32 MB a page and 1 MB a token, and refused past it with an error that says so. Pagination is how a source sends more than that. **§913: the API counted its output twice, as the worker had.** A sync run from the API (up to 200 MB of source), a model run, an action's edit, which rewrites the object type's whole backing dataset, a file sync, a listener archive, which holds every event archived so far, and a fork each wrote parquet to a temporary file and read it whole into memory to store it. They now store from the file through the API's own `put_file`. What still goes through memory is a file a person sent, which the request holds anyway and the body limit caps at 51 MB. **§914: so did an upload dataset of many files.** Adding a file to one, or parsing its files again, read every file it held into memory at once: a dataset of twenty 50 MB files held a gigabyte. Each is now copied from its local path into the directory it is read in.

**E.28 — A new stack's first owner was whoever reached its setup page first. Done (§886), S.** Found while checking every route that needs no sign-in. Self-signup is off and an invitation cannot grant owner, so `POST /api/bootstrap/first-owner` creates the first organisation and its owner with no sign-in, once (db 0017). The stack is reachable at its CloudFront address from the moment it is deployed. Between the deploy and the customer's first visit, anyone who finds that address can make themselves owner of the stack, and the customer finds a "this platform has already been set up" page. §882 fixed the smaller half of this: after setup the route asked Cognito to create a user, which emails an invitation to an address of the caller's choosing, before the database refused, and it now refuses first. Closing the race needs a secret the provisioner holds. For example, the stack generates a setup token in Secrets Manager, the control plane shows it to the customer with the stack's address, and the setup page asks for it. **§886 closed it without asking the customer for anything.** The control plane already holds what the setup form asks for: the organisation's name and slug, and the contact address given at onboarding. It keeps a token for each stack, encrypted like the external ID, and passes only its SHA-256 to every deploy (`-c bootstrapTokenHash`). The template can be read in the customer's account, so the token itself never goes into it. The stack's API then takes a first owner only from the holder of that token. As soon as the stack is ready, the provisioner creates the owner, and Cognito emails the invitation. The onboarding page says where the invitation went, instead of linking to a setup form. If that call fails, the stack is still ready: the next deploy asks again, and so does `cli.py invite-owner`. Unset, as in development, the setup page works as before.

**E.29 — No deployed worker ever ran a schedule. Done (§883), S.** Found while measuring how much the worker's own Dagster storage grows. Dagster starts every schedule stopped until somebody turns it on in its web UI. The worker's UI was never reachable on a stack: no port mapping, and no load balancer rule. Whatever it turned on would have lived on the task's disk, which every deploy replaces. So a deployed stack never ran a scheduled sync, model run, export, test or preview run, listener archive or nightly cleanup. The browser suite calls the ops directly, which is why nothing saw it. Every schedule now starts running, and a test fails for any that does not. The image runs `dagster-daemon` alone instead of `dagster dev`. §883 ran that command locally for two minutes either side of the change: no runs before, nine after. The schedules start about 5,500 runs a day. At Dagster's default of an event-log file per run, about 150 KB each, they would fill the task's 20 GB disk in about three weeks; that disk also holds the S3 cache and DuckDB's spill. The instance now keeps one event log of about 35 KB a run, sends op output to CloudWatch rather than to files, and forgets finished runs hourly: successes after a day, failures after a week. **And the runs it now makes are bounded (§888, §894).** A poll skips its tick while its own last run is unfinished, so a long model run no longer has a second pass start beside it every minute. The instance allows four runs at once, and at most two of the four jobs that work datasets in the worker's own process. Measured under `dagster-daemon`: about 290 MB for the daemon and about 160 MB for each run's process. That put the worst case past the worker's 2 GB, so the worker task is now 4 GB, and `scaling-check.ts` holds it to the sum, reading the limits from `apps/worker/dagster.yaml`.

**E.30 — A listener's events stayed in the database for good. Done (§915), S.** Found while looking for tables nothing ever empties. Every request a listener takes is a row in `listener_events`, body and all, up to 1 MB (db 0106), and the archive copies it into the listener's dataset every five minutes (db 0108) but kept the row. A listener takes up to 100 requests a second, so one busy sender could fill the database's 500 GB ceiling in hours, and a quiet one in months; a full database stops every workspace on the stack. The worker's five-minute archive job now also deletes events that are archived and older than `LISTENER_EVENT_RETENTION_DAYS` (7), up to 100,000 a run in transactions of 5,000, through a SECURITY DEFINER function that refuses anything under a day (db 0168). An event not yet archived is kept however old it is, and so is every event of a listener whose dataset was deleted, since its archive starts again from the oldest one held. The stream is what waits to be archived and what the listener's screen shows; the dataset is the record, as p.261 has it.

**E.31 — A request could fail on its way in for nothing it did. Done (§918), S.** Found while reading what happens to a long request in a deploy. uvicorn and Next.js close an idle connection after 5 seconds; the load balancer keeps its own for 60, and reuses one the server has just closed, so a request now and then got a 502, more often under load: the mismatch AWS's own guidance on load balancer timeouts warns of. And CloudFront waits 30 seconds for an answer by default, so a sync or a model run run from the API that took longer was a 504 to the person who started it while the API carried on and finished it. Each hop now outlasts the one in front of it: CloudFront waits 60 seconds, the most it allows without a quota increase, the load balancer keeps a quiet connection 75, and both servers keep theirs 90. `stack-check.ts` holds the order on both origins. An operation past a minute is still a 504; moving those onto the worker is the remedy if one is found that needs it.

## Suggested order

**First, out of band:** E.1.

| Pass | Items | Why this grouping |
|---|---|---|
| **1 — Navigation** (S) | A.1 Workshop to `/r/{id}` · A.2 delete the duplicate editor · A.3 pillar pages as filtered views | Cheap, mostly deletion, and literally what complaint 3 asks for. |
| **2 — Feel** (S–M) | C.1 the three config tabs · C.2 vertical header · C.3 Flow + Toolbar layouts · C.5 versions dialog · C.6 the four input widgets + Markdown · B.2 editor tabs · B.3 five tabs + sandbox rule · B.4 Problems and File Changes | The items that change how the product reads per unit of work. Most are re-organisations or small additions to things that already exist. |
| **3 — Depth** (M–L) | C.4 external IDs (interface + state saving + deep links unified) · B.1 models into repositories · D Object Views · C.5 changelog panel · B.4 Tests panel | Real capability. C.4 and Object Views are the two that pay for themselves. |

**Deliberately not scheduled:** B.5 language intelligence, B.6 Code Workspaces, D Pipeline Builder, D Global Branching, and the long tail of C.6.

**Running alongside:** E.2 through E.7.

---

## How you would know it worked

The repo's standard is that a check you cannot make fail is not a check (§106, §111, §113, §114 — six green tests that could not reach the condition they named). Applying it:

- **A.1** — a browser test that opens a module from the resource browser and asserts the project sidebar is **absent**. Mutation: put the builder back inside `(platform)` and watch it fail.
- **A.2** — grep for `textarea` under `app/(platform)` and assert `code/page.tsx` and `models/page.tsx` are not in the results. Crude, and it cannot pass for the wrong reason.
- **B.2** — open three files, edit two, reload; both drafts survive and the third is clean.
- **B.3** — committing directly to a protected branch is refused, and the refusal names the branch.
- **C.1** — a widget's input variable is settable from Widget setup and the rendered widget changes without a save; the Metadata tab's raw JSON round-trips.
- **C.4** — one test, three assertions: a host module sets an embedded module's interface variable and the embedded row count changes; the same variable initialises from a URL query parameter; the same variable survives a save-and-reload of state. If any one of the three needs its own mechanism, the design is wrong.
- **C.5** — publishing version N while version N+1 is saved leaves viewers on N; `/dev/` shows N+1.
- **E.1** — a CI run, green, on a real commit. Nothing else counts.
- **E.4** — a named number for p95 dataset-preview latency at a million rows. Any number.

---

## What happened next

This document is the analysis. **The decision that followed it was to go further than it recommends.**

> "I do want to reach parity with at least the parts we are doing. Workshop, code editor etc. This isn't a full replication of Foundry, but I want full parity/replication in a few applications. Foundry without all the bloat."

So the closing position of this document — a map of the distance, with the cheap parts marked — is no longer the plan. The plan is **full parity inside a named boundary, and nothing outside it**. That boundary and the checklists that implement it live in [`docs/parity/`](parity/README.md):

| Spec | Covers |
|---|---|
| [`parity/workshop.md`](parity/workshop.md) | core builder and the full widget library — we have 13 of ~52 widgets |
| [`parity/code-repositories.md`](parity/code-repositories.md) | five tabs, nine helper panels, sandbox branches |
| [`parity/ontology.md`](parity/ontology.md) | Ontology Manager, Object Explorer, Object Views, Action Types |
| [`parity/datasets-lineage.md`](parity/datasets-lineage.md) | Dataset Preview, Data Lineage |
| [`parity/data-connection.md`](parity/data-connection.md) | sources, syncs, exports, egress |

Out of scope, and named there so that skipping them is a decision: Pipeline Builder, Slate, Contour, Quiver, Code Workbook, Code Workspaces, Carbon, Marketplace, AIP everything, and — within Workshop — Scenarios, Mobile and the AIP widgets.

**What survives from this document unchanged** is sections A and E. The navigation work is stage 1 of the parity plan because it is mostly deletion and everything else lands in a cleaner shape afterwards. Section E was stage 0 — **E.1 is now done**, and it found a real bug rather than merely proving wiring, which is the best possible argument for having put it first.
