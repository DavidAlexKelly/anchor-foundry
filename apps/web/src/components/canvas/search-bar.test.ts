import { describe, expect, it } from "vitest";

import {
  MAX_MENU, availableLinks, availableProperties, describeLinked, linkMenu, linkScopeOf,
  placeholderOf, propertyScopeOf, searchMenu, suggestionDefinition, suggestionsOf,
  withLinkedFilter, type Link, type Property,
} from "./search-bar";

const properties: Property[] = [
  { api_name: "name", display_name: "Name", data_type: "string", visibility: "prominent" },
  { api_name: "region", display_name: "Region", data_type: "string" },
  { api_name: "size", display_name: "Size", data_type: "integer", visibility: "normal" },
  { api_name: "secret", display_name: "Secret code", data_type: "string", visibility: "hidden" },
  { api_name: "opened", display_name: null, data_type: "date", visibility: null },
];

describe("p.473's Property types available (§577)", () => {
  const names = (list: Property[]) => list.map((p) => p.api_name);

  it("is Visible unless the map says otherwise", () => {
    expect(propertyScopeOf(undefined)).toBe("visible");
    expect(propertyScopeOf("everything")).toBe("visible");
    expect(propertyScopeOf("toString")).toBe("visible");
    for (const scope of ["all", "prominent", "visible", "custom"]) {
      expect(propertyScopeOf(scope)).toBe(scope);
    }
  });

  it("offers what each scope names, in the type's order", () => {
    expect(names(availableProperties(properties, "all"))).toEqual(
      ["name", "region", "size", "secret", "opened"]);
    expect(names(availableProperties(properties, "visible"))).toEqual(
      ["name", "region", "size", "opened"]);
    expect(names(availableProperties(properties, "prominent"))).toEqual(["name"]);
    expect(names(availableProperties(properties, "custom", ["secret", "size"]))).toEqual(
      ["size", "secret"]);
    expect(names(availableProperties(properties, "custom"))).toEqual([]);
  });
});

describe("what the menu offers for what is typed (§577)", () => {
  it("offers every property to filter on before anything is typed", () => {
    expect(searchMenu("", properties, { keyword: true })).toEqual([
      { kind: "property", property: "name", label: "Name" },
      { kind: "property", property: "region", label: "Region" },
      { kind: "property", property: "size", label: "Size" },
      { kind: "property", property: "secret", label: "Secret code" },
      { kind: "property", property: "opened", label: "opened" },
    ]);
    expect(searchMenu("   ", properties, { keyword: true })).toHaveLength(5);
  });

  it("offers a keyword search in each string property first, then the names that match", () => {
    expect(searchMenu(" Re ", properties, { keyword: true })).toEqual([
      { kind: "keyword", property: "name", label: 'Search "Re" in Name' },
      { kind: "keyword", property: "region", label: 'Search "Re" in Region' },
      { kind: "keyword", property: "secret", label: 'Search "Re" in Secret code' },
      { kind: "property", property: "region", label: "Region" },
      { kind: "property", property: "secret", label: "Secret code" },
    ]);
  });

  it("matches a name or an API name, whatever its case", () => {
    const named = [{ api_name: "cap_mw", display_name: "Capacity", data_type: "integer" }];
    expect(searchMenu("CAP_MW", named, { keyword: false }).map((m) => m.label)).toEqual(["Capacity"]);
    const menu = searchMenu("OPEN", properties, { keyword: false });
    expect(menu).toEqual([{ kind: "property", property: "opened", label: "opened" }]);
    expect(searchMenu("code", properties, { keyword: false }).map((m) => m.label))
      .toEqual(["Secret code"]);
    expect(searchMenu("zzz", properties, { keyword: false })).toEqual([]);
  });

  it("offers no keyword search when p.473 turns it off", () => {
    expect(searchMenu("re", properties, { keyword: false }).every((m) => m.kind === "property"))
      .toBe(true);
  });

  it("stops at a screenful", () => {
    const many = Array.from({ length: 30 }, (_, n) => ({ api_name: `p${n}`, data_type: "string" }));
    expect(searchMenu("", many, { keyword: true })).toHaveLength(MAX_MENU);
    expect(searchMenu("p", many, { keyword: true })).toHaveLength(MAX_MENU);
  });
});

describe("the values suggested (§577)", () => {
  const groups = [
    { value: "North", count: 9 }, { value: "", count: 7 }, { value: "south", count: 5 },
    { value: "Northeast", count: 2 },
  ];

  it("are those holding the text, in the counts' order, without the empty value", () => {
    expect(suggestionsOf(groups, "")).toEqual([
      { value: "North", count: 9 }, { value: "south", count: 5 }, { value: "Northeast", count: 2 }]);
    expect(suggestionsOf(groups, " north ")).toEqual([
      { value: "North", count: 9 }, { value: "Northeast", count: 2 }]);
    expect(suggestionsOf(groups, "TH", 2)).toEqual([
      { value: "North", count: 9 }, { value: "south", count: 5 }]);
  });

  it("stop at eight by default", () => {
    const many = Array.from({ length: 12 }, (_, n) => ({ value: `v${n}`, count: 1 }));
    expect(suggestionsOf(many, "v")).toHaveLength(8);
  });
});

describe("p.473's Placeholder (§577)", () => {
  it("is the builder's, or says what the bar does", () => {
    expect(placeholderOf("Find a site", true)).toBe("Find a site");
    expect(placeholderOf("  ", true)).toBe("Search, or filter by a property…");
    expect(placeholderOf(undefined, false)).toBe("Filter by a property…");
  });
});

describe("where the suggestions are read from (§577)", () => {
  const set = { object_type_id: "t", filters: [{ property: "band", op: "eq", value: "new" }] };

  it("is the set, narrowed to the values starting with what is typed", () => {
    expect(suggestionDefinition(set, "region", " so ")).toEqual({
      object_type_id: "t",
      filters: [{ property: "band", op: "eq", value: "new" },
        { property: "region", op: "starts_with", value: "so" }],
    });
    expect(suggestionDefinition({ object_type_id: "t" }, "region", "so")).toEqual({
      object_type_id: "t", filters: [{ property: "region", op: "starts_with", value: "so" }] });
  });

  it("is the set itself before anything is typed", () => {
    expect(suggestionDefinition(set, "region", "  ")).toBe(set);
    expect(suggestionDefinition(null, "region", "so")).toBeNull();
    expect(suggestionDefinition("x", "region", "so")).toBe("x");
  });
});

describe("links in the bar (§578)", () => {
  const links: Link[] = [
    { link_type_id: "L1", side_name: "Inspections", far_type_id: "T2",
      far_type_display_name: "Inspection" },
    { link_type_id: "L2", side_name: "Owner", far_type_id: "T3", far_type_display_name: "Company" },
  ];

  it("offers every link unless p.473 says a list or none", () => {
    expect(linkScopeOf(undefined)).toBe("all");
    expect(linkScopeOf("toString")).toBe("all");
    expect(linkScopeOf("none")).toBe("none");
    expect(linkScopeOf("custom")).toBe("custom");
    expect(availableLinks(links, "all")).toEqual(links);
    expect(availableLinks(links, "none")).toEqual([]);
    expect(availableLinks(links, "custom", ["L2"])).toEqual([links[1]]);
    expect(availableLinks(links, "custom")).toEqual([]);
  });

  it("lists the links after the properties, by either of their names", () => {
    expect(searchMenu("", [], { keyword: true }, links)).toEqual([
      { kind: "link", link: "L1", label: "Inspections (Inspection)" },
      { kind: "link", link: "L2", label: "Owner (Company)" },
    ]);
    expect(searchMenu("comp", [], { keyword: false }, links).map((m) => m.label))
      .toEqual(["Owner (Company)"]);
    expect(searchMenu("INSP", [], { keyword: false }, links).map((m) => m.label))
      .toEqual(["Inspections (Inspection)"]);
    expect(searchMenu("owner", [], { keyword: false }, links).map((m) => m.label))
      .toEqual(["Owner (Company)"]);
    const menu = searchMenu("re", properties, { keyword: false }, links);
    expect(menu.map((m) => m.kind)).toEqual(["property", "property"]);
  });

  it("offers has-any first, then the linked type's properties", () => {
    const far: Property[] = [
      { api_name: "status", display_name: "Status", data_type: "string" },
      { api_name: "score", data_type: "integer" },
    ];
    expect(linkMenu("", links[0]!, far)).toEqual([
      { kind: "has_link", label: "Has any Inspections" },
      { kind: "far_property", property: "status", label: "Status" },
      { kind: "far_property", property: "score", label: "score" },
    ]);
    expect(linkMenu(" STAT ", links[0]!, far)).toEqual([
      { kind: "has_link", label: "Has any Inspections" },
      { kind: "far_property", property: "status", label: "Status" },
    ]);
    const many = Array.from({ length: 30 }, (_, n) => ({ api_name: `p${n}` }));
    expect(linkMenu("", links[0]!, many)).toHaveLength(MAX_MENU);
  });

  it("gathers a link's filters into its one clause", () => {
    const kept = { property: "region", op: "eq", value: "north" };
    const one = withLinkedFilter([kept], "L1", { property: "status", op: "eq", value: "open" });
    expect(one).toEqual([kept, { property: "L1", op: "has_link",
      value: { filters: [{ property: "status", op: "eq", value: "open" }] } }]);
    const two = withLinkedFilter(one, "L1", { property: "score", op: "gte", value: 3 });
    expect(two).toEqual([kept, { property: "L1", op: "has_link", value: { filters: [
      { property: "status", op: "eq", value: "open" }, { property: "score", op: "gte", value: 3 }] } }]);
  });

  it("names a link's pill in the link's words", () => {
    expect(describeLinked({ property: "L1", op: "has_link", value: { filters: [] } }, links))
      .toBe("Has Inspections");
    expect(describeLinked({ property: "L1", op: "has_link", value: { filters: [
      { property: "status", op: "eq", value: "open" },
      { property: "score", op: "gte", value: 3 }] } }, links))
      .toBe("Has Inspections where status is open and score is at least 3");
    expect(describeLinked({ property: "L9", op: "has_link", value: {} }, links)).toBeNull();
    expect(describeLinked({ property: "region", op: "eq", value: "x" }, links)).toBeNull();
    // Only a link's own clause: another on a property that happens to share
    // a link's id is not one.
    expect(describeLinked({ property: "L1", op: "eq", value: "x" }, links)).toBeNull();
    expect(describeLinked({ property: "L2", op: "has_link", value: null }, links)).toBe("Has Owner");
  });
});

describe("p.473's Prominent and Visible link scopes (§714)", () => {
  const link = (id: string, side_visibility?: string) => ({
    link_type_id: id, side_name: id, far_type_id: "t", far_type_display_name: "T",
    ...(side_visibility ? { side_visibility } : {}),
  });
  const links = [link("a", "prominent"), link("b", "normal"), link("c", "hidden"), link("d")];

  it("reads them", () => {
    expect(linkScopeOf("prominent")).toBe("prominent");
    expect(linkScopeOf("visible")).toBe("visible");
  });

  it("offers only the prominent sides, or every side but the hidden", () => {
    expect(availableLinks(links, "prominent").map((l) => l.link_type_id)).toEqual(["a"]);
    expect(availableLinks(links, "visible").map((l) => l.link_type_id)).toEqual(["a", "b", "d"]);
    expect(availableLinks(links, "all").map((l) => l.link_type_id)).toEqual(["a", "b", "c", "d"]);
  });
});
