import { describe, expect, it } from "vitest";

import { ICON_CLASS, iconPropertyOf, imageUrlOf, typeClassesOf } from "./type-classes";

/** p.91's type classes and p.222's hubble:icon (§671). */

describe("typeClassesOf", () => {
  it("reads a box of kind:name classes, each once, and names the rest", () => {
    expect(typeClassesOf(" hubble:icon, team:photo  hubble:icon,,")).toEqual({
      classes: ["hubble:icon", "team:photo"], bad: [] });
    expect(typeClassesOf("icon, a:b:c, :x, y:, ok.one:two-3")).toEqual({
      classes: ["ok.one:two-3"], bad: ["icon", "a:b:c", ":x", "y:"] });
    expect(typeClassesOf(`a:${"x".repeat(98)}`).classes).toHaveLength(1);
    expect(typeClassesOf(`a:${"x".repeat(99)}`).bad).toHaveLength(1);
    expect(typeClassesOf("")).toEqual({ classes: [], bad: [] });
  });
});

describe("hubble:icon", () => {
  it("is the first property that carries it", () => {
    expect(ICON_CLASS).toBe("hubble:icon");
    expect(iconPropertyOf([
      { api_name: "name" }, { api_name: "logo", type_classes: ["team:x", "hubble:icon"] },
      { api_name: "photo", type_classes: ["hubble:icon"] },
    ])).toBe("logo");
    expect(iconPropertyOf([{ api_name: "name", type_classes: [] }])).toBeNull();
  });

  it("loads an http or https image and nothing else", () => {
    expect(imageUrlOf(" https://example.com/a.png ")).toBe("https://example.com/a.png");
    expect(imageUrlOf("http://example.com/a.png")).toBe("http://example.com/a.png");
    expect(imageUrlOf("javascript:alert(1)")).toBeNull();
    expect(imageUrlOf("data:image/png;base64,AAAA")).toBeNull();
    expect(imageUrlOf("not a url")).toBeNull();
    expect(imageUrlOf(42)).toBeNull();
  });
});
