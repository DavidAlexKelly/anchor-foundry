# 0008 — One transaction per action

**Status:** decided, not built.
**Parity items:** `docs/parity/ontology.md` §5 (the rule kinds that write no property) and §8 (an action editing two objects where the second fails must leave *neither* applied).
**Source:** `docs/pal/foundry_action-types.pdf` (174 pp). Citations are `(p.2)`.
**Follows:** decision 0007, which is built (`STATUS.md` §127–§131). This is the blocker its last section named.

---

## The problem, in one sentence

**An action can be half-applied, and nothing notices.**

Foundry is unambiguous about what an action is:

> "An action is a **single transaction** that changes the properties of one or more objects, based on a user-defined logic." (p.2)

> "…all edits are applied **atomically** at the end of the action call." (p.84)

Ours is not one transaction. `routes/actions.py` executes a single `modify_object` rule against a single instance, and the write goes out in two places that can disagree:

1. `datasets.add_version` puts a new Parquet object in storage, then updates `datasets` and inserts a `dataset_versions` row;
2. `instance_store.update_properties` writes the same values into the search index.

Today the blast radius is small, because §127's executor collects every rule's writes into *one* `{property: value}` dict and applies it as *one* row rewrite. That is not a transaction — it is a single write, which is a different thing that happens to look the same while there is only one rule kind and one object.

The moment §5's remaining rule kinds arrive, it stops looking the same:

| Rule kind | What it writes | Why the current path cannot |
|---|---|---|
| `create_object` | a new row in the target type's source dataset | a second dataset write in the same action |
| `delete_object` | a row removed | same |
| `create_link` / `delete_link` | a row in *another* dataset (or a link table) | a second dataset entirely |
| several `modify_object` on different objects | rows in one or more datasets | one version per write today |

Each of those is a second write, and `add_version` bumps `current_version` per call. So an action with two rules produces **two dataset versions**, and a failure between them leaves the first applied, the second not, and a caller told the action failed.

## The decision

**Stage every write, then commit them in one Postgres transaction, and treat the search index as a projection that is repaired rather than transacted.**

Three parts, in the order they matter.

### 1. `add_version` splits into stage and commit

Storage and metadata come apart:

```
stage_version(...)   -> writes the Parquet object, returns a pending version record
commit_versions(...) -> inserts every dataset_versions row and updates every
                        datasets row, in one transaction
```

A staged-but-uncommitted Parquet object is garbage in the bucket and nothing else: no `datasets` row points at it, so no reader can see it. **That is the whole reason for the ordering** — the expensive, slow, non-transactional part happens first and is discardable, and the cheap, atomic part happens last. The reverse order would need a distributed transaction to be correct.

Orphan objects are collectable by a sweep over keys with no `dataset_versions` row. Not built by this decision; named so that nobody is surprised by them.

### 2. One version per dataset per action, not per write

An action that rewrites three rows of one dataset produces **one** new version of it. That is what p.2's sentence means in our storage model, and it is also the only reading that keeps dataset history legible: three versions with the same `produced_by_id` and no way to tell which was the "real" state after the action is a history that has to be interpreted rather than read.

An action touching two *different* datasets produces one version of each, both committed in the same Postgres transaction, both carrying the same `produced_by_id`.

### 3. The instance store is repaired, not transacted

OpenSearch has no transactions, and pretending otherwise by writing to it inside the Postgres transaction would only move the failure — a commit that succeeds in Postgres and fails in OpenSearch is still two outcomes.

So: **the datasets are the record and the index is a projection.** The index is updated after the commit; a failure there is logged against the action run and the projection is rebuilt by re-syncing the source, which is a path that already exists and is already exercised. What must never happen — a dataset that says one thing and a `dataset_versions` history that says another — is exactly what the single transaction prevents.

The honest consequence, stated rather than buried: **for a window after a partly-failed action, the Object Explorer can show stale values while the dataset is correct.** That is recoverable and detectable. The alternative — a half-written dataset — is neither.

## What this unblocks

- `create_object`, `delete_object`, `create_link`, `delete_link` (p.75's "simple rules")
- an action editing several objects at once, which is `ontology.md` §5's row and §8's requirement
- writeback webhooks (p.106) later, which are defined in terms of the same boundary: "if the webhook execution fails, no other changes will be made"

## What this does not do

- **No cross-service atomicity.** Postgres commits; OpenSearch catches up. Said plainly above.
- **No orphan sweep.** Named in part 1, deliberately separate: a sweep that runs against a bug in the staging path deletes live data, so it wants its own piece of work and its own tests.
- **No functions.** p.75 answers the cases simple rules cannot express with function-backed actions, and `[fn]` is out of scope for this build. This decision is about making the *simple* rules honest, not about replacing them.
- **No change to what one rule does today.** The conversion in §127 stays exactly as it is; this changes how the writes it produces are committed, not what they are.

## How you would know it worked

Per the repo standard, each of these must be made to fail by removing the thing it tests:

- **An action whose second rule fails leaves the first unapplied.** The acceptance test `ontology.md` §8 asks for by name. Mutation: commit each write as it is staged, and the dataset comes back with one rule applied.
- **An action that rewrites two rows of one dataset produces exactly one new version.** Mutation: version per write, and the count goes to two.
- **An action touching two datasets commits both or neither.** Fail the second commit and assert the first dataset's `current_version` is unchanged.
- **A staged version nothing committed is invisible.** No `dataset_versions` row, no change to `current_version`, and the dataset still reads as it did.
- **A failed index update is recorded on the action run and repaired by a re-sync**, rather than being silent or fatal.

## The alternative that was rejected

**Keep versioning per write and add a compensating undo** — on failure, append another version restoring the previous state. It needs no schema change and it is wrong in the way that matters: the compensation is itself a write that can fail, the history fills with pairs of versions that have to be read as one, and any reader between the two sees a state that never existed as far as the user is concerned. Foundry's word is "transaction", and a compensating write is what you build when you cannot have one. We can have one — the metadata all lives in a single Postgres database.
