import { describe, expect, it } from "vitest";

import {
  DEFAULT_SEARCH_MODE, DEFAULT_SORT, PAGE_LIMIT, SEARCH_MODES, SORTS,
  allowNoSelectionOf, isSearchable, labelOf, matchesQuery, propertyListOf,
  searchModeOf, searchProperties, sortOf, titleOf, truncationNote,
} from "./object-dropdown";

/** p.455-458's Object Dropdown. */

const ALL = [
  { api_name: "name", display_name: "Name", data_type: "string" },
  { api_name: "region", display_name: "Region", data_type: "string" },
  { api_name: "capacity", display_name: "Capacity", data_type: "integer" },
  { api_name: "note", display_name: "Note", data_type: "string" },
];

function scope(over: Partial<Parameters<typeof searchProperties>[0]> = {}) {
  return searchProperties({
    mode: undefined, all: ALL, shown: ["name", "capacity"], specific: "", ...over,
  });
}

describe("p.458's search modes", () => {
  it("has the three p.458 names and defaults to on-screen", () => {
    expect(Object.keys(SEARCH_MODES).sort()).toEqual(["all", "on_screen", "specific"]);
    expect(DEFAULT_SEARCH_MODE).toBe("on_screen");
    expect(searchModeOf(undefined)).toBe("on_screen");
    expect(searchModeOf("all")).toBe("all");
    expect(searchModeOf("specific")).toBe("specific");
  });

  it("falls back for a mode the widget does not have", () => {
    expect(searchModeOf("everything")).toBe("on_screen");
    expect(searchModeOf("constructor")).toBe("on_screen");
    expect(searchModeOf(2)).toBe("on_screen");
  });
});

describe("which properties a search runs on", () => {
  it("searches the displayed string properties by default", () => {
    // p.458: "all **string** properties that are displayed". `capacity` is
    // displayed and is an integer, so it is not one of them — and the fixture
    // shows it deliberately, or the type filter would have nothing to remove.
    expect(scope()).toEqual(["name"]);
  });

  it("searches the configured properties when told to", () => {
    expect(scope({ mode: "specific", specific: "region, note" }))
      .toEqual(["region", "note"]);
  });

  it("searches every string property of the type when told to", () => {
    // Not the displayed ones: `region` and `note` are searched here and are
    // not on screen, which is the whole difference between this mode and the
    // default.
    expect(scope({ mode: "all" })).toEqual(["name", "region", "note"]);
  });

  it("drops a configured property the type no longer has", () => {
    // A stale name would make the box match nothing and read as a broken
    // widget rather than a stale configuration.
    expect(scope({ mode: "specific", specific: "region,gone" })).toEqual(["region"]);
  });

  it("drops a configured property that is not a string", () => {
    expect(scope({ mode: "specific", specific: "capacity,region" })).toEqual(["region"]);
  });

  it("does not repeat a property named twice", () => {
    expect(scope({ mode: "specific", specific: "region,region" })).toEqual(["region"]);
  });

  it("keeps the configured order rather than the type's", () => {
    expect(scope({ mode: "specific", specific: "note,region" })).toEqual(["note", "region"]);
  });

  it("treats a property with no declared type as a string", () => {
    // Every fixture in the browser suite declares `string`, and a type read
    // that omitted `data_type` would otherwise make the search box match
    // nothing at all.
    expect(isSearchable({ api_name: "x" })).toBe(true);
    expect(isSearchable({ api_name: "x", data_type: "string" })).toBe(true);
    expect(isSearchable({ api_name: "x", data_type: "integer" })).toBe(false);
  });
});

describe("what matching means", () => {
  const VALUES = { name: "North West Depot", region: "north", capacity: 40 };

  it("matches inside a value, not only at the start", () => {
    // **`starts_with` would pass a test written on "north".** The Exploration
    // Search Bar uses that operator because it narrows a set on the server;
    // this is a picker, and an option findable only by its first word is a
    // worse way to find it than scrolling.
    expect(matchesQuery(VALUES, "depot", ["name"])).toBe(true);
    expect(matchesQuery(VALUES, "North", ["name"])).toBe(true);
  });

  it("ignores case in both directions", () => {
    expect(matchesQuery(VALUES, "DEPOT", ["name"])).toBe(true);
    expect(matchesQuery({ name: "depot" }, "DEPOT", ["name"])).toBe(true);
  });

  it("only looks at the properties it was given", () => {
    // The point of p.458's setting: `region` holds "north" and is not searched.
    expect(matchesQuery(VALUES, "north", ["name"])).toBe(true);
    expect(matchesQuery(VALUES, "orth", ["region"])).toBe(true);
    expect(matchesQuery(VALUES, "orth", ["capacity"])).toBe(false);
  });

  it("matches everything while the box is empty", () => {
    // A dropdown that showed nothing until somebody typed would be a dropdown
    // with no list.
    expect(matchesQuery(VALUES, "", ["name"])).toBe(true);
    expect(matchesQuery(VALUES, "   ", ["name"])).toBe(true);
    expect(matchesQuery(VALUES, undefined, ["name"])).toBe(true);
    // Even with nothing to search on — the alternative is an empty widget
    // whenever a configuration names no searchable property.
    expect(matchesQuery(VALUES, "", [])).toBe(true);
  });

  it("matches nothing when there is nothing to search on", () => {
    expect(matchesQuery(VALUES, "depot", [])).toBe(false);
    expect(matchesQuery(undefined, "depot", ["name"])).toBe(false);
  });

  it("does not match a null through its own emptiness", () => {
    // `String(null)` is "null", so a search for "ul" would find every blank
    // property of every object.
    expect(matchesQuery({ name: null }, "ul", ["name"])).toBe(false);
    expect(matchesQuery({ name: undefined }, "efine", ["name"])).toBe(false);
  });

  it("searches values that are not strings", () => {
    // The *property* has to be a string type to be offered; the value that
    // arrives is whatever the store holds, and a number rendered in the list
    // should be findable by what it reads as.
    expect(matchesQuery({ capacity: 40 }, "4", ["capacity"])).toBe(true);
  });
});

describe("what an option is called", () => {
  it("is the title property's value", () => {
    expect(titleOf({ name: "Alpha" }, "name", "S1")).toBe("Alpha");
  });

  it("falls back to the primary key when there is no title to show", () => {
    // Each of these is a real state on real data, and an option with no text
    // is one nobody can pick on purpose.
    expect(titleOf({ name: null }, "name", "S1")).toBe("S1");
    expect(titleOf({ name: "   " }, "name", "S1")).toBe("S1");
    expect(titleOf({}, "name", "S1")).toBe("S1");
    expect(titleOf({ name: "Alpha" }, null, "S1")).toBe("S1");
    expect(titleOf(undefined, "name", "S1")).toBe("S1");
  });

  it("keeps a title that only looks empty", () => {
    expect(titleOf({ name: 0 }, "name", "S1")).toBe("0");
    expect(titleOf({ name: false }, "name", "S1")).toBe("false");
  });

  it("does not read a property called null when there is no title property", () => {
    // **`values[null]` is `values["null"]`, and `null` matches the api-name
    // pattern** (`^[a-z][a-z0-9_]{0,99}$`), so a guard that checked only
    // whether there were values would make "this type has no title property"
    // depend on whether some property happens to be called that. The harness
    // found it; the input is exotic and the confusion is not.
    expect(titleOf({ null: "Weird" }, null, "S1")).toBe("S1");
  });
});

describe("p.457's allow no selection", () => {
  it("is off unless a document says so", () => {
    // Off is what makes this a dropdown rather than a filter: the
    // unconfigured widget picks the first object so downstream widgets have
    // something to read on load.
    expect(allowNoSelectionOf(undefined)).toBe(false);
    expect(allowNoSelectionOf("true")).toBe(false);
    expect(allowNoSelectionOf(true)).toBe(true);
  });
});

describe("p.457's label", () => {
  it("is the text, or nothing at all", () => {
    expect(labelOf("Site")).toBe("Site");
    expect(labelOf("  Site  ")).toBe("Site");
    expect(labelOf("")).toBeNull();
    expect(labelOf("   ")).toBeNull();
    expect(labelOf(undefined)).toBeNull();
    expect(labelOf(7)).toBeNull();
  });
});

describe("reading a property list", () => {
  it("splits, trims and drops the blanks", () => {
    expect(propertyListOf(" name , region ,, ")).toEqual(["name", "region"]);
    expect(propertyListOf("")).toEqual([]);
    expect(propertyListOf(undefined)).toEqual([]);
  });
});

describe("saying when the list is only part of the set", () => {
  it("says so when the set is larger than the page", () => {
    // Said rather than hidden: a search box that answers about part of a set
    // looks exactly like one that answered about all of it.
    expect(truncationNote(1500, PAGE_LIMIT)).toContain("200");
    expect(truncationNote(1500, PAGE_LIMIT)).toContain("1,500");
  });

  it("says nothing when the whole set is loaded", () => {
    expect(truncationNote(PAGE_LIMIT, PAGE_LIMIT)).toBeNull();
    expect(truncationNote(3, PAGE_LIMIT)).toBeNull();
    expect(truncationNote(undefined, PAGE_LIMIT)).toBeNull();
  });

  it("loads a page a picker can actually be a picker over", () => {
    expect(PAGE_LIMIT).toBe(200);
  });
});

describe("p.458's sort", () => {
  it("offers only the sorts the object-set language has", () => {
    // **Not a property picker**: `object_sets.parse_sort` refuses those,
    // because instance properties are stored untyped and the two stores would
    // order 250 and 40 differently (decision 0006). A widget offering a
    // property here would produce a request the server answers with a 422.
    expect(Object.keys(SORTS).sort()).toEqual(["-key", "key", "oldest", "recent"]);
  });

  it("defaults to the key rather than to recency", () => {
    // A picker's list has to be in an order a person can predict, and on a
    // freshly synced type every row shares an `updated_at` — so "recent" is
    // arbitrary and can reorder under a viewer for no visible reason.
    expect(DEFAULT_SORT).toBe("key");
    expect(sortOf(undefined)).toBe("key");
    expect(sortOf("")).toBe("key");
  });

  it("keeps a sort the language has and refuses one it does not", () => {
    expect(sortOf("-key")).toBe("-key");
    expect(sortOf("oldest")).toBe("oldest");
    // A property name is exactly what a document written against p.458 would
    // hold, and sending it on would be a 422 in place of a list.
    expect(sortOf("name")).toBe("key");
    expect(sortOf("constructor")).toBe("key");
  });
});
