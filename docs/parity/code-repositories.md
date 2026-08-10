# Code Repositories — parity specification

**Source:** `docs/pal/foundry_code-repositories.pdf`, 140 pages. Citations are `(p.13)`.

**Today:** `apps/web/src/components/applications/repository-app.tsx`, 1173 lines, full-screen at `/r/{id}`. Tabs: Files (with editor and Preview), History, Branches, Publish. Proposals and checks exist but live on the project's Code pillar page, not in the application.

Foundry's own summary of the product: "a web-based integrated development environment (IDE) for writing and collaborating on production-ready code", with all common Git tasks through the web UI, integrated pull-request review, and "IntelliSense, code linting and error checking, and rich help dialogs" (p.2).

**Also delete `app/(platform)/[workspace]/[project]/code/page.tsx`.** 463 lines duplicating this, worse, with a `<textarea className="code-editor">` at line 332. Parity is unreachable while two editors exist, and users currently hit the wrong one.

---

## 1. The five tabs (p.10)

| Tab | Status | Notes |
|---|---|---|
| **Code** | ✅ | ours is called Files |
| **Branches** | ✅ | create, list, delete, fast-forward, merge |
| **Pull requests** | ◑ | exists as *proposals*, on a different page |
| **Checks** | ◑ | checks run and block, no tab |
| **Settings** | ○ | |

Ours has **History** and **Publish**, which have no Foundry counterpart at tab level. History belongs in the File Changes helper; Publish belongs on the branch. Keep both until their replacements land, then fold them in.

---

## 2. The Code tab

Six labelled regions (p.10–11): In-App Help, Branch Options, Code Editor Options, File Editor, Helper Panels, Status bar.

### 2.1 Branch options

| Feature | Status | Notes |
|---|---|---|
| Branch dropdown | ✅ | |
| Create a sandbox branch from an existing branch | ✅ | |
| **Protected branches cannot be directly edited** | ○ | "To edit code in your repository, you must work in a sandbox branch" (p.12). We allow editing `main` directly. |
| Global branches | ○ | out of scope — see `README.md` on Global Branching |

The protected-branch rule is the one to take seriously. It is what makes the Pull requests tab load-bearing rather than optional, and it is a refusal, so it is testable.

### 2.2 Code editor options (p.13)

| Action | Status |
|---|---|
| **Preview** — run the transform on a sample of input datasets | ◑ SQL only |
| **Test** — run all unit tests in the current file | ○ |
| **Commit** — commit changes on the sandbox branch, triggering automatic checks | ✅ |
| **Build** — build output datasets of the current file after checks; no-op if the file produces none | ○ |
| **Create Pull request** | ◑ via proposals, elsewhere |
| Merge another branch into the current one | ✅ |
| **Reset** — discard uncommitted changes, matching the remote branch | ○ |
| **Upgrade** — upgrade the branch to latest language versions | ○ (may never apply to us) |
| New file / folder / **sub-project** | ◑ file only |

### 2.3 File editor

| Feature | Status | Notes |
|---|---|---|
| Monaco-class editor, self-hosted | ✅ | deliberately not CDN-loaded |
| File tree | ✅ | |
| **Multiple open files with tabs** | ○ | the single biggest thing making ours feel unlike an IDE |
| **Draft persistence across reload** | ○ | see the warning below |
| IntelliSense over platform types | ○ | Monaco's built-ins only |
| Linting and error checking | ○ | needs §2.4 Problems |
| Command palette on F1 | ○ | (p.11) |
| In-app help walkthrough | ○ | (p.11) |

> **Do persistence before tabs.** Uncommitted edits live in `useState` keyed by path (`repository-app.tsx:206`) with no persistence anywhere. That survives switching files but not a page reload — so a five-tab editor with unsaved work is five ways to lose work at once. Tabs are what make the loss expensive; ship `localStorage` keyed by repository and branch first.

### 2.4 Helper panels — nine (p.13–15)

| Panel | Status | Notes |
|---|---|---|
| **Foundry Explorer** | ○ | browse files and folders; select a dataset and Open it. Our equivalent: browse datasets and object types from inside the editor and insert a reference. Small, and disproportionately makes the editor feel connected to the platform. |
| **Problems** | ○ | "Click on a specific issue listed here to open up the problematic code." `ruff` for Python in the transform runner; DuckDB's parser for SQL, which preview already runs. |
| **Debugger** | ○ | defer — assumes Foundry's transform debugging model |
| **Preview** | ◑ | SQL only; extend to Python |
| **Tests** | ○ | the runner already executes customer Python in an isolated container with an empty task role (`docs/decisions/0004-running-customer-code.md`). A test job is the same mechanism with a different entrypoint. |
| **File Changes** | ○ | uncommitted changes to the current file, and comparison with previous versions. The diff machinery exists for commits (§60); point it at uncommitted state. |
| **Build** | ○ | defer — assumes Foundry's build orchestration, which is not our worker |
| **Docs** | ○ | language references in-product |
| **SQL Scratchpad** | ◑ | we have query-and-preview; missing the **favourites** and **history** tabs, and the branch-qualified syntax `` SELECT * FROM `branch_A`.`/path/to/dataset` `` (p.15) |

### 2.5 Status bar (p.15) — ○ entirely

Four indicators:

- **Code Assist state** — "essential for detecting problems in your code and running previews… Hover over the Code Assist status you can get details on the initialization progress."
- **Problems** — an indication on the left; click to open the Problems helper
- **Checks status** — on the right
- **File saving** — automatic save progress after any change

Our equivalent of Code Assist is whatever backs Problems and Preview. The lesson worth copying is not the widget, it is that **Foundry tells you when the thing that makes the editor smart is not yet ready**, rather than silently behaving like a dumb editor.

---

## 3. Branches tab (p.16–17)

| Feature | Status |
|---|---|
| List all branches, including other users' | ✅ |
| Create a branch from a specific branch | ✅ |
| **Checks column** — whether automatic checks passed for a branch | ○ |
| **Pull request column** — existing PR state (Open / Closed / Merged) or a Propose changes button | ○ |
| Choose a non-default merge target from a dropdown | ◑ |
| View code on a branch without switching to it | ○ |
| Delete a branch | ✅ |
| **Tags** — "like immutable branches", created from a branch head or any commit | ○ |
| Tag name validation by regex via `repoSettings.json` | ○ |

The docs add a note we should honour: "You should not delete any branches that you did not create. This can result in lost work for others" (p.17). Ours should say so at the point of deletion.

---

## 4. Pull requests tab (p.18–19)

| Feature | Status | Notes |
|---|---|---|
| List PRs; switch Open / Closed | ◑ | proposals, elsewhere |
| Search by title or author | ○ | |
| Create a PR, choosing the base branch | ◑ | |
| **Line-by-line review with comments** | ◑ | §52 built a review surface; verify it is line-level, not file-level |
| Require at least one approving review before merge, per repository settings | ✅ | §28 review-gated promotion |
| **See how changes affect datasets** when reviewing transform code | ○ | see §4.1 |

### 4.1 Impact analysis (p.52–55)

The largest single gap in this file, and the one that most changes what a review *is*. Ours reviews text; Foundry reviews the consequences of text.

Impact analysis requires the affected datasets to have been built on **both** the head and the base branch — head "to validate that the code builds properly, the outputs appear as expected, and that all Data Expectations are met", base "to compare the outputs to the latest version of the target" (p.52). The PR page warns when affected datasets are **stale** and offers **Configure and build** to review and build them.

| Feature | Status | Notes |
|---|---|---|
| List of directly affected datasets | ○ | Python repos derive this from Transforms Level Logic Versioning; Java treats a dataset as affected if its source file changed (p.53) |
| **Add datasets to analysis** — pull derived datasets in, plus every intermediate between (p.54) | ○ | |
| **Code** — changes to the source file only | ◑ | our diff is the source file |
| **Schema** — column changes on the output dataset | ○ | we detect schema drift on syncs (§5); this is the same question asked of a proposal |
| **Security** — changes to markings applied to the output | ○ | |
| **Expectations** — data expectations on the head branch | ◑ | we have quality gating (§11), not surfaced on a proposal |
| Trashed datasets shown faded | ○ | |
| Inaccessible datasets marked as such rather than hidden | ○ | a small honesty that is easy to get wrong |
| Staleness warning + Configure and build | ○ | |
| **Pipeline review tab** — lineage view of affected datasets; select a node to see the code and schema changes that produced it (p.54–55) | ○ | we have the lineage graph (§14) |
| **Per-file approve/reject**, shown as an indicator on the corresponding output dataset node in the graph (p.55) | ○ | |

Two limits Palantir states plainly and we should copy rather than discover: the staleness warning "only covers affected datasets within a specific code repository" and says nothing about stale parent datasets outside it or about uncommitted changes (p.52); and reviewing affected datasets requires access to the data, so an inaccessible dataset is labelled, not silently dropped (p.53).

**Sequencing.** This depends on the publish path (§55) knowing which datasets a proposal touches, and on being able to build a dataset on a branch without promoting it. Neither exists yet, so this is late — but it is worth naming early, because "which datasets does this change break" is the question a data platform exists to answer, and a review surface that cannot answer it is a code-review tool that happens to live next to data.

---

## 5. Checks tab (p.19)

| Feature | Status |
|---|---|
| Summary of running and completed checks per branch | ◑ (no tab) |
| Branch selector | ○ |
| Drill into a specific check | ◑ |
| **Unit test output included in checks** | ○ |
| Custom checks (TOC §25) | ○ |

---

## 6. Settings tab (p.20)

"Code authors can configure their personal editor preferences and repository administrators can control the repository's behavior and policies." Most options are admin-only, defaulting to repository owners.

| Setting group | Status | Source |
|---|---|---|
| Personal editor preferences | ○ | p.20 |
| Branch settings — protection, required reviews | ◑ scattered | TOC §28 |
| Repository settings | ○ | TOC §29 |
| Compute usage | ○ | TOC §35 |
| Ontology imports | ○ | TOC §33 |
| Artifact settings, Spark profiles, upgrades | — | not applicable to us |

---

## 7. Repository types

Foundry supports several; two matter here (p.3):

- **Transforms repositories** — "authoring data transformation logic… previewing and debugging transforms. Supported languages include Python, Java, and SQL." Ours: Python and SQL. ◑
- **Functions repositories** — "writing business logic that can be executed with low latency in an operational context… native support for accessing data from the Foundry Ontology. The Code Repositories environment supports autocomplete based on Ontology data types, and enables code authors to preview Functions while authoring them." ○ — this is the Functions dependency from `README.md`.

---

## 8. Related capabilities

| Feature | Status | Notes |
|---|---|---|
| **Unit tests** (TOC §12) | ○ | prerequisite for the Tests panel and for test output in checks |
| Libraries / dependency management (TOC §14) | ○ | how does a customer add a Python package? Currently unanswered. |
| In-product documentation (TOC §15) | ○ | |
| Project references — use datasets across projects (TOC §10) | ◑ | |
| Analyze the impact of changes (TOC §11) | ○ | |

---

## 9. Build order

1. **Fold the pillar page in** — delete `code/page.tsx`, move proposal creation into the application. Nothing else can be judged while two editors exist.
2. **Draft persistence**, then **multi-file tabs**.
3. **The five tabs** — Pull requests and Checks re-homed, Settings created.
4. **Protected branches and the sandbox rule.** A refusal, so it is testable, and it makes the PR tab meaningful.
5. **Problems**, then **File Changes**. These two make the editor feel like an IDE more than anything else here.
6. **Unit tests**, then the **Tests panel**, then test output in the Checks tab.
7. **Tags**, branch checks column, PR column.
8. **Foundry Explorer equivalent**, SQL Scratchpad history and favourites.
9. **Status bar** — last, because it reports on the things above and is meaningless before they exist.

Deferred indefinitely: Debugger, Build helper, IntelliSense over platform types, sub-projects, repository upgrades.

---

## 10. Acceptance tests

- **One editor** — grep for `textarea` under `app/(platform)` and assert `code/page.tsx` is not in the results. Crude, and it cannot pass for the wrong reason.
- **Draft persistence** — open three files, edit two, reload; both drafts survive and the third is clean.
- **Protected branches** — committing directly to a protected branch is refused, and the refusal names the branch. Mutation: remove the check, and the test goes red.
- **Tabs** — each of the five is reachable by URL and by click, and a deep link survives a reload.
- **Problems** — a file with a deliberate syntax error produces a diagnostic at the right line; clicking it moves the cursor there. Fix the error, and the panel empties.
- **File Changes** — an uncommitted edit shows as a diff against the committed version; committing empties the panel.
- **Tests panel** — a failing test is reported as failing. A test suite that cannot fail is the exact thing this repo does not accept.
- **Checks** — a check that fails blocks the merge, and the block names the check.
- **Tags** — a tag pinned to a commit still resolves to that commit after the branch moves on.

---

## 11. What "full integrated VS Code" actually means

**Source:** `docs/pal/foundry_vs-code.pdf` (37 pages) and `foundry_code-workspaces.pdf` (134 pages). Citations in this section are to `vs-code` unless stated.

The request that started this work was *"I want a full integrated VS Code like in Foundry."* Foundry ships a feature-comparison table across its three code surfaces (p.7–8), and it settles the question more precisely than any amount of reasoning about it could.

**Code Repositories — the browser IDE this specification describes — answers "No" to exactly three things:**

| | Code Repositories | VS Code workspaces |
|---|---|---|
| Shell terminal | **No** | Yes (remote host) |
| Keybinding customization | **No** | Yes |
| Public extension support | **N/A** | No — local extension only, if the organization allows it |

And three capabilities run the *other* way — things the browser IDE has that VS Code workspaces do not:

| | Code Repositories | VS Code workspaces |
|---|---|---|
| Java transforms | Yes | **No** |
| SQL integration | Yes | **No** |
| TypeScript function preview | Yes | **No** |

Everything else in the table — Python transform preview, debugger support, unit tests — is **Yes** on both.

The division of labour is stated outright (p.14):

> "**Code Repositories:** A Palantir-built IDE focused on all code-management needs, including editing, version control, change management, and continuous integration. **This is the intended platform tool for pull request reviews and repository management.**"

> "**VS Code:** A VS Code environment deployed on Palantir infrastructure… Provides the familiar VS Code editing experience with automatic environment setup and integration with Foundry resources."

VS Code does not replace the browser IDE in Foundry. It sits beside it for people who want a terminal and their own keybindings, and it sends them back to Code Repositories to review a pull request. Foundry even makes the relationship structural: a repository opens in VS Code via an **Open in VS Code** button in Code Repositories' upper right, and the default can be flipped per user from the **Settings tab** of any repository (p.3) — the tab in §6 of this document.

### What this means for scope

**The three missing things are the entire ask, and they are the expensive part.** A terminal means a container per user with a persistent volume, an authenticating proxy, idle shutdown, and a security model for a shell inside the VPC. That is `docs/decisions/0004-running-customer-code.md` again with a much larger blast radius: the transform runner is a batch task with an empty task role and a fixed entrypoint, and an interactive shell is none of those things.

**So the scope boundary is:** everything in §1–§10 is in. A terminal, keybinding customization and third-party extensions are **out**, and named here so that skipping them is a decision rather than an oversight — consistent with `README.md`'s treatment of Code Workspaces.

This is not a compromise dressed up as a principle. It is what Foundry itself did: shipped a browser IDE with no terminal and no extensions, made it the mandatory surface for reviewing changes, and added VS Code beside it years later for the people who wanted a shell. Delivering §1–§10 delivers the IDE the complaint is actually about. If "I want my own extensions and a terminal" survives that, it is a separate project with its own decision record.

### Acceptance test

There isn't one, and that is the point. The check on this section is negative: **no item in the build order (§9) depends on a terminal, a per-user container, or an extension host.** If one appears, this boundary has moved and should move deliberately.
