import { describe, expect, it } from "vitest";

import { DEFAULT_HINTS, NEEDS_SEARCHABLE, RENDER_HINTS, hintLabels, hintsOf, toggledHint } from "./render-hints";

describe("render hints (§724; object-link-types p.248-252)", () => {
  it("is p.249-252's table, in its order, with the server's default and rule", () => {
    // `services/render_hints.py`'s HINTS, DEFAULT and NEEDS_SEARCHABLE.
    expect(RENDER_HINTS.map((h) => h.key)).toEqual([
      "disable_formatting", "identifier", "keywords", "long_text", "low_cardinality",
      "selectable", "sortable", "searchable", "leading_wildcards", "regex"]);
    expect(DEFAULT_HINTS).toEqual(["selectable", "sortable", "searchable"]);
    expect(NEEDS_SEARCHABLE).toEqual(["low_cardinality", "selectable", "sortable", "leading_wildcards", "regex"]);
  });

  it("reads none named as the default, and orders and dedupes the rest", () => {
    expect(hintsOf(undefined)).toEqual(DEFAULT_HINTS);
    expect(hintsOf(null)).toEqual(DEFAULT_HINTS);
    expect(hintsOf([])).toEqual([]);
    expect(hintsOf(["searchable", "keywords", "nonsense", "keywords"])).toEqual(["keywords", "searchable"]);
  });

  it("ticks Searchable with a hint that needs it, and unticks what needed it", () => {
    expect(toggledHint([], "sortable", true)).toEqual(["sortable", "searchable"]);
    expect(toggledHint([], "keywords", true)).toEqual(["keywords"]);
    expect(toggledHint(["keywords", "regex", "searchable"], "searchable", false)).toEqual(["keywords"]);
    expect(toggledHint(undefined, "sortable", false)).toEqual(["selectable", "searchable"]);
    // Unticking a dependent leaves Searchable as it was.
    expect(toggledHint(["regex", "searchable"], "regex", false)).toEqual(["searchable"]);
  });

  it("says what is set by name", () => {
    expect(hintLabels(["long_text", "searchable"])).toEqual(["Long text", "Searchable"]);
    expect(hintLabels(undefined)).toEqual(["Selectable", "Sortable", "Searchable"]);
  });
});
