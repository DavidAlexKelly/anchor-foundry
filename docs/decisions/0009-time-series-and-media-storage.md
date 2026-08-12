# 0009 — Where time series and media live

**Status:** accepted. Media half built (`STATUS.md` §147); time series settled, not built.
**Context:** `docs/parity/ontology.md` §7 build order, item 5 — "Time series and media
reference property types. Both unlock Workshop widgets; both need a storage decision first."

Two `○` rows in `ontology.md` §1.1 sit in front of four other rows, and the build order says
what is holding them: not the property type, the **storage**. This settles both questions so
that whoever builds the first one is not choosing a data model against a half-finished
widget.

| Blocked | By |
|---|---|
| Standard Object View: time series → interactive chart | §4.1 |
| Standard Object View: media reference → dedicated media viewer | §4.1 |
| Workshop: Time series set variables | `workshop.md` §3.2 |
| Workshop: Chart XY / Map / Metric Card / Object Table time-series columns | `workshop.md` §10 |

They are two different problems that got filed together because they are both "a property
whose value is not a scalar". The answers are not symmetric and this document does not
pretend they are.

---

## Part 1 — Time series

### The actual problem, stated once

**A time series property is not a value, it is a table.** Foundry's own description is "a
history of timestamped values": one instance carries thousands of `(timestamp, value)` pairs,
and a fleet of ten thousand sensors carries tens of millions.

Everything this platform stores about an instance today is one document —
`object_instances.properties` as `jsonb`, or one OpenSearch document per instance
(decision 0006). That shape is exactly wrong for a series, and not marginally:

- **Every read pays for every point.** The Object Explorer lists fifty instances at a time
  and the standard Object View reads one whole instance to draw a table of four fields.
  Neither wants a decade of readings, and neither can ask for the instance without them.
- **A sync rewrites the whole history on every run.** `mark-and-sweep` full-snapshot sync
  (§16) upserts the instance document; if the document holds the series, an unchanged
  instance rewrites its entire history each time it is synced.
- **OpenSearch has an opinion.** A document is a unit of indexing; a multi-megabyte
  properties blob is a mapping explosion and a refresh cost on a store whose whole job here
  is fast lookup by property.

### The three options

**1. Points inside `properties`.** Rejected for the three reasons above. It is the option
that looks cheapest for a week and is unpickable afterwards, because by then every
`get_instance` caller is shaped around it.

**2. A `time_series_points` table in Postgres**, keyed by `(source_id, primary_key,
property, timestamp)`. Rejected, and the reason is not performance:

> It is a **second copy of data this platform already stores well.** The points arrive in a
> dataset — a customer's readings land as a Parquet file like everything else — and copying
> them into Postgres means a second retention policy (decision 0005 governs datasets, not
> this table), a second lineage story (`data-lineage` knows about datasets), a second
> backfill path, and a second answer to "what did this look like last Tuesday" (dataset time
> travel, §3.3, would not cover it).

Two stores for one fact is the thing decision 0002 exists to stop, one layer down.

**3. A series *reference*, points read from the backing dataset on demand.** **Chosen.**

The property does not hold points. It holds the identity of a series, and where series live
is declared once — on the **object type source**, which is already the place this platform
says "here is the dataset behind this type, and here is how its columns map".

```
object_type_series (
  object_type_source_id,   -- which mapping this series belongs to
  property_api_name,       -- the time_series property it feeds
  dataset_id,              -- where the points are
  key_column,              -- matched against the instance's series id
  timestamp_column,
  value_column
)
```

An instance's `time_series` property value is then a small scalar — the series id, which is
usually the instance's own primary key — and reading points is a `dataset_engine` query
against the named dataset, filtered by key and time window, aggregated to the interval the
caller asked for.

**Why this is the right shape here specifically.** The platform already has the hard half:
Parquet storage, a DuckDB query path, versioning, retention, lineage and time travel. A
series is tabular data over time, which is what all of that is for. The alternative options
both amount to teaching a *second* subsystem to do what the dataset subsystem already does.

**What it costs, stated plainly.** Points are only as fresh as the dataset. A live sensor
feed is a sync away from the chart, not a stream — and this platform has no streaming
ingestion, so an option that implied one would be describing a different product. Named here
so nobody discovers it from a graph that lags.

**Geotemporal series** (`ontology.md` §1.1) is the same decision with a geopoint in the value
column, and is not a separate mechanism.

### What is deliberately not settled

The **aggregation vocabulary** a caller may ask for (`avg`, `min`, `max`, `last` per bucket)
and the interval grammar. Both are `object_sets`-shaped problems and both should be decided
against a real widget rather than in advance — decision 0006 has already been through one
round of withdrawing operators that were chosen before anything compared them.

---

## Part 2 — Media reference

### The actual problem, stated once

Foundry's media reference is not a file. It is a pointer into a **media set**: p.128 gives
`mimeType` plus a triple of media-set / view / item RIDs. A media set is a managed
collection with its own views, its own permissions and its own lifecycle.

**We have no media sets, and the honest question is whether to build them.**

What we do have is attachments (§39): object storage under a per-workspace prefix, an upload
endpoint, a download route that checks every key against that prefix, and an `attachment`
property type whose value is `{key, filename, content_type, size}`.

### The three options

**1. Build media sets as a first-class resource.** A `media_set` resource kind, views,
per-set permissions, an items table, a sync path. This is a *product*, roughly the size of
Datasets, and nothing in the five in-scope applications asks for the parts that make a media
set more than a folder. Rejected as out of proportion: the only consumer named anywhere in
the parity set is "render this image in an Object View".

**2. Add a `media_reference` base type that looks like Foundry's triple** but points at our
attachment storage, with the media-set and view RIDs left null or faked. Rejected, and this
is the important refusal:

> A type whose shape promises a media set and whose values have no media set behind them is
> a lie that every future reader has to discover. Two of the three RIDs would be permanently
> null, and the first person to write code branching on them would be writing dead code
> against a contract nobody honours.

**3. Render the media we already store, and do not add a type.** **Chosen.**

An `attachment` whose `content_type` is an image, video or audio type is *already* a media
reference in every sense this platform can honour: bytes, a MIME type, and a URL that
enforces the workspace boundary. What was missing was a renderer — `PropertyValue` drew a
download link for a PNG, so the "media reference → dedicated media viewer" row in §4.1 was
blocked on **display**, not on storage.

So: no new base type, no new table, no migration. The standard Object View and the property
renderer show an image inline, a video and an audio file in their native players, and
everything else stays a download link.

**What this does not claim.** `ontology.md` §1.1's media-reference row stays `○`, because a
media *set* is genuinely absent and marking it done would be the lie option 2 was rejected
for. §4.1's media-viewer row becomes `◑` with the gap named: media renders, media sets do
not exist.

**What would change this.** A consumer that needs a *collection* — "show every photo
attached to this inspection, paged, with a thumbnail view" — is the thing a media set is
for, and is the point at which option 1 stops being out of proportion. Until one exists,
building it would be inventing a requirement.

---

## Summary

| Question | Answer |
|---|---|
| Where do time series points live? | In the dataset they arrive in. The property holds a series *id*; a `object_type_series` mapping says which dataset, key, timestamp and value columns. |
| Why not Postgres? | It is a second copy of data the dataset subsystem already versions, retains and traces. |
| What does a time series property cost? | Freshness is sync-shaped, not streaming. Named rather than discovered. |
| Where does media live? | In attachment storage, where it already is. |
| Is there a `media_reference` type? | **No.** A type shaped like a media set with no media set behind it is a contract nobody honours. |
| What was actually missing for media? | The renderer. Built in §147. |
