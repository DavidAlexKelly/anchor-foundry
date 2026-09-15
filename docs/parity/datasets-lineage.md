# Datasets and Lineage — parity specification

**Covers:** Dataset Preview, Data Lineage.

**Sources:** `foundry_dataset-preview.pdf` (39 pp), `foundry_data-lineage.pdf` (89 pp).

**Today:** `components/applications/dataset-app.tsx` with tabs Preview, Schema, History, Lineage, Details; dataset time travel at §56; lineage graph at §14.

We are closer to parity here than anywhere else. Dataset Preview is a 39-page product and our application already has the right five tabs.

---

## 1. Dataset Preview

Foundry's layout is header, information panel, tab views, preview table (`dataset-preview` p.2).

### 1.1 Header

| Feature | Status |
|---|---|
| Name, display name, location, selected branch | ◑ — no branch selector |
| Share, move, rename | ○ |

### 1.2 Information panel — three sections (p.3)

| Section | Feature | Status |
|---|---|---|
| **About** | created / updated time and user | ✅ |
| | table size | ◑ |
| | tools and input datasets used to create the data | ◑ via Lineage |
| | tags | ○ |
| | **Edit schema** — infer a schema for CSV and JSON | ○ |
| | parsing options: drop jagged rows, change encoding, add file path / byte offset / import timestamp / row number columns | ○ |
| **Columns** | type, description, **data stats — null percentage, distributions, samples** | ✅ §8 profiling |
| **Schedules** | configured build schedules | ◑ |

### 1.3 Tabs

| Tab | Feature | Status |
|---|---|---|
| **Preview** | sample table with light interaction over the full dataset | ✅ |
| **History** | job/build list with statuses and durations | ✅ |
| | **Summary view** — aggregated job statuses over time | ○ |
| | job detail: progress, specification, **build logs**, files, resulting schema | ◑ |
| | **Create a branch from a historical transaction** | ○ — we have time travel (§56); this is the branch-from-a-point action (p.4) |
| **Details** | technical information and administrative operations | ✅ |
| **Schema** | schema view and edit | ✅ |

Streaming datasets add a Streaming tab and change History to appear only in Archive view (p.4). Out of scope — we have no streaming.

### 1.4 CSV parsing (TOC §3)

A whole documented sub-area we have nothing for. Worth a look before anyone hand-rolls CSV options a third time.

---

## 2. Data Lineage

Foundry's navigation has six regions (`data-lineage` p.6): lineage graph, branch settings, side panel, node details panel, graph tools, save graph.

### 2.1 Graph

| Feature | Status | Notes |
|---|---|---|
| Interactive graph of resources | ✅ | §14 |
| **Expand a node's related resources** via arrows on either side | ○ | (p.7) |
| Auto-layout, with manual drag and a **Layout all nodes** reset | ◑ | |
| Pan mode and **drag-select mode**; multi-select with Ctrl/Cmd+click | ○ | (p.7) |
| **Node colouring** | ○ | TOC §9 |
| Graph elements reference (shapes and states) | ○ | TOC §10 |

### 2.2 Side panel

| Helper | Status | Notes |
|---|---|---|
| **Search & Browse** — free-text or tree, add resources to the graph, add all results with or without sub-folders, advanced filters and sort | ○ | (p.8) |
| **Properties and Histogram** | ○ | |
| **Manage Builds** | ○ | |
| **Manage Schedules** | ◑ | |
| **Related Artifacts** | ○ | |

### 2.3 Beyond the graph

| Feature | Status | Notes |
|---|---|---|
| **Branch selector, with fallback branches in order** when a branch does not exist for a resource | ○ | (p.8) — a genuinely subtle behaviour worth copying exactly |
| View dataset preview and logic from the graph | ◑ | TOC §11 |
| **View build timeline** | ○ | TOC §12 |
| **Understand out-of-date datasets** | ◑ §352 | (TOC §13; `data-lineage` p.51) — p.51 asks three questions and **two of them are answerable here; the third is named rather than guessed at**. "Is my dataset build failing?" was already on the graph, as a model's `last_run_status`. "Is there an upstream dataset that hasn't built and isn't up to date?" is what §352 built. "Have we received up-to-date data from the source?" needs an expectation about how often data *arrives*, and this platform has nowhere to record one — inventing a freshness target would put a number on the screen that nothing stands behind, so an uploaded dataset with nothing feeding it reports nothing. **Times, not version numbers**: two datasets' version counters are independent, so "input at v7, output at v3" says nothing at all; when each last *became what it is* is the comparison that means something. `built_at` is the latest version's `created_at` and deliberately **not** `datasets.updated_at`, because a rename touches that one and a rename is not a build — comparing those would mark everything downstream of a renamed dataset stale, which is a warning nobody can act on. **Two reasons rather than one flag**, which is p.51's own two questions: `input_is_newer` names *this* dataset as the thing to rebuild, `upstream_is_out_of_date` says the thing to rebuild is further up — a single "out of date" would have somebody rebuilding the wrong one and watching it come back stale. The direct reason wins when both apply, because it is the more specific. **Unbuilt is not stale**: a model that has never run has an output with no version, and reporting that as out of date would put a warning on every pipeline the moment it is drawn — one says press run, the other says press run *again*. The downstream walk is breadth-first with a `seen` set, so a cycle terminates rather than spinning (`_layer` reports cycles; it does not remove them). **Not on the Mermaid export**, and that is a decision rather than an omission: `lineage_for_dataset` emits names only and carries no node attributes at all, so there is nowhere for a staleness flag to go — §351's "check both builders" rule asked the question and this is the answer. ○: p.52's *Expand node* / *Expand parents* controls, which belong with the node-expansion row

**The sweep scored 11/3 with one no-op, and re-swept 12/2 after three corrections.** All three survivors were the same shape — a branch nothing could reach — and they were resolved three different ways, which is §213's whole point. **One was deleted**: the downstream walk carried an "unless it already has a reason" guard, and `seen` already is that check, because it starts as the directly-stale set and so every node the walk reaches is one nothing has marked. **Two stay, with the reasoning in the docstring rather than in a test that pretends to exercise them**: the `None` guards on `built_at` cannot be reached, since `models.output_dataset_id` is NULL until the first run and a never-run model therefore contributes no output *node* at all — but `None > datetime` raises, and a `TypeError` on a read path is a 500 rather than a wrong answer, which is the stated exception §213 makes. **And one test was claiming a state that cannot exist**, which is what the sweep actually found: it was written as "a dataset nothing has built yet is unbuilt rather than stale", and there is no such dataset. It asserts the shape of the graph now instead, and its first draft of *that* was wrong too — a never-run model has no *output* edge, but its input edge is there. **A fixture that sounded stronger was weaker**: re-running two models rather than one makes every stale dataset directly stale, which quietly removes the only node in the project that exercises the transitive reason at all. |
| **Find datasets with a given column** | ◑ §353 | (TOC §14; `data-lineage` p.54-55) — p.55's **Frequent Columns**: the columns on the graph, most frequent first, and clicking one highlights the datasets that have it. **Which datasets, not how many** — the count is what the section is *sorted* by and the list's length is that count, while the ids are what make p.55's click possible at all. **By name only, not by name and type**: p.55 says "by name", and a column that is a string in one dataset and an integer in another is exactly the case somebody changing a schema is looking for, which keying on the pair would hide. **The selection is the graph as drawn**, which is a decision rather than an omission: p.54 selects datasets with drag-select first, this platform's graph has single selection, and multi-select is its own ○ row in §2.2 — so the *graph* is the selection, which is p.54's own first instruction ("ensure you added all datasets of interest in your pipeline to your lineage graph") and leaves the narrowing to the row that owns it. Computed **after** the focus narrowing, for the reason §351's links are: a lineage view asks about the datasets it drew. **The highlight dims the rest rather than only colouring the lit ones**, because what a reader is looking for is which of forty nodes has the column, and clicking the same column again clears it — a highlight nothing can turn off is a mode rather than a question. No migration: `datasets.table_schema` is the current schema and the graph already reads that row. ○: p.54's drag-select and multi-select, on the §2.2 row that owns them, and the rest of p.54's *histogram* — this is the Frequent Columns section of it, not the value distributions

**The sweep scored 9/5 and re-swept 2/2**, and the five split three ways — which is the case for writing mutants against the *code* rather than the tests, since a list drawn from the test file would have produced none of them. **One was a bad mutant**: `columns = [] or _frequent_columns(...)` evaluates to the call, so it changed nothing; re-run as `columns = []` it is caught. **One was a missing test**: the fixture's three columns had three different frequencies, so nothing exercised the name tiebreak at all — there is a project now whose two columns are equally common and declared in non-alphabetical order, which is the only arrangement that can tell a tiebreak from the absence of one. **Three were unfalsifiable**, and stay with the reasoning in the docstring rather than a test that pretends to reach them: the `isinstance` on a schema row and the `not in` before appending guard shapes the write path cannot produce — db 0003's rows are objects, and DuckDB renames a CSV's duplicate column (`id, id` arrives as `id, id_1`), which was checked rather than assumed — and the `kind == "dataset"` filter is a statement of what is counted rather than a check, since an object type's id is not a dataset id and the lookup would miss anyway. |
| Build datasets from the graph | ○ | TOC §15 |
| **Roll back a pipeline** / **roll back a dataset** | ○ | TOC §17–18 |
| Check resource permissions from the graph | ○ | TOC §19 |
| **See the impact of marking changes** | ○ | TOC §20 — which downstream consumers a permission change would break |
| **Save and share a graph** | ○ | TOC §8 |

### 2.4 Ontology entities in lineage

"Explore artifacts and ontology entities" (TOC §7; `data-lineage` p.30-32). Foundry's lineage graph is not dataset-only — object types and their backing datasets appear in the same graph. ◑ §351.

**Built:** an object type a project's dataset backs is a node on the graph, and the sync is an ordinary **edge** into it — a sync reads the dataset and writes the type's instances, so the type is downstream of it exactly as a model's output dataset is downstream of the model. A type backed by several of the project's datasets is **one** node with an arrow from each (db 0003 allows it), reporting the **worst** of their syncs: the question this view answers is "what is wrong downstream of here", and an `ok` beside an `error` would answer it with the reassuring half. p.32's **link types are drawn beside the edges, never among them** — `edges` is what the layering and the cycle report are built from, and a link type is a relationship rather than a dependency, so putting one there would report two object types that reference each other as a cycle in a *pipeline*, which is an ordinary and correct ontology. They are also resolved **after** the focus narrowing, so a link cannot drag a dataset into a lineage view that has no data path to the focus; both ends must already be on the graph. An object type is a node the graph can be **centred on** too, because a node a view draws and cannot centre on is one whose neighbours are unreachable from it.

**The boundary is the one this graph always had, stated for the ontology:** `object_types` and `link_types` are *workspace*-scoped and this graph is a *project's*, so a type reached through another project's dataset is not this project's lineage — the same line `_validate_and_set_inputs` draws for a model's inputs. `object_type_sources` has no project of its own; it is project-scoped by the dataset it names.

**Both builders, because there are two.** `pipeline.project_graph` is what the browser draws and `models.lineage_for_dataset` is the Mermaid/JSON export, and a feature added to one of them is a feature half the product does not have — the kind of split §216 exists to catch. Object types are in both; **link types are deliberately only in the first**, because the export's question is "what touches *this dataset*" and a link type joins two object types rather than touching any dataset.

**○ — p.30's Related artifacts panel**, and the reason is structural rather than effort: it lists "Contour visualizations and Slate applications", and this platform has neither. Building a panel with a badge counting nothing would be §214's control that cannot work.

**The sweep scored 17/1 with one no-op, and re-swept 3/0.** The survivor was a fixture that could not tell the difference: `sites` had two sources and both were `never_synced`, so the mutant that stopped folding them survived — with two identical states there is nothing a fold does that not folding does differently (§213). One source is synced now, which makes the two halves of the fold answer from *different rows*: a build that took whichever row came last would report either `ok` with a timestamp or `never_synced` with none, and the node reports `never_synced` **with** a timestamp. The no-op was a mutant whose anchor had drifted from the SQL, re-run separately rather than counted as a catch. And the harness tripped §350's own lesson twice — the browser stage's freshness guard fires once a sweep has restored anything under `apps/api/src`, so the server mutants are scored on the pytest stage and the stack is restarted before each baseline.

---

## 3. Build order

1. ~~**Ontology entities in the lineage graph.**~~ — **done (§351)**, and it turned lineage into the impact-analysis tool this line said it would. What §2.4 now records that this line could not have: the interesting decision was **not** which nodes to add but which arrows *are not edges* — a link type between two object types is a relationship, and `edges` means data flows this way. Struck in the commit that finished it, per §216. p.30's Related artifacts panel stays ○ with its reason on the row.
2. ~~**Out-of-date datasets**, and **find datasets with a given column**.~~ — **both done (§352, §353)**, and struck in halves as each landed per §216. They shared a line and nothing else: one compares build times across edges, the other counts column names across schemas, and neither needed the other. "Cheap" held for both — no migration between them, because `datasets.table_schema` and `dataset_versions.created_at` were already on the rows the graph reads. **The first half is done (§352)** and struck here rather than at the end of the pair, per §216 — a line goes stale in the commit that finishes *part* of it, which is how three entries of `ontology.md`'s list came to describe work already shipped. The two are independent despite sharing a line: one compares build times across edges, the other searches schemas, and neither needs the other. "Cheap" held for this half — no migration, one walk over edges the graph already had.
3. **Search & Browse helper**, node expansion, drag-select.
4. **Branch from a historical transaction** (Dataset Preview) — the missing half of §56.
5. **Build logs** in the job detail view, and the History summary.
6. **Save and share a graph.**
7. **Roll back a dataset**, then roll back a pipeline.
8. CSV parsing options and Edit schema.

---

## 4. Acceptance tests

- **Impact analysis** — a graph containing a dataset shows the object types backed by it; deleting the mapping removes them from the graph.
- **Out-of-date** — a dataset whose upstream rebuilt is marked stale; rebuilding clears the mark.
- **Column search** — a column present in three datasets returns exactly those three.
- **Branch from transaction** — a branch created from transaction *N* reads the data as of *N*, not as of head.
- **Branch fallback** — a graph on branch `feature` shows resources that exist only on `main`, in the documented fallback order.
- **Rollback** — rolling a dataset back to transaction *N* makes head read as *N*, and the rollback itself appears in history.
