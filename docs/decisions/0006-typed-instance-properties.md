# 0006 — Typed instance properties

**Status:** accepted, not built
**Context:** the blocker `STATUS.md` names as holding four separate features

Four things are refused today, each with the same sentence in its refusal, and each with a
one-line implementation that was deliberately not written:

| Refused | Where |
|---|---|
| Ordered filters — `gt`, `gte`, `lt`, `lte` | `object_sets.ORDERED_OPERATORS` |
| Numeric aggregations — `sum`, `avg`, `min`, `max` | `object_sets.parse_aggregation` (`STATUS.md` §74) |
| Sorting a table by a property | `object_sets.SORTS`, `PROPERTY_SORT_HINT` (§83) |
| Selecting an area on a map to filter by it | roadmap 1.5, the Map row (§86) |

The refusals are correct and this document does not soften them. What it settles is the
question underneath, so that whoever builds this is not deciding it at three in the morning
against a cluster.

## The actual problem, stated once

**Instance properties are stored untyped, and one index serves every object type in a
workspace.**

The ontology has declared types — `object_type_properties.data_type` since db 0003, widened
to the current set by db 0029, one of
`string, integer, float, boolean, date, timestamp, geopoint, json, attachment`. Values are
already normalised on write by `property_values.coerce_property_value`, shared verbatim by
the API and the worker. So the *declaration* exists and the *values* are clean.

What does not exist is any connection between the declaration and how a store compares two
values:

- **Postgres** keeps `properties` as `jsonb`. `capacity > 40` can be cast, and casting is a
  choice the query makes.
- **OpenSearch** maps `properties.*` dynamically to `text` with a `.keyword` subfield
  (`instance_store._ensure_index`). `capacity > 40` compares indexed text.

So the same filter reads `250 > 40` on one store and `"250" < "40"` on the other. The first
implementation shipped both and the cross-store test caught them disagreeing on the first
run, which is why the operators were withdrawn rather than picked.

**And the index is per *workspace*, not per object type** — `_index_name` is
`{search_prefix}object-instances`, holding every type's instances together. That is the part
that makes this a design decision rather than a patch: a workspace with an Order whose
`status` is a string and a Reading whose `status` is an integer cannot have one mapping for
`properties.status`. Mapping the declared types into the index as it stands is not merely
hard, it is not expressible.

## 1. One index per object type

`{search_prefix}objects-{object_type_id}`, mapping each `properties.<name>` to the field type
its declaration asks for.

**Why this and not the alternatives.**

- *Type-qualified paths* (`properties.{type_id}.{name}`) keep one index and avoid the
  collision, but the stored document then has a different shape from the one Postgres holds
  and the API returns, and the mapping grows as types × properties against a default field
  limit of 1000. Two shapes for one object is the thing decision 0002 exists to stop.
- *Type-suffixed field names* (`properties.capacity__integer`) also fit in one index and are
  genuinely tempting: two object types that both declare `capacity` as an integer would share
  a field, which is correct. But every query would have to rewrite property names on the way
  in and out, so the name in the document is not the name in the ontology — and the first
  person to read an index by hand would be looking at a schema nobody wrote down.
- *One index per type* says exactly what is true: **an object type is a schema**, and two
  schemas are two mappings. It is also the shape OpenSearch's own guidance points at when
  documents in an index would need different mappings.

**What it costs, named rather than discovered.**

- **Shard count grows with object types.** One primary shard per index, no replicas beyond
  what the domain's default gives — a workspace with 200 object types is 200 shards, which is
  well within a small domain's budget but is no longer free. A workspace with thousands of
  object types is not a shape this platform has, and if it acquires one this decision should
  be revisited rather than stretched.
- **The workspace-wide Object Explorer becomes a pattern search.** `STATUS.md` §98's explorer
  searches every type at once; it would query `{search_prefix}objects-*` instead of one index.
  OpenSearch does this natively, and the per-row `object_type_id` the explorer already carries
  keeps the results attributable.
- **Deleting an object type deletes an index**, which is cleaner than the delete-by-query it
  does today.

## 2. Which types become orderable, and which never do

| Declared type | Ordered comparison | Why |
|---|---|---|
| `integer`, `float` | **yes** | Numeric on both stores; agreement is arithmetic |
| `date`, `timestamp` | **yes** | ISO-8601 in, `date` mapping and `timestamptz` cast out |
| `geopoint` | **yes, as a box** | See §3 |
| `boolean` | no | "greater than false" is not a question |
| `json`, `attachment` | no | Composite values have no order anybody would agree on |
| `string` | **no, deliberately** | See below |

**String ordering is refused permanently by this document, not postponed.** Lexicographic
comparison is well-defined on each store *separately* and differently between them:
Postgres orders by the database collation, OpenSearch by the keyword's byte order. `'Z' < 'a'`
is true in one and false in the other for any non-C collation. Allowing `gt` on a string
would reintroduce the exact class of bug this whole document exists to remove, one layer
down and much harder to see. If somebody needs "codes after X", the honest answer is a
derived property with an orderable type, not a comparison whose meaning depends on where it
ran.

Sorting a table by a `string` property is the same refusal for the same reason, so
`SORTS` grows by the orderable types only, and `PROPERTY_SORT_HINT` keeps its job for the rest.

## 3. The map's area selection is a bounding box, not four comparisons

`geopoint` is stored `{lat, lon}` (db 0029). The temptation is to express "in this rectangle"
as four ordered comparisons on two numbers. **Do not.** Mapped as OpenSearch's `geo_point`,
the query is `geo_bounding_box`, which handles the antimeridian and pole cases that four
comparisons get wrong — and gets them wrong *silently*, on the small number of customers whose
data crosses 180°.

Postgres compares the two numbers directly, and must implement the same wrap rule explicitly:
a box whose west edge is greater than its east edge spans the antimeridian. That rule belongs
in `object_sets` beside `matches`, which is already the one place a filter's meaning is
defined for both stores.

## 4. What a type change does

`STATUS.md` §38 lets a property's declared type be edited. OpenSearch cannot change a field's
mapping in place, so **a type change is a reindex of that object type**, and this is the
strongest argument for §1: it reindexes one type's documents, not a workspace's.

The existing type-change path already computes an impact report (`/object-types/{id}/impact`)
and already refuses breaking changes without acknowledgement. Reindex cost belongs in that
report — "this changes a property's type, so N instances will be rewritten" — for the same
reason retention costs belong on the dataset screen (decision 0005 §1): you cannot consent to
a cost you cannot see.

## 5. A value that does not fit its declared type fails loudly

Reindexing will meet values that no longer coerce — a property retyped from `string` to
`integer` over rows containing `"n/a"`.

**The reindex refuses and names them.** It does not write null, and it does not skip the
document. Both of those produce an index that is quietly missing rows a filter should have
matched, and the first person to notice is somebody trusting a count.

This is the same rule as §90 and §94: it is better to be loudly broken than quietly wrong,
and a migration is exactly where that trade is usually got backwards.

## 6. Neither store ships the new operators until both do

The Postgres half of this is a day's work and is fully testable here; the OpenSearch half
needs a cluster. Shipping the Postgres half first would mean an app whose results depend on
which store the deployment happens to run — which is the *original* bug, reintroduced by the
fix for it.

So `ORDERED_OPERATORS`, the numeric aggregations, property sorts and the map box all stay
refused until both stores implement them and the cross-store test passes.

## 7. What the fixture must gain before any of this is checkable

`tests/opensearch_fixture_server.py` implements the REST subset the store uses and **has no
mapping enforcement** — by design, and it says so in its own docstring. It treats
`properties.x` and `properties.x.keyword` as the same value, which is exactly why the first
cross-store disagreement was catchable and why a *typed* one would not be.

Before this is built, the fixture must:

1. **Accept and remember a mapping** from `indices.create`, per index.
2. **Compare according to it** — a field mapped `integer` compares numerically, a `keyword`
   compares as bytes, a `geo_point` answers `geo_bounding_box`.
3. **Refuse a document whose value contradicts the mapping**, as a real cluster does, so §5's
   reindex failure is reachable in a test.

That does not prove real OpenSearch agrees. It narrows the unproven claim from *"does any of
this work"* to *"does OpenSearch behave like the mapping it was given"*, which is a much
smaller thing to check on a first real cluster — and which the deployment runbook should list
as a step rather than leaving to be discovered.

## Consequences

- **A migration and a backfill.** Every workspace's single instance index is replaced by one
  index per object type, and every instance is rewritten. This is the largest data movement
  the platform has asked for, and it is the reason this is a decision document rather than a
  commit.
- **Four features unblock together**, and their refusals become implementations rather than
  sentences.
- **String ordering stays refused forever**, and `PROPERTY_SORT_HINT` should be reworded to
  say *which* types can be sorted rather than implying all of them will be one day.
- **The Postgres-only deployments are unaffected until they adopt OpenSearch**, since
  `OPENSEARCH_ENDPOINT` unset already leaves everything on the Postgres store. They gain the
  operators at the same time as everybody else, because of §6.
