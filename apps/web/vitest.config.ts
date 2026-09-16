import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Only the pure-function tests. The browser suite is `e2e/`, in Python,
    // against real servers — see `apps/web/src/components/canvas/pure.ts` for
    // why that boundary is drawn and kept.
    include: ["src/**/*.test.ts"],

    // **The timezone is set in `package.json`'s `test` script, not here**, and
    // the distance between those two places cost a session to find (§359).
    //
    // *Why it is not UTC.* The time-series labels are formatted in UTC on
    // purpose, and on a machine whose clock is already UTC a test of that
    // proves nothing: deleting the `timeZone: "UTC"` option is invisible. A
    // mutation confirmed it — the check passed against code with the option
    // removed, because this container runs in UTC. New York is chosen because
    // it is *behind* UTC, so an instant at the very start of a UTC day falls
    // on the previous local day; a zone ahead of UTC (Tokyo, Kiritimati) would
    // leave a midnight-UTC bucket on the same date and hide the bug again —
    // the same trap a mutation on the browser suite fell into in `STATUS.md`
    // §106.
    //
    // *Why it cannot live here.* This file said `env: { TZ: "America/New_York" }`
    // for as long as the comment above has existed, and **it did nothing**:
    // `test.env` assigns `process.env` after the worker has started, and Node
    // resolves the zone `Date` uses once, at startup. Inside a test
    // `process.env.TZ` read back `undefined` and `Intl` resolved `UTC`, so
    // every timezone-sensitive test in this repository was running in the one
    // zone the comment says proves nothing. Found by a §359 mutant that read
    // the local date instead of the UTC one and survived; `npm test` exports
    // it before Node starts, which is the only place that works.
  },
});
