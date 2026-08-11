import { describe, expect, it } from "vitest";

import { moduleTitle } from "./module-title";

const header = (title: unknown) => ({
  hdr: { type: { resolvedName: "CanvasHeader" }, props: { title } },
});

describe("moduleTitle", () => {
  it("uses the header's title", () => {
    expect(moduleTitle(header("Fleet status"), "Module 4")).toBe("Fleet status");
  });

  it("falls back to the resource name when no title is set", () => {
    // p.47: "If a title is not set, the Workshop module resource name will be
    // used instead."
    expect(moduleTitle(header(""), "Module 4")).toBe("Module 4");
    expect(moduleTitle(header(undefined), "Module 4")).toBe("Module 4");
  });

  it("treats a whitespace-only title as unset", () => {
    // Otherwise the tab is blank, which is worse than the module's own name.
    expect(moduleTitle(header("   "), "Module 4")).toBe("Module 4");
  });

  it("falls back when the module has no header at all", () => {
    expect(moduleTitle({ txt: { type: "CanvasText", props: {} } }, "Module 4")).toBe("Module 4");
    expect(moduleTitle({}, "Module 4")).toBe("Module 4");
    expect(moduleTitle(null, "Module 4")).toBe("Module 4");
  });

  it("ignores a title prop on a widget that is not the header", () => {
    // Several widgets carry a `title` - a chart's caption is not the tab name.
    // Without this the type check can be deleted and every test still passes.
    const layout = {
      chart: { type: { resolvedName: "CanvasChart" }, props: { title: "Arrivals by hour" } },
    };
    expect(moduleTitle(layout, "Module 4")).toBe("Module 4");
    expect(moduleTitle({ ...layout, ...header("Fleet status") }, "Module 4")).toBe("Fleet status");
  });

  it("reads a bare string node type as well as the builder's object form", () => {
    // Both shapes are in the stored corpus; assuming the object form is what
    // made an earlier parser crash on converted documents (STATUS §114).
    expect(moduleTitle({ hdr: { type: "CanvasHeader", props: { title: "Ops" } } }, "M")).toBe("Ops");
  });
});
