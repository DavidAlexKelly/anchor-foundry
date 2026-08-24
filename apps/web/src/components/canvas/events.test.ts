import { describe, expect, it, vi } from "vitest";

import { run } from "./event-run";
import type { EventContext, WorkshopEventDef } from "./event-run";

/** Running a widget's events (Foundry `workshop` p.80, p.85).
 *
 * `run` had no unit tests before §193, which is why the rule it exists to
 * enforce was only ever asserted through a browser:
 *
 * > "Events in Workshop execute sequentially based on their configuration
 * > order." (p.80)
 *
 * That matters most where two effects touch the same variable in opposite
 * directions — a Set and p.85's Reset — because one is a write and the other a
 * deletion, and they are applied through different capabilities at the end of
 * the run. Whichever came *last* has to be the one that survives, and nothing
 * about the code's shape makes that automatic.
 */

function contextWith(overrides: Partial<EventContext> = {}) {
  const setVariables = vi.fn();
  const resetVariables = vi.fn();
  const context: EventContext = { setVariables, resetVariables, ...overrides };
  return { context, setVariables, resetVariables };
}

const event = (...effects: { type: string; config?: Record<string, unknown> }[]):
WorkshopEventDef => ({ id: "e_1", trigger: { node: "btn", on: "click" }, effects });

const set = (variable: string, value: unknown) =>
  ({ type: "set_variable", config: { variable, value } });
const reset = (variable: string) => ({ type: "reset_variable", config: { variable } });

describe("reset_variable (p.85)", () => {
  it("asks for the variable to be forgotten", () => {
    const { context, resetVariables, setVariables } = contextWith();
    run([event(reset("v_a"))], context);
    expect(resetVariables).toHaveBeenCalledWith(["v_a"]);
    // **A deletion, never a write of the default.** Writing the default would
    // be wrong for a variable an embedding module has mapped, whose definition
    // is the parent's (p.128) - and the child does not have that value.
    expect(setVariables).not.toHaveBeenCalled();
  });

  it("collects several resets into one call", () => {
    // One click is one render, the same argument `setMany` makes.
    const { context, resetVariables } = contextWith();
    run([event(reset("v_a"), reset("v_b"))], context);
    expect(resetVariables).toHaveBeenCalledTimes(1);
    expect(resetVariables.mock.calls[0]![0]).toEqual(["v_a", "v_b"]);
  });

  it("skips a reset with no variable rather than throwing", () => {
    // Same rule as every other effect: a click that does part of its job beats
    // one that throws in the middle of the list.
    const { context, resetVariables } = contextWith();
    run([event({ type: "reset_variable", config: {} }, set("v_a", "x"))], context);
    expect(resetVariables).not.toHaveBeenCalled();
  });

  it("is skipped when the runtime has no reset capability", () => {
    // A widget rendered outside a `VariableBridge` - a Craft preview, a test.
    const context: EventContext = { setVariables: vi.fn() };
    expect(() => run([event(reset("v_a"))], context)).not.toThrow();
  });
});

describe("recompute (p.85)", () => {
  const recompute = (variable: string) => ({ type: "recompute", config: { variable } });

  it("asks for the variable to be recomputed", () => {
    const recomputeVariables = vi.fn();
    const { context } = contextWith({ recomputeVariables });
    run([event(recompute("v_a"))], context);
    expect(recomputeVariables).toHaveBeenCalledWith(["v_a"]);
  });

  it("collects several recomputes into one call", () => {
    const recomputeVariables = vi.fn();
    const { context } = contextWith({ recomputeVariables });
    run([event(recompute("v_a"), recompute("v_b"))], context);
    expect(recomputeVariables).toHaveBeenCalledTimes(1);
    expect(recomputeVariables.mock.calls[0]![0]).toEqual(["v_a", "v_b"]);
  });

  it("does not route a recompute through the reset capability", () => {
    // **The two forget different things.** A reset forgets what the *viewer*
    // set; a recompute forgets what the *server* computed. Sending one down
    // the other's path would clear a viewer's filter selection when they
    // clicked a refresh button.
    const recomputeVariables = vi.fn();
    const { context, resetVariables, setVariables } = contextWith({ recomputeVariables });
    run([event(recompute("v_a"))], context);
    expect(resetVariables).not.toHaveBeenCalled();
    expect(setVariables).not.toHaveBeenCalled();
  });

  it("skips a recompute with no variable rather than throwing", () => {
    const recomputeVariables = vi.fn();
    const { context } = contextWith({ recomputeVariables });
    run([event({ type: "recompute", config: {} }, set("v_a", "x"))], context);
    expect(recomputeVariables).not.toHaveBeenCalled();
  });

  it("is skipped when the runtime has no recompute capability", () => {
    // A widget rendered outside a `VariableBridge` - a Craft preview, a test.
    const context: EventContext = { setVariables: vi.fn() };
    expect(() => run([event(recompute("v_a"))], context)).not.toThrow();
  });
});

describe("a Set and a Reset of the same variable (p.80's ordering)", () => {
  it("lets a Reset that comes second win", () => {
    const { context, setVariables, resetVariables } = contextWith();
    const written = run([event(set("v_a", "x"), reset("v_a"))], context);
    expect(resetVariables).toHaveBeenCalledWith(["v_a"]);
    // The pending write is discarded rather than left to race the deletion.
    expect(written).toEqual({});
    expect(setVariables).not.toHaveBeenCalled();
  });

  it("lets a Set that comes second win", () => {
    const { context, setVariables, resetVariables } = contextWith();
    const written = run([event(reset("v_a"), set("v_a", "x"))], context);
    expect(written).toEqual({ v_a: "x" });
    expect(setVariables).toHaveBeenCalledWith({ v_a: "x" });
    // And the reset is dropped, so the write is not undone a moment later.
    expect(resetVariables).not.toHaveBeenCalled();
  });

  it("keeps a Set and a Reset of *different* variables apart", () => {
    const { context, setVariables, resetVariables } = contextWith();
    run([event(set("v_a", "x"), reset("v_b"))], context);
    expect(setVariables).toHaveBeenCalledWith({ v_a: "x" });
    expect(resetVariables).toHaveBeenCalledWith(["v_b"]);
  });

  it("settles on the last instruction however many times they alternate", () => {
    // The two piles have to stay disjoint through the whole list, not just
    // across one swap - which is what makes the order of the two calls at the
    // end unable to matter.
    const { context, setVariables, resetVariables } = contextWith();
    run([event(set("v_a", "1"), reset("v_a"), set("v_a", "2"), reset("v_a"))], context);
    expect(resetVariables).toHaveBeenCalledWith(["v_a"]);
    expect(setVariables).not.toHaveBeenCalled();
  });
});

describe("set_variable still behaves as p.80 says", () => {
  it("copies the value immediately, so the next effect sees it", () => {
    const { context, setVariables } = contextWith();
    const written = run([event(set("v_a", "north"), set("v_b", "{{v_a}}"))], context);
    // Not an assertion about interpolation - `{{v_a}}` reads the *payload*,
    // not another variable - but it does pin that both writes land in one call.
    expect(Object.keys(written).sort()).toEqual(["v_a", "v_b"]);
    expect(setVariables).toHaveBeenCalledTimes(1);
  });

  it("writes nothing when a widget's events do nothing", () => {
    const { context, setVariables, resetVariables } = contextWith();
    expect(run([event()], context)).toEqual({});
    expect(setVariables).not.toHaveBeenCalled();
    expect(resetVariables).not.toHaveBeenCalled();
  });
});
