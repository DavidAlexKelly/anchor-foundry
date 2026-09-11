import { describe, expect, it } from "vitest";
import {
  TYPE_PAGE, emptyNote, needsSearch, truncationNote, withSelected,
} from "./type-picker";
import type { ObjectTypeSummary } from "./types";

function type(id: string, api_name = id): ObjectTypeSummary {
  return {
    id,
    api_name,
    display_name: api_name,
    description: "",
    icon: "",
    colour: "",
    title_property_id: null,
    source_count: 0,
  failing_source_count: 0,
  source_error: null,
    hidden_properties: [],
    resource_id: `r-${id}`,
    status: "experimental",
    deprecation: null,
    groups: [],
    interfaces: [],
    created_at: "",
    updated_at: "",
  };
}

describe("needsSearch", () => {
  it("is decided by the total, not by what fitted on the page", () => {
    // A page of fifty looks identical whether the workspace holds fifty or six
    // hundred. Telling them apart is the whole reason the total is sent.
    expect(needsSearch(TYPE_PAGE)).toBe(false);
    expect(needsSearch(TYPE_PAGE + 1)).toBe(true);
  });

  it("leaves a small ontology alone", () => {
    // A search box over eight types is a control nobody needed.
    expect(needsSearch(8)).toBe(false);
  });

  it("does not vanish while a search is still in the box", () => {
    // **Found by a browser test, not reasoned out.** The total a picker holds
    // is the total *matching the current search*, so narrowing 791 types to
    // one used to make this false and take the box off the screen mid-word,
    // with the query still applied. §246's shape: a control that disappears as
    // a consequence of being used.
    expect(needsSearch(1, "veh")).toBe(true);
    // And whitespace is not a search, so it does not pin the box open.
    expect(needsSearch(1, "   ")).toBe(false);
  });
});

describe("truncationNote", () => {
  it("says nothing when the whole set is on screen", () => {
    expect(truncationNote(8, 8)).toBeNull();
  });

  it("names both numbers and what to do about it", () => {
    const note = truncationNote(50, 613);
    expect(note).toContain("50");
    expect(note).toContain("613");
    // A count alone is a fact; this has to be an instruction.
    expect(note).toContain("search");
  });
});

describe("withSelected", () => {
  const page = [type("a"), type("b")];

  it("leaves the page alone when nothing is chosen", () => {
    expect(withSelected(page, null)).toEqual(page);
  });

  it("leaves the page alone when the choice is already on it", () => {
    expect(withSelected(page, type("a"))).toEqual(page);
  });

  it("puts the chosen type back when a search dropped it", () => {
    // **The invariant: a select's value is always among its options.** Without
    // this the control renders blank and the next save writes the blank — the
    // type is changed by a search somebody typed and then cleared (§175).
    const out = withSelected(page, type("z"));
    expect(out.map((t) => t.id)).toEqual(["z", "a", "b"]);
  });

  it("does not duplicate it when the id matches under a different name", () => {
    // The same type, re-fetched: same id, and only one option for it.
    const renamed = { ...type("a"), display_name: "Renamed" };
    expect(withSelected(page, renamed).map((t) => t.id)).toEqual(["a", "b"]);
  });
});

describe("emptyNote", () => {
  it("tells a fruitless search apart from an empty ontology", () => {
    // Different problems with different next steps.
    expect(emptyNote(0, "veh")).toContain("veh");
    expect(emptyNote(0, "  ")).toContain("declare one");
  });
});
