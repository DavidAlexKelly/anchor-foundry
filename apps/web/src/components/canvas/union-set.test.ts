import { describe, expect, it } from "vitest";

import { keysOf, selectionClauses } from "./object-table-selection";
import {
  UNION, selectionIn, tabIndex, typedSelection, unionParts, unionProperties,
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
