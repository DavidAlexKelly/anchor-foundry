import { describe, expect, it } from "vitest";

import {
  addHoverAction, annotationColorOf, annotationFormatOf, annotationLayersOf, annotationsOf,
  hoverActionsOf, markdownClickItems, segmentsOf, tooltipOf,
  type AnnotationLayer,
} from "./markdown-annotations";

/** p.321-322's annotations (§637). */

const LAYER: AnnotationLayer = {
  name: "Notes", objectSetVariable: "v_notes", startProperty: "start", endProperty: "end",
  color: null, colorMode: "static", colorRules: null,
};

describe("annotation layers", () => {
  it("reads what a saved widget holds, a colour only when it is one", () => {
    expect(annotationLayersOf([
      { name: " Notes ", objectSetVariable: "v_notes", startProperty: "start",
        endProperty: "end", color: "#ff0000" },
      { name: "Bad", objectSetVariable: "", color: "red" }, null, 7,
    ])).toEqual([
      { name: "Notes", objectSetVariable: "v_notes", startProperty: "start",
        endProperty: "end", color: "#ff0000", colorMode: "static", colorRules: null },
      { name: "Bad", objectSetVariable: null, startProperty: "", endProperty: "", color: null,
        colorMode: "static", colorRules: null },
    ]);
    expect(annotationLayersOf({})).toEqual([]);
  });

  it("highlights unless told otherwise", () => {
    expect(annotationFormatOf(undefined)).toBe("highlight");
    for (const f of ["underline", "dashed", "both"]) expect(annotationFormatOf(f)).toBe(f);
  });
});

describe("annotationsOf", () => {
  it("takes whole, non-negative ranges and counts the rest", () => {
    const got = annotationsOf(0, LAYER, [
      { primary_key: "a", properties: { start: 2, end: 5 } },
      { primary_key: "b", properties: { start: "6", end: "9" } },
      { primary_key: "c", properties: { start: -1, end: 4 } },
      { primary_key: "d", properties: { start: 4, end: 4 } },
      { primary_key: "e", properties: { start: 1.5, end: 4 } },
      { primary_key: "f", properties: { start: 3 } },
      { primary_key: "g", properties: { start: " ", end: 4 } },
    ]);
    expect(got.annotations.map((a) => [a.key, a.start, a.end])).toEqual([["a", 2, 5], ["b", 6, 9]]);
    expect(got.unreadable).toBe(5);
    expect(got.annotations[0]!.layer).toBe(0);
  });
});

describe("segmentsOf", () => {
  const note = (key: string, start: number, end: number) =>
    ({ key, layer: 0, start, end, properties: {} });

  it("splits a run where annotations start and end", () => {
    const pieces = segmentsOf("hello world", 10, [note("a", 12, 16), note("b", 14, 30)]);
    expect(pieces.map((p) => [p.text, p.at, p.covering.map((a) => a.key)])).toEqual([
      ["he", 10, []], ["ll", 12, ["a"]], ["o ", 14, ["a", "b"]], ["world", 16, ["b"]],
    ]);
  });

  it("leaves a run whole that nothing touches, or that one covers entirely", () => {
    expect(segmentsOf("abc", 0, [note("a", 5, 9)]))
      .toEqual([{ text: "abc", at: 0, covering: [] }]);
    const whole = segmentsOf("abc", 3, [note("a", 0, 9)]);
    expect(whole).toHaveLength(1);
    expect(whole[0]!.covering.map((a) => a.key)).toEqual(["a"]);
    // An annotation ending where the run starts does not cover it.
    expect(segmentsOf("abc", 3, [note("a", 0, 3)])[0]!.covering).toEqual([]);
  });
});

describe("tooltipOf", () => {
  it("lists the chosen properties it has, one to a line", () => {
    const a = { key: "a", layer: 0, start: 0, end: 1,
                properties: { author: "Ada", tag: null, score: 3 } };
    expect(tooltipOf(a, ["author", "tag", "score", "missing"])).toBe("author: Ada\nscore: 3");
    expect(tooltipOf(a, [])).toBe("");
  });
});

describe("p.322's Highlight color by rules (§669)", () => {
  const red = { kind: "standard" as const, property: "severity", comparison: "string" as const,
    operator: "is_exactly" as const, value: "high", colour: "#ffffff", background: "#dc2626" };
  const amber = { kind: "standard" as const, property: "severity", comparison: "string" as const,
    operator: "is_exactly" as const, value: "low", colour: "#b45309" };
  const at = (properties: Record<string, unknown>) => ({ key: "a", layer: 0, start: 0, end: 1, properties });

  it("reads a layer's colour mode and its rules", () => {
    const [byRules, other] = annotationLayersOf([
      { name: "N", colorMode: "rules", colorRules: [red] },
      { name: "M", colorMode: "property", colorRules: [{ kind: "junk" }] },
    ]);
    expect([byRules!.colorMode, byRules!.colorRules]).toEqual(["rules", [red]]);
    expect([other!.colorMode, other!.colorRules]).toEqual(["static", null]);
  });

  it("paints with the fill before the text, and falls back to the static colour", () => {
    const layer = { ...LAYER, color: "#123456", colorMode: "rules" as const, colorRules: [red, amber] };
    expect(annotationColorOf(layer, at({ severity: "high" }))).toBe("#dc2626");
    expect(annotationColorOf(layer, at({ severity: "low" }))).toBe("#b45309");
    expect(annotationColorOf(layer, at({ severity: "none" }))).toBe("#123456");
    // Switched back to static, a layer keeps its rules, and they paint nothing.
    expect(annotationColorOf({ ...layer, colorMode: "static" }, at({ severity: "high" }))).toBe("#123456");
  });
});

describe("p.322's On hover interactions (§669)", () => {
  it("are hover_N items, added under an id no other has", () => {
    const one = addHoverAction([]);
    expect(one).toEqual([{ id: "hover_1", label: "Interaction 1" }]);
    expect(addHoverAction([{ id: "hover_2", label: "x" }]).map((i) => i.id)).toEqual(["hover_2", "hover_3"]);
    expect(hoverActionsOf([{ id: "hover_1", label: "Resolve" }, { id: "i_1", label: "Stray" }, null]))
      .toEqual([{ id: "hover_1", label: "Resolve" }]);
  });

  it("are listed after the highlighted-text actions, said as hover ones", () => {
    expect(markdownClickItems([{ id: "i_1", label: "Annotate" }],
      [{ id: "hover_1", label: "Resolve" }, { id: "hover_2", label: "" }])).toEqual([
      { id: "i_1", label: "Annotate" }, { id: "hover_1", label: "On hover: Resolve" },
      { id: "hover_2", label: "On hover: Interaction" },
    ]);
  });
});
