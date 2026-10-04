# 0021 — File-based syncs: a folder, a transaction type, and filters

**Status:** decided; §749 builds the API's run, §750 the worker's schedule, §751 the form.
**Parity items:** `docs/parity/data-connection.md` §2 (*File-based syncs*, whose ✅ said more than was built, and *Source exploration*'s file-import filter).
**Source:** `docs/pal/foundry_data-connection.pdf` p.160-164, cited `(p.N)`.
**Follows:** decision 0020 (transaction types), whose APPEND and UPDATE this commits, and §746 (`dataset_files`), whose "a dataset is a set of named files" this reuses.

---

## What the document says

> "Batch mirror with SNAPSHOT (default) … Each run will ingest all files nested in the external system's subdirectory, including files ingested in previous runs, and commit a SNAPSHOT transaction." (p.160)

> "Incremental mirror with APPEND … Filters: Exclude files already synced … Each run will ingest all files that have not yet been ingested, keyed by file path name, and commit an APPEND transaction." (p.161)

> "Incremental mirror with UPDATE … Exclude files already synced with the Last modified date option … and/or … File size option … Each run will ingest all files that have not yet been ingested or have since changed, keyed by file path name, and commit an UPDATE transaction." (p.161-162)

> "Trailing window with SNAPSHOT … The output dataset view will contain a single SNAPSHOT transaction containing only files that were never present in any previous job run." (p.162)

> "Filters allow you to filter source files before they are imported into Foundry." (p.164): Exclude files already synced, Path matches, Path does not match, Last modified after, File size is between, Any file has path matching, At least N files, Limit number of files.

**What was here.** An S3 sync read **one object**, `source_schema` / `source_table` being a folder and a file name, and an incremental run re-read that one object when its LastModified moved. `data-connection.md` marked *File-based syncs* ✅ on that, but p.160's unit is a **subfolder**, "including files ingested in previous runs", and the four modes above are about which of its files a run takes. None of that existed.

## 1. A file sync is a scheduled sync of mode `files`

`sync_mode` gains `files` (db 0146), for an S3 connection only. `sync_source_schema` is the subfolder under the connection's prefix, and `sync_source_table` is unused. The connection already holds "one managed sync target", and a folder is that target as well as a table is.

Two settings go with it:

* `sync_file_transaction`: `SNAPSHOT`, `APPEND` or `UPDATE`, which is p.160's "Transaction type", and decision 0020's types.
* `sync_file_filters`: p.164's filters. `exclude_synced` (with `by_modified` and `by_size`), `path_matches`, `path_not_matches`, `modified_after`, `size_min` / `size_max`, `any_path_matches`, `at_least` and `limit`.

p.160-162's four modes are combinations of the two, exactly as p.160 says ("the low-level settings required to achieve the desired behavior"):

| Mode | Transaction | Exclude files already synced |
|---|---|---|
| Batch mirror | SNAPSHOT | off |
| Incremental mirror with APPEND | APPEND | on, by path only |
| Incremental mirror with UPDATE | UPDATE | on, by modified date and/or size |
| Trailing window | SNAPSHOT | on |

## 2. p.160-162's contradictory settings are refused, not warned about

p.160-162 list "Contradictory settings" for each mode. Two of them make a sync do something other than what its type says, so saving them is refused:

* **APPEND without Exclude files already synced** re-ingests every file each run into an APPEND, duplicating every row the dataset already holds. An APPEND that repeats the view is not an APPEND.
* **APPEND with the modified or size option** "would attempt to incorrectly re-ingest existing files, keyed by file path name, in an APPEND transaction" (p.161), the same duplication for one file.
* **UPDATE without the modified or size option** can never see a changed file, so it is an APPEND labelled UPDATE. It is refused with APPEND named.

p.160's other contradictions (a limit or an "at least" on a batch mirror, a limit on a trailing window) produce a subset of files, not a wrong type. Each is the person's call, and the form says what it does.

## 3. What a run remembers

**Files the sync has ever taken** are a table of their own: `sync_files(connection_id, path, size, modified, synced_at)`. "Exclude files already synced" is about every previous run (p.162's trailing window shows only new files, yet must remember the old ones), so it cannot be the dataset's current files.

**The files the current view holds** are `dataset_files` (§746), keyed by the path under the subfolder. Each file's rows are kept as their own Parquet under `{dataset}/files/`, so:

* a **SNAPSHOT** writes the files it took and nothing else (p.160, p.162);
* an **APPEND** adds its files to the view's (p.161);
* an **UPDATE** adds its files and replaces those of the same path (p.161-162), which needs the rows each file contributed. That is why a file's Parquet is kept rather than only the combined one;

and the version is those Parquets combined (`combine_parquets`, §746), committed with the configured transaction type.

**A run that finds no file to take writes no version**: the sync run records it as nothing new. p.164's "At least N files … will yield an empty transaction", and an empty version would be a history entry for nothing.

## 4. A file that cannot be read fails the run, whole

p.163: "If a sync fails at any point, the transaction is aborted and none of the files from that run are committed." Every file is read and combined before anything is written. A file that does not parse, or whose columns differ from the others, fails the run with its path named, and `sync_files` is not updated, so the next run tries the same files again.

## 5. Not built

* **Transformers** (p.165). p.165 itself recommends "performing data transformations in Foundry with Pipeline Builder and Code Repositories", which is what models are here.
* **Completion strategies** (p.165-167): "read-only and cannot be configured on new syncs".
* **Sources other than S3**: no other connector here reads files.
