# Parity specification

**The goal changed.** Earlier roadmap documents treated Foundry as a reference to borrow from. This one treats it as a specification to meet — for a deliberately small set of applications.

> "This isn't a full replication of Foundry, but I want full parity/replication in a few applications. Foundry without all the bloat."

Everything here follows from that sentence: **full** inside the boundary, **nothing** outside it.

---

## In scope

| Application | Spec | Foundry source |
|---|---|---|
| Workshop — core builder and the full widget library | [`workshop.md`](workshop.md) | `foundry_workshop.pdf`, 718 pp |
| Code Repositories | [`code-repositories.md`](code-repositories.md) | `foundry_code-repositories.pdf`, 140 pp |
| Ontology — Manager, Object Explorer, Object Views, Action Types | [`ontology.md`](ontology.md) | `foundry_ontology*.pdf`, `foundry_object-*.pdf`, `foundry_action-types.pdf` |
| Datasets and Lineage | [`datasets-lineage.md`](datasets-lineage.md) | `foundry_dataset-preview.pdf`, `foundry_data-lineage.pdf` |
| Data Connection | [`data-connection.md`](data-connection.md) | `foundry_data-connection.pdf`, 417 pp |

## Explicitly out of scope

Named so that skipping them is a decision rather than an omission.

**Whole products:** Pipeline Builder, Slate, Contour, Quiver, Insight, Code Workbook, Code Workspaces, Notepad, Fusion, Vertex, Machinery, Foundry Rules, HyperAuto, Linter, Marketplace, DevOps, Carbon, Solution Designer, Pilot, Developer Console, Modeling Objectives, Model Assets.

**Within Workshop:** Scenarios, Mobile, AIP widgets (AIP Analyst, AIP Chatbot, AIP Generated Content), and anything else AIP-branded.

**Twenty widgets, named individually on their rows in `workshop.md` §10 and marked ⊘.** A whole product is easy to put out of scope in one line; a widget inside an application that *is* in scope is not, so each one carries its own reason. They fall into five kinds, and only the first is a judgement about the widget itself:

- **The spec is somebody else's.** Vega Chart is eleven pages pointing at the Vega and Vega-Lite grammars — implementing it is implementing Vega, and "we have a Vega Chart" would be a claim about a grammar rather than about Workshop.
- **The source is one sentence in an overview list, with no section behind it.** Status Tracker, Waterfall Chart, Header text and Comments. Building from a sentence means inventing the specification and then claiming parity against it. §215's Object Selector was built on exactly one such sentence, so this is a threshold rather than a rule — but a sentence like "enables collaboration in a Workshop module" describes nothing to build.
- **They rest on a Foundry service this platform does not have.** Resource List and Linked Compass Resources need Compass; Observability Chart needs platform telemetry; Data Freshness needs per-datasource index times; Edit History needs per-object-type edit tracking; Audio and Transcription Display and Audio Recorder need the `media reference` property type. Each would be a platform unit wearing a widget's clothes. **Spreadsheet Display needed that same property type and was deliberately *not* here** — it stayed ○ through §224, because "blocked on something we have not built" and "decided against" are different states and the mark is what keeps them apart. §235 moved it, which is the distinction doing its job rather than failing: the property type is still unbuilt, and the widget is now unwanted as well, so the row changed for a reason it can state.
- **A scope call, plainly.** PDF Viewer, Video Display and Image Annotation have real pages and real specifications, and are not being built. Saying so is the difference between a boundary and a gap.
- **The set is enough — the five §235 added, on the user's call.** Gantt Chart, Free-form Analysis, Action Log Timeline, Media Uploader and Spreadsheet Display. This kind is not a judgement about any of them individually; it is a judgement about the *set*, and it is the only kind here that is. The widgets that exist cover the applications this platform is for. The condition attached to the call was that they all work, which is what the mutation testing and the three green suites are for — §235 ran all of them before marking anything, because "these are enough" is a claim about the built ones as much as about the dropped ones. Four of the five also carried a build-order estimate that reading the pages contradicted, every one under-counting; that did not cause the decision, but a scope call made against the clause rather than the pages would have been made against the wrong number.

The mark is what makes this reversible: `grep '⊘' docs/parity/*.md` is the whole list, and nothing was deleted to produce it.

**Platform-wide:** AIP Assist, Approvals, Checkpoint, Cipher, Sensitive Data Scanner, Data Lifetime, Walkthroughs, Training, OSDK, Compute Modules, MCP servers, Global Branching.

Two of these deserve a note rather than a line. **Global Branching** — one branch spanning a pipeline, an ontology and a Workshop module — is what makes Foundry's per-application branching cohere (`foundry-branching` p.2–3). We are not building it, but every branching decision inside these five specs should leave the door open. **Code Workspaces** is explicitly *backed by* Code Repositories (`code-workspaces` p.2–3), so it is a layer on top of in-scope work, not a competitor to it.

---

## The one hard dependency we did not choose

**Functions.** It is out of scope as an authoring application, but Workshop parity reaches into it repeatedly:

- function-backed columns in Object Table (`workshop` p.221)
- function-backed layers in Chart XY (`workshop` p.278)
- Functions on Objects as a variable source (`workshop`, FOO section)
- function-backed actions (`action-types` §15–17)

Foundry describes Functions as logic "executed on the server side in an isolated environment" with "first-class support for authoring logic based on the Ontology" (`functions` p.2). We already run customer Python in an isolated container with an empty task role (`docs/decisions/0004-running-customer-code.md`) — the execution half exists.

**Decision required.** Either accept that these specific widget features stay unimplemented and mark them so, or bring a minimal Functions runtime into scope: a TypeScript or Python function, registered against the ontology, callable from a widget. The specs below assume **the minimal runtime**, and every line that depends on it is tagged `[fn]` so the decision can be reversed by grep.

---

## How to read the checklists

Each spec is a table of Foundry features with a status and a citation.

| Mark | Meaning |
|---|---|
| ✅ | at parity — the feature exists and behaves as documented |
| ◑ | partial — exists but materially narrower than the documented behaviour; the gap is named |
| ○ | absent — not built, and still on the target |
| ⊘ | **out of scope** — deliberately not building it, with the reason on the row |
| `[fn]` | depends on the Functions runtime decision above |
| `[?]` | Foundry behaviour not fully determinable from `docs/pal/` — needs a judgement call, flagged rather than guessed |

Citations are `(workshop p.65)` = `docs/pal/foundry_workshop.pdf`, page 65.

### A caveat that applies to every page here

These are the docs, not the product. The checklists are reliable about **what exists**. They are not reliable about **how it feels** — spacing, density, animation, the hundred decisions that make an interface feel finished. Nobody in this loop has used Foundry. Parity as specified here gets the feature set right; matching the feel needs either screenshots, a trial enrollment, or an explicit decision to diverge.

One source gap is worth naming up front: **Object Explorer has no dedicated PDF in `docs/pal/`**. Its behaviour is reconstructed from the standard Object View documentation (`object-views` p.9–11), the application reference (`getting-started` p.48), and scattered mentions. That section of `ontology.md` is the least well-sourced in this set.

---

## Sequencing

Parity is a large target, so the order matters more than usual. Four principles:

1. **Structural before decorative.** A missing section layout blocks applications; a missing Waterfall chart annoys one person.
2. **Unifying mechanisms first.** External IDs alone close three separate Workshop gaps (see `workshop.md` §C4). Do those before the things that depend on them.
3. **Foundation before surface.** Object Views are Workshop modules; Workshop's object widgets need the ontology behind them. Ontology work is upstream of both.
4. **The long tail last, and in public.** The last 30 widgets are individually cheap and collectively enormous. They should be visibly tracked so progress is legible, and they should never block anything else.

### Stages

| Stage | Contents | Why here |
|---|---|---|
| **0** | ~~Make CI actually run~~ — **done, PR #52; the guarantee re-earned in §271** | It had already been running, and had been **red for nineteen consecutive runs** on a single cause: CI never set `PLATFORM_APP_PASSWORD`, so `platform_app` kept its placeholder password while everything connected as it with `devpass`. Four jobs now green — and "now" has a date on it, because between §258 and §271 the browser job was red on `main` for ten consecutive merges with an identical 28-failure set, and this row went on claiming otherwise. §271 fixed all 28. **A green-CI claim is a claim about the last run, not a property of the repo**, so read this row as saying what was true when it was last checked. |
| **1** | Navigation (phase-3 §A) — Workshop onto `/r/{id}`, pillar pages become filtered views, ~~delete the duplicate editor~~ **(done, §291)** | "Mostly deletion" was wrong twice over, and the record below says how. The editor is gone; the page it lived on became the project's repositories, because emptying it exposed that nothing in the product could create or list one. |

#### Stage 1 progress

- **Workshop onto `/r/{id}`** — done.
- **Pillar pages become filtered views** — the mechanism is in: the resource
  browser's kind filter lives in the URL (`?kind=dataset&kind=model`), so a
  pillar page can *be* the browser with a filter applied. Rules in
  `resource-filter.ts` with unit tests; behaviour in
  `e2e/test_resource_filter.py`. Pointing each pillar page at it is the
  remaining half, and it is not uniform: `dataset`, `object_type`,
  `canvas_app` and `code_repo` have applications to open into, while `model`
  and `connection` do not yet, so their pages cannot become pure lists.
- **Delete the duplicate editor** — **done (§291)**. It was blocked for thirteen sections; the record below is what the blocker actually was, and what deleting it turned up.

#### Stage 1 is not as deletable as it looked

Two of the three parts are straightforward. The third is blocked, and the
blocker is worth stating because it reorders the plan.

**"Delete the duplicate editor" cannot happen until models live in
repositories** — which is stage 2's B.1, not stage 1. The reason is the review
gate, and it is enforced server-side on both write paths: a direct model edit
is refused when `require_code_review` is set (`services/models.py:476`), and so
is publishing a repository commit (`services/transform_publish.py:202`, which
refuses it explicitly so that "a gate with a documented way round it" cannot be
had by putting the code in a repository first).

So in a review-required project, a transform can only be changed by a
**proposal**, and proposals come in two shapes: typed changes, and *publish
this commit*. The typed-changes shape is created in exactly one place —
`code/page.tsx:179` — and a model with no `source_path` has no repository
commit to publish. Deleting that page therefore strands every non-repository
model in a review-required project with no way to change it at all. Nothing
would error; the capability would simply be gone.

The order that follows: **B.1 first, then the deletion.** Until then the Code
pillar keeps its editor, and the honest description of it is not "a duplicate"
but "the only authoring surface for transforms that are not yet files".

**Progress, and the blocker re-verified rather than inherited (§272–§274).**
Before building on this paragraph its central claim was checked: `.propose(` is
called in exactly two places, and `repository-app.tsx:432` only ever sends the
`source_repo_id`/`source_commit_id` shape, so `code/page.tsx:179` really is the
sole creator of typed-changes proposals. The paragraph holds.

Asking what a model *becomes* in a repository then turned up two defects on the
way, both merged: the Python transform shape decision 0004 prints could not run
at all (§272), and a script — which is what every model authored in the Models
editor is — had no way to declare, so it could not live in a repository under
any name (§273). §274 built **adoption**: a model becomes a file, one
transaction, with the declaration written from what the model already says.

**The blocker is cleared, and not the way this paragraph predicted (§289–§290).**
It said what remained was *moving* typed-changes proposal creation into the
application. That turned out to be the wrong answer: it would have kept a second
shape of proposal alive — one that names no repository, so it lands on no
branch and can say nothing about what applying it moves (§283) — for the sake of
transforms whose real problem is that they are not files yet.

So creation is **withdrawn** rather than moved. §274 made a transform into a
file, §289 made that a batch (which is what the change set becomes: *these six
changed together, for one reason*), and the answer for a transform outside a
repository is now to move it into one and change the file. The path holds in a
review-required project too, which is the case that made this a blocker:
adopting into a protected default branch is refused by §284's rule and the
message names the remedy, so the move goes onto a sandbox branch and the commit
is proposed like any other.

What §290 then had to do was **not** strand the proposals that already exist.
They are reviewed on the Models screen, beside the transforms they change —
`e2e/test_direct_proposals.py` — because a proposal belonging to no repository
cannot honestly be listed under one, and the Pull requests tab's empty state
literally said they were "reviewed on the Code screen", a sentence the deletion
would have turned into a lie with nothing to notice.

What remains before the deletion is the deletion.

#### Stage 2 progress

- **External IDs and the module interface** — done (`STATUS.md` §116). A
  variable carries an external ID and an interface block; an embed maps host
  variables onto a child's interface; the same external ID seeds a variable
  from the URL. Foundry's precedence rule is implemented rather than noted, so
  a mapped variable ignores the child's own default and derivation.
  `e2e/test_module_interface.py` asks one module about two of the three
  consumers on purpose.
- **State saving is the third consumer and is now built** (§153). It keys on
  the same external ID (p.202–203), and the prediction held: no new naming
  mechanism was needed. What it *did* need was storage (db 0048) and one
  asymmetry worth recording — routing requires interface membership because
  `seedFromQuery` only reads interface variables, and state saving does not,
  because a state is read back by the module itself.
- **The three widget-configuration tabs** — done (`STATUS.md` §117). Widget
  setup / Metadata / Display, named as p.65–68 names them. The raw JSON editor
  is the piece worth having early: every widget option Foundry documents and we
  have not built a form for is now survivable rather than blocking, which
  matters most for stage 5's long tail.
- **The six section layouts** — done (`STATUS.md` §118). Flow and Toolbar leave
  their children's natural size alone, which is what separates a Toolbar from a
  Columns section. Loop renders one embedded module per object, using §116's
  interface mapping per row rather than a second mechanism; looping an *array*
  is refused until there is a typed-array kind, and **p.132's property sorts
  are built (§231)** — this line said they were refused for decision 0006's
  reason, which §221 removed eight units earlier and nobody noticed, one of the
  six copies `STATUS.md` §230 found.
- **The vertical header** — done (`STATUS.md` §119). Orientation, width,
  height, collapsibility and collapsed-by-default, plus the one part of a
  header that is a rule rather than styling: collapsed, only Button and Tabs
  render, as glyphs with their labels dropped (p.49). There is no icon library,
  so an icon is one or two characters and falls back to an initial — the
  behaviour is faithful, the picker is not built.
- **The versions dialog** — done (`STATUS.md` §120). Timestamp, editor name and
  description per version; publish a *named* version; view one read-only with
  the conditional warning banner; revert as a new version with a generated
  description; and p.192's two settings.
- **Stage 2 is done**, the Widget setup tab included. §178 to §182 made it
  variables-first — p.65's Inputs → Configuration → Outputs, with p.66's
  progressive disclosure — across **all fifteen** variable-bearing panels,
  starting with p.65-67's own worked example. (The count read "eighteen" until
  §181, which counted six panels that bind no variable at all.) The last two,
  Map and Chart, were a restructure rather than a wrap: their inputs and
  configuration are interleaved inside `source` conditionals, and reading them
  closely enough to unpick that turned up four controls that were disabled
  with their options already loaded (`STATUS.md` §182). §6's **Changelog
  panel** (p.193) is finished too as of §183 — the JSON diff and the visual
  hierarchy joined §132's five change kinds — which clears the prerequisite
  p.193 names for module branching. What branching still needs is its own
  model: two heads of one module, and a rule for what a conflict is.
| **2** | Workshop structural: the three config tabs, six section layouts, vertical header, ~~external IDs~~ **done, §116**, versions dialog | The mechanisms everything else hangs off. External IDs in particular collapse three roadmap items into one. |
| **3** | Ontology depth: property types and formatting, link types, action types, Object Views | Upstream of Workshop's object widgets. Object Views are the highest value per unit of work in the whole set. |
| **4** | ~~Code Repositories: five tabs, sandbox branches, multi-file tabs, the nine helper panels~~ — **its nine-item build order is finished (§307)** — which is not the same as the application being finished, and the difference is worth keeping visible: **43 rows in `code-repositories.md` are still ○ or ◑**, each with its reason. §10 lists what each closed item was checked with | Self-contained, and being self-contained is what let it run to completion while stages 2–3 sat still. Nine items, closed in the order that document set: the last two were the Explorer and the SQL Scratchpad (§303–§306), then the status bar (§307) — **last on purpose, because it reports on the other eight and building it last is what let it reuse their answers rather than recompute them.** Four of the nine helper panels stay ○ with reasons on their rows: Debugger and Build assume Foundry's own transform-debugging and build orchestration, Docs is language reference in-product, and Preview is ◑ pending Python. |
| **5** | Widget library, in the priority order given in `workshop.md` | Long, cheap, parallel, and it should never block. |
| **6** | Datasets and Lineage, then Data Connection | Lowest felt urgency; Data Connection is mostly plumbing users rarely see. |

Stage 4 is deliberately parallel-shaped. Stages 2 and 3 are not — they have a real dependency between them.

---

## What "done" means

The repo's standard is that **a check you cannot make fail is not a check** (`STATUS.md` §106, §111, §113, §114 — six green tests that could not reach the condition they named). Parity makes that standard harder and more important, because "we have a Timeline widget" is easy to assert and hard to mean.

Each spec ends with the acceptance tests for its area. Two rules for all of them:

- A widget is not done because it renders. It is done when its **documented configuration options** work, and when a test drives one of them and fails if it is removed.
- A feature that Foundry documents as refusing something is not done until **our version refuses it too**, with a test that removes the refusal and goes red.

### And the same standard applied to these documents (§302)

The rule above was held over the code and not over the pages holding the code to it. Five specifications, 204 rows marked ✅, 837 page citations into `docs/pal/` — and **nothing had ever opened one**. A test could be renamed, a PDF replaced with a longer edition, a page number mistyped, and every table would go on saying exactly what it said before.

`apps/api/tests/test_parity_marks.py` resolves what is resolvable, on every run of the API suite:

- a backticked path on a ✅ row is a file that exists;
- the page counts these headers declare are the PDFs' real lengths;
- every cited page exists in a source the citing document names.

It found one: `ontology.md` cited p.582 and p.583 against a source set whose longest PDF is 274 pages. The pages are real and the sentence about them is right — they are `foundry_workshop.pdf`'s, and they do name Map, Metric Card and Object Table — but a reader following the citation as written would have opened a 274-page PDF and found nothing. Qualified, and the source named in the header so it resolves.

**Three limits, stated rather than discovered later.** It checks *names*, not behaviour: a row citing `e2e/test_tags.py` is checked as far as the file being there, and whether it tests tags was §299's mutation run to answer. An unqualified citation in a multi-source document only has to fit that document's *longest* source, which is why the qualified form exists and why `ontology.md`'s header asks for it. And **`§NNN` is deliberately not checked** — a section number is a reference into a narrative, eleven of the ones cited by finished rows appear in no source file and eight in no commit message either, and enforcing it would mean grandfathering those eight. A grandfather list is the thing a check rots into before someone deletes it.

**The rot runs both ways, and only one way is checkable.** §307 found two rows in `code-repositories.md` marked ○ for features that had been built for eleven and twelve units — test output in the Checks tab (§296) and unit tests themselves (§292–§296). Four other places in that same document cited §296 for the first of them the whole time.

`test_parity_marks.py` cannot catch this and never will: it resolves what a *finished* row cites, and a row claiming a feature is absent cites nothing to resolve. A ✅ that is not true has a citation to check; a ○ that is not true has nothing. So the asymmetry is worth stating rather than being surprised by twice: **a row that says something is missing is the kind that goes quietly wrong**, because nobody re-reads a row about work they are not doing — and the cost is real, since these rows are what decides what gets built next. The remedy is not another check, it is re-reading the ○ rows of a section when it closes, which is what §307 did. **The rest of them were then read too** — every ○ row in `ontology.md`, `datasets-lineage.md` and `data-connection.md`, against the code — and nothing else was stale. Where a row's words appear in the codebase it is a different feature wearing the same word: `histogram` is object aggregation and a canvas widget, not the lineage graph's panel; `writeback` is a webhook rule, not Foundry's writeback dataset; `favourite` is §306's scratchpad, not a starred object. So the count is three, and it is bounded rather than open.

A ✅ row should say what made it true. Not every one does — the earliest predate the convention — so the rule is a floor rather than a requirement, and the floor is what stops the habit quietly ending.

### The harness has to be checked too (§316–§317)

Mutation testing is what makes "a check you cannot make fail is not a check" enforceable, which makes the harness itself a check — and it went wrong in both directions inside one afternoon, each time scoring every browser mutant identically and each time looking like a clean result.

The harness restores a mutated file with `git show HEAD:<path>`, which writes identical bytes and a **new mtime**. `e2e/conftest.py` refuses to run when anything under `apps/api/src` is newer than the running API process — rightly, since it cannot know what the process loaded. So after a service sweep, every browser mutant died on that guard and was reported **caught**, having never reached a browser. Three units' browser verdicts were recorded that way.

The obvious fix — put the mtime back after every restore — is the same mistake in the other direction, and it cost a full re-run to find. Next's watcher decides what to recompile from the mtime, so a *web* mutant written with the old one is never built: the browser tests the original page and every mutant is reported **survived**, equally having proved nothing. §313's three browser mutants came back 3/3 caught under the first bug and 0/3 under the second, with the code identical both times.

The rule that holds: freeze the mtime only for `apps/api/`, where nothing hot-reloads and the mutants are checked in-process by pytest; let every web file's mtime move, because moving it is how the change is seen at all. Both failure modes were silent and both produced a plausible number, which is the same shape as everything else on this page — **a verdict you cannot make wrong is not a verdict**, and the way to tell is to check that a mutant you know is lethal actually kills.

The note lives in `e2e/conftest.py` beside the guard, where the next person to write a harness will meet it.
