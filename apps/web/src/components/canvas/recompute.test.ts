import { describe, expect, it } from "vitest";

import { behaviourOf, forget, heldFor, holds, remember } from "./recompute";
import type { WorkshopVariable } from "../../lib/types";

/** p.76's recompute behaviours (Foundry `workshop` p.76, p.85).
 *
 * The bookkeeping, not the values: which variables hold, what goes on the
 * wire, what comes back into memory. Worth testing this hard because every
 * mistake here is a variable that is silently one resolve out of date — the
 * failure mode has no error and no visible symptom until somebody compares two
 * numbers that should agree.
 */

const variable = (
  id: string, extra: Partial<WorkshopVariable> = {},
): WorkshopVariable => ({ id, kind: "string", label: id, ...extra } as WorkshopVariable);

const derived = (id: string, recompute?: string) =>
  variable(id, {
    derivation: { transform: "concat", inputs: ["v_in"] },
    ...(recompute ? { recompute } : {}),
  } as Partial<WorkshopVariable>);

const DECLARED: Record<string, WorkshopVariable> = {
  v_static: variable("v_static"),
  v_auto: derived("v_auto"),
  v_event: derived("v_event", "only_on_event"),
  v_load: derived("v_load", "on_load_and_event"),
};

describe("behaviourOf", () => {
  it("defaults an absent field to automatic", () => {
    // **A stored "automatic" and a missing field must mean the same thing**, or
    // upgrading the platform would change what every module written before
    // this existed does.
    expect(behaviourOf(variable("v"))).toBe("automatic");
    expect(behaviourOf(undefined)).toBe("automatic");
    expect(behaviourOf(variable("v", { recompute: "automatic" } as never))).toBe("automatic");
  });

  it("reads p.76's other two", () => {
    expect(behaviourOf(DECLARED.v_event)).toBe("only_on_event");
    expect(behaviourOf(DECLARED.v_load)).toBe("on_load_and_event");
  });

  it("treats an unknown behaviour as automatic", () => {
    // The server refuses one at save, so reaching here means a document from
    // somewhere else - and the safe reading is the one that recomputes, not
    // the one that pins a value nothing can refresh.
    expect(behaviourOf(variable("v", { recompute: "sometimes" } as never))).toBe("automatic");
  });
});

describe("holds", () => {
  it("is true only for a derived variable off Automatic", () => {
    expect(holds(DECLARED.v_event)).toBe(true);
    expect(holds(DECLARED.v_load)).toBe(true);
    expect(holds(DECLARED.v_auto)).toBe(false);
    expect(holds(undefined)).toBe(false);
  });

  it("refuses a static variable even if the document marks it", () => {
    // **The check the server already makes, made again.** A static variable
    // wrongly marked would be sent as held and pinned forever, and nothing on
    // screen would say why it stopped following its control.
    expect(holds(variable("v", { recompute: "only_on_event" } as never))).toBe(false);
  });
});

describe("heldFor", () => {
  it("sends what is remembered for the variables that still hold", () => {
    const remembered = { v_event: "one", v_load: "two" };
    expect(heldFor(DECLARED, remembered)).toEqual({ v_event: "one", v_load: "two" });
  });

  it("drops an entry whose variable no longer holds", () => {
    // The author moved it back to Automatic, or deleted it. The server would
    // ignore the entry, but keeping it alive in the request forever makes the
    // wire unreadable when something does go wrong.
    const remembered = { v_event: "one", v_auto: "stale", v_gone: "older" };
    expect(heldFor(DECLARED, remembered)).toEqual({ v_event: "one" });
  });

  it("sends nothing before anything has been captured", () => {
    expect(heldFor(DECLARED, {})).toEqual({});
  });
});

describe("remember", () => {
  it("captures a holding variable the server just computed", () => {
    // First load: nothing was sent, so what came back is the fresh value. The
    // resolved map carries *every* variable - the server evaluates the whole
    // document - so `v_event` is in it too, as the null p.76 says it should be
    // before its first event.
    const next = remember(
      DECLARED, {}, {}, { v_load: "computed", v_event: null, v_auto: "ignored" },
    );
    expect(next).toEqual({ v_load: "computed", v_event: null });
  });

  it("captures a null for only_on_event, which is its whole point", () => {
    // p.76: recomputed "only when explicitly triggered". Before the first
    // event it genuinely has no value. **Capturing the null is what pins it**
    // - without it the variable reads as never-captured and would compute the
    // next time anything else changed.
    const next = remember(DECLARED, {}, {}, { v_event: null });
    expect(next).toHaveProperty("v_event", null);
    expect("v_event" in next).toBe(true);
  });

  it("carries a held value rather than re-reading the echo", () => {
    // **The hazard this avoids**: a resolve that raced a recompute would echo
    // the old value, and re-capturing it would put the stale number straight
    // back after the event had just cleared it.
    const next = remember(
      DECLARED, { v_load: "held" }, { v_load: "held" }, { v_load: "held" },
    );
    expect(next.v_load).toBe("held");
  });

  it("never remembers a variable that does not hold", () => {
    const next = remember(DECLARED, {}, {}, { v_auto: "x", v_static: "y" });
    expect(next).not.toHaveProperty("v_auto");
    expect(next).not.toHaveProperty("v_static");
  });

  it("forgets a variable that has left the document", () => {
    const next = remember(DECLARED, { v_gone: "old" }, { v_gone: "old" }, {});
    expect(next).not.toHaveProperty("v_gone");
  });
});

describe("forget", () => {
  it("drops the variables a recompute event named", () => {
    const remembered = { v_event: "one", v_load: "two" };
    expect(forget(DECLARED, remembered, ["v_event"])).toEqual({ v_load: "two" });
  });

  it("ignores a name that does not hold", () => {
    // The server refuses a recompute aimed at a static or Automatic variable
    // at save time, so one arriving here means the document moved underneath
    // the event - skipped, like every other effect whose target has gone.
    const remembered = { v_event: "one" };
    expect(forget(DECLARED, remembered, ["v_auto", "v_static", "v_gone"]))
      .toBe(remembered);
  });

  it("returns the same object when there is nothing to drop", () => {
    // Identity, not just equality: the bridge stores this in React state, and
    // a fresh object every render would resolve in a loop.
    const remembered = { v_event: "one" };
    expect(forget(DECLARED, remembered, [])).toBe(remembered);
  });
});
