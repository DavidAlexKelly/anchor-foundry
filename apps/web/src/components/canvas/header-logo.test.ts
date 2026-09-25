import { describe, expect, it } from "vitest";

import {
  headerMark, imageRefOf, logoHeightOf, logoPositionOf, logoPositionsFor,
} from "./header-logo";

const png = { key: "ws/attachments/1/logo.png", filename: "logo.png", content_type: "image/png", size: 9 };
const mini = { ...png, key: "ws/attachments/2/mini.png", filename: "mini.png" };

describe("imageRefOf", () => {
  it("keeps an uploaded image and nothing else", () => {
    expect(imageRefOf(png)).toEqual(png);
    expect(imageRefOf({ ...png, content_type: "application/pdf" })).toBeNull();
    expect(imageRefOf({ ...png, key: "" })).toBeNull();
    expect(imageRefOf("ws/attachments/1/logo.png")).toBeNull();
    expect(imageRefOf(null)).toBeNull();
    expect(imageRefOf({ key: "k", content_type: "image/gif" }))
      .toEqual({ key: "k", filename: "", content_type: "image/gif", size: 0 });
  });
});

describe("position and height (p.47)", () => {
  it("offers left, center and right across, top and bottom down", () => {
    expect(logoPositionsFor("horizontal")).toEqual(["left", "center", "right"]);
    expect(logoPositionsFor(undefined)).toEqual(["left", "center", "right"]);
    expect(logoPositionsFor("vertical")).toEqual(["top", "bottom"]);
    expect(logoPositionOf("right", "horizontal")).toBe("right");
    expect(logoPositionOf("bottom", "vertical")).toBe("bottom");
    // Switched orientation: the old position is read as the new default.
    expect(logoPositionOf("right", "vertical")).toBe("top");
    expect(logoPositionOf("bottom", "horizontal")).toBe("left");
  });

  it("keeps the height within what a header holds", () => {
    expect(logoHeightOf(48)).toBe(48);
    expect(logoHeightOf("40")).toBe(40);
    expect(logoHeightOf(4)).toBe(12);
    expect(logoHeightOf(500)).toBe(120);
    expect(logoHeightOf(undefined)).toBe(32);
    expect(logoHeightOf("tall")).toBe(32);
    expect(logoHeightOf(0)).toBe(32);
  });
});

describe("headerMark (p.47-49)", () => {
  it("shows the image over the icon", () => {
    expect(headerMark({ icon: "◎", image: png, collapsedImage: null, collapsed: false }))
      .toEqual({ kind: "image", image: png });
    expect(headerMark({ icon: " ◎x!", image: null, collapsedImage: null, collapsed: false }))
      .toEqual({ kind: "icon", text: "◎x" });
    expect(headerMark({ icon: "", image: null, collapsedImage: null, collapsed: false })).toBeNull();
  });

  it("collapsed, shows the collapsed image only beside a header image", () => {
    expect(headerMark({ icon: "◎", image: png, collapsedImage: mini, collapsed: true }))
      .toEqual({ kind: "image", image: mini });
    expect(headerMark({ icon: "◎", image: png, collapsedImage: mini, collapsed: false }))
      .toEqual({ kind: "image", image: png });
    // p.49: "you must first set up a header image".
    expect(headerMark({ icon: "◎", image: null, collapsedImage: mini, collapsed: true }))
      .toEqual({ kind: "icon", text: "◎" });
    expect(headerMark({ icon: "◎", image: png, collapsedImage: null, collapsed: true }))
      .toEqual({ kind: "image", image: png });
  });
});
