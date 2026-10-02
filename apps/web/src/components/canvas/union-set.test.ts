import { describe, expect, it } from "vitest";

import { keysOf, selectionClauses } from "./object-table-selection";
import {
  OBJECTS_CLAUSE, UNION, UNION_PAGE_DEPTH, combinedColumns, isPicked, pickOf, pickedClauses,
  pickedIn, selectedType, selectionIn, tabIndex, typedSelection, unionParts, unionProperties,
} from "./union-set";

/** p.450's union, as the Object Table reads it (§686). */

const SITES = { object_type_id: "t-sites", filters: [] };
const STAFF = { object_type_id: "t-staff", filters: [{ property: "grade", op: "eq", value: 3 }] };

describe("a union's parts", () => {
  it("are the sets it holds, in order", () => {
    expect(UNION).toBe("union");
    expect(unionParts({ union: [SITES, STAFF] })).toEqual([SITES, STAFF]);
  });

  it("are null for anything that is not a union", () => {
    expect(unionParts(SITES)).toBeNull();
    expect(unionParts(undefined)).toBeNull();
    expect(unionParts(null)).toBeNull();
    expect(unionParts([SITES])).toBeNull();
    expect(unionParts({ union: "no" })).toBeNull();
    // A definition naming a type is that type's, whatever else it carries.
    expect(unionParts({ object_type_id: "t-sites", union: [STAFF] })).toBeNull();
  });

  it("leave out a part that names no type", () => {
    expect(unionParts({ union: [SITES, { filters: [] }, null, "x", { object_type_id: 4 }] }))
      .toEqual([SITES]);
  });
});

describe("the tab showing", () => {
  it("is the one asked for, or the last when the union shrank", () => {
    expect(tabIndex(1, 3)).toBe(1);
    expect(tabIndex(0, 3)).toBe(0);
    expect(tabIndex(2, 3)).toBe(2);
    expect(tabIndex(4, 3)).toBe(2);
    expect(tabIndex(-1, 3)).toBe(0);
    expect(tabIndex(0, 0)).toBe(0);
  });
});

describe("a selection in a union's tab", () => {
  it("names its type ahead of its keys", () => {
    expect(typedSelection(selectionClauses(["S1"]), "t-staff")).toEqual([
      { property: "$object_type", op: "eq", value: "t-staff" },
      { property: "$primary_key", op: "in", value: ["S1"] },
    ]);
    // Over one set, unchanged.
    expect(typedSelection(selectionClauses(["S1"]), null)).toEqual(selectionClauses(["S1"]));
  });

  it("is read back by its own tab and by no other", () => {
    const written = typedSelection(selectionClauses(["S1"]), "t-staff");
    expect(keysOf(selectionIn(written, "t-staff"))).toEqual(["S1"]);
    expect(selectionIn(written, "t-sites")).toEqual([]);
    // A selection naming no type, and a table over one set, read as they are.
    expect(selectionIn(selectionClauses(["S1"]), "t-sites")).toEqual(selectionClauses(["S1"]));
    expect(selectionIn(written, null)).toBe(written);
    expect(selectionIn("junk", "t-sites")).toBe("junk");
    expect(selectionIn([null, 3, written[1]], "t-sites")).toEqual([null, 3, written[1]]);
  });
});

describe("the properties a union can be filtered on", () => {
  const prop = (api_name: string, display_name = "") => ({ api_name, display_name });
  const sites = { displayName: "Sites", properties: [prop("region", "Region"), prop("size"), prop("name")] };
  const staff = { displayName: "Staff", properties: [prop("name", "Name"), prop("grade"), prop("region")] };
  const vans = { displayName: "Vans", properties: [prop("region"), prop("grade", "Grade")] };

  it("are p.450's common ones, in the first type's order, and single ones named with their type", () => {
    const { common, single } = unionProperties([sites, staff]);
    expect(common).toEqual([prop("region", "Region"), prop("name")]);
    expect(single).toEqual([prop("size", "size (Sites)"), prop("grade", "grade (Staff)")]);
  });

  it("leave out a property some types share and another lacks", () => {
    const { common, single } = unionProperties([sites, staff, vans]);
    expect(common.map((p) => p.api_name)).toEqual(["region"]);
    // `grade` is Staff's and the Vans', `name` the Sites' and the Staff's.
    expect(single.map((p) => p.api_name)).toEqual(["size"]);
  });

  it("are none until every type has loaded", () => {
    expect(unionProperties([sites, undefined])).toEqual({ common: [], single: [] });
    expect(unionProperties([undefined, staff])).toEqual({ common: [], single: [] });
  });

  it("are one type's own, all common, for a union of one", () => {
    expect(unionProperties([sites])).toEqual({ common: sites.properties, single: [] });
    expect(unionProperties([])).toEqual({ common: [], single: [] });
  });
});

describe("the type a selection names", () => {
  it("is its type clause's, or none", () => {
    expect(selectedType(typedSelection(selectionClauses(["K1"]), "t-staff"))).toBe("t-staff");
    expect(selectedType(selectionClauses(["K1"]))).toBeNull();
    // Wherever in the list it is.
    expect(selectedType([...selectionClauses(["K1"]),
                         { property: "$object_type", op: "eq", value: "t-sites" }])).toBe("t-sites");
    expect(selectedType([null, { property: "$object_type", op: "eq", value: 4 }])).toBeNull();
    expect(selectedType("t-staff")).toBeNull();
    expect(selectedType(undefined)).toBeNull();
  });
});

describe("a combined table's columns (p.225)", () => {
  const prop = (api_name: string, display_name: string) => ({ api_name, display_name });
  it("are one per api name and display name, covering the types that have it", () => {
    const columns = combinedColumns([
      { id: "t-sites", properties: [prop("name", "Name"), prop("region", "Region"), prop("size", "Size")] },
      { id: "t-staff", properties: [prop("name", "Name"), prop("region", "Area"), prop("grade", "Grade")] },
    ]);
    expect(columns.map((c) => [c.api_name, c.display_name, c.covers])).toEqual([
      ["name", "Name", ["t-sites", "t-staff"]],
      ["region", "Region", ["t-sites"]],
      ["size", "Size", ["t-sites"]],
      // p.225: "share both display names and IDs" - an ID alone is not enough.
      ["region", "Area", ["t-staff"]],
      ["grade", "Grade", ["t-staff"]],
    ]);
    expect(combinedColumns([])).toEqual([]);
    // None until every type has loaded.
    expect(combinedColumns([{ id: "t-sites", properties: [prop("name", "Name")] }, undefined]))
      .toEqual([]);
  });

  it("pages as deep as the server's union does", () => {
    expect(UNION_PAGE_DEPTH).toBe(200);
  });
});

describe("a selection in a combined table", () => {
  const site = { primary_key: "K1", object_type_id: "t-sites" };
  const staff = { primary_key: "K1", object_type_id: "t-staff" };
  const grace = { primary_key: "K3", object_type_id: "t-staff" };

  it("of one type is that type's keys", () => {
    const clauses = pickedClauses([pickOf(staff, true), pickOf(grace, true)], true, null);
    expect(clauses).toEqual(typedSelection(selectionClauses(["K1", "K3"]), "t-staff"));
    expect(pickedIn(clauses, true, null)).toEqual(
      [{ type: "t-staff", key: "K1" }, { type: "t-staff", key: "K3" }]);
  });

  it("of several types is their pairs beside all their keys", () => {
    const clauses = pickedClauses([pickOf(site, true), pickOf(grace, true)], true, null);
    expect(clauses).toEqual([
      { property: OBJECTS_CLAUSE, op: "in", value: [["t-sites", "K1"], ["t-staff", "K3"]] },
      ...selectionClauses(["K1", "K3"]),
    ]);
    const back = pickedIn(clauses, true, null);
    expect(isPicked(back, site)).toBe(true);
    expect(isPicked(back, staff)).toBe(false);
    expect(isPicked(back, grace)).toBe(true);
  });

  it("of nothing is the empty selection", () => {
    expect(pickedClauses([], true, null)).toEqual(selectionClauses([]));
    expect(pickedIn(selectionClauses([]), true, null)).toEqual([]);
  });

  it("leaves out a pair that is not one", () => {
    const raw = [{ property: OBJECTS_CLAUSE, op: "in", value: [["t-sites", "K1"], ["x"], "K2"] }];
    expect(pickedIn(raw, true, null)).toEqual([{ type: "t-sites", key: "K1" }]);
    expect(pickedIn([{ property: OBJECTS_CLAUSE, op: "in", value: "K1" }], true, null)).toEqual([]);
  });

  it("is the keys, as it always was, outside a combined table", () => {
    expect(pickOf(site, false)).toEqual({ type: null, key: "K1" });
    const clauses = pickedClauses([pickOf(site, false)], false, "t-sites");
    expect(clauses).toEqual(typedSelection(selectionClauses(["K1"]), "t-sites"));
    expect(pickedIn(clauses, false, "t-sites")).toEqual([{ type: null, key: "K1" }]);
    expect(pickedIn(clauses, false, "t-staff")).toEqual([]);
    // An entry with no type is any object with the key.
    expect(isPicked([{ type: null, key: "K1" }], staff)).toBe(true);
    expect(isPicked([{ type: null, key: "K1" }], { primary_key: "K1" })).toBe(true);
    expect(isPicked([{ type: "t-sites", key: "K1" }], { primary_key: "K1" })).toBe(false);
  });
});
