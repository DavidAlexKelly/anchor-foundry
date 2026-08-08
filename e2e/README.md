# The browser suite

Playwright against real dev servers. No mocks, no component harness — the
module is built through the API the way a person would build it, opened in a
browser, and asked what it shows.

```bash
scripts/dev-up.sh      # Postgres, the API on 8300, Next on 3100
scripts/check.sh e2e   # or: .venv-api/bin/python -m pytest e2e -q
```

## Why this exists

`ROADMAP.md`'s cross-cutting section puts it plainly: *"Playwright coverage of
the builder is not optional."* Two of the four defects found in one week
(`STATUS.md` §52) were invisible to the API tests and obvious in a browser, and
that ratio has held since. A widget can read the right data and draw the wrong
thing; a filter can be sent when it should have been dropped; an action form
can succeed and leave the table beside it stale. None of those are API bugs.

Everything here was previously a throwaway script outside the repo. That worked
for the person who wrote it and for nobody else, and it did not survive the
machine it ran on.

## Why Python

The seeding is API calls, the assertions are about server-computed numbers, and
the repo already has one test runner. A second one with its own lockfile and its
own fixtures would be a second place test setup lives.

**The cost is real and worth stating**: a change to `widgets.tsx` is verified by
a suite in another language in another directory, and a front-end developer has
to know that. `scripts/check.sh` runs everything so nobody has to remember.

What this does *not* cover, and what a JavaScript runner still would: unit tests
for the pure functions in the widget layer — `seriesLabel`, `pivotClauses`, the
`useUrlState` reducer. Those deserve tests and do not have them.

## How a test is put together

`api.py` builds a module: upload a CSV, declare an object type, map a source,
sync it, then save a format-2 document. Everything is tagged with a random
suffix, so two runs against the same dev database cannot collide.

**Nothing is torn down on purpose.** A failed run leaves its module in place and
its URL in the fixture, which is the difference between debugging a browser
failure and re-running it blind.

`conftest.py` holds the fixtures and, importantly, fails a test on any console
error: a React error boundary catches a thrown render and shows *something*, so
a widget can be broken while a screenshot looks plausible.

## Things that have already gone wrong here

Kept because each cost real time and none is obvious:

- **`.canvas-block` matches ancestors.** A container holding two widgets
  "has_text" both their titles, so `locator(".canvas-block", has_text=...)`
  quietly returns the whole page. Scope to the widget's own element.
- **`get_by_role(name=...)` matches substrings.** A cell labelled
  `"Filter to region = north, status = open"` matches a query for
  `"Filter to region = north"`. Pass `exact=True` for headings.
- **An SVG `<title>` is not an HTMLElement.** `inner_text` refuses it outright;
  use `text_content`. That is the good kind of failure — it did not return
  something plausible and wrong.
- **A checkbox backed by the URL does not tick synchronously.** Playwright's
  `check()` verifies state immediately after clicking and the tick lands a
  router round-trip later. Click, then wait.
- **Never run `next build` while these are running.** Both write
  `apps/web/.next`, and the dev server starts 500ing mid-suite. Every assertion
  after that point fails for a reason that has nothing to do with the code.

## Coverage

| File | Covers |
|---|---|
| `test_pivot_table.py` | Pivot Table (`STATUS.md` §105) |
| `test_time_series.py` | Time Series (§106) |
| `test_narrowing_widgets.py` | Chart drill-down (§101), Card List (§102), Search (§103) — one module, because the claim that matters is that they *compose* |
| `test_section_resize.py` | Drag-to-resize sections (§109) — the only suite that drives the **builder** rather than Preview |

Not covered by a browser test: everything else. The Filter List, the Map, the
Action form, the builder's own panels, publishing, and the Object Explorer all
have API tests and no browser test. That is a gap, not a decision.
