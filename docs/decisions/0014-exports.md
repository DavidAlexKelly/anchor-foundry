# 0014 — Exports: the reverse direction, and the four modes we cannot mean

**Status:** decided, **not yet built**.
**Parity items:** `docs/parity/data-connection.md` §2 (capabilities — *Exports, push data out*) and build order item 3 — *"the reverse direction; currently data only flows in."*
**Source:** `docs/pal/foundry_data-connection.pdf` (417 pp), cited `(p.N)`.
**Follows:** decision 0013, which is built. Every export is an outbound call, so the allowlist it introduced already governs this — and whether that is true by construction or only by intention is one of the things this decision has to settle.

---

## The source is unusually complete here, which changes the job

§263 was designed from fragments and had to mark every inference. This is the opposite problem: p.192–p.215 is a full chapter — three export types, six table export modes with a table of what each one means, a page of special considerations, a permissions model, and a legacy path it explicitly deprecates. **Almost nothing here needs inferring.**

So the risk is not under-specification. It is the other one: **implementing the words without having the thing they describe**. Four of p.195–196's six modes are defined over a transaction log this platform does not keep, and a build that shipped all six would be shipping four settings that could not do what their own names say.

---

## What the document says

> "Data Connection supports exporting datasets and streams from Foundry to external systems." (p.192)

> "File exports are the opposite of file batch syncs… Table exports are the opposite of table batch syncs… Streaming exports are the opposite of streaming syncs." (p.17)

> "The behavior of exports will depend on the type of data the destination system can accept." (p.193)

> "In general, exports do not support any data transformations executed as part of the export job. This means that the dataset or stream you select to export should already be in your desired format." (p.200)

> "The destination table must already exist in the source system; it will not be automatically created by Foundry." (p.197)

> "Prior to June 2025, exports have been marked as `failed` if there are no new files or rows to be exported during a build. From June 2025 onward, exports with no new files or rows to be exported will be marked as `success`." (p.192)

---

## The decision

**Two export types, two table modes, and a per-source switch that starts off.**

### 1. File and table. Not streaming, and the reason is not effort

p.17 pairs each export type with the sync it reverses, and that pairing decides this cleanly: we have file batch syncs (S3) and table batch syncs (Postgres, MySQL), so we get file exports and table exports. We have no streams — `data-connection.md` lists streaming under "deliberately never" — so there is no streaming sync to reverse and nothing p.194's replay-behaviour setting could be about.

**A REST source is not a destination here, because it already is one.** p.17 lists webhooks in the same breath as the three export types, as the other way data leaves for an external system, and decision 0012 built exactly that: a request shape on a REST source, with inputs, outputs and a history. An "export to a REST source" would have to invent a request body, a method and a path — which is a webhook, described worse. So the export form refuses a REST source with a sentence naming webhooks rather than offering a mode that would have to guess.

### 2. Two of p.195–196's six modes, because four are about transactions we do not have

`dataset_versions` is, in its own migration's words, a "snapshot per sync/upload". Every version is a **complete view**. There is no transaction type on it — no `SNAPSHOT`, `APPEND`, `UPDATE`, `DELETE` — because nothing in this platform has ever needed one: a full sync writes a new view, an incremental sync merges and writes a new view, an action writes a new view (decision 0008: one file and one version per action, however many rows it touched).

Now read the six modes with that in mind:

| p.195–196 mode | What it needs | Here |
|---|---|---|
| Efficiently mirror dataset to external table *(recommended)* | "incrementally exporting any unexported **transactions**… truncating when there is a `SNAPSHOT` transaction" | **no** |
| Full dataset without truncation | the current view | **`full`** |
| Full dataset with truncation | truncate, then the current view | **`mirror`** |
| Export incrementally | "only unexported **transactions** from the current view" | **no** |
| Export incrementally with truncation | the same, plus a truncate | **no** |
| Export incrementally and fail if not APPEND | "failing if there is a `SNAPSHOT`, `UPDATE`, or `DELETE` transaction" | **no** |

Four of the six name transaction types in their definition. Two do not, and those two are built.

**What is lost is real and worth saying plainly.** p.195 calls the first mode *recommended*, and it is absent. `mirror` reaches the same end state — "the external table always matches what you see in the dataset" — by p.195's own second-best route, which p.195 describes as "less efficient than the incremental option". So the outcome is available and the efficiency is not, and the efficiency is precisely the part that needs the transaction log.

**This is a dataset-model gap, not an export gap, and it is the honest place to record it.** Adding transaction types to `dataset_versions` would unlock four modes here and would change every writer in the platform. That is a migration and a decision of its own, not something to smuggle in behind an export dropdown.

### 3. "Nothing new to export" is a success, and it is not a mode

p.192's June 2025 change: an export with nothing to export succeeds rather than failing. That is exactly expressible — an export records the last dataset version it wrote, and a run finding that version unchanged succeeds having written nothing.

It applies where the document applies it and not elsewhere:

* **File export** — p.193: "only files that were modified since the last successfully exported transaction on the upstream dataset will be written." One file per version, so "modified" means "the version changed". A run on an unchanged version writes nothing and succeeds.
* **`mirror`** — the end state is already correct, so rewriting identical rows is pure cost and a window during which the target is empty.
* **`full`** — **does not skip**, and this is not an exception to p.192 but a consequence of it. p.195 says this mode is "useful when external systems consume and remove rows after each run": there is always something new to export, because the destination emptied itself. A `full` export that skipped would be a queue that stopped being fed.

### 4. Exports are off until somebody turns them on

> "To export data, you must enable exports in the Connection settings section of the source to which you are exporting… A Foundry user with the `Information Security Officer` role should navigate to this tab and toggle on the option to Enable exports to this source." (p.202)

A per-source flag, defaulting to **off**, and a workspace admin is who may set it. Two things this platform does not have, named rather than approximated:

* **The `Information Security Officer` role.** It is an enrollment-level role granted in Control Panel (p.202). Workspace admin is the nearest thing here and is a genuine narrowing: it is per-workspace where Foundry's is per-enrollment. Recorded on the parity row.
* **Exportable markings** (p.202). Markings are a classification system this platform has never had — "you must provide the set of markings that may be exported to this source", and data carrying a marking not on the list fails to export. With no markings there is no list, and the flag is the whole control rather than the coarse half of it.

**The flag is the point, not the paperwork.** Without it, any project editor who can create a connection can move every row they can read out of the platform, and nothing anywhere says so. §263 controls *where* a source may reach; this controls *whether* it may be written to at all. They are the two halves of the same question and neither substitutes for the other.

### 5. Enforced at the same chokepoints as everything else, and that is a claim to test

An export is a **fifth outbound path**, and decision 0013's enforcement table gets a row. Table exports build their connection through `PostgresConnector._conninfo` and `MySQLConnector._connect_kwargs`; file exports go through `S3Connector._client`. All three already call `egress.check_current` — §263 put the guard at the chokepoint every operation shares rather than at each operation — so an export is guarded **without a line being added**.

That is exactly the kind of sentence §263 learned not to trust. "The guard is in a shared function" is not the same claim as "every path reaches it", and two of four paths did not. So the export path gets its own paired test against a real socket, like the four before it.

### 6. What the document refuses, we refuse in the same words

p.197 is a page of constraints, and each is cheaper to enforce than to explain after a failure:

* **The destination table must already exist.** Not created for you. A missing table is a sentence, not a driver error.
* **A 1:1 schema match, column names case-sensitive.** Checked against the destination's own columns *before* the first row is written — Foundry lets this "fail at runtime", and failing at row 40,000 of a table export tells nobody which column was wrong.
* **`Array`, `Map` and `Struct` columns are not exportable.** Refused with p.197 named, at configuration time rather than at run time, because a dataset's schema is known when the export is created.
* **Truncation needs permission in the external system** (p.197, p.203). Not knowable in advance; the failure says so.
* **No transformations during the export** (p.200). No column mapping, no filter, no rename. The dataset is exported as it is, and the tool for changing that is a model — which is what p.201 says at greater length.

---

## What this does not build

* **Streaming exports** (p.194) and their replay behaviour — §1 above.
* **Export tasks** (p.211–215), which p.211 opens by recommending against and p.206 says table exports "fully replace". Building a path the source deprecates would be parity with Foundry's history rather than with Foundry.
* **Scheduling** (p.205). Exports "should be scheduled to run regularly", and this build runs them on demand with a history. The scheduler exists — `sync_schedule` and the worker's `run_due_scheduled_syncs` are the shape it would take — and this is a follow-up unit, not a gap in the model.
* **Exportable markings** (p.202) — §4 above. No marking system to draw a list from.
* **Multi-threaded exports with a staging table** (p.200). An optimisation whose stated purpose is atomicity under parallelism, and this build writes one file's rows serially.
* **The four transaction-dependent modes** — §2 above, and the reason is in `dataset_versions`, not here.

---

## The acceptance tests this owes

* A table export in `mirror` mode leaves the destination equal to the dataset, **run twice** — once onto an empty table and once onto one holding the previous run's rows. The second run is the one that distinguishes `mirror` from `full`.
* A table export in `full` mode run twice leaves **twice the rows**, because p.195 says so in as many words and because a `full` that quietly de-duplicated would be a fifth mode nobody chose.
* An unchanged dataset re-exported **succeeds and writes nothing** — and its paired half: a changed dataset re-exported *does* write, without which the first passes against an export that never writes at all.
* A `full` export on an unchanged dataset **does** write, which is §3's whole distinction and the one a single skip-test would erase.
* A column the destination does not have is refused **before any row is written**, naming the column.
* A dataset with a `Struct` column is refused when the export is configured, naming p.197.
* An export to a source with exports disabled is refused, and enabling it is refused to a project editor and allowed to a workspace admin.
* A destination the source's egress policies do not permit is refused — with the presence half beside it, as every test in §263 has.
* A REST source is refused as an export destination with a sentence naming webhooks.
