import { describe, expect, it } from "vitest";

import { heldBy, strandedSummary } from "./state-impact";

describe("p.203's warning before a save (§740)", () => {
  it("names the states that hold a key, and counts the rest", () => {
    expect(heldBy(["Monday"])).toBe("Monday");
    expect(heldBy(["Monday", "Tuesday"])).toBe("Monday and Tuesday");
    expect(heldBy(["Monday", "Tuesday", "Wednesday"])).toBe("Monday, Tuesday and 1 more");
    expect(heldBy(["A", "B", "C", "D", "E"], 3)).toBe("A, B, C and 2 more");
    expect(heldBy(["A", "B", "C"], 3)).toBe("A, B and C");
    expect(heldBy([])).toBe("");
  });

  it("counts each state once, however many of its keys go", () => {
    expect(strandedSummary([
      { external_id: "region", states: ["Monday", "Tuesday"] },
      { external_id: "status", states: ["Monday"] },
    ])).toBe("2 saved states will reopen without 2 values this save stops reading.");
    expect(strandedSummary([{ external_id: "region", states: ["Monday"] }]))
      .toBe("1 saved state will reopen without a value this save stops reading.");
  });
});
