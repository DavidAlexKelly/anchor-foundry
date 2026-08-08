# Roadmap phase 3 — fidelity, and the road to production

_Phase 1 built six pillars (`docs/roadmap-phase-1-pillars.md`). Phase 2 reshaped them into Foundry-shaped applications (`ROADMAP.md`) and is essentially complete: sections 0, 3 and 4 are done, 1 and 2 are done but for named remainders._

_This document exists because "done" and "right" turned out to be different things. Phase 2 asked whether each surface **existed**. This one asks whether it is **the thing Foundry users would recognise**, and what else stands between here and a system worth putting in front of a paying customer._

---

## What is actually being asked for

Three complaints, and they are all correct:

1. **"Code is a very simple model runner. I want a full integrated VS Code like in Foundry."**
2. **"Canvas should work exactly like Foundry Workshop from a UI perspective."**
3. **"When you are in a project the navigation is fine, but it should simply be the navigation. When going to stuff like edit a canvas or a code repo this should be a new screen."**

The third is the cheapest to fix and the one that makes the other two feel different immediately, so it goes first.

### A note on how this was researched, and its limits

Palantir's documentation at `palantir.com/docs/foundry` is **not directly fetchable from this environment** — the network egress proxy blocks the domain. Everything below about Foundry comes from search-engine summaries of those doc pages, cited at the end of each section.

That is a real limitation and it should shape how you read this. Claims of the form *"Foundry has five tabs named X"* are well-sourced. Claims about **how something feels to use** are not — nobody in this loop has used Foundry. Where a design decision hinges on feel rather than fact, this document says so rather than inventing confidence.

---

## The headline finding

**The good version usually already exists, beside a worse one that people actually hit.**

This was not what I expected to find. Three examples, all verified in the working tree:

| The good thing | Where it is | The worse thing beside it |
|---|---|---|
| Monaco editor, file tree, branches, PRs, checks, preview | `components/applications/repository-app.tsx` (1173 lines), full-screen at `/r/{id}` | `/[workspace]/[project]/code/page.tsx:332` — a plain `<textarea className="code-editor">` |
| Full-viewport application shell, no platform chrome | `app/(app)/layout.tsx` + `application-shell.tsx` | The Workshop builder renders *inside* the project sidebar at `/[workspace]/[project]/canvas/[appId]` |
| Typed variables, events, layout system, 21 widgets | `components/canvas/` | `/[workspace]/[project]/models/page.tsx:330` — SQL and Python authored in a `<textarea className="sql-box">` |

So the honest framing of complaint #1 is not "the code editor is bad". It is: **there are two code editors, and the pillar page still ships the 2023 one.** Complaint #3 is not "canvas needs a new screen" — the new-screen machinery is built, tested and in use by three other resource kinds; Workshop simply was never moved onto it.

That is very good news for sequencing. Section A below is mostly deletion.

---

## Section A — Navigation: make the project page *only* navigation

**Size: S. Highest leverage in this document.**

### What Foundry does

The sidebar is the constant companion and the starting point for navigation, openable and collapsible with `Cmd+O`. **Files**, powered by Compass, is the landing page for the project folder structure. A project is a folder of resources; opening a resource opens **its own application**, full-screen. The Applications portal is a separate surface for finding apps, not resources.

### A.1 Move the Workshop builder to `/r/{id}` — **S**

**Today.** `app/(platform)/[workspace]/[project]/canvas/[appId]/page.tsx` (507 lines) sits inside the `(platform)` route group, so it inherits `ProjectLayout`'s sidebar: breadcrumbs, project name, and six section links with counts. A Workshop builder with three of its own panels then competes for what is left.

Meanwhile `app/(app)/r/[resourceId]/page.tsx` already dispatches `dataset`, `code_repo` and `object_type` to full-screen applications — and `canvas_app` still falls through to `APPLICATIONS`, a stub that renders a summary and a link back to the pillar page it came from.

**Build.**
- A `WorkshopApplication` in `components/applications/`, wrapping the existing builder. This is a move, not a rewrite: the Craft.js `<Editor>`, the three panels and the viewer all stay.
- Register `canvas_app` in the `/r/{id}` dispatch alongside the other three and delete its `APPLICATIONS` entry.
- `/[workspace]/[project]/canvas/[appId]` becomes a permanent redirect to `/r/{id}`. **Not a deletion** — links to it exist in the wild, in the e2e suite, and in `STATUS.md`.
- The e2e helper `open_module()` in `e2e/conftest.py` changes once and every browser test follows.

**Prove it.** Open a module from the resource browser: full viewport, no project sidebar, the module's own name in the shell. The old URL still lands in the same place. All 32 browser tests still pass.

**Watch for.** The builder currently reads `useParams<{workspace, project, appId}>`. Under `/r/{id}` it has a resource id and must resolve the rest. `resolve()` already returns `workspace_slug` and `project_slug` — the shell has them, the builder should take them as props rather than re-fetching.

### A.2 Delete the second code editor — **S, and it is mostly deletion**

`/[workspace]/[project]/code/page.tsx` is 463 lines that duplicate, worse, what `repository-app.tsx` does in 1173. Point the pillar page at the resource browser filtered to `kind=code_repo`, and let the repository open at `/r/{id}`.

The same applies to `models/page.tsx:330`. That one is harder, because a model is not yet a repository — see B.1.

**Watch for.** The code pillar page is where review-required proposals are created today. Check `review-surface.tsx` and the proposal flow reach the same place from the application before removing the page, or the governance path loses its entry point.

### A.3 Pillar pages become filtered views — **S**

Phase 2's section 0.2 already recommended this and it was only half-taken: the resource browser exists, and the six pillar pages exist beside it as separate implementations. Two implementations of one list is the condition under which they drift, and they have.

Keep the nav *entries* — they are good discoverability for somebody who does not yet know what a resource is. Make each one `/[workspace]/[project]?kind=dataset` against the browser.

**Sources.** [Orientation and navigation](https://www.palantir.com/docs/foundry/getting-started/orientation-and-nav) · [Compass overview](https://www.palantir.com/docs/foundry/compass/overview) · [Projects and resources](https://www.palantir.com/docs/foundry/getting-started/projects-and-resources)

---

## Section B — Code Repositories: from a repository surface to an IDE

**Size: L overall, and genuinely incremental.**

### What Foundry does

Code Repositories is a **web-based IDE** for production code, with all common Git tasks — branching, committing, tagging releases — through the web UI. Five tabs across the top: **Code, Branches, Pull requests, Checks, Settings**. Repositories include IntelliSense, code linting and error checking, and rich help dialogs.

Alongside the editor sit **helper panels**: the **Foundry Explorer** for browsing files and folders, **Problems** (click an issue to jump to the code), **File Changes** (uncommitted changes on the current file, and comparison with previous versions), **Tests** (run unit tests, see results), and **Docs**. A **status bar** reports environment state and checks results, including **Code Assist** state — which the docs call essential for detecting problems and running previews.

Separately, **Code Workspaces** brings JupyterLab, RStudio and **VS Code** as real containerised IDEs, backed by the Code Repositories infrastructure so branching, merging and commit history still apply.

### Where we actually are

Better than the complaint suggests, and worse than Foundry:

| Foundry | Anchor today |
|---|---|
| Code tab with Monaco-class editor | ✅ Monaco, self-hosted (`code-editor.tsx`, deliberately not CDN-loaded) |
| File tree | ✅ `FilesTab` |
| Branches tab | ✅ create/list/delete, fast-forward, merge |
| Pull requests tab | ⚠️ exists as *proposals* with review + checks, but is not a repository tab |
| Checks tab | ⚠️ checks run and block, but have no tab of their own |
| Settings tab | ❌ |
| Problems / File Changes / Tests / Docs panels | ❌ |
| Status bar | ❌ |
| IntelliSense beyond Monaco's built-ins | ❌ |
| Multi-file editor tabs | ❌ one file at a time |
| Preview on a sample before commit | ✅ SQL only (`PreviewPanel`) |
| Code Workspaces (real VS Code container) | ❌ |

### B.1 One editor, one repository model — **M**

Before anything is added, the duplication has to go, and the awkward part is `models`. A model today is a single SQL or Python string in a `<textarea>`. In Foundry the equivalent lives in a repository as a file. Until a model *is* a file in a repository, there will always be a second editor.

**Build.** Make the model's transform a file in the project's repository, edited through the same application. Keep the model row as the *declaration* (inputs, output, trigger, schedule); move the *body* into the repo. `STATUS.md` §94's publish path already connects a repository file to a model — this is finishing that direction rather than starting a new one.

**Watch for.** This is a data migration with a real failure mode: a model whose body is mid-edit when the migration runs. Write it as "copy into the repo, leave the column, read from the repo, drop the column in a later migration" rather than a single cutover.

### B.2 Multi-file editing with tabs — **M**

One open file at a time is the single biggest thing that makes the current editor feel unlike an IDE. Editor tabs, per-tab undo history, and dirty markers.

**Watch for.** Uncommitted edits live in `useState` keyed by path (`edits`, `repository-app.tsx:206`) with no persistence anywhere. That survives switching files but not a page reload, so a multi-tab editor with unsaved work in five tabs is five ways to lose work at once. Persist to `localStorage` keyed by repository and branch **before** adding tabs, not after — tabs are what make the loss expensive.

### B.3 The five tabs — **M**

Mostly re-homing what exists: `Pull requests` from the proposal surface, `Checks` from the check runs, plus a new `Settings`. Our current four are Files, History, Branches, Publish; Foundry's are Code, Branches, Pull requests, Checks, Settings. `History` and `Publish` have no Foundry counterpart at that level — history belongs in a panel, publish belongs on the branch.

### B.4 Helper panels — **M each, and independently useful**

- **Problems** — needs a linter. Python: `ruff` in the transform runner container, results back as diagnostics. SQL: parse errors from DuckDB's parser, which we already run for preview.
- **File Changes** — a diff of the working draft against the committed version. The diff machinery exists for commits already (`STATUS.md` §60); this points it at uncommitted state.
- **Tests** — needs the runner to accept a "run pytest" job shape. The runner (`docs/decisions/0004-running-customer-code.md`) already executes customer Python in an isolated container with an empty task role; a test job is the same mechanism with a different entrypoint.
- **Foundry Explorer equivalent** — browse datasets and object types *from inside the editor*, and insert a reference. This is small and disproportionately makes the editor feel connected to the platform.

### B.5 Language intelligence — **L**

Monaco gives basic completion for free. Real IntelliSense over *your* datasets — completing column names on a DataFrame — needs a language server with platform context. This is the most expensive item in section B and the one most safely deferred: it is the difference between a good editor and Foundry's, not between a textarea and an editor.

**Recommendation.** Defer until B.1–B.4 are done and in use. Then decide with evidence about what people actually reach for.

### B.6 Code Workspaces — **XL, and a separate product decision**

Real VS Code in a container per user, backed by the same repository storage. This is what the request literally asked for, and it is a large piece of infrastructure: per-user containers, lifecycle and idle shutdown, persistent volumes, a proxy that authenticates into a session, and a security model for a shell inside your VPC.

**The honest recommendation: do not start here.** B.1–B.4 close most of the felt gap at a fraction of the cost, and they are prerequisites either way — Code Workspaces in Foundry is explicitly *backed by* Code Repositories, not a replacement for it. Revisit once the browser IDE is good and the remaining complaint is specifically "I want my own extensions and a terminal".

**Sources.** [Code Repositories overview](https://www.palantir.com/docs/foundry/code-repositories/overview) · [Navigation](https://www.palantir.com/docs/foundry/code-repositories/navigation) · [Code Workspaces overview](https://www.palantir.com/docs/foundry/code-workspaces/overview) · [VS Code workspaces](https://www.palantir.com/docs/foundry/vs-code/overview) · [Comparison: Repositories vs Workbook vs Workspaces](https://www.palantir.com/docs/foundry/code-workbook/code-products-comparison)

---

## Section C — Workshop: UI fidelity

**Size: L, and almost entirely additive — the model underneath is sound.**

Phase 2 built the hard part. Variables are typed with derivations, cycle refusal and usage-aware deletion; events are trigger → ordered effects with Foundry's sequential copy-immediately semantics; layouts have pages, sections, overlays, tabs and a header. What is missing is mostly *shape of the UI*, which is exactly what the complaint says.

### C.1 The widget configuration panel — **M**

**Foundry.** The core configuration options live within a **Widget setup** tab, where the builder configures input and output variables, plus additional configuration and display options. Widgets are *wired to each other through variables* rather than configured in isolation.

**Us.** `SettingsPanel.tsx` shows a flat list of props for the selected widget. The variable wiring exists but reads as one field among many, rather than as the primary thing a widget *is*.

**Build.** Split the panel into the Foundry shape: **Widget setup** (inputs/outputs as variables, first and prominent), **Display**, **Actions/Events**. This is a re-organisation of an existing panel, not new capability, and it is probably the single change that would most make the builder "feel like Workshop".

### C.2 The vertical header — **S**

Foundry offers a **vertical header** displayed on the left of the module, with configurable width. We have a horizontal header only (`STATUS.md` §80). Small, visible, and very characteristic of Workshop applications.

### C.3 Module interface and embedded-module variable mapping — **M**

**Foundry.** The Embedded Module widget lets a builder select a module *and define a mapping of variables in the current module to the embedded module's interface variables*. A module declares an **interface** — the variables it accepts from a host.

**Us.** `STATUS.md` §114 built embedding and **explicitly deferred the mapping**, with the Settings panel saying so where somebody would otherwise assume. That was the right call at the time and it is now the gap: an embedded module that cannot be parameterised is a picture, not a component.

**Build.** An `interface` block in the module document (`format: 2` already has room), an interface editor in the Variables panel, and a mapping editor on the Embedded Module widget. The save-time refusals to add: mapping a variable that is not in the interface, type mismatch between host and interface variable, and a required interface variable left unmapped.

### C.4 The versions dialog — **S**

**Foundry.** A **Versions dialog** listing saved versions with timestamp, editor and description, each publishable so viewers get it. Saving does not move viewers; publishing does.

**Us.** The *semantics* are already right — `STATUS.md` §88 pinned publishing to a version so saving no longer moves viewers. What is missing is the dialog. The data is there; this is a UI.

### C.5 State saving — **M**

**Foundry.** Users can save the state of a module (filters, selections) and return to it, via a dropdown in the module header.

**Us.** Nothing. `STATUS.md` §99 built deep links into application state, which is the same idea addressed to a URL rather than to a saved record — so the state serialisation already exists. This is "give that a name and a table".

### C.6 The widget library — **XL, incremental, and the least urgent**

We have 21 widgets. Foundry's documented library, by category:

- **Filtering** — Filter List ✅, Object Dropdown ❌, Object Selector ❌, String Selector ❌, Checkbox ❌, Date Input ❌, Text Input ❌
- **Core display** — Object Table ✅, Metric Card ✅, Pivot Table ✅
- **Visualization** — Chart XY ✅, Map ✅, Timeline ❌, Waterfall Chart ❌, Status Tracker ❌, Stepper ❌, PDF Viewer ❌, Resource List ❌
- **Event-trigger & navigational** — Tabs ✅, Button Group ✅, Inline Action ❌, Media Uploader ❌
- **Other** — Embedded modules ✅, Comments/Notepad ❌, AIP Interactive ❌ (out of scope)

Our `CanvasParameterControl` covers several of Foundry's filtering widgets generically. That is a defensible design — but it is *our* design, and the complaint was that Workshop should feel like Workshop. Worth deciding deliberately rather than by omission.

**Priority order if pursued:** Text Input, Date Input, String Selector (the three that make a filter bar feel complete) → Inline Action → Timeline → Resource List → the rest on demand.

### C.7 Edit and view are already separate

Worth recording because it is easy to re-litigate: Preview exists in the builder, the viewer route exists, and `STATUS.md` §114 keeps the embedded editor disabled in both. Nothing to do.

**Sources.** [Workshop widgets](https://www.palantir.com/docs/foundry/workshop/concepts-widgets) · [Layouts](https://www.palantir.com/docs/foundry/workshop/concepts-layouts) · [Variables](https://www.palantir.com/docs/foundry/workshop/concepts-variables) · [Module interface](https://www.palantir.com/docs/foundry/workshop/module-interface) · [Embedded modules](https://www.palantir.com/docs/foundry/workshop/embedded-modules) · [Publishing and versioning](https://www.palantir.com/docs/foundry/workshop/versions) · [State saving](https://www.palantir.com/docs/foundry/workshop/state-saving) · [Visualization widgets](https://www.palantir.com/docs/foundry/workshop/widgets-visualization) · [Event-trigger & navigational widgets](https://www.palantir.com/docs/foundry/workshop/widgets-event-navigational)

---

## Section D — What is missing entirely

Not gaps in existing surfaces; whole products we have no answer to. Listed so the decision to skip them is deliberate.

| Foundry | What it is | Recommendation |
|---|---|---|
| **Pipeline Builder** | Visual, strongly-typed pipeline authoring — graph and form interfaces, join-key and cast suggestions, errors flagged immediately rather than at build time. Two renderings: board and pseudocode. | **The largest genuine product gap.** Our `/project/pipeline` is a read-only DAG *view*; Foundry's is an authoring environment. XL. Worth a design spike before any commitment. |
| **Object Views** | A configured full-screen view of a single object instance, with tabs (which can themselves be Workshop modules) and an Actions section. | M–L. Sits naturally on the Object Explorer we already have, and is what makes an ontology feel navigable rather than tabular. **Best value-per-effort item in this table.** |
| **Functions** | Code-based logic natively integrated with the Ontology — takes objects and object sets, used by action types and applications. Backs "function-backed actions". | L. Our actions are declarative only. Needed before actions get much richer. |
| **Applications portal / Favorites / Recent** | Platform-level discovery. | S each, and they make a platform feel like a platform. Cheap wins. |
| **Carbon workspaces** | Multi-module tabbed workspaces across applications. | Skip. Deep Foundry-specific idiom; no evidence it is wanted here. |

**Sources.** [Pipeline Builder overview](https://www.palantir.com/docs/foundry/pipeline-builder/overview) · [Transforms overview](https://www.palantir.com/docs/foundry/pipeline-builder/transforms-overview) · [Object Views](https://www.palantir.com/docs/foundry/object-views/config-object-views) · [Ontology overview](https://www.palantir.com/docs/foundry/ontology/overview) · [Action types](https://www.palantir.com/docs/foundry/action-types/overview)

---

## Section E — Production readiness, which is not the same as fidelity

**None of the above makes this production-ready.** These are the things that would embarrass us in front of a customer, roughly in order of how much.

### E.1 The CI workflow has never executed — **S, and do it first**

`.github/workflows/ci.yml` exists, was written carefully, was fixed once by inspection (`STATUS.md` §108) — and **has never run**. No GitHub Actions run has ever been triggered from this environment. A workflow that has never executed is a workflow that does not work; that is not pessimism, it is the base rate.

**Do this before anything else in this document.** Push a branch, watch it run, fix what breaks. Everything else here is built on the assumption that checks are real.

### E.2 Decision 0006 is unproven against a real cluster — **M**

Typed instance properties are implemented and tested against a *fixture* — a fixture that now enforces mappings and has 17 tests of its own fidelity (`STATUS.md` §112). But as that work said plainly: this narrows the unproven claim from "does any of this work" to "does OpenSearch behave like the mapping it was given". It does not close it. **One deployment against a real cluster, running the existing suite, closes this.**

### E.3 Observability — **M, and there is nothing today**

No error tracking, no structured request logging worth querying, no metrics, no alerting. The first production incident will be diagnosed by SSH and guesswork. Sentry-or-equivalent plus structured logs on the API is a day of work and changes the character of every incident after it.

### E.4 Scale is entirely unmeasured — **M**

Every test runs against tens of rows. Nothing here has met a million-row dataset, a hundred concurrent users, or an object type with 200 properties. Not "it will be slow" — **unknown**, which is worse, because it cannot be planned around. A load test against realistic volumes turns a set of unknowns into a list of specific problems.

### E.5 Dependency advisories — **S**

`npm audit` reports two advisories in the Next 14.2.5 tree. Pre-existing and known; still an answer somebody will want.

### E.6 The `export` effect — **S**

Refused with its reason (`STATUS.md` §76) because it needs a download surface the viewer route lacks. Small, and the most visible unfinished thing in Workshop.

### E.7 Backup and restore has never been rehearsed — **M**

RDS snapshots presumably exist. Nobody has restored one and checked the platform comes back. An untested backup is a hope.

---

## Suggested order

**First, and out of band:** E.1 (make CI actually run). Everything below assumes checks are real.

**Then, in three passes:**

| Pass | Items | Why this grouping |
|---|---|---|
| **1 — Navigation** (S) | A.1 Workshop to `/r/{id}` · A.2 delete the duplicate code editor · A.3 pillar pages as filtered views | Cheap, mostly deletion, and it is what the complaint about screens is literally asking for. Everything after it lands in a cleaner shape. |
| **2 — Feel** (M–L) | C.1 widget setup panel · C.2 vertical header · C.4 versions dialog · B.2 editor tabs · B.3 the five tabs · B.4 Problems + File Changes | The items that change how the product *reads* per unit of work. Half are re-organisations of things that already exist. |
| **3 — Depth** (L–XL) | B.1 models into repositories · C.3 module interface · C.5 state saving · D Object Views · B.4 Tests panel | Real new capability. Object Views is the best value here and the easiest to underrate. |

**Deliberately not scheduled:** B.5 language intelligence, B.6 Code Workspaces, C.6 the long tail of widgets, D Pipeline Builder. Each is large, each is defensible later, and none of them is what makes the current product feel unfinished.

**Running alongside, not after:** E.2 through E.7. These do not compete with feature work for the same attention, and E.3 in particular gets more valuable the more there is to break.

---

## How you would know it worked

The repo's standard is that a check you cannot make fail is not a check (`STATUS.md` §106, §111, §113, §114 — six green tests that could not reach the condition they named). Applying it here:

- **A.1** — a browser test that opens a module from the resource browser and asserts the project sidebar is **absent**. Mutation: put the builder back inside `(platform)` and watch it fail.
- **A.2** — grep for `textarea` under `app/(platform)` and assert the code and models pages are not in the results. Crude, and it cannot pass for the wrong reason.
- **B.2** — open three files, edit two, reload, assert both drafts survive and the third is clean.
- **B.3** — each tab reachable by URL and by click; deep links survive a reload (the `use-url-state` pattern from `STATUS.md` §99).
- **C.1** — a widget's input variable is settable from the Widget setup tab and the change is visible in the rendered widget without a save.
- **C.3** — a host module sets an embedded module's interface variable and the embedded module's row count changes. This is the §114 test extended: it already proves the boundary is a wall, and this proves there is a door in it.
- **E.1** — a CI run, green, on a real commit. Nothing else counts.
- **E.4** — a named number for p95 dataset-preview latency at a million rows. Any number. The point is to have one.

---

## What this document is not

It is not a commitment to reach parity with Foundry. Foundry is a decade of work by a large team, and several things in section D would each be a quarter on their own.

It is a map of the distance, with the cheap parts marked. The three complaints that prompted it are addressed by pass 1 and pass 2 — roughly the top third of this document — and that is the part worth doing next.
