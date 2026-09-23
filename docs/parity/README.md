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

## The one structural difference we did not choose

**Foundry grants access per resource. This platform grants it per project.**
`rls_can_access_project(project_id)` is the whole of it: `datasets`, `models`
and the rest carry that one policy (db 0006, db 0061), there is no per-dataset
grant table anywhere, and nothing has a marking.

That is a legitimate design — a project *is* the unit people share here — and it
is not being revisited. It is written down because **four rows across two specs
turn on it**, and each was read independently before anybody noticed they were
the same finding (§370, §374, §375, §376 found them one at a time):

| Row | What the difference does to it |
|---|---|
| `code-repositories.md` — **Inaccessible datasets marked rather than hidden** (p.53) | **Unreachable.** A proposal is project-scoped and a dataset inherits the project, so a reviewer who can open the proposal can read every dataset it names. Withdrawn in §370 |
| `code-repositories.md` — **Security: changes to markings on the output** (p.54) | **Not an impact-analysis gap.** Markings are Foundry's per-resource classification; building the diff means building the access model first |
| `ontology.md` §1.2 — **edit-only properties permissioned to one of the backing datasets** (p.113) | **No counterpart.** Datasets carry no permissions of their own to be permissioned *to* — except in the one case below |
| `ontology.md` §5.3 — **Writeback dataset** (`action-types` p.3) | **Decides where it lives.** §324 established a type mapped from two projects genuinely has two homes and this platform refuses to pick one; a writeback dataset meets that question first (§375) |
| `code-repositories.md` — **Project references: use datasets across projects** (TOC §10) | **Refused, in code.** `models._validate_and_set_inputs` requires every input to live in the model's own project — "cross-project reads would be a permission bypass". Foundry's references work because a resource carries its own permission; here the reference *is* the bypass (§381) |

**The exception is the interesting part, and it is the same one each time.** A
type mapped from datasets in *two projects* does have two genuinely different
access answers, which is why §324 makes the Explorer name both and refuse
rather than choose. So the per-resource/per-project difference collapses to
nothing on a single-project type and becomes a real decision on a multi-project
one — and every row above is easy until somebody maps a type across two
projects.

**What this section is for.** Any of these four can be reopened, and reopening
one means answering the access question rather than the row's own question. A
reader who has this in hand will not cost themselves the reading four separate
times, which is what happened to produce it.

---

## Work starts from the resource, never from a view of it

A second cross-cutting fact, smaller than the access one and worth the same
treatment. Three rows across two specifications read as missing features and
were really one shape. **All three are built now** (§385–§387), and the
section stays because what it records is not the gap but how badly the gap was
sized — the estimates were wrong in both directions, and the reason they were
wrong is the reusable part:

| Row | |
|---|---|
| ~~`datasets-lineage.md` — **Manage Builds** (p.9)~~ | **Done (§386).** Two of p.9's three selections were already on the graph — §354's multi-select and the `All upstream` chip — so what was missing was the build over a selection, not the selections |
| ~~`datasets-lineage.md` — **Manage Schedules** (p.10)~~ | **Done (§387)**, reusing §386's plan: which models a selection means is one question |
| ~~`code-repositories.md` — **Build** the current file (p.13–14)~~ | **Done (§385)**, as one unit with p.14's Build helper. `POST /models/{id}/run` existed; what was missing was the control and somewhere for it to report. **Cited to p.16 until §384** — that is the Branches tab; the button is p.13 and its helper panel is p.14 |

Foundry lets you act on a selection *from wherever you are looking* — the
lineage graph, the code editor, the impact panel. Here every build and every
schedule is started from the resource's own page, and the views are views.

**None of these is a missing capability**, which is why each row's note says so
rather than sizing the work as if it were. What they need is a control and a
decision about what a multi-node selection means — "build all datasets between
these two" (p.9) is a path query over edges `services/pipeline.py` already
returns, not a build system. **§369 is the precedent that this is cheap when the
view already exists**: the pipeline review tab put the graph on the review
surface by composing what §14, §364, §365 and §366 had already built.

**The cascade already here runs the other way, and that is the direction to
build in** (§383). `enqueue_due_upstream_models` propagates *downstream* — a
build writes an output version, and whatever reads it with
`trigger_mode='upstream'` fires on its own. Every strategy p.9 names reaches
*upstream or across*. So the cascade is what happens after a build rather than
how a build finds its set, and the three rows are not equally sized: **`Build`
the current file needs no selection question answered at all**, which makes it
the one to build first and the one whose cost the other two should be measured
against — **as one unit with p.14's Build helper**, which §384 found was a
second ○ row for the same feature. p.14 pairs the trigger with a progress view,
and a trigger with nowhere to report progress is §214's control that looks like
it works.

## What the three of them cost, which is the part to keep

| Row | Estimated as | What it was |
|---|---|---|
| **Build** the current file | a build system (§381), then one button (§383) | one module, one panel copied from its neighbour, no new endpoint |
| **Manage Builds** | three strategies to design | two of the three selections were already chips on the graph; the build over a selection was the work |
| **Manage Schedules** | a second control | §386's plan answered "which models", so it was a summary, a box and two buttons |

**Every estimate was made from the row's wording and missed what was already
built.** §191 — check whether the thing exists before writing a second one —
turned each of them from a feature into a composition, and it did so *after*
the note had already been written twice. The habit that would have caught it
earlier is the cheap one: before sizing a row, read the code it would touch.

**§385 built it, and the measurement is the useful part.** It came to one pure
module, one panel copied from the Tests panel next door, and no new endpoint —
because the progress half was already there (`lib/run-logs.ts`, `run-summary.ts`)
and the listing already carried what the panel needed. The two rows that remain
are the ones that *do* have a selection question, and this is the number to
size them against.

---

## A refusal is a row, and its premise expires

**§390's whole cost was reading a sentence this repo had already written.**
`code-repositories.md` §2.2 and §2.4 both sat at ◑ for one reason: a Python
transform could not be previewed, because decision 0004 confines customer
Python to a process holding no platform credentials, *"which takes long enough
to need a job you can watch rather than a request that waits"*.

That sentence is not an argument against building it. It is a **description of
the work** — and by the time it was read again, this repository had built that
exact shape twice: code test runs (§293–§295, db 0071, whose migration header
quotes this very refusal) and the Build panel (§385). The refusal outlived the
thing that made it a refusal, and nothing marked the row when that happened.

| | |
|---|---|
| What the row said | Python previews are refused; a preview would need a job with a status |
| What it cost | a migration, a service, a worker job, a `lib/` module, six panels' worth of nothing — the panel was already there |
| Why it looked bigger | the note named a constraint and stopped, so every re-reading re-derived the constraint and never asked whether the shape it implied existed |

**The reusable part is a question to ask of every refusal in this repo**, not
only parity rows: *what would have to be true for this to be buildable, and is
it true now?* A refusal records a decision made against the platform as it was.
The platform moves; the sentence does not. §191 says check whether a thing
exists before building a second one — this is its other half: check whether the
reason you are not building something still holds.

Two places to look, because both are written in the same voice and neither is
re-read on a schedule: an `HTTPException` whose detail explains *why not* (this
one lived in `routes/repositories.py` for six months), and a `◑` whose note
names a dependency rather than a gap.

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

### Where to check first: the thin rows

**Every row-level error found in §370–§378 was in a short note**, and none was
in a long one. That is not a coincidence worth ignoring: a row somebody wrote a
paragraph about is a row somebody checked, and a row carrying a mark and a
citation is a row nobody has opened since it was written.

So a reading that starts at the top and works down spends its first hour on the
rows least likely to be wrong. Start here instead:

```
python3 - <<'EOF'
import re, glob
rows = []
for f in sorted(glob.glob('docs/parity/*.md')):
    for n, line in enumerate(open(f, encoding='utf-8'), 1):
        m = re.match(r'^\|([^|]+)\|\s*(○|◑)[^|]*\|(.*)\|\s*$', line)
        if m:
            rows.append((len(m.group(3).strip()), f, n, m.group(1).strip()))
for length, f, n, name in sorted(rows)[:20]:
    print(f"{length:5d}  {f}:{n}  {name}")
EOF
```

**The second thing to know about a thin row is that it may not be checkable at
all.** §302's citation test resolves every page a row *cites*; a row citing
nothing passes it vacuously. Measured in §379: **45 of 164 unfinished rows
carry no page or TOC reference**, which is a quarter of the board and a project
rather than an afternoon. **31 of 157 as of §391**, and the two numbers moved
for different reasons — some rows were finished, and some were opened and
written up.

**The empty-note count reached zero in §391**, which is the narrower thing the
snippet above was really measuring. Six rows carried a mark and nothing else;
§388's sorting found them, §389 closed two of them (and found they were one
feature twice — see `code-repositories.md` §2.2), §390 built it, and the last
four were read and written up. A row with a note can be wrong; a row without
one cannot even be argued with, which is why this was worth finishing as its
own thing rather than as a side effect of building.

That is why there is no check enforcing it yet, and the reason is §302's own,
written about `§NNN` references: "enforcing it would mean grandfathering eight
numbers, and a grandfather list is a thing that rots into the reason the check
gets deleted." Forty-five is worse. **The number is the thing to watch**: when
readings have worked it down far enough that the remainder can be fixed rather
than grandfathered, the check becomes worth adding — and it is re-derived by
the same snippet above with `p\.\d+|TOC §\d+` searched for instead of note
length.

§378 is what that found on its first run: **Analyze the impact of changes**,
marked ○ with an empty note, in a document whose §4.1 is that exact capability
and had just been finished. The row and the section it indexes had disagreed
for as long as §4.1 had been building.

**The fix for a duplicated row is a pointer, not a second mark.** §8's rows
index the source's table of contents and several restate a row covered in
detail elsewhere; a pointer cannot drift from what it points at, and two marks
for one capability is this repository's most-found failure sitting in its own
scoreboard.

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
  `components/resource-filter.ts` with unit tests; behaviour in
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

**And the deletion happened (§291), so stage 1 is done.** This paragraph went on saying otherwise for the same reason `data-connection.md`'s item 7 did (§363): the bullet above it was struck through and the prose under it was not, so a reader following the argument reached a sentence telling them to do work that was finished. `code/page.tsx` is the project's repositories now and its header says so in the first line. **The deletion also exposed a hole worth keeping on the record**: nothing in `apps/web` had ever called `POST /repositories`, so every repository in the product had been made by a script and none could be listed anywhere — the old file opened by calling the absence of a "new repository" button *the design*, which had been true under decision 0001 and false since §94. The pillar became what it should have been.

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
| **4** | ~~Code Repositories: five tabs, sandbox branches, multi-file tabs, the nine helper panels~~ — **its nine-item build order is finished (§307)** — which is not the same as the application being finished, and the difference is worth keeping visible: **41 rows in `code-repositories.md` are still ○ or ◑**, each with its reason — a count that moves, so it is re-derived with `grep -cE '^\|[^|]*\|[^|]*(○|◑)' docs/parity/code-repositories.md` rather than trusted. It read 43 until §373 checked it; §4.1 closed in the meantime and nothing updated the number, which is the same failure as the stale line in stage 1 wearing arithmetic instead of prose. §10 lists what each closed item was checked with | Self-contained, and being self-contained is what let it run to completion while stages 2–3 sat still. Nine items, closed in the order that document set: the last two were the Explorer and the SQL Scratchpad (§303–§306), then the status bar (§307) — **last on purpose, because it reports on the other eight and building it last is what let it reuse their answers rather than recompute them.** Four of the nine helper panels stay ○ with reasons on their rows: Debugger and Build assume Foundry's own transform-debugging and build orchestration, Docs is language reference in-product, and Preview is ◑ pending Python. |
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

### Two more ways a browser sweep lies (§414)

Both showed up in one sweep, both produced plausible numbers, and both inflate the score rather than deflate it — which is the dangerous direction, because an inflated score is never investigated.

**A mutant that deletes a line can orphan a binding.** Three of §414's mutants removed the only use of an import or a const. Next's dev server puts an error overlay over the page for an unused binding, the overlay swallows clicks, and tests that never touch the feature go red. Every one of the three was scored *caught* — correctly, as it happens, but for a reason that had nothing to do with the mutation, and a mutant scored right for the wrong reason is a mutant nobody re-examines. Re-run with variants that orphan nothing — `paletteOf(x).slice(0, 0)` rather than `[]`, a condition inverted rather than a line removed, `f(x) && undefined` rather than deleting the field — all three still died, and each then failed exactly the one test written for it. **Change a value; do not delete a line.**

**Run the suite with no mutant at all, against the database the sweep uses.** §414's seam table read "3 failed" for five consecutive mutants, which is a suspicious constant. A control run with the source untouched came back "2 failed": two tests were failing on their own, so every count was one real kill plus two passengers. The two were selecting a widget by clicking it on the canvas immediately after opening the builder — visible is not selectable — and they passed under `fresh-e2e.sh` and failed against the accumulated dev stack, which is §271 again. One of them had been failing since §398 and no sweep had noticed, because a sweep only ever looks at whether the number *changed*.

The control run costs one suite execution and is the only thing that makes a mutant's count mean anything. **A number you never took a baseline for is not a measurement.**

### A mutant belongs in the group that can run it (§416)

The rule above about mtimes has a consequence nobody had written down: **which group a mutant goes in is decided by which file it touches, not by which test would notice it.**

A mutant on `apps/api/` checked by the *browser* suite cannot work. Writing it makes `apps/api/src` newer than the running API, and `e2e/conftest.py` refuses to run — rightly, since it cannot know what the server process loaded. §416 put "the route does not rehydrate" in the seam group because a browser test would have noticed it, and got `NO RESULT` instead of a verdict. Moved to the server group, checked in-process by pytest, it dies immediately.

So: **web files in the seam group, API files in the server group.** The seam group exists for changes Next must rebuild; the server group for changes a pytest process imports fresh. A mutant in the wrong one measures the harness rather than the code.

Two smaller harness rules earned the same way, both in `§415`–`§416`'s sweeps:

- **An anchor that matches twice is not an anchor.** Refuse and say so (`SKIPPED (anchor x2)`) rather than mutating the first match — §416's rehydration line exists in both evaluate routes, and silently taking one would have tested a route the browser suite does not reach.
- **Print the reason, not the tail.** A run that produced no result has a cause, and it is usually one line (`the running API is older than apps/api/src`). Truncating the output to its last few lines threw exactly that line away.
- **Restart the stack between groups.** A sweep's server group writes and restores files under `apps/api/src`, which leaves every one of them newer than the running API — so the seam group that follows is refused by `conftest.py` before a single test runs, and reports the same count for the baseline and every mutant. §422 saw `5 errors in 0.74s` seven times in a row; a `dev-down && dev-up` between the groups is the whole fix. `awake()` does not catch it, because the stack is up and answering — it is simply the wrong build.

### The positive you wait for has to be downstream of the absence (§437)

`e2e/conftest.py`'s `settled` states the rule §318 earned — "every test that asserts an absence waits for a presence first" — and §437 found the half of it that had not been written down: **which presence.**

p.47's toggle takes a star off the published module, so the test waits for the module's frame to render and then asserts the star's count is zero. It passed. It also passed against a mutant that offered the star to every module, because the star waits on a *second* round trip — the module's resource has to resolve before anything can be drawn — and the frame is up well before that. The wait was for a presence, and it was a presence that says nothing about the thing being asserted absent.

The sweep is the only reason this is known. The test was green, the feature worked, and the check was measuring how quickly the page painted.

So: **a presence that renders from different data than the absence is not a guard.** Wait for something the absent thing would have had to overtake — the network going quiet on a page whose requests are bounded, a sibling drawn from the same query, or the state the decision is read from. `e2e/test_module_favourite.py` takes the first of those and says why it is available there.

### A control found by the name it would have if it were right (§440)

§437's rule has a sibling, and §440 walked into it from the other side.

The review surface only puts a `+` on a diff cell that holds a line, because a blank cell is the absence of a line rather than line zero — giving it a number would make it commentable. The test for that asks whether "Comment on live line 4" exists on a proposal that only adds. Removing the guard survived: the blank cell's button *does* appear, and it announces itself as "Comment on live line **null**", so the locator matched nothing and the assertion passed for the wrong reason.

The shape is worth naming because it looks like careful work. Addressing a control by its accessible name is the right habit (§337), and it is exactly what fails here: **a locator built from the correct label cannot see the control when the label is what went wrong.** The assertion was about a name, and the claim was about a count.

The remedy is one more line and is general: **assert the population, not only the absence.** Three live lines and four proposed ones is seven places a comment may hang; the mutant makes it eight, and a count notices whatever the eighth calls itself.

### A `-k` filter is a second list of test names (§449)

§317's rule is that a number you never took a baseline for is not a measurement. §449 found the version of that failure which *does* take a baseline, and still measures nothing.

Its server group narrowed a 56-test file with `-k 'icon or colour or look or default'` to keep the runs short. The baseline came back "5 passed, 51 deselected" — a plausible number — and then **every one of the five mutants survived**, including one that deleted the assignment entirely. Applied by hand, the same mutant killed a test immediately.

The filter had selected five tests. Five *other* tests: not one of the new ones has `icon`, `colour`, `look` or `default` anywhere in its name, and the words matched elsewhere in the file. The group was running, passing, and never touching the code under test.

The shape is worth naming because narrowing is the obvious thing to do when a suite is slow, and the filter is written once and then never read again while the test names move underneath it. **A `-k` expression is a second list of the tests you meant**, kept in step with the first by nobody.

So: **name the file, not a filter** — and if a group is genuinely too slow for that, name the tests with `::` so a rename is an error rather than a silent deselection. The tell is cheap and worth looking for: if the mutants' failure counts never move off the baseline's, check what was selected before believing the score.

### A summary line that carries a duration is never equal to itself (§450)

§317's rule is to take a baseline, and §449's is that a `-k` filter is a second
list of test names. §450 found the failure one step further in: the baseline was
taken, the whole file was named, the groups were split correctly — and the
*comparison* was wrong.

The harness read pytest's last summary line and scored a mutant `caught` when it
differed from the baseline's. That line ends `in 52.47s`, and no two runs of
anything take the same time. So **every** pytest mutant differed from the
baseline, and every one was scored caught — including two that changed nothing
at all. The tell was not in the verdict column, which read clean; it was that
`73 passed` appeared beside the word `caught`, which is the baseline's own
number.

Two of that sweep's adversarial mutants were survivors reported as kills, and
both turned out to be unreachable guards worth deleting — so the bug hid exactly
the thing the adversarial pass exists to find. The vitest group was unaffected
only by luck: its tally line (`Tests  67 passed (67)`) has no duration in it.

So: **compare the counts, not the line.** `summary.split(" in ")[0]` is the
whole fix. And the general form is the one this page keeps arriving at from new
directions — a verdict computed from a value that changes on its own is not a
verdict, and the way to tell is to check that a mutant you know is harmless
actually survives.

### A run that errored has no verdict (§451)

§450's rule was that a verdict must compare the counts rather than a line that
carries a duration. §451 found the other half of the same mistake: a comparison
of counts calls `5 errors` different from `5 passed`, and scores the mutant
**caught**.

It is nothing of the kind — the suite did not run. One of §451's seam mutants
reported `5 errors` inside its group and was a clean `1 failed, 4 passed` when
re-run on its own a minute later; the group's restore had left the dev server
mid-rebuild. Both numbers "differ from the baseline", and only one of them is a
result.

So the harness reads the summary for the word *error* and prints `NO RESULT`,
which is what §416's rule about groups already asks for in the other direction.
The general form is the one this page keeps finding from new angles: **a verdict
is a comparison of two things that ran.** Anything else is arithmetic on
noise — and it always inflates the score, which is the direction nobody
investigates.

### A clean first pass means the list came from the test file (§350, §450)

Recorded on §350's row and worth having here, because §450 walked into it again:
its three groups scored 22 of 22, which is not a result to celebrate but a
question to answer. The adversarial pass that followed — seven mutants written
by reading the *source* and poking at the branches a reader would doubt — found
three unreachable guards in code written that same afternoon. Two were in a
function whose every reachable line was already covered.

### A sweep that shares a backup name corrupts the tree (§429)

Every sweep in this repository saves each file it will mutate and copies the saved bytes back after each run. §429's saved them as `pul-<basename>.orig`, and its two server files were `apps/api/src/services/code.py` and `apps/api/src/routes/code.py` — **two different files with one name.** The second backup overwrote the first, and the restore then wrote the service's bytes into the route. The working tree was corrupt from the first mutant onwards.

What is worth recording is how close it came to being invisible. The corruption does not fail loudly: the mutants that followed reported `1 error in 1.67s` where the baseline said `3 passed`, which reads like a mutant that broke an import — exactly the kind of number a sweep produces all the time. It was caught by opening the file, not by reading the log, and a sweep whose later mutants had happened to still pass would have left a route file replaced by a service file with a green column beside it.

So: **key the backup by the whole path, and assert the names are distinct before writing any of them.** A one-line `assert len({backup_name(p) for p in FILES}) == len(FILES)` is the whole fix, and it is worth having in every sweep rather than in the ones whose files happen to collide — this repository has several pairs (`routes/models.py` and `services/models.py`, `routes/objects.py` and `services/objects.py`), so the next sweep to touch a route and its service hits it too.

A sweep is a program that edits the source tree. It deserves the same rule as any other: **a restore that cannot be wrong is worth more than a result that can.**

### A test that walks a table cannot check the table (§428)

§428's hint table — the words that find a tab, "diff" for Pull requests, "log" for History — was checked by a test that iterated it: for every tab, for every hint, assert the hint finds the tab. It reads like thorough coverage and it is worth nothing. A mutant that deleted `"editor"` from the table deleted the test for `"editor"` along with it, and the suite came back **green with one fewer test**.

The tell is in the denominator, not the failures: `71 passed (71)` became `70 passed (70)`. A sweep that only asks "did the count of failures change" cannot see that, which is why the rule is **read the total as well** — a mutant that moves the denominator has eaten a check rather than passed one.

The fix is to write the table out again in the test, as a list of `[word, tab]` pairs, plus one assertion that the pairs cover every tab. It is duplication, and the duplication is the point: the source says what the words are and the test says what they must still be, so deleting one is a disagreement rather than a quiet subtraction. **A check generated from the thing it checks is not a check.**
