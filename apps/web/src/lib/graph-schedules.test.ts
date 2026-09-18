/** Scheduling from the lineage graph (§387; `data-lineage` p.10). */
import { describe, expect, it } from "vitest";
import type { PlannedModel } from "./graph-builds";
import { alreadyScheduled, clearSummary, looksLikeCron, scheduleSummary } from "./graph-schedules";

const model = (name: string, trigger_mode: string | null = "manual"): PlannedModel =>
  ({ id: `${name}-res`, name, layer: 0, trigger_mode });

describe("which of the selected already run on a schedule", () => {
  it("takes the cron ones and leaves the rest", () => {
    const found = alreadyScheduled([model("a", "cron"), model("b"), model("c", "upstream")]);
    expect(found.map((m) => m.name)).toEqual(["a"]);
  });

  it("does not count an upstream-triggered model as scheduled", () => {
    // **The distinction that matters here.** An upstream model fires on its
    // inputs, not on a clock; calling it scheduled would have the control
    // report it as something a cron expression is about to replace.
    expect(alreadyScheduled([model("b", "upstream")])).toEqual([]);
  });
});

describe("what setting a schedule would do", () => {
  it("counts the transforms it would schedule", () => {
    expect(scheduleSummary([model("a"), model("b")])).toBe("schedule 2 transforms");
  });

  it("says what it would replace, and names them while it can", () => {
    // §214: replacing two schedules while the reader believes they are
    // setting one is the reading this prevents. p.10 says "set and edit", so
    // the overwrite is correct — being quiet about it would not be.
    expect(scheduleSummary([model("a", "cron"), model("b", "cron"), model("c")]))
      .toBe("schedule 3 transforms, replacing 2 existing (a, b)");
  });

  it("stops naming them when there are too many to read", () => {
    const many = ["a", "b", "c", "d"].map((n) => model(n, "cron"));
    expect(scheduleSummary(many)).toBe("schedule 4 transforms, replacing 4 existing");
  });

  it("asks for a selection when there is none", () => {
    expect(scheduleSummary([])).toContain("select a dataset");
  });
});

describe("what clearing would do", () => {
  it("counts only the schedules there are to clear", () => {
    expect(clearSummary([model("a", "cron"), model("b")])).toBe("clear 1 schedule");
    expect(clearSummary([model("a", "cron"), model("b", "cron")])).toBe("clear 2 schedules");
  });

  it("says nothing when there is nothing to clear", () => {
    // Not "clear 0 schedules": the control is absent rather than offered over
    // a selection it would not change.
    expect(clearSummary([model("a"), model("b", "upstream")])).toBe("");
    expect(clearSummary([])).toBe("");
  });
});

describe("whether a box holds something shaped like a cron expression", () => {
  it("takes five fields", () => {
    expect(looksLikeCron("0 * * * *")).toBe(true);
    expect(looksLikeCron("  15 3 * * 1  ")).toBe(true);
  });

  it("refuses what was never going to be one", () => {
    // An empty box is refused **by the field count**: a trimmed empty string
    // splits to one field, not five. The first draft also checked each field
    // was non-empty, which no mutation could make fail — trimmed input never
    // produces an empty field at all — so it is gone (§213).
    expect(looksLikeCron("")).toBe(false);
    expect(looksLikeCron("   ")).toBe(false);
    expect(looksLikeCron("0 * * *")).toBe(false);
    expect(looksLikeCron("0 * * * * *")).toBe(false);
  });

  it("does not try to be the validator", () => {
    // **Deliberately passes an expression `croniter` will reject.** The server
    // parses it and refuses it by name; a second validator here would be a
    // second opinion that disagrees the first time either changes (§191).
    // This only stops a request that was visibly unfinished.
    expect(looksLikeCron("99 99 99 99 99")).toBe(true);
  });
});
