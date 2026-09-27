import { describe, expect, it } from "vitest";

import { layerColorOf, layerOpacityOf, layerVisibleOf } from "./map-layer";

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
