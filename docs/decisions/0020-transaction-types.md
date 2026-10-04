# 0020 — Transaction types on dataset versions

**Status:** decided and built: §747 built §1–§3, §748 §4.
**Parity items:** `docs/parity/datasets-lineage.md` §1.3 (History), `data-connection.md` §2 (*Exports*: the four transaction modes decision 0014 §2 left out; *Source exploration*: p.160-161's file-import filter).
**Source:** `docs/pal/foundry_data-integration.pdf` p.21-26, cited `(p.N)`; `foundry_data-connection.pdf` p.195-196 and p.160-161, cited `(dc p.N)`.
**Follows:** decision 0014 §2, which named this as "a migration and a decision of its own, not something to smuggle in behind an export dropdown". Decision 0008 (one version per action) is unchanged by it.

---

## What the document says

> "Behind the scenes, however, datasets are updated over time using transactions, which represent modifications to the files within a dataset." (p.22)

> "There are four possible transaction types: SNAPSHOT, APPEND, UPDATE, and DELETE." (p.22)

> "A SNAPSHOT transaction replaces the current view of the dataset with a completely new set of files." (p.22) "An APPEND transaction adds new files to the current dataset view. An APPEND transaction cannot modify existing files in the current dataset view." (p.22-23) "An UPDATE transaction, like an APPEND, adds new files to a dataset view, but may also overwrite the contents of existing files." (p.23) "A DELETE transaction removes files that are in the current dataset view." (p.24)

> "Because a new view only begins at a SNAPSHOT transaction, the number of views in a dataset's history is equal to the number of SNAPSHOT transactions it contains." (p.26)

Foundry's transactions are about **files**, and its view is the files a run of transactions leaves. A version here is one Parquet file holding the whole view (db 0001), so the two models do not line up file for file. They line up on the question the types answer, which is **how a version relates to the one before it**. That question is what decision 0014 §2 found four export modes need, and it is the one this decision records.

## 1. A version says how it relates to the one before

`dataset_versions.transaction_type` (db 0144) is one of:

| Type | Here | p.22-24 |
|---|---|---|
| `SNAPSHOT` | a new view. Nothing before it is part of this one | "replaces the current view … with a completely new set of files" |
| `APPEND` | the previous view plus rows, no row of it changed | "adds new files … cannot modify existing files" |
| `UPDATE` | the previous view with rows added, changed or removed | "adds new files … but may also overwrite the contents of existing files" |

**Each version is still stored whole.** Time travel, rollback, branching and every reader that opens a version read one file and need nothing from this. The type is a statement about the version, not a different way of storing it.

**DELETE is not a value.** p.24's DELETE removes files from a view, and nothing here removes rows without possibly changing others: an action that deletes an object, or an undo that removes a created one, writes an `UPDATE`. A value with no writer would be a promise nothing keeps. p.24 says DELETE is "mostly used to enable data retention workflows", and retention here (decision 0005) removes whole versions rather than rows of one, so nothing is lost.

## 2. Every writer says which, and none may leave it out

The column has **no default** after the backfill, and `stage_version` / `add_version` take it as a required argument. A writer that does not say which it is fails, rather than being filed as a SNAPSHOT by omission. This is db 0023's lesson: its trigger caught writers nobody had listed.

| Writer | Type | Why |
|---|---|---|
| upload, fork, rollback, re-parse, model run, full sync, an empty dataset | `SNAPSHOT` | each writes a whole view. A rollback's view is an old one *again*, and that is a new view (p.26: views begin at SNAPSHOTs, and nothing else could begin one here) |
| p.10's upload of a new file (§746) | `APPEND` | "If the filename is different from previous uploads, you can append data" |
| p.10's upload over a file of the same name | `UPDATE` | it replaces that file's rows |
| listener archive | `APPEND` | it only ever adds the events since the last |
| incremental sync | `APPEND` or `UPDATE` | `APPEND` when no row of the new batch has a key the view already holds (`merge_transaction`), and `UPDATE` when one does, since the merge replaced it. The first run is a `SNAPSHOT` |
| action, undo, batch | `APPEND` or `UPDATE` | `APPEND` when the write only added rows (`write_rows` refuses an added row whose key exists), and `UPDATE` when it changed or removed any (`written_transaction`) |
| join table pairs | `APPEND` or `UPDATE` | `UPDATE` only when a pair was removed |

**The incremental sync decides per run rather than per mode**, because the mode does not know. A source whose rows are only ever inserted produces APPENDs run after run, and that is exactly the dataset p.196's incremental exports are for. One that updates rows in place produces UPDATEs, and those modes refuse it, which they should.

## 3. The backfill claims only what the history shows

Versions written before db 0144 are typed from what they recorded:

* `listener` → `APPEND`. Archives have only ever appended.
* `action`, `action_batch` → `UPDATE`. An action rewrote rows of the view it read. Some only added rows, and the history does not say which.
* an incremental sync (`sync_cursor_value` set, db 0127) after its first version → `UPDATE`, since the merge may have replaced rows.
* everything else → `SNAPSHOT`.

**Under-claiming is the safe direction.** What reads the type (§4) refuses an UPDATE and re-exports a SNAPSHOT, and neither duplicates a row. Claiming APPEND for a version that replaced rows would duplicate them in the target table, so the backfill never guesses APPEND.

## 4. What reads it: p.195-196's transaction modes (§748)

Decision 0014 §2 built two of p.195-196's six table export modes, `full` and `mirror`, because "four name transaction types in their definition". With §1 they can be built:

| Mode (dc p.195-196) | Behaviour here |
|---|---|
| Efficiently mirror dataset to external table | the unexported versions of the current view. If one of them is a SNAPSHOT (a new view began), truncate and export the view, otherwise export each APPEND's rows. Refuse an UPDATE |
| Export incrementally | the same without truncating. A new view is exported whole, which is p.196's "may produce duplicate records … if the upstream dataset has a SNAPSHOT transaction" |
| Export incrementally with truncation | truncate, then the unexported versions as above |
| Export incrementally and fail if not APPEND | after the first run, refuse anything but APPENDs |

**An APPEND's rows are computed, not stored.** By §1's definition version N is version N-1 plus rows, so the rows it added are `N EXCEPT ALL N-1`. That is exact for a multiset, and it needs no second file per version. It needs N-1's bytes, so a version whose predecessor retention removed (decision 0005) cannot be exported incrementally. The export says so and names `mirror` as the way through, rather than guessing.

## 5. Not decided here

p.160-161's file-import filter ("Exclude files already synced") for S3 syncs is the other thing decision 0014 §2's gap blocked. It needs the S3 connector to keep the paths it has ingested. It is separate work on the connector, and this decision only gives it the APPEND and UPDATE types to commit.
