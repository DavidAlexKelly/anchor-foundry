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

"Explore artifacts and ontology entities" (TOC §7). Foundry's lineage graph is not dataset-only — object types and their backing datasets appear in the same graph. Ours stops at datasets. ○

That is the item to prioritise: it is what turns lineage from a pipeline tool into the answer to "if I change this column, what breaks?"

---

## 3. Build order

1. **Ontology entities in the lineage graph.** Turns lineage into an impact-analysis tool.
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
