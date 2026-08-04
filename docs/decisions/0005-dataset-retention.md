# 0005 — Dataset retention

**Status:** accepted
**Context:** ROADMAP phase 2, item 3.3 (Time travel)

The item says: *"Browse a dataset at a previous version. Needs a decision on retention, and it is the one item here that has a storage bill attached — say so in the item rather than in the invoice."*

## What was already true, and nobody had said

**Every version of every dataset has always been kept, in full.** Since migration 0003, each version is written to its own key —
`workspaces/{ws}/datasets/{id}/v{n}/data.parquet` — and nothing has ever deleted one. A dataset synced hourly for a year is 8,760 complete copies of itself.

That is not a decision anybody made. It is what fell out of writing versioned keys and never writing a sweeper, and the first time it becomes visible is on a bill.

So the retention decision below is not a change to what happens. It is a decision about what happens *next*, made now that the cost is on a screen rather than in an invoice.

## 1. Keep everything, by default, and say what it costs

**Default: no expiry.** Nothing is deleted.

The alternative — a default that expires old versions — would silently delete data on every existing deployment the moment it shipped, to fix a problem none of them have reported. A default that destroys data to save money nobody has complained about is the wrong way round.

**But the cost is now reported**: `GET /datasets/{id}/retention` returns the number of versions and the bytes they occupy, and the version list carries a size per row. The dataset application shows both. This is the whole of what item 3.3 asked for on the money side, and it is deliberately the part built first: you cannot decide a retention policy for data whose volume you cannot see.

## 2. A version's *record* and a version's *bytes* are different things

When expiry is built, it must delete bytes and keep rows.

`model_runs.output_version` points at the version a run produced. `dataset_versions` holds the schema and row count each version reported. Deleting those rows would make history lie — a run that says it produced nothing, a dataset that appears to have sprung into existence at v40.

So expiry marks a version as no longer retained and removes the object. The row stays, still true about what the data *was*: 12,431 rows, these columns, produced by this sync at this time. What changes is that it can no longer be read, and the surface says so in those words rather than reporting a missing file as an error.

This is the same rule §90 and §94 apply elsewhere: a record of what happened must not change when live state does.

## 3. What can never be expired

- **The current version.** Expiring it would delete the dataset's data while leaving the dataset.
- **A version another dataset was forked from**, while that fork has not produced a version of its own. `STATUS.md` §28's fork copies the *bytes* at fork time, so in practice this is already safe — stated here so a future change to forking does not quietly make it unsafe.

Nothing else is protected, and in particular **a version a model run points at is not protected**. Protecting those would protect almost everything, since almost every version was produced by a run. A run record whose output can no longer be read is still a true record of what ran; a policy that cannot expire anything is not a policy.

## 4. Where the policy will live

Per dataset, not per workspace. Datasets differ by three orders of magnitude in both size and churn in the same project, and a single number for all of them would be set for the largest and wrong for everything else.

Shape: `datasets.retention_versions integer NULL` — keep the newest N, NULL means keep everything. Versions rather than days, because "how many versions back can I look" is the question time travel actually answers, and a day-based rule on an hourly sync and a monthly one mean wildly different things.

**Not built yet.** Expiry deletes customer data, and shipping the delete before anybody can see what would be deleted is the wrong order. The reporting is here; the policy and its sweeper are the next item, and this document is what they will be built against.

## Consequences

- Time travel works on every existing dataset with no migration and no backfill, because the bytes were always there.
- Storage grows without bound until §3 is built. That is now a visible number rather than a surprise.
- A future expiry cannot be a `DELETE FROM dataset_versions`. It is an update plus an object delete, and any code reading a version must handle "retained: no".
