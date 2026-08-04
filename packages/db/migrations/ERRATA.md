# Errata

Applied migrations are immutable — `migrate.py` records a SHA-256 of every file
it applies and aborts hard if one changes. That guard cannot tell a comment from
a statement, and it should not try to: a file that has run somewhere is a file
that has run, and "it was only a docstring" is a judgement no runner can make
from a hash.

So when a migration's *prose* turns out to be wrong, the correction goes here
instead of into the file. This list is short on purpose. If it stops being
short, the problem is the review of migrations, not this document.

---

## `0034_workshop_module_format.py` — its summary contradicts its own next paragraph

The summary says:

> **What changes.** `canvas_apps.definition` becomes a `format: 2` document, and
> every version row is converted alongside it.

The second half of that sentence is **wrong**, and the paragraph immediately
below it in the same file says so:

> **The original is kept, and precisely this way.** Historical
> `canvas_app_versions` rows are left untouched […] Only `canvas_apps.definition`,
> the live document, is rewritten, and the conversion appends a *new* version row
> carrying the converted document.

**The code does the latter.** Historical version rows keep the format they were
written in; one new row is appended carrying the converted document.

It is not a cosmetic slip. `STATUS.md` §88 made the published read path join to a
version row, so "are old version rows v1?" became a question with consequences,
and the file answered it both ways. For the record, the answer: a
`published_version` can only point at a post-conversion row, because 0034 bumped
`current_version` for every app it converted and §88's backfill pinned
`current_version`. A v1 document cannot reach a viewer through that path — and
if one somehow did, the browser renders it rather than failing.

The correction was briefly made *in the file* (commit `b0235cd`) and then
reverted, because it broke `migrate.py` for every database that had already
applied 0034 — which is the whole point of the guard, demonstrated at the cost of
one afternoon. See `STATUS.md`'s rough edges.
