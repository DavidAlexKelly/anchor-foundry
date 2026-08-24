import { describe, expect, it } from "vitest";

import {
  behaviourOf, heldFor, holds, remember, request, requested, settled,
} from "./recompute";
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

  it("leaves out a variable with a recompute pending", () => {
    // **So the answer is the fresh value and `remember` captures it.** Left in,
    // the server would echo the stale value straight back and the event would
    // have changed nothing.
    const remembered = { v_event: "one", v_load: "two" };
    expect(heldFor(DECLARED, remembered, new Set(["v_load"])))
      .toEqual({ v_event: "one" });
  });
});

describe("request", () => {
  it("records the names a recompute event fired for", () => {
    expect([...request(DECLARED, new Set(), ["v_event"])]).toEqual(["v_event"]);
  });

  it("keeps asks that have not been answered yet", () => {
    const pending = new Set(["v_event"]);
    expect([...request(DECLARED, pending, ["v_load"])].sort())
      .toEqual(["v_event", "v_load"]);
  });

  it("returns the same set when the name does not hold", () => {
    // Identity, not just equality: the bridge compares the two to decide
    // whether a resolve is worth making, and a fresh set every time would make
    // a click on a stale button cost a request.
    const pending = new Set(["v_event"]);
    expect(request(DECLARED, pending, ["v_auto", "v_static", "v_gone"]))
      .toBe(pending);
    expect(request(DECLARED, pending, [])).toBe(pending);
  });

  it("returns the same set when the ask is already pending", () => {
    const pending = new Set(["v_event"]);
    expect(request(DECLARED, pending, ["v_event"])).toBe(pending);
  });
});

describe("requested", () => {
  it("sends the pending asks", () => {
    expect(requested(DECLARED, new Set(["v_event"]))).toEqual(["v_event"]);
  });

  it("drops an ask whose variable stopped holding", () => {
    // The author moved it to Automatic between the click and the request.
    expect(requested(DECLARED, new Set(["v_auto", "v_gone"]))).toEqual([]);
  });
});

describe("settled", () => {
  it("drops the asks the resolve carried", () => {
    expect([...settled(new Set(["v_event", "v_load"]), ["v_event"])])
      .toEqual(["v_load"]);
  });

  it("keeps an ask fired while the request was in flight", () => {
    // **The reason this takes `sent` rather than clearing the set**, walked
    // through: one event fires, its request goes out, a second event fires
    // before the answer lands. That resolve did not answer `v_load` - it did
    // not know about it - so `v_load` has to still be pending afterwards, or
    // the second event vanishes with nothing to show for it.
    let pending = request(DECLARED, new Set(), ["v_event"]);
    const sent = requested(DECLARED, pending);
    pending = request(DECLARED, pending, ["v_load"]);

    pending = settled(pending, sent);
    expect([...pending]).toEqual(["v_load"]);
  });

  it("returns the same set when the resolve carried no asks", () => {
    const pending = new Set(["v_event"]);
    expect(settled(pending, [])).toBe(pending);
    expect(settled(pending, ["v_load"])).toBe(pending);
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
    // **The hazard this avoids**: a resolve that raced a recompute echoes what
    // *that* request sent, which is not what is held any more. Re-capturing it
    // would put the stale value straight back after the event had cleared it.
    //
    // So the three arguments have to differ. Written with all three the same -
    // which is how this test started - it passes whichever way round the two
    // branches go, and the mutation harness said so.
    const next = remember(
      DECLARED, { v_load: "current" }, { v_load: "current" }, { v_load: "a stale echo" },
    );
    expect(next.v_load).toBe("current");
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

describe("a recompute, end to end", () => {
  it("asks, captures the fresh value, and goes back to holding", () => {
    // **The bookkeeping half of the loop the browser test walks.** Written as
    // one sequence because the bug it guards is not in any single step: each of
    // these calls can be right on its own while the round trip still leaves the
    // variable recomputing forever, or pinned forever.
    let remembered: Record<string, unknown> = { v_event: "old" };
    let pending: ReadonlySet<string> = new Set();

    pending = request(DECLARED, pending, ["v_event"]);
    const asks = requested(DECLARED, pending);
    const sent = heldFor(DECLARED, remembered, pending);
    // Nothing held goes out for it, and the ask does - so the server computes.
    expect(sent).toEqual({});
    expect(asks).toEqual(["v_event"]);

    remembered = remember(DECLARED, remembered, sent, { v_event: "new" });
    pending = settled(pending, asks);
    expect(remembered.v_event).toBe("new");

    // And the next resolve holds it again, rather than recomputing every time.
    expect(requested(DECLARED, pending)).toEqual([]);
    expect(heldFor(DECLARED, remembered, pending)).toEqual({ v_event: "new" });
  });
});
