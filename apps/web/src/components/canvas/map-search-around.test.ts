import { describe, expect, it } from "vitest";

import {
  RESULT_COLORS, hopLabel, locationProperties, pinStart, resultColor, resultLabel, searchAroundLinks,
  searchAroundOf, searchAroundSet, toolbarStart,
} from "./map-search-around";
import { PRIMARY_KEY } from "./object-table-selection";

const hop = (over: Partial<Parameters<typeof hopLabel>[0]> = {}) => ({
  link_type_id: "l1", side_name: "Departures", far_type_id: "flight", far_type_display_name: "Flight",
  ...over,
});

describe("p.303's search around on the Map (§734)", () => {
  it("is off unless turned on", () => {
    expect(searchAroundOf(true)).toBe(true);
    expect(searchAroundOf(undefined)).toBe(false);
    expect(searchAroundOf("true")).toBe(false);
  });

  it("starts the toolbar from every object on the layer when none is selected", () => {
    const set = { object_type_id: "airport", filters: [{ property: "country", op: "eq", value: "US" }] };
    expect(toolbarStart(set, [], " Airports ")).toEqual({ label: "Airports", typeId: "airport", base: set });
    expect(toolbarStart(set, [], "")?.label).toBe("Objects");
  });

  it("narrows the toolbar's start to the selection, keeping the set's own filters", () => {
    const set = { object_type_id: "airport", filters: [{ property: "country", op: "eq", value: "US" }] };
    expect(toolbarStart(set, ["BOS", "JFK"], "Airports")).toEqual({
      label: "2 selected",
      typeId: "airport",
      base: {
        object_type_id: "airport",
        filters: [
          { property: "country", op: "eq", value: "US" },
          { property: PRIMARY_KEY, op: "in", value: ["BOS", "JFK"] },
        ],
      },
    });
    // The set itself is left as it was.
    expect(set.filters).toHaveLength(1);
    expect(toolbarStart({ object_type_id: "airport" }, ["BOS"], "")?.base.filters).toEqual([
      { property: PRIMARY_KEY, op: "in", value: ["BOS"] },
    ]);
  });

  it("starts nowhere from a set that is not over one type", () => {
    expect(toolbarStart(undefined, [], "")).toBeNull();
    expect(toolbarStart({ union: [] }, [], "")).toBeNull();
    expect(toolbarStart("airport", [], "")).toBeNull();
  });

  it("starts the context menu from the one object", () => {
    expect(pinStart("airport", "BOS", "Boston Logan")).toEqual({
      label: "Boston Logan",
      typeId: "airport",
      base: { object_type_id: "airport", filters: [{ property: PRIMARY_KEY, op: "in", value: ["BOS"] }] },
    });
  });

  it("offers prominent sides first and hidden ones not at all (p.217)", () => {
    const links = [
      hop({ link_type_id: "a", side_visibility: "normal" }),
      hop({ link_type_id: "b", side_visibility: "hidden" }),
      hop({ link_type_id: "c", side_visibility: "prominent" }),
      hop({ link_type_id: "d" }),
    ];
    expect(searchAroundLinks(links, "airport").map((l) => l.link_type_id)).toEqual(["c", "a", "d"]);
  });

  it("offers a link from a type to itself once, the way the server walks it", () => {
    const links = [
      hop({ link_type_id: "manager", far_type_id: "employee", direction: "outbound" as const }),
      hop({ link_type_id: "manager", far_type_id: "employee", direction: "inbound" as const }),
      hop({ link_type_id: "employer", far_type_id: "company", direction: "inbound" as const }),
    ];
    expect(searchAroundLinks(links, "employee").map((l) => `${l.link_type_id}:${l.direction}`))
      .toEqual(["manager:outbound", "employer:inbound"]);
  });

  it("names a link by its side, and its type when the side does not say it", () => {
    expect(hopLabel(hop())).toBe("Departures (Flight)");
    expect(hopLabel(hop({ side_name: " flight " }))).toBe("flight");
    expect(hopLabel(hop({ side_name: " " }))).toBe("Flight");
  });

  it("creates the far type's set, reached by the link from the start", () => {
    const start = pinStart("airport", "BOS", "Boston");
    expect(searchAroundSet(start, hop())).toEqual({
      object_type_id: "flight",
      filters: [],
      via: { link_type_id: "l1", base: start.base },
    });
  });

  it("labels the result in p.37's words", () => {
    const start = pinStart("airport", "BOS", "Boston");
    expect(resultLabel(start, hop())).toBe("Departures of Boston");
    expect(resultLabel(start, hop({ side_name: "" }))).toBe("Flight of Boston");
  });

  it("finds where the far type's objects can stand", () => {
    expect(locationProperties([
      { api_name: "name", data_type: "string" },
      { api_name: "at", data_type: "geopoint" },
      { api_name: "gate", data_type: "geopoint" },
      { api_name: "x" },
    ])).toEqual(["at", "gate"]);
  });

  it("gives each result layer the next colour, round again after the last", () => {
    expect(resultColor(0)).toBe(RESULT_COLORS[0]);
    expect(resultColor(1)).toBe(RESULT_COLORS[1]);
    expect(resultColor(RESULT_COLORS.length)).toBe(RESULT_COLORS[0]);
    expect(resultColor(-1)).toBe(RESULT_COLORS[RESULT_COLORS.length - 1]);
  });
});
