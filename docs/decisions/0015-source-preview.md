# 0015 — Source preview: reading data the platform does not own yet

**Status:** decided, **not yet built**.
**Parity items:** `docs/parity/data-connection.md` §2 (capabilities — *Source exploration*) and build order item 4 — *"browse tables and files before configuring a sync."*
**Source:** `docs/pal/foundry_data-connection.pdf` (417 pp), cited `(p.N)`.
**Follows:** decision 0013 (egress policies), which governs this the way it governs exports — through the connector chokepoints rather than by a new guard. Whether that is true by construction or only by intention is settled below, in the same way and for the same reason decision 0014 §4 had to settle it.

---

## The source is two pages, and one sentence of it is not where you would look

The whole of *Sources / Source exploration* is p.142–143, and most of those two pages is the numbered callouts of a screenshot. Taken alone it reads as a small feature: a tree, a graph, a preview pane, a basket.

The sentence that decides what to build is on **p.18**, in the capability overview, three chapters earlier:

> "The interactive exploration capability allows you to see what data is contained in an external system before performing syncs, exports, or other capabilities that interact with that system. **Exploration is most commonly used to check that a connection is working as intended and that the correct permissions and credentials are being used to connect.**" (p.18)

**The most common use of the data browser is not browsing data.** It is answering "does this work, as this user?" — and the sharpest possible answer to that question is a handful of real rows from a real table, because a row that arrives proves the host, the port, the credential, the privilege and the table name all at once, and no test button proves the last two.

That reframes the build. A preview is not a convenience laid over discovery; it is the only check in the platform that exercises the *read path* a sync will actually take.

---

## What the document says

> "When setting up syncs from a source, you may want to explore the source and the data it contains to preview syncs before they bring data into Foundry." (p.142)

> "Table details: Preview a sample of the selected table." (p.143)

> "Left panel: Find and add tables and views from the source system to the graph. Use the free text search helper to find specific tables, or browse the tree to find resources." (p.143)

> "Graph: Explore tables and views and the relationships between them… **Note that the graph is not always available for table-based data exploration.** For example, a graph would not appear for exploration of a table-based REST API model as there are no clear relations between objects." (p.143)

> "Left panel: Explore and select the directory containing contents to sync into Foundry. Preview: See a preview of the files that will be synced." (p.143, file-based)

> "Exploration — Interactively explore the data and schema of an external system before using other capabilities." (p.14)

---

## 1. Half of this is already built, and saying which half is the useful part

`discover()` has been on `SourceConnector` since §2 and is exposed at `POST /connections/{id}/discover`; `DiscoverDialog` renders the tree. So p.143's callout 1 exists in its "browse the tree" form, and p.14's *schema* is done.

What p.142–143 asks for that this platform does not have:

| p.143 | Have it? |
|---|---|
| Browse the tree of tables and views | **yes** — `discover()` and `DiscoverDialog` |
| Free-text search across that tree | no — the dialog renders every schema and every table, unfiltered |
| **Preview a sample of the selected table** | **no** — nothing reads a row until a sync writes a dataset |
| The relationship graph, with foreign keys highlighted | no |
| Create a sync from the exploration view | partly — `SyncDialog` picks from the discovered list, but the two screens do not talk |
| File-based: preview the files a sync would take | no — `discover()` lists objects and their inferred columns, never their contents |

**The preview is the row that is missing, in both senses.** It is also the only one of the six that needs a connector method; the rest are a screen.

---

## 2. Why a preview is not just a small sync

A sync writes a dataset, and every permission question about the result is then a question about that dataset. A preview writes nothing, and that is exactly what makes it awkward: **it returns data that no platform permission covers, because the data is not in the platform.**

The only two things standing between a caller and the source's contents are the connection's stored credential and the caller's project role. So the role has to be chosen deliberately rather than copied:

- **Editor**, matching `discover`. The argument is that a project editor can already *run* a sync against the connection, which pulls the whole table into a dataset they can then read. Someone who can take all of it can be shown fifty rows of it.
- Not viewer, even though a viewer can read the datasets a sync produced. A dataset that exists has been through somebody's decision to bring it in; the source behind it has not, and a viewer being able to read arbitrary tables through a connection they cannot configure is a widening nobody asked for.

**The rule this leaves:** *preview is bounded above by what a sync could already do, and by nothing else.* If that ever stops being true — a connection whose credential can read more than any sync would — this decision is the thing to revisit.

## 3. It is a preview of a table, never a query

The endpoint takes a schema and a table, which are checked with `check_identifier` and interpolated as identifiers, exactly as `snapshot` does. **It does not take SQL, a filter, or a column list**, and it should not grow them: the moment a caller can shape the read, an editor's ability to see fifty rows of a table becomes an ability to run arbitrary statements as the connection's user, which is a different and much larger grant than "a sync could have fetched this".

The narrowing costs something real — you cannot preview *the rows that matter*, only rows — and §5 says what that means for the sample.

## 4. Caps, and the one place a preview is allowed to be inexact

Three limits, all of them because a preview's result travels in a JSON response rather than into a file:

- **Rows**: `PREVIEW_ROWS = 50`. Enough to see shape and spot a column of nulls.
- **Cells**: `PREVIEW_CELL = 500` characters. A single text column can hold megabytes, and fifty of them would be a denial of service the platform performs on itself.
- **Everything is a string.** The connectors already stringify for CSV, and a JSON preview that tried to preserve types would be a second type system that could disagree with `dataset_engine`'s — the browser would show a number the sync would later store as text.

The cell cap is the one inexactness, and it is worth naming rather than burying. A truncated value is returned shortened with an ellipsis, and **a genuine value that is exactly the cap long and ends in an ellipsis is indistinguishable from a truncated one.** Mitigated rather than solved: the response carries an exact count of how many cells were shortened, so "3 values were shortened" is a sentence the screen can say, and the column list and the row count are never approximate. This is acceptable here and would not be in a dataset read — `size_cap_error`'s refuse-rather-than-lie is still the rule everywhere the result is a source of record.

## 5. The sample is a sample, and the document already has the word for it

`SELECT * FROM t LIMIT 50` returns whatever the source hands back first. There is no `ORDER BY`, which means **the fifty rows are not the first fifty and are not stable between calls.**

Adding an order would need a key the source may not have, and would make a preview of a large table a full sort of it — turning the cheapest check in the platform into one nobody would press twice. p.161 uses the exact phrase for the equivalent choice on the file side: *"a non-deterministic subset of the desired files"*. So the sample stays unordered, and the screen says so rather than letting somebody conclude that row 1 is the first row.

## 6. Egress: the sixth path, and the reason it needs no new guard

Decision 0013 §3 enumerated four outbound paths and found two of them unchecked. §265's exports were the fifth, and needed no line added because they run through `PostgresConnector._conninfo`, `MySQLConnector._connect_kwargs` and `S3Connector._client` — the chokepoints the check was deliberately put at.

A preview is the sixth, and the same argument applies to it:

| Path | Checked at send time |
|---|---|
| Preview (table, file, endpoint) | **yes** — through the connector chokepoints above, by construction |

And the same distrust applies to the argument. Decision 0013 wrote *"'the guard is in a shared function' is not the same claim as 'every path reaches it'"* and two of its four original rows exist because that reasoning had been applied and was wrong. **The REST connector is where it could be wrong here**, because a REST preview does not go through `_client` or `_conninfo` at all — it goes through `_fetch_page`, which calls `_check_url`, which is a *different* one of the four chokepoints. That is still a chokepoint, but it is a second claim, not the same one.

So the row above is a test's claim, not an argument's: a paired refused/allowed pair against a real socket, for a database preview and for a REST preview separately, because one fixture that cannot distinguish the two cannot test which of them fired.

## 7. What this does not build, and why each one is a choice

**The relationship graph (p.143).** Foundry says of its own feature that it "is not always available", and gives a source type where it does not appear. A graph needs foreign keys, and foreign keys need a catalogue query per connector that only two of our four could answer. The honest version of this is not a graph but a *column annotation* — `ColumnInfo` already carries `is_primary_key`, and a `references` field beside it would be the same shape. Left out of this unit because the preview is what p.142's own first sentence asks for; recorded here so the next person does not read the absence as an oversight.

**The file-import filter (p.143 callout 2).** A filter on which files a sync takes is not a preview feature — p.160–161 defines it in terms of `SNAPSHOT`, `APPEND` and `UPDATE` transactions, and **that is the same transaction log decision 0014 §2 found `dataset_versions` does not keep.** Two chapters have now been narrowed by the same missing concept, which is worth more than either narrowing on its own: the gap is in the dataset model, and it will keep surfacing.

**Free-text search over the tree, and creating a sync from the preview.** Both are the browser's half and belong with the screen, not with the connector method.

---

## What is owed

- Foreign keys on `ColumnInfo`, if a relationship view is ever wanted (§7).
- The browser half: search, the preview pane, and the path from a previewed table to a configured sync.
