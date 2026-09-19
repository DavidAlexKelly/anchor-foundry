import { describe, expect, it } from "vitest";
import type { ModuleActionUsage } from "./types";
import {
  change, changeLabel, emptyReason, previousTotal, rising, scopeNote, share,
  total, usageLabel,
} from "./workshop-metrics";

function row(over: Partial<ModuleActionUsage> = {}): ModuleActionUsage {
  return {
    action_type_id: "a1", display_name: "Ship", api_name: "ship",
    submissions: 10, previous: 5,
    used_by: [{ node: "form", via: "widget" }],
    ...over,
  };
}

describe("what the panel says the numbers are about", () => {
  it("says the count is not scoped to this module", () => {
    // **The load-bearing sentence.** "Submissions" over a module's action list
    // reads as "submissions made here" to anybody who has not read p.186, and
    // they would be wrong by however much the action is used elsewhere.
    expect(scopeNote()).toContain("outside this module");
  });
});

describe("the overview card", () => {
  it("totals what is listed", () => {
    expect(total([row({ submissions: 3 }), row({ submissions: 4 })])).toBe(7);
    expect(previousTotal([row({ previous: 1 }), row({ previous: 2 })])).toBe(3);
  });

  it("is zero for a module with no actions", () => {
    expect(total([])).toBe(0);
  });
});

describe("the change against the period before", () => {
  it("is a percentage of the previous period", () => {
    expect(change(15, 10)).toBeCloseTo(50);
    expect(change(5, 10)).toBeCloseTo(-50);
  });

  it("refuses to report a trend from nothing", () => {
    // A jump from zero is not "+100%", it is a first period - and a percentage
    // there invites somebody to read a trend off one data point.
    expect(change(12, 0)).toBeNull();
    expect(changeLabel(12, 0)).toBeNull();
  });

  it("does not call zero-to-zero steady", () => {
    // `0%` would read as "steady", which is a claim about a comparison that
    // was never made.
    expect(change(0, 0)).toBeNull();
  });

  it("rounds to whole percent, because a tenth is noise dressed as precision", () => {
    expect(changeLabel(103, 100)).toBe("+3%");
    expect(changeLabel(97, 100)).toBe("-3%");
  });

  it("says so in words when nothing moved", () => {
    expect(changeLabel(100, 100)).toBe("no change");
  });

  it("tells up, down and cannot-say apart", () => {
    expect(rising(15, 10)).toBe(true);
    expect(rising(5, 10)).toBe(false);
    expect(rising(10, 10)).toBeNull();
    expect(rising(10, 0)).toBeNull();
  });
});

describe("the proportional bar", () => {
  it("is relative to the busiest action, not to the total", () => {
    // **A module with twelve actions would otherwise draw twelve slivers.**
    // The comparison a reader is making is between the rows: which is busiest,
    // and by how much.
    const rows = [row({ submissions: 10 }), row({ submissions: 5 })];
    expect(share(rows[0]!, rows)).toBe(100);
    expect(share(rows[1]!, rows)).toBe(50);
  });

  it("draws nothing when nothing has been submitted", () => {
    // Rather than twelve full bars from dividing by itself.
    const rows = [row({ submissions: 0 }), row({ submissions: 0 })];
    expect(share(rows[0]!, rows)).toBe(0);
  });
});

describe("an empty panel", () => {
  it("tells a module with no actions from one whose actions are unused", () => {
    // **Different facts.** A module that runs no actions has nothing to
    // report; a module whose action nobody has used has something to report
    // and the answer is zero. Collapsing them would tell a builder their
    // action is unused when they never wired one up.
    expect(emptyReason([])).toContain("does not run any actions");
    expect(emptyReason([row({ submissions: 0 })])).toBeNull();
  });
});

describe("where an action is used", () => {
  it("counts widgets and events separately", () => {
    expect(usageLabel(row({
      used_by: [
        { node: "f", via: "widget" },
        { node: "b", via: "event" },
        { node: "c", via: "event" },
      ],
    }))).toBe("1 widget, 2 events");
  });

  it("does not name a kind that is not there", () => {
    expect(usageLabel(row())).toBe("1 widget");
  });

  it("says something rather than nothing for an empty list", () => {
    // A blank cell reads as a bug rather than as an empty list.
    expect(usageLabel(row({ used_by: [] }))).toBe("not used");
  });
});
