import { describe, expect, it } from "vitest";

import { favouriteAllowed, headerProps } from "./module-header";

const header = (props: Record<string, unknown>) => ({
  hdr: { type: { resolvedName: "CanvasHeader" }, props },
});

describe("headerProps", () => {
  it("finds the header among other widgets", () => {
    const layout = {
      chart: { type: { resolvedName: "CanvasChart" }, props: { title: "Arrivals" } },
      ...header({ title: "Fleet status" }),
    };
    expect(headerProps(layout)).toEqual({ title: "Fleet status" });
  });

  it("reads a bare string node type as well as the builder's object form", () => {
    // Both shapes are in the stored corpus (STATUS §114).
    expect(headerProps({ hdr: { type: "CanvasHeader", props: { title: "Ops" } } }))
      .toEqual({ title: "Ops" });
  });

  it("answers null when the module has no header", () => {
    expect(headerProps({ txt: { type: "CanvasText", props: {} } })).toBeNull();
    expect(headerProps({})).toBeNull();
    expect(headerProps(null)).toBeNull();
    expect(headerProps(undefined)).toBeNull();
  });

  it("tells a header with no props from no header at all", () => {
    // The distinction this module exists to keep: `{}` is an author who left
    // everything at its default, `null` is a module with nobody to have
    // chosen. A reader that collapsed the two would be reading one answer
    // where there are two.
    expect(headerProps({ hdr: { type: "CanvasHeader" } })).toEqual({});
    expect(headerProps({ hdr: { type: "CanvasHeader" } })).not.toBeNull();
  });

  it("is not fooled by a node whose type is missing or oddly shaped", () => {
    expect(headerProps({ hdr: { props: { title: "Ops" } } })).toBeNull();
    expect(headerProps({ hdr: { type: null, props: { title: "Ops" } } })).toBeNull();
    expect(headerProps({ hdr: null })).toBeNull();
    expect(headerProps({ hdr: "CanvasHeader" })).toBeNull();
  });
});

describe("favouriteAllowed", () => {
  it("is false only when the builder unticked it", () => {
    // p.47: "Toggle the ability for users to favorite the module in view
    // mode." One value turns it off; everything else leaves it on.
    expect(favouriteAllowed(header({ allowFavourite: false }))).toBe(false);
  });

  it("is true when the builder left it on", () => {
    expect(favouriteAllowed(header({ allowFavourite: true }))).toBe(true);
  });

  it("is true for a header written before the setting existed", () => {
    // The whole stored corpus. Defaulting the other way would strip the star
    // from every module in it, which is a behaviour change wearing a default's
    // clothes.
    expect(favouriteAllowed(header({ title: "Fleet status" }))).toBe(true);
    expect(favouriteAllowed(header({ allowFavourite: undefined }))).toBe(true);
  });

  it("is true for a module with no header at all", () => {
    // A header is optional — p.46 gives it a visibility toggle. A module that
    // hid its header did not thereby forbid anything.
    expect(favouriteAllowed({ txt: { type: "CanvasText", props: {} } })).toBe(true);
    expect(favouriteAllowed({})).toBe(true);
    expect(favouriteAllowed(null)).toBe(true);
  });

  it("reads the header's setting, not another widget's", () => {
    // Without the type check in `headerProps` this passes anyway, which is why
    // it is here: a Button with its own `allowFavourite` is not the module's.
    const layout = {
      btn: { type: { resolvedName: "CanvasButton" }, props: { allowFavourite: false } },
      ...header({ title: "Fleet status" }),
    };
    expect(favouriteAllowed(layout)).toBe(true);
  });

  it("does not take a truthy-looking string for a decision", () => {
    // Craft stores what a control wrote. Only `false` is the unticked box; a
    // stray "false" is not one, and reading it as one would turn the star off
    // on a document nobody touched.
    expect(favouriteAllowed(header({ allowFavourite: "false" }))).toBe(true);
    expect(favouriteAllowed(header({ allowFavourite: 0 }))).toBe(true);
  });
});
