import { describe, expect, it } from "vitest";

import {
  PANEL_CHARTS, formFactorOf, keyProperties, panelBehaviorOf, panelChartProperties,
  panelListProperties, panelShows, VIEW_FORMS, subjectKindOf, viewFormOf } from "./object-panels";

/** p.41's default panels and p.263's panel behaviours (§694). */

const p = (api_name: string, data_type = "string", visibility = "normal", id = api_name) =>
  ({ id, api_name, data_type, visibility });

describe("a set panel's Charts tab", () => {
  it("groups by up to five category properties, prominent first, never the title", () => {
    const props = [
      p("name"), p("region"), p("status", "string", "prominent"), p("size", "integer"),
      p("secret", "string", "hidden"), p("open", "boolean"), p("a"), p("b"), p("c"), p("d"),
    ];
    expect(panelChartProperties(props, "name").map((x) => x.api_name))
      .toEqual(["status", "region", "open", "a", "b"]);
    expect(PANEL_CHARTS).toBe(5);
    expect(panelChartProperties([p("name")], "name")).toEqual([]);
    // Nor the key, mapped as a property.
    expect(panelChartProperties([p("id"), p("region")], null, ["id"]).map((x) => x.api_name))
      .toEqual(["region"]);
  });

  it("finds the properties holding each object's key", () => {
    const rows = [{ primary_key: "C1", properties: { id: "C1", code: "C1", region: "north" } },
                  { primary_key: "C2", properties: { id: "C2", code: "X", region: "C2" } }];
    expect(keyProperties(rows, [p("id"), p("code"), p("region")])).toEqual(["id"]);
    expect(keyProperties([], [p("id")])).toEqual([]);
  });
});

describe("a set panel's List tab", () => {
  it("shows media then prominent properties, three with the title", () => {
    const props = [
      p("name", "string", "prominent"), p("photo", "attachment"),
      p("region", "string", "prominent"), p("status", "string", "prominent"), p("notes"),
      p("scan", "attachment", "hidden"),
    ];
    expect(panelListProperties(props, "name").map((x) => x.api_name)).toEqual(["photo", "region"]);
    expect(panelListProperties([p("name"), p("a", "string", "prominent")], "name")
      .map((x) => x.api_name)).toEqual(["a"]);
    // A prominent attachment is media, and counted once.
    expect(panelListProperties([p("photo", "attachment", "prominent")], null)
      .map((x) => x.api_name)).toEqual(["photo"]);
  });
});

describe("p.263's panel behaviours", () => {
  it("choose the instance or the set view by the set's size", () => {
    expect([0, 1, 2].map((n) => panelShows("instance", n))).toEqual(["instance", "instance", "instance"]);
    expect([0, 1, 2].map((n) => panelShows("adaptive", n))).toEqual(["set", "instance", "set"]);
    expect([0, 1, 2].map((n) => panelShows("set", n))).toEqual(["set", "set", "set"]);
  });

  it("read what a document holds", () => {
    expect(panelBehaviorOf("adaptive")).toBe("adaptive");
    expect(panelBehaviorOf("set")).toBe("set");
    expect(panelBehaviorOf("nope")).toBe("instance");
    expect(formFactorOf("panel")).toBe("panel");
    expect(formFactorOf(undefined)).toBe("full");
  });
});


describe("the three views a type may configure (§744)", () => {
  it("reads a form, and anything else as the full view", () => {
    expect(viewFormOf("panel_set")).toBe("panel_set");
    expect(viewFormOf("panel")).toBe("panel");
    expect(viewFormOf("sidebar")).toBe("full");
    expect(viewFormOf(undefined)).toBe("full");
    expect(Object.keys(VIEW_FORMS)).toEqual(["full", "panel", "panel_set"]);
  });

  it("has the set panel receive a set and the others one object (p.41)", () => {
    expect(subjectKindOf("panel_set")).toBe("object_set");
    expect(subjectKindOf("panel")).toBe("single_object");
    expect(subjectKindOf("full")).toBe("single_object");
  });
});
