import { describe, expect, it } from "vitest";

import {
  annotationFormatOf, annotationLayersOf, annotationsOf, segmentsOf, tooltipOf,
  type AnnotationLayer,
} from "./markdown-annotations";

/** p.321-322's annotations (§637). */

const LAYER: AnnotationLayer = {
  name: "Notes", objectSetVariable: "v_notes", startProperty: "start", endProperty: "end",
  color: null,
};

describe("annotation layers", () => {
  it("reads what a saved widget holds, a colour only when it is one", () => {
    expect(annotationLayersOf([
      { name: " Notes ", objectSetVariable: "v_notes", startProperty: "start",
        endProperty: "end", color: "#ff0000" },
      { name: "Bad", objectSetVariable: "", color: "red" }, null, 7,
    ])).toEqual([
      { name: "Notes", objectSetVariable: "v_notes", startProperty: "start",
        endProperty: "end", color: "#ff0000" },
      { name: "Bad", objectSetVariable: null, startProperty: "", endProperty: "", color: null },
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
