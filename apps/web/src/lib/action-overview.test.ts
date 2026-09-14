/**
 * p.7's Overview tab (§345; `action-types` p.7).
 *
 *     "Enter a Display name for your action type." (p.7)
 *
 *     "You can make additional adjustments, like adding a Description in the
 *      Overview tab." (p.7)
 */
import { describe, expect, it } from "vitest";
import { overviewEdit, overviewRefusal } from "./action-overview";

const saved = { display_name: "Rename ticket", description: "Fix a typo" };

describe("what a save would send (§345)", () => {
  it("sends only the field that changed", () => {
    // **The audit log is why.** A present `display_name` writes an
    // `action_type.rename` row, so sending back one nobody touched would put a
    // rename in the log that never happened.
    expect(overviewEdit(saved, { ...saved, description: "Correct a typo" }))
      .toEqual({ description: "Correct a typo" });
    expect(overviewEdit(saved, { ...saved, display_name: "Rename it" }))
      .toEqual({ display_name: "Rename it" });
  });

  it("sends both when both changed", () => {
    expect(overviewEdit(saved, { display_name: "A", description: "B" }))
      .toEqual({ display_name: "A", description: "B" });
  });

  it("is null when nothing changed", () => {
    // `null` rather than `{}`, so a caller cannot post an empty body by
    // forgetting to check — the type makes the check the only way through.
    expect(overviewEdit(saved, { ...saved })).toBeNull();
  });

  it("is null when only the whitespace changed", () => {
    // The server trims before storing, so without this a trailing space
    // reports a change and stores none — and the screen closes claiming a save
    // that wrote nothing.
    expect(overviewEdit(saved, {
      display_name: "  Rename ticket  ", description: "Fix a typo ",
    })).toBeNull();
  });

  it("sends an emptied description rather than dropping it", () => {
    // **The one that separates "absent" from "empty".** An omitted field means
    // unchanged, so clearing a description has to arrive as `""` — a version
    // that treated falsy as nothing-to-send would make a description
    // impossible to remove.
    expect(overviewEdit(saved, { ...saved, description: "" }))
      .toEqual({ description: "" });
  });

  it("does not send a name emptied to nothing as a change on its own", () => {
    // It is still reported as a change — `overviewRefusal` is what stops the
    // save, and this says the two are separate decisions rather than one.
    expect(overviewEdit(saved, { ...saved, display_name: "   " }))
      .toEqual({ display_name: "" });
  });
});

describe("what the screen refuses before asking (§345)", () => {
  it("refuses a name that is not there", () => {
    // db 0013 checks `length(display_name) BETWEEN 1 AND 200`; a Save that
    // posts a name the server is certain to refuse is §214's control that
    // looks like it works.
    expect(overviewRefusal({ ...saved, display_name: "  " }))
      .toContain("needs a name");
  });

  it("refuses a name past the column's length", () => {
    const said = overviewRefusal({ ...saved, display_name: "x".repeat(201) });
    expect(said).toContain("200");
    // The number it is, so the reader knows how much to cut.
    expect(said).toContain("201");
  });

  it("refuses a description past the column's length", () => {
    expect(overviewRefusal({ ...saved, description: "x".repeat(2001) }))
      .toContain("2000");
  });

  it("is silent about a draft the server will take", () => {
    // The negative control: without it, a refusal that fired on everything
    // would pass all three above.
    expect(overviewRefusal(saved)).toBe("");
    expect(overviewRefusal({
      display_name: "x".repeat(200), description: "x".repeat(2000),
    })).toBe("");
  });
});
