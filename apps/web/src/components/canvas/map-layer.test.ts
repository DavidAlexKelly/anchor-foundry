import { describe, expect, it } from "vitest";

import {
  MAX_LAYERS, bubbleColor, layerColorOf, layerOpacityOf, layerPoints, layerVisibleOf, layersOf, withLayerSetting,
  withNewLayer, withoutLayer,
} from "./map-layer";

describe("p.300's layer settings (§559)", () => {
  it("takes a colour only in the panel's own form", () => {
    expect(layerColorOf("#1a2B3c")).toBe("#1a2B3c");
    expect(layerColorOf("red")).toBeNull();
    expect(layerColorOf("#123")).toBeNull();
    expect(layerColorOf(null)).toBeNull();
  });

  it("holds the opacity where the layer can still be seen", () => {
    expect(layerOpacityOf(0.5)).toBe(0.5);
    expect(layerOpacityOf("0.25")).toBe(0.25);
    expect(layerOpacityOf(0)).toBe(0.1);
    expect(layerOpacityOf(3)).toBe(1);
    expect(layerOpacityOf("x")).toBe(1);
    expect(layerOpacityOf(undefined)).toBe(1);
  });

  it("shows the layer as its variable says, else as its static setting", () => {
    expect(layerVisibleOf(true, false, true)).toBe(false);
    expect(layerVisibleOf(false, true, true)).toBe(true);
    expect(layerVisibleOf(false, "yes", true)).toBe(false);
    // A bound variable with no boolean in it yet leaves the static setting.
    expect(layerVisibleOf(true, null, true)).toBe(true);
    expect(layerVisibleOf(undefined, undefined, false)).toBe(true);
    expect(layerVisibleOf(false, true, false)).toBe(false);
  });
});

describe("p.300's Add object layer (§642)", () => {
  const full = {
    id: "layer-2", objectSetVariable: "v_ports", locationProperty: "where", labelProperty: "name",
    label: "Ports", selectedVariable: "v_sel", visible: false, visibleVariable: "v_show",
    locked: true, color: "#aa3300", opacity: 0.5,
    geometries: [{ id: "geometry-1", property: "area", color: "#112233", legend: false }], inLegend: false,
  };

  it("reads each layer's settings by their own rules", () => {
    expect(layersOf([full])).toEqual([full]);
    expect(layersOf([{ id: "a", color: "red", opacity: 0, label: 7, locked: "yes", visible: 0 }]))
      .toEqual([{ id: "a", objectSetVariable: null, locationProperty: null, labelProperty: null,
        label: "", selectedVariable: null, visible: true, visibleVariable: null, locked: false,
        color: null, opacity: 0.1, geometries: [], inLegend: true }]);
  });

  it("leaves out what is not a layer, a repeated id, and past the cap", () => {
    expect(layersOf("x")).toEqual([]);
    expect(layersOf([null, "x", { label: "no id" }, { id: "" }])).toEqual([]);
    expect(layersOf([{ id: "a" }, { id: "a", label: "again" }]).map((l) => l.label)).toEqual([""]);
    const many = Array.from({ length: MAX_LAYERS + 1 }, (_, n) => ({ id: `l${n}` }));
    expect(layersOf(many)).toHaveLength(MAX_LAYERS);
  });

  it("adds an empty layer under an id nobody has", () => {
    const one = withNewLayer(undefined);
    expect(one).toHaveLength(1);
    expect(one[0]).toMatchObject({ id: "layer-2", visible: true, opacity: 1, locked: false });
    // The map's own layer is the first, so the first added is the second.
    expect(withNewLayer([{ id: "layer-3" }]).map((l) => l.id)).toEqual(["layer-3", "layer-4"]);
    expect(withNewLayer([{ id: "layer-4" }]).map((l) => l.id)).toEqual(["layer-4", "layer-3"]);
    const capped = Array.from({ length: MAX_LAYERS }, (_, n) => ({ id: `l${n}` }));
    expect(withNewLayer(capped)).toHaveLength(MAX_LAYERS);
  });

  it("changes one layer's setting, and removes one layer", () => {
    const two = [full, { ...full, id: "layer-3", label: "Depots" }];
    expect(withLayerSetting(two, "layer-3", "label", "Stores").map((l) => l.label))
      .toEqual(["Ports", "Stores"]);
    expect(withoutLayer(two, "layer-2").map((l) => l.id)).toEqual(["layer-3"]);
    expect(withoutLayer(two, "layer-3").map((l) => l.id)).toEqual(["layer-2"]);
  });

  it("places a layer's objects, labelled, and counts those it cannot", () => {
    const layer = layersOf([full])[0]!;
    const locate = (v: unknown) => (Array.isArray(v) ? { lat: v[0] as number, lon: v[1] as number } : null);
    const out = layerPoints(layer, [
      { id: "1", primary_key: "A", properties: { where: [1, 2], name: "Alpha" } },
      { id: "2", primary_key: "B", properties: { where: [3, 4] } },
      { id: "3", primary_key: "C", properties: { where: "nowhere", name: "Gamma" } },
    ], locate, (i, at, label) => ({ key: i.primary_key, label, ...at }));
    expect(out).toEqual({ points: [
      { key: "A", label: "Alpha", lat: 1, lon: 2 },
      { key: "B", label: "B", lat: 3, lon: 4 },
    ], unplaceable: 1 });
    // No location property: a layer of shapes alone (§670), with no pins
    // and none counted as unplaceable.
    expect(layerPoints({ ...layer, locationProperty: null },
      [{ id: "1", primary_key: "A", properties: { where: [1, 2] } }], locate, (i) => i))
      .toEqual({ points: [], unplaceable: 0 });
  });
});

describe("a bubble of pins from added layers (§642)", () => {
  it("takes the layer's colour only when every pin shares it", () => {
    expect(bubbleColor(["#aa3300", "#aa3300"], "var(--accent)")).toBe("#aa3300");
    expect(bubbleColor(["#aa3300", null], "var(--accent)")).toBe("var(--accent)");
    expect(bubbleColor(["#aa3300", "#003300"], "var(--accent)")).toBe("var(--accent)");
    expect(bubbleColor([undefined, null], "var(--accent)")).toBe("var(--accent)");
  });
});
