import { describe, expect, it } from "vitest";

import { buttonLook, customColourOf, intentOf, readableOn } from "./button-look";

describe("intentOf", () => {
  it("is the intent set, for each of p.486's five and custom", () => {
    for (const intent of ["none", "primary", "success", "warning", "danger"]) {
      expect(intentOf({ intent })).toBe(intent);
    }
    expect(intentOf({ intent: "custom", customColour: "#123456" })).toBe("custom");
  });

  it("reads a button saved before intents from its old style", () => {
    expect(intentOf({ style: "primary" })).toBe("primary");
    expect(intentOf({ style: "quiet" })).toBe("none");
    expect(intentOf({ style: "danger" })).toBe("danger");
    expect(intentOf({})).toBe("primary");
  });

  it("prefers the intent over the old style", () => {
    expect(intentOf({ intent: "success", style: "danger" })).toBe("success");
  });

  it("ignores an intent it does not know", () => {
    expect(intentOf({ intent: "sparkly", style: "danger" })).toBe("danger");
  });

  it("is none for a custom intent with no usable colour", () => {
    // Not primary: a class list that quietly dropped the custom style would
    // otherwise paint the button in a colour nobody chose.
    expect(intentOf({ intent: "custom" })).toBe("none");
    expect(intentOf({ intent: "custom", customColour: "red" })).toBe("none");
  });
});

describe("customColourOf", () => {
  it("takes a three- or six-digit hex, trimmed and lower-cased", () => {
    expect(customColourOf("#ABC")).toBe("#abc");
    expect(customColourOf(" #A1B2C3 ")).toBe("#a1b2c3");
  });

  it("refuses anything else, since it is written into a style", () => {
    for (const bad of ["red", "#12", "#1234", "#12345g", "url(x)", "#123456; color: red", 7, null]) {
      expect(customColourOf(bad), String(bad)).toBeNull();
    }
  });
});

describe("buttonLook", () => {
  it("names the intent and each display option as a class", () => {
    expect(buttonLook({ intent: "warning" }).className).toBe("btn btn-intent-warning");
    expect(buttonLook({ intent: "success", minimal: true, tag: true, large: true, fill: true })
      .className).toBe("btn btn-intent-success btn-minimal btn-tag btn-large btn-fill");
  });

  it("fills a custom colour, with text that reads on it", () => {
    expect(buttonLook({ intent: "custom", customColour: "#0b3d2e" }).style).toEqual({
      background: "#0b3d2e", borderColor: "#0b3d2e", color: "#ffffff",
    });
    expect(buttonLook({ intent: "custom", customColour: "#ffe08a" }).style.color).toBe("#16232f");
  });

  it("reverses a custom colour when minimal, as p.486 says", () => {
    expect(buttonLook({ intent: "custom", customColour: "#0b3d2e", minimal: true }).style)
      .toEqual({ color: "#0b3d2e", background: "transparent" });
  });

  it("writes no style for a preset intent", () => {
    expect(buttonLook({ intent: "danger", customColour: "#0b3d2e" }).style).toEqual({});
  });
});

describe("readableOn", () => {
  it("expands a short hex the same as the long one", () => {
    expect(readableOn("#fff")).toBe(readableOn("#ffffff"));
    expect(readableOn("#000")).toBe("#ffffff");
  });

  it("switches at WCAG's luminance, not at a midpoint", () => {
    // The boundary falls between these two greys (luminance 0.178 and
    // 0.181), well below the midpoint of the hex range.
    expect(readableOn("#757575")).toBe("#ffffff");
    expect(readableOn("#767676")).toBe("#16232f");
  });
});
