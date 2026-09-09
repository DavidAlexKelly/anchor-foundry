# 0016 — Export schedules: a cron where Foundry has a scheduler

**Status:** decided, **not yet built**.
**Parity items:** `docs/parity/data-connection.md` §2 (capabilities — *Exports*), whose row names **scheduling (p.205 — the runner exists, the trigger does not)** as the one piece of build-order item 3 still owed.
**Source:** `docs/pal/foundry_data-connection.pdf` (417 pp), cited `(p.N)`.
**Follows:** decision 0014, which built the export and said this was missing; decision 0013, whose allowlist governs a scheduled export as it governs a manual one — through the worker's copy of the check, which is the part that has to be proved rather than argued.

---

## The sentence that shapes this is not about exports

> "To schedule an export, navigate to the Overview page for the export. Then, select Add schedule to open the export in Data Lineage. From there, select Create new schedule to the right of your screen and **configure as you would for any other job**." (p.205)

**Export scheduling is not an export feature in Foundry.** It is the platform's build scheduler, reached through Data Lineage, pointed at an export the same way it is pointed at anything else. The export half of it is one sentence: exports have an Overview page, and schedules that trigger them are listed there.

This platform has no general job scheduler. It has a cron column per schedulable resource — `models.next_run_at` (0014), `connections.sync_next_run_at` (0014), instance syncs (0016) — each with a `list_due_*` discovery function and a Dagster op. So an export schedule is a **third instance of an existing shape**, not the first use of a general one.

---

## What the document says

> "Exports should be scheduled to run regularly, exporting recent data to the external destination." (p.205)

> "Streaming exports do not need to be scheduled since they should simply be started or stopped." (p.205)

> "View any schedules that trigger a specific export on the Overview page for that export." (p.205)

> "Some source export options may not be editable after initial setup. If immutable options must be changed, you must delete and re-create the export." (p.205)

> "Similar to syncs, exports run as jobs using the Foundry build system." (p.206)

---

## 1. A cron approximates an event trigger, and p.192 is why it is close enough

The real difference between a general scheduler and a per-resource cron is not where the setting lives. It is that Foundry's schedules can be **triggered by upstream events** — when the dataset updates — and a cron fires on the clock whether or not anything changed.

p.205's own wording is about freshness: *"exporting recent data to the external destination."* An event trigger serves that directly; a cron serves it by polling.

**What makes the gap small is a decision already made.** p.192's June 2025 behaviour says an export with nothing new is a **success**, and §265 implemented it: `should_skip` compares `last_version` to the dataset's current version and the run records a skip. So a cron that fires hourly against a dataset that changes daily performs twenty-three cheap no-ops and one export, and the history says exactly that — §267's "nothing new (v7)" rather than a green tick that means nothing.

The cost is real and worth stating: **the destination is stale for up to one cron interval**, where an event trigger would be stale for as long as the export takes. That is a latency choice, not a correctness one, and it is the same one scheduled syncs already made in the other direction.

## 2. It runs in the worker, and that costs a third copy of the connector layer

A cron that fires must fire somewhere. The API is request-scoped and would fire once per replica; the worker is where every other scheduled thing in this platform runs, with the discover-then-verify pattern 0014 established.

The cost is not small and should not be hidden: **`apps/api` and `apps/worker` are independently deployable images with no shared Python package in this build**, so the worker already carries trimmed copies of `connectors`, `dataset_engine`, `storage` and a byte-identical copy of `egress`. A scheduled export adds to that:

- the export rule (`should_skip`, `truncates`, `missing_columns`);
- the runner (`perform`, `_put_file`, `_put_rows`, `_header`);
- `dataset_engine.export_csv`;
- `destination_columns` and `export_rows` on the Postgres and MySQL connectors, and `export_file` on S3.

**The mitigation is the one this repo already uses, and it is a test rather than an intention.** `test_egress.py` holds the worker's copy of `egress.py` byte-identical to the API's and fails when it drifts; §267 made the browser's destination map answer to the server's the same way.

**And the rule module turned out not to need copying at all**, which is worth more than the guard would have been. `services/exports.py` imports `re` and `typing` and nothing else — no database, no driver, no framework — so `anchor_worker/exports.py` is the *same file*, held byte-for-byte by a test, exactly as `egress.py` is. That matters most for the one function in it that decides everything: p.192's skip semantics are the difference between a scheduled export that reports honestly and one that rewrites a destination every poll, and **two implementations of "is there anything new" that disagreed would disagree silently**, because both answers look like success.

What genuinely had to be copied is what touches a driver: the runner's orchestration, `export_csv`, and the three connectors' export methods. Those get the weaker guard — a test that asserts the worker's connectors have the methods by name, and the worker's own suite running one export end to end into a real database. Weaker, and said so here rather than left to look equivalent.

`packages/db/dsn.py` is not a counter-example. It is shared through `PYTHONPATH` by tests and shell scripts; neither deployed image imports it. There is still no runtime shared package, and creating one is a change to how both images are built — a real option, and a different unit from this one.

## 3. The switch is re-checked when the schedule fires, not when it was set

p.202 makes exports something an admin turns on per source, and §265 enforces it at create time. A schedule set while it was on must not keep running after somebody turns it off — **the same argument decision 0013 §3 made about send time versus save time**, and the reason two of its four original rows were wrong.

So `list_due_exports()` joins `connections.exports_enabled` rather than trusting that an export could not exist without it. The test is the one that matters: turn the switch off, let the schedule come due, and assert nothing was written.

## 4. One failing export must not take the others down

§263 found this in the worker and it was not hypothetical: a refused sync killed the whole op, because `EgressRefused` is deliberately not a `ConnectorError` and the enumerated `except` tuple did not list it. The export op catches per export, and the test pins the ordering so a refusal really is followed by a candidate that must still run.

## 5. A guard that was untestable is not any more

`export_store.record` guards its version mark with `GREATEST(COALESCE(last_version, 0), :v)`, and §265 recorded that its harness could not kill a mutant removing it — every test there makes one request at a time, so two runs finishing out of order never happens. That note was correct and is now out of date: **a schedule makes the interleaving reachable**, because a manual run and a scheduled one can genuinely overlap and the one that read v5 can commit after the one that read v6.

The line does not change. What changes is that the reason it exists stopped being hypothetical, which is the kind of thing a comment claiming "the tests cannot construct this" should be re-read for whenever a new caller appears. §213 recorded the general form: a sentence about what the platform cannot express has a shelf life, and nothing points at it when it expires.

## 6. What this does not build

**Event-driven triggers.** §1 says why: there is no lineage-driven scheduler to hang them on, and p.192's skip makes a cron close enough to be honest. If a general scheduler ever exists, this is one of the things that should move onto it.

**Streaming exports' start/stop** (p.205). There are no streams to start.

**Editing an export.** p.205 says some options "may not be editable after initial setup" and that changing them means deleting and re-creating. This platform's exports are create-and-delete already, so the shapes match — recorded because it looks like a gap and is not.

---

## What is owed

- The screen: p.205's "view any schedules that trigger a specific export", on the export's row.
- A general job scheduler, if the platform ever grows one — at which point three per-resource crons become one thing.
