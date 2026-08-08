import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Only the pure-function tests. The browser suite is `e2e/`, in Python,
    // against real servers — see `apps/web/src/components/canvas/pure.ts` for
    // why that boundary is drawn and kept.
    include: ["src/**/*.test.ts"],

    // **Deliberately not UTC.** The time-series labels are formatted in UTC on
    // purpose, and on a machine whose clock is already UTC a test of that
    // proves nothing: deleting the `timeZone: "UTC"` option is invisible. A
    // mutation confirmed it — the check passed against code with the option
    // removed, because this container runs in UTC.
    //
    // New York is chosen because it is *behind* UTC, so an instant at the very
    // start of a UTC day falls on the previous local day. A zone ahead of UTC
    // (Tokyo, Kiritimati) would leave a midnight-UTC bucket on the same date
    // and hide the bug again — the same trap a mutation on the browser suite
    // fell into in `STATUS.md` §106.
    env: { TZ: "America/New_York" },
  },
});
