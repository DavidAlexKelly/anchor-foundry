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

**Recommendation: do not start here.** B.1–B.4 close most of the felt gap at a fraction of the cost and are prerequisites either way. Revisit when the remaining complaint is specifically "I want my own extensions and a terminal".

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

**E.1 — The CI workflow has never executed. S. Do this first.** `.github/workflows/ci.yml` was written carefully and fixed once by inspection (§108), and no GitHub Actions run has ever been triggered from this environment. A workflow that has never executed is a workflow that does not work. Everything else here assumes checks are real.

**E.2 — Decision 0006 is unproven against a real cluster. M.** Typed instance properties are tested against a fixture that now enforces mappings and has 17 tests of its own fidelity (§112). As that work said: this narrows the unproven claim from "does any of this work" to "does OpenSearch behave like the mapping it was given". One deployment closes it.

**E.3 — Observability: there is none. M.** No error tracking, no structured logging worth querying, no metrics, no alerting. The first incident will be diagnosed by SSH and guesswork.

**E.4 — Scale is entirely unmeasured. M.** Every test runs against tens of rows. Not "it will be slow" — **unknown**, which is worse, because it cannot be planned around.

**E.5 — Dependency advisories. S.** Two in the Next 14.2.5 tree. Pre-existing and known; still an answer somebody will want.

**E.6 — The `export` effect. S.** Refused with its reason (§76) because it needs a download surface the viewer route lacks. Foundry's Button Group treats export as a first-class `On click` target alongside actions, events and URLs (`workshop` p.482) — so this is not an exotic ask.

**E.7 — Backup and restore has never been rehearsed. M.** An untested backup is a hope.

---

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

**What survives from this document unchanged** is sections A and E. The navigation work is stage 1 of the parity plan because it is mostly deletion and everything else lands in a cleaner shape afterwards. Section E is stage 0 and unaffected by any of it: **CI has still never once executed**, and every parity claim below is worthless until it does.
