# Code Repositories — parity specification

**Source:** `docs/pal/foundry_code-repositories.pdf`, 140 pages. Citations are `(p.13)`.

**Today:** `apps/web/src/components/applications/repository-app.tsx`, full-screen at `/r/{id}`. Tabs: Files (with editor, tabs and Preview), History, Branches, **Pull requests** (§276), **Checks** (§285), Publish, **Settings** (§279). The typed-changes proposal shape is **withdrawn rather than moved** (§290): nothing creates one any more, and the open ones are reviewed on the Models screen beside the transforms they change.

Foundry's own summary of the product: "a web-based integrated development environment (IDE) for writing and collaborating on production-ready code", with all common Git tasks through the web UI, integrated pull-request review, and "IntelliSense, code linting and error checking, and rich help dialogs" (p.2).

**Also delete `app/(platform)/[workspace]/[project]/code/page.tsx`.** 463 lines duplicating this, worse, with a `<textarea className="code-editor">` at line 332. Parity is unreachable while two editors exist, and users currently hit the wrong one.

> **Done (§291), and it took thirteen sections rather than one commit.** The editor is gone and `apps/api/tests/test_one_editor.py` is what keeps it gone — §10's acceptance test, run. The route did not go with it: the page was *emptied and refilled*, because emptying it exposed a hole nobody had noticed. See the second correction below.

> **Correction (§278): it is not only a duplicate, and this reorders the work.** The line above was written from the editor half and is right about that half. Grepping every call it makes turns up **five capabilities that exist nowhere else in the product**:
>
> | only on this page | consequence of deleting it today |
> |---|---|
> | ~~`setReviewPolicy`~~ | **no way to turn code review on or off.** `require_code_review` was *read* in `models/page.tsx` and `repository-app.tsx` and *set* here alone. **Re-homed by §279** into the Settings tab this file has wanted since it was written |
> | ~~`saveChangeSet`~~ | decision 0001's "one genuinely new concept" — several transforms saved as one change — becomes unexpressible. **Succeeded by §289**: several transforms move into a repository as one commit, and a commit is what says they belong together |
> | ~~`codeApi.history`~~ | the project's change-set history. The repository app's History tab is *commits in one repository*, a different list. **Re-homed by §280** onto the Models screen, where the transforms it describes are listed |
> | ~~`changeSet` + `diff`~~ | reading what a change set contained (**§280**, in the same dialog). Its *diffs* stayed here until **§291** moved them into the model's own History dialog as a **Changes** button beside **Code** — the half §280 left behind, and the question a history is usually opened to answer |
> | ~~`codeApi.tree`~~ | the project-wide transform tree, across repositories and directly-authored models alike. **Redundant rather than moved (§291)**: the Models screen lists every transform in the project with the repository and path of each one that is in a repository, which is the same set with more on it. The route stays; the client method is gone, because a second way to ask a question that already has a first way is two things that drift |
>
> Plus creation of the *typed-changes* proposal shape (`code/page.tsx:179`), which §276 could not re-home because it names no repository. **Settled by §290, and not by moving it**: creating one would keep alive a proposal that lands on no branch and can say nothing about what applying it does (§283), for the sake of transforms whose real problem is that they are not files yet. So creation is withdrawn — the answer is §289's move-it-into-a-repository, which holds under the review gate too — and the proposals that already exist are reviewed on the Models screen, because the Pull requests tab's empty state literally said they were "reviewed on the Code screen".
>
> **§289 gave the change set its successor.** `saveChangeSet` was the row §278 called "decision 0001's one genuinely new concept" — *"these three transforms changed together, for one reason"*. A commit says the same thing about a repository's files, so the successor is *adopt them together, then commit together* — and that only works if adopting is together, which it now is. Six adoptions would be six commits and six unrelated moves in the history, and a migration costing six clicks per transform is one a project with forty of them will not do.
>
> So "mostly deletion" is wrong: the page has to be **emptied before it is removed**. The first row was the one that mattered — a security-relevant setting whose only control would have gone with it — and §279 moved it; §280 moved the history and the change-set contents. Two of the rest were made redundant rather than moved, by adoption: a multi-transform change becomes a commit, and a change to a file becomes a commit proposal. **All six are settled as of §291.**
>
> **Second correction (§291): emptying the page turned up a hole the same size.** The file opened with *"There is no 'new repository' button, and its absence is the design"* — true when decision 0001 made the pillar a view over `model_versions`, and false since §94 gave the project real `code_repos`. Grepping for the create call turns up **nothing in `apps/web` at all**: a repository could only be made by calling the API directly, none could be listed anywhere, and this whole application was reachable only by a `/r/{id}` link somebody already had. §275's adopt dialog had already been caught by it, telling people to "create one on the Code screen" — a screen with no such control, which is §290's shape exactly: a pointer at a place that cannot do what it says, unnoticed because every test of it asserts its wording.
>
> So the pillar is not deleted, it is **replaced**: the project's repositories, each opening into this application by resource id, with the create form that never existed. The adopt dialog's sentence is now a link to it, which is what makes the two testable together rather than two sentences kept in agreement by hand. And the sidebar badge counts `code_repos` again — it counted `models`, so a project with one repository and forty transforms showed 40 beside a list of one.

---

## 1. The five tabs (p.10)

| Tab | Status | Notes |
|---|---|---|
| **Code** | ✅ | ours is called Files |
| **Branches** | ✅ | create, list, delete, fast-forward, merge |
| **Pull requests** | ◑ | the tab exists (§276) and shows this repository's commit proposals, reviewed in place. Still ◑ because the *typed-changes* shape belongs to no repository (db 0039's `source_repo_id` is null for it) and so cannot be shown here honestly — **§290 gave it a home on the Models screen**, beside the transforms it changes, and the empty state now points there. Nothing creates that shape any more: §277 and §289 made the answer for a transform outside a repository "move it into one" |
| **Checks** | ◑ | §285: the tab exists, per branch, and a check opens the change it is about. **§296 added p.19's unit-test output**, labelled as what it is: a check belongs to a *proposal* and a test run belongs to a *branch and a working set* (db 0071), so one tab shows two scopes and says so rather than merging them into a list that implies a third. Still ◑ because **the checks half runs on a proposal rather than on a commit** — the schema check asks what the code would do to this project's datasets, and a commit nobody has proposed has not said which change it means |
| **Settings** | ◑ | §279: the tab exists and holds the code-review gate, which §278 found had exactly one control in the product — on the page B.1 deletes. p.20's other groups are §6's ○ rows |

Ours has **History** and **Publish**, which have no Foundry counterpart at tab level. History belongs in the File Changes helper; Publish belongs on the branch. Keep both until their replacements land, then fold them in.

---

## 2. The Code tab

Six labelled regions (p.10–11): In-App Help, Branch Options, Code Editor Options, File Editor, Helper Panels, Status bar.

### 2.1 Branch options

| Feature | Status | Notes |
|---|---|---|
| Branch dropdown | ✅ | |
| Create a sandbox branch from an existing branch | ✅ | |
| **Protected branches cannot be directly edited** | ✅ §284 | "To edit code in your repository, you must work in a sandbox branch" (p.12). **Protection is the review gate, not a second switch:** a repository's default branch is protected exactly when its project requires review. A divergence from Foundry, which protects `main` always — and the same choice §279's Settings tab already states out loud, for the reason §278 gives. A branch with no commits is not protected: the first commit is how a repository starts. §283 is what makes the sandbox not a detour |
| Global branches | ○ | out of scope — see `README.md` on Global Branching |

The protected-branch rule is the one to take seriously. It is what makes the Pull requests tab load-bearing rather than optional, and it is a refusal, so it is testable.

> **§284 built it, and chose the editor over the rule where they disagreed.** The obvious reading is a read-only editor on a protected branch. People open a file, edit it, and think about branches afterwards — an editor that refused the typing would be right about the rule and wrong about the work. So the typing is kept and the commit bar offers a branch that can hold it: *Commit to a new branch from main*, which creates the sandbox, commits there, and switches to it. §214 asks not to take typing you will refuse to keep; nothing here is refused, it just lands somewhere else.

### 2.2 Code editor options (p.13)

| Action | Status | Notes |
|---|---|---|
| **Preview** — run the transform on a sample of input datasets | ◑ SQL only | |
| **Test** — run all unit tests in the current file | ◑ | §295: the Tests panel runs the *repository's* tests, not the current file's. p.13's per-file scoping is the remaining half; pytest takes a path argument, so it is a narrowing of the run rather than a second mechanism |
| **Commit** — commit changes on the sandbox branch, triggering automatic checks | ✅ | |
| **Build** — build output datasets of the current file after checks; no-op if the file produces none | ○ | |
| **Create Pull request** | ◑ via proposals, elsewhere | |
| Merge another branch into the current one | ✅ | |
| **Reset** — discard uncommitted changes, matching the remote branch | ✅ §288 | the button existed and nothing tested it. Since §281 it also has to take the *persisted* draft with it, which was an emergent consequence of writing an empty map rather than anything written down — and it asks first, because it is the one control here that destroys work and it sits beside the one that saves it |
| **Upgrade** — upgrade the branch to latest language versions | ○ (may never apply to us) | |
| New file / folder / **sub-project** | ◑ file only | |

### 2.3 File editor

| Feature | Status | Notes |
|---|---|---|
| Monaco-class editor, self-hosted | ✅ | deliberately not CDN-loaded |
| File tree | ✅ | |
| **Multiple open files with tabs** | ✅ §282 | the open set is **rebuilt, not restored**: a tab for every file with uncommitted work plus the one the link names, so there is no second store to disagree with the drafts. A tab is a view, not a container — closing one keeps the edit, and the button says so |
| **Draft persistence across reload** | ✅ | §281, `localStorage` keyed by repository *and branch* — the same path on two branches is two files |
| IntelliSense over platform types | ○ | Monaco's built-ins only |
| Linting and error checking | ○ | needs §2.4 Problems |
| Command palette on F1 | ○ | (p.11) |
| In-app help walkthrough | ○ | (p.11) |

> **Do persistence before tabs.** Uncommitted edits live in `useState` keyed by path (`repository-app.tsx:206`) with no persistence anywhere. That survives switching files but not a page reload — so a five-tab editor with unsaved work is five ways to lose work at once. Tabs are what make the loss expensive; ship `localStorage` keyed by repository and branch first.
>
> **Both are done (§281, §282), and the order paid twice.** It found a bug tabs would have multiplied — a save effect that deleted the draft it was meant to keep — and it removed the need for a second store here: the strip is derived from the drafts, so it survives a reload without being persisted at all.

### 2.4 Helper panels — nine (p.13–15)

| Panel | Status | Notes |
|---|---|---|
| **Foundry Explorer** | ○ | browse files and folders; select a dataset and Open it. Our equivalent: browse datasets and object types from inside the editor and insert a reference. Small, and disproportionately makes the editor feel connected to the platform. |
| **Problems** | ✅ §286 | "Click on a specific issue listed here to open up the problematic code" — and it does: the click opens the file and puts the caret on the line. **Every rule it reports is one the publish already refuses**; what the panel changes is *when* you hear about it. DuckDB's parser for SQL (`json_serialize_sql`, which parses without running anything and gives a character offset to turn into a line), the declaration reader's own words for Python, plus unknown inputs and two files claiming one output. `ruff`-style style lint is not here and is not the valuable part |
| **Debugger** | ○ | defer — assumes Foundry's transform debugging model |
| **Preview** | ◑ | SQL only; extend to Python |
| **Tests** | ✅ | §293-§295. p.14: *"lets you run those tests and displays their results"*. **A job rather than a request** (db 0071): running unit tests is running customer Python, which decision 0004 confines to a process holding no platform credentials, so the button queues a run and the panel polls. A run with no tests is reported as *no tests*, never as a pass |
| **File Changes** | ✅ §287 | both halves. The diff is built by `code.side_by_side` — the same aligner the review surface uses, because "what changed" is the one question a repository must not have two answers to. The version picker offers the commits that *changed* this file, compared by content address rather than by whether the commit touched anything |
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
| **Checks column** — whether automatic checks passed for a branch | ✅ §300 | **`not run` is its own answer and never a tick.** "Nothing failed" and "everything passed" are the same number, and this is the column somebody glances at before merging |
| **Pull request column** — existing PR state (Open / Closed / Merged) or a Propose changes button | ✅ §300 | p.16-17's *rule*: the button and the state are one slot, and which is there says which situation you are in. Ours names an immutable commit rather than a branch (db 0039), so "this branch's pull request" is a proposal over the commit it is on — and it stops being that the moment somebody commits again, which is the honest reading of our model. The default branch's button is **disabled with the reason on it rather than hidden**, because p.16 makes the button's absence mean "a PR already exists" and hiding it for a second reason would make that sentence untrue. Our three states are translated into p.17's three: `applied` shows as **Merged** |
| Choose a non-default merge target from a dropdown | ◑ |
| View code on a branch without switching to it | ○ |
| Delete a branch | ✅ |
| **Tags** — "like immutable branches", created from a branch head or any commit | ✅ §299 | db 0072. **The immutability is a trigger, not a service rule**: a refusal that lives in a service is one the next writer of an UPDATE does not meet, and a tag whose commit moved is a lie discovered by whoever resolves it, possibly a year later |
| Tag name validation by regex via `repoSettings.json` | ✅ §299 | **The first thing in this platform to read that file**, and the reason to start with it rather than invent a settings table: the rule is about a repository's contents, so it travels with them — a branch that adds it, a commit that relaxes it, and a history saying who changed the convention and when. The repository's own `errorMessage` is what the person typing sees; replacing it with "invalid tag name" would throw away the only part of the refusal that helps. A settings file that will not parse is *ignored*, because a convention that fails closed blocks work while the person who can fix it is elsewhere |

The docs add a note we should honour: "You should not delete any branches that you did not create. This can result in lost work for others" (p.17). Ours should say so at the point of deletion.

---

## 4. Pull requests tab (p.18–19)

| Feature | Status | Notes |
|---|---|---|
| List PRs; switch Open / Closed | ◑ | §276: this repository's open proposals, in the tab. Open-only so far; and an empty tab says *where the others are* — three absences with three remedies (nothing anywhere, typed changes reviewed on the **Models screen** since §290, another repository's) |
| A home for proposals that name **no** repository | ✅ | §290: a proposal whose `source_repo_id` is null belongs to no repository and cannot honestly be listed under one, so it is reviewed on the Models screen beside the transform it changes. Nothing creates them any more (§277, §289), so the section is silent when the list is empty — this exists so B.1 can delete the Code pillar page without stranding an open review |
| Search by title or author | ○ | |
| Create a PR, choosing the base branch | ◑ | the base is the repository's default branch and is not chosen. **Applying a proposal now lands the commit on it (§283)** — before that it published and stopped there, which was invisible while everything was committed to `main` first and would have made §2.1's protected-branch rule unworkable |
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
| Summary of running and completed checks per branch | ✅ §285 |
| Branch selector | ✅ §285 — the application's own, at the top of every tab. A second one inside this tab would be a second answer to "which branch am I looking at" |
| Drill into a specific check | ✅ §285 — it opens the proposal the check belongs to, because that *is* the detail a check has |
| **Unit test output included in checks** | ○ |
| Custom checks (TOC §25) | ○ |

---

## 6. Settings tab (p.20)

"Code authors can configure their personal editor preferences and repository administrators can control the repository's behavior and policies." Most options are admin-only, defaulting to repository owners.

| Setting group | Status | Source |
|---|---|---|
| Personal editor preferences | ○ | p.20 |
| Branch settings — protection, required reviews | ◑ | required reviews are in the tab (§279); protection is §2.1's ○. **A divergence stated on the screen:** Foundry sets required review per repository (`repoSettings.json`), ours per project — the gate has to cover transforms that are in no repository | TOC §28 |
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
| **Unit tests** (TOC §12) | ○ | prerequisite for the Tests panel and for test output in checks. **The chapter is a pointer, not a specification** — p.56 says Code Repositories "support discovering and running unit tests through an integrated helper" and links to per-language docs that are not in `docs/pal/`. What is actually specified is three lines elsewhere: run all tests in the current file (p.13), a Tests helper that runs them and displays results (p.14), and their output in the Checks tab (p.19). Enough to build honestly, and worth saying so rather than implying we are meeting a specification that is not here. **§292 cleared the prerequisite nobody had scoped**: a test's first line is an import, and the declared transform shape was not importable — see the note below |
| Libraries / dependency management (TOC §14) | ○ | how does a customer add a Python package? Currently unanswered. |
| In-product documentation (TOC §15) | ○ | |
| Project references — use datasets across projects (TOC §10) | ◑ | |
| Analyze the impact of changes (TOC §11) | ○ | |

---

## 9. Build order

1. ~~**Fold the pillar page in**~~ — **done (§279, §280, §289, §290, §291)**. The editor is gone, `apps/api/tests/test_one_editor.py` keeps it gone, and the page is now the project's *repositories* — which is what emptying it turned out to require, because nothing in `apps/web` could create or list one. Proposal creation was not moved into the application: the typed-changes shape is **withdrawn** (§290), because the answer for a transform outside a repository is to move it into one. The paragraph below is the record of how the blocker was found and what it actually was. **The original blocker is cleared and a larger one was found (§278): see the correction in the header — five capabilities live only on that page, including the only control for `require_code_review`. The editor half is now redundant; the page cannot go until the other five have somewhere to be.** `README.md` records why: deleting this page strands every model that has never been in a repository, because `code/page.tsx:179` is the only place a *typed-changes* proposal is created and a model with no `source_path` has no commit to publish — so in a review-required project it would have no editable path at all. Verified rather than inherited (`repository-app.tsx:432` only ever creates the publish-a-commit shape). §273 gave a script a way to declare and §274 built adoption, so a model can now become a file, and §276 re-homed the review surface into the repository application. **§290 settled the last row, by withdrawing the typed-changes shape rather than moving it** — the open ones are reviewed on the Models screen; `codeApi.tree` is the only entry left, and the Models screen already lists the same transforms with the path of every one that is in a repository. What remains before the deletion is the deletion.
2. ~~**Draft persistence**, then **multi-file tabs**~~ — **done (§281, §282)**. The order was the point: tabs are what make the loss expensive, and shipping them first would have multiplied a bug rather than found it.
3. ~~**The five tabs**~~ — **done (§276, §279, §285)**. Pull requests and Checks re-homed, Settings created. All five of p.10's tabs now exist, and the two that diverge say so on the screen: review policy is per project rather than per repository (§279), and checks attach to a proposal rather than to a commit (§285).
4. ~~**Protected branches and the sandbox rule.**~~ — **done (§283, §284)**. §283 cleared the prerequisite it would otherwise have broken: applying a proposal lands the commit on the default branch. Protect `main` without that and the first person to use the review path as intended leaves `main` behind forever — the branch everybody opens the repository on would stop describing the repository.
5. ~~**Problems**, then **File Changes**~~ — **done (§286, §287)**. These two make the editor feel like an IDE more than anything else here, and both turned out to be re-pointings rather than new machinery: Problems runs the readers the publish already runs, and File Changes runs the aligner the review already runs.
6. ~~**Unit tests**, then the **Tests panel**, then test output in the Checks tab~~ — **done (§292–§296)**. **§292 built the prerequisite and found a production bug on the way.** A unit test's first line is an import, and the declared transform shape was not importable: `@transform(...)` worked because `python_sandbox.py` bound the name into the namespace it `exec`s a file into, and `import anchor` found no module because none existed on disk. So the decorator was a convention enforced by one exec namespace rather than a contract — and `transform_runner.py`, the container that runs customer Python *in production*, never bound it at all, which meant every repository-authored Python transform answered `NameError` when deployed and ran fine in development. §272's finding a second time, in the half nobody re-checked. `user_api.py` is now one decorator and one set of shape rules, copied into every directory customer code runs in and imported by both runners. What remains of this item: running pytest over a repository's files, then the panel, then the Checks tab.
7. ~~**Tags**, branch checks column, PR column~~ — **done (§299, §300)**. Tags brought p.17's `repoSettings.json` naming convention with them; the two columns arrive in one request, because twenty branches would otherwise be twenty round trips and that is how a column becomes something people wait for rather than glance at.
8. **Foundry Explorer equivalent**, SQL Scratchpad history and favourites.
9. **Status bar** — last, because it reports on the things above and is meaningless before they exist.

Deferred indefinitely: Debugger, Build helper, IntelliSense over platform types, sub-projects, repository upgrades.

---

## 10. Acceptance tests

- **One editor** — grep for `textarea` under `app/(platform)` and assert `code/page.tsx` is not in the results. Crude, and it cannot pass for the wrong reason. **✅ §291**, as `apps/api/tests/test_one_editor.py`, narrowed to `className="code-editor"` — a pillar page may perfectly well hold a description field, and a check that forbids every `<textarea>` is one that gets deleted the first time it is in somebody's way. Paired with a second assertion that the page *can* create and list repositories, because a check that only forbids would pass on a blank page.
- **Draft persistence** — open three files, edit two, reload; both drafts survive and the third is clean.
- **Protected branches** — committing directly to a protected branch is refused, and the refusal names the branch. Mutation: remove the check, and the test goes red. **✅ §284**, and the refusal names the route as well as the branch — a rule that only says no teaches people the product is broken.
- **Tabs** — each of the five is reachable by URL and by click, and a deep link survives a reload.
- **Problems** — a file with a deliberate syntax error produces a diagnostic at the right line; clicking it moves the cursor there. Fix the error, and the panel empties. **✅ §286**, and the panel reads the *working set* rather than the commit, which is the whole reason it is earlier than a publish.
- **File Changes** — an uncommitted edit shows as a diff against the committed version; committing empties the panel. **✅ §287**, and the version picker adds p.14's other half.
- **Tests panel** — a failing test is reported as failing. A test suite that cannot fail is the exact thing this repo does not accept. **✅ §295** (`e2e/test_tests_panel.py`), and the harder half with it: a repository with *no* tests is reported as having none rather than as passing, because "nothing failed" and "everything passed" are the same number. The browser test drives the worker's own op, since the dev stack runs no Dagster daemon — what is skipped is the cron, not the work.
- **Checks** — a check that fails blocks the merge, and the block names the check. Unit-test output is on the tab as of **§296**, and it names the failing tests rather than counting them: "3 failed" sends you to the panel, `tests/test_daily.py::test_totals` sends you to the test.
- **Tags** — a tag pinned to a commit still resolves to that commit after the branch moves on. **✅ §299** (`e2e/test_tags.py`), asserted by moving the branch afterwards and looking again — a test that only made a tag would pass against an implementation that stored a branch name.
- **One transform, two runners** — the same transform through the subprocess path and the container path produces the same table, and the same refusal in the same words. **✅ §298** (`apps/worker/tests/test_execution_parity.py`), borrowed from the Bun team's Zig-to-Rust rewrite: feed both implementations the same input and compare, because *agreement proves nothing but disagreement is a precise investigation queue*. It found one on its first tightening — the row cap was declared twice with two different sentences, and which one a person saw depended on whether ECS was configured.

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
