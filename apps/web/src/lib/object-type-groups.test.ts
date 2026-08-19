/**
 * Object type groups, as a form needs them (Foundry `object-link-types`
 * p.261-263).
 *
 * **`sameSelection` is why this file exists.** Membership is its own resource
 * with its own verb, so the object type's PATCH cannot carry it — but the edit
 * dialog holds both, and a dialog that PUT the groups on every save would
 * reintroduce the carry-through failure one layer up: open the dialog, someone
 * else files the type under a group, change a description, save, and the
 * grouping is gone.
 *
 * The fix is to send nothing when nothing changed, which makes this comparison
 * load-bearing and silent when wrong in *either* direction — always-true drops
 * edits, always-false clobbers other people's. So it is a pure function with
 * its own tests rather than an inline `JSON.stringify`.
 */
import { describe, expect, it } from "vitest";

import {
  groupSummary, memberSummary, sameSelection, toGroupApiName, toggleSelection,
} from "./object-type-groups";

function refs(...names: string[]) {
  return names.map((display_name, i) => ({
    id: `id-${i}`,
    api_name: display_name.toLowerCase(),
    display_name,
  }));
}

describe("sameSelection", () => {
  it("ignores order", () => {
    // The two sides come from different places: the server sorts by display
    // name, and a person ticks boxes in whatever order they like. A comparison
    // that cared would report a change on every save and undo the point of
    // asking.
    expect(sameSelection(["a", "b"], ["b", "a"])).toBe(true);
  });

  it("sees an addition and a removal", () => {
    expect(sameSelection(["a"], ["a", "b"])).toBe(false);
    expect(sameSelection(["a", "b"], ["a"])).toBe(false);
  });

  it("sees a swap of the same size", () => {
    // The case a length check alone would miss, and the one that matters:
    // moving a type from one group to another keeps the count.
    expect(sameSelection(["a", "b"], ["a", "c"])).toBe(false);
  });

  it("treats two empty selections as unchanged", () => {
    // An ungrouped type saved again must not PUT an empty membership — the
    // request would succeed and look identical, which is exactly how a clobber
    // hides.
    expect(sameSelection([], [])).toBe(true);
  });

  it("does not call a duplicate a difference", () => {
    // A list naming the same group twice is the same request as naming it
    // once (the server dedupes it), so reporting a change here would issue a
    // PUT that changes nothing.
    expect(sameSelection(["a"], ["a", "a"])).toBe(false);
    expect(sameSelection(["a", "a"], ["a", "a"])).toBe(true);
  });
});

describe("toggleSelection", () => {
  it("adds and removes", () => {
    expect(toggleSelection([], "a")).toEqual(["a"]);
    expect(toggleSelection(["a", "b"], "a")).toEqual(["b"]);
  });

  it("does not mutate what it was given", () => {
    // React state mutated in place re-renders with the old value, which reads
    // as a checkbox that will not tick.
    const before = ["a"];
    toggleSelection(before, "b");
    expect(before).toEqual(["a"]);
  });
});

describe("groupSummary", () => {
  it("names a couple and counts the rest", () => {
    expect(groupSummary(refs("Logistics", "Finance", "People"))).toBe(
      "Logistics, Finance +1",
    );
  });

  it("names them all when they fit", () => {
    expect(groupSummary(refs("Logistics"))).toBe("Logistics");
  });

  it("says nothing at all for an ungrouped type", () => {
    // Not "0 groups". An ungrouped object type is the ordinary case — p.261
    // makes grouping something somebody does, not something every type has —
    // so labelling its absence would be noise on most of an ontology.
    expect(groupSummary([])).toBeNull();
  });
});

describe("memberSummary", () => {
  it("says zero rather than nothing", () => {
    // p.263: "all groups will now be discoverable to any user that can view
    // the ontology". An empty group is a group, and a listing that went quiet
    // for zero would hint at the behaviour p.263 describes having removed.
    expect(memberSummary(0)).toBe("0 object types");
  });

  it("agrees with itself about plurals", () => {
    expect(memberSummary(1)).toBe("1 object type");
    expect(memberSummary(4)).toBe("4 object types");
  });
});

describe("toGroupApiName", () => {
  it("makes a machine name from what somebody typed", () => {
    expect(toGroupApiName("Logistics & Supply")).toBe("logistics_supply");
  });

  it("survives a name with nothing usable in it", () => {
    expect(toGroupApiName("!!!")).toBe("");
  });
});
