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
| **Understand out-of-date datasets** | ○ | TOC §13 — which downstream datasets are stale and why |
| **Find datasets with a given column** | ○ | TOC §14 — cheap, and very useful during a schema change |
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
2. **Out-of-date datasets**, and **find datasets with a given column**. Both cheap; both directly useful during a schema change.
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
