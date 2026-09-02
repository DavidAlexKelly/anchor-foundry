import { describe, expect, it } from "vitest";

import {
  MAX_TERMS,
  blankTerm, countLabel, labelOf, renderableTerms, selectedValues,
  termOf, termsOf, toClauses, toggled, visibleTerms,
} from "./prominent-terms";

/** p.475's Prominent Terms. The widget is `CanvasProminentTerms`; what is here
 * is every rule it applies, so each can be made to fail on its own. */

describe("reading one configured term", () => {
  it("takes the value, the display name and an icon", () => {
    expect(termOf({ value: "north", label: "Northern", icon: "N" }))
      .toEqual({ value: "north", label: "Northern", icon: "N" });
  });

  it("names nothing without a value to match on", () => {
    // A term is *defined* by the value it filters on. A row with a display name
    // and nothing to match would show the count of the whole set beside a name
    // somebody typed, which is a number that means nothing and looks like one
    // that means something.
    expect(termOf({ label: "Northern" })).toBeNull();
    expect(termOf({ value: "", label: "Northern" })).toBeNull();
    expect(termOf({ value: 7 })).toBeNull();
    expect(termOf(null)).toBeNull();
    expect(termOf("north")).toBeNull();
  });

  it("does not trim the value it will match exactly", () => {
    // **p.475: "the filter uses an exact match."** So " north" is a different
    // value from "north", and repairing it here would make a term that returns
    // nothing silently start returning rows — the author would never see the
    // typo, and the two would disagree about what the document says.
    expect(termOf({ value: " north " })?.value).toBe(" north ");
  });

  it("trims the label and the icon, which are only ever displayed", () => {
    // The asymmetry with the value is the point: these two are shown, not
    // matched, so whitespace in them is a rendering artefact rather than data.
    const term = termOf({ value: "north", label: "  Northern  ", icon: "  N  " });
    expect(term?.label).toBe("Northern");
    expect(term?.icon).toBe("N");
  });

  it("keeps an icon to two characters", () => {
    // There is no icon library here, so an icon is one or two characters — the
    // same ○ every icon setting in this build carries. A longer string would
    // render as a word in the icon's place and break the row's alignment.
    expect(termOf({ value: "n", icon: "🚚" })?.icon).toBe("🚚");
    expect(termOf({ value: "n", icon: "North" })?.icon).toBe("No");
  });
});

describe("the Terms setting as the panel holds it", () => {
  it("keeps a half-written row so it can be finished", () => {
    // §225's rule at a different widget: dropping a blank row would delete it
    // on the keystroke that emptied its value, under the author's cursor.
    expect(termsOf([{ value: "north" }, { label: "not typed yet" }])).toEqual([
      { value: "north", label: "", icon: "" },
      blankTerm(),
    ]);
  });

  it("stops at the cap", () => {
    const many = Array.from({ length: MAX_TERMS + 4 }, (_, n) => ({ value: `v${n}` }));
    expect(termsOf(many)).toHaveLength(MAX_TERMS);
  });

  it("reads nothing from what is not a list", () => {
    expect(termsOf(undefined)).toEqual([]);
    expect(termsOf("north,south")).toEqual([]);
    expect(termsOf({ value: "north" })).toEqual([]);
  });
});

describe("the terms the widget actually draws", () => {
  it("drops the rows with nothing to ask about", () => {
    expect(renderableTerms(termsOf([{ value: "north" }, {}]))
      .map((t) => t.value)).toEqual(["north"]);
  });

  it("drops a repeat rather than asking twice", () => {
    // Two rows on one value are two identical requests and two identical
    // numbers — and ticking one would light up the other, because the clause
    // list holds values rather than rows and cannot tell them apart.
    const terms = termsOf([
      { value: "north", label: "A" }, { value: "north", label: "B" },
      { value: "south" },
    ]);
    expect(renderableTerms(terms).map((t) => t.label)).toEqual(["A", ""]);
  });

  it("keeps the author's order", () => {
    // p.475's Terms is a list somebody arranged; nothing here sorts it.
    const terms = termsOf([{ value: "z" }, { value: "a" }, { value: "m" }]);
    expect(renderableTerms(terms).map((t) => t.value)).toEqual(["z", "a", "m"]);
  });
});

describe("what a row is called", () => {
  it("prefers the display name and falls back to the value", () => {
    expect(labelOf({ value: "north", label: "Northern", icon: "" })).toBe("Northern");
    expect(labelOf({ value: "north", label: "", icon: "" })).toBe("north");
  });
});

describe("p.475's Hide empty terms", () => {
  const TERMS = [
    { value: "north", label: "", icon: "" },
    { value: "south", label: "", icon: "" },
  ];

  it("keeps every term when the setting is off", () => {
    expect(visibleTerms(TERMS, { north: 3, south: 0 }, false)).toHaveLength(2);
    expect(visibleTerms(TERMS, { north: 3, south: 0 }, undefined)).toHaveLength(2);
  });

  it("hides a term the platform answered zero for", () => {
    expect(visibleTerms(TERMS, { north: 3, south: 0 }, true).map((t) => t.value))
      .toEqual(["north"]);
  });

  it("keeps a term whose count has not arrived", () => {
    // **The rule this function exists for.** `undefined` is a request in flight
    // or a failed one; `0` is an answer. Treating them alike makes every term
    // vanish on load and reappear, and makes a failure look like a deliberate
    // hide — which is the one thing a viewer cannot distinguish from the truth.
    expect(visibleTerms(TERMS, {}, true)).toHaveLength(2);
    expect(visibleTerms(TERMS, { north: 3 }, true).map((t) => t.value))
      .toEqual(["north", "south"]);
  });

  it("only accepts a true, not anything truthy", () => {
    // The prop arrives from a document, so a string "false" would enable it.
    expect(visibleTerms(TERMS, { south: 0 }, "true")).toHaveLength(2);
    expect(visibleTerms(TERMS, { south: 0 }, 1)).toHaveLength(2);
  });
});

describe("the clauses the widget writes", () => {
  it("writes one value as eq and several as in", () => {
    // The Filter List's vocabulary exactly (§40) — both mean the same thing on
    // both stores, and `eq` is what a reader of the saved document expects for
    // a single choice.
    expect(toClauses("region", ["north"]))
      .toEqual([{ property: "region", op: "eq", value: "north" }]);
    expect(toClauses("region", ["north", "south"]))
      .toEqual([{ property: "region", op: "in", value: ["north", "south"] }]);
  });

  it("writes no clause at all when nothing is picked", () => {
    // p.475's filter variable holds "the currently applied filtering criteria".
    // None applied is no criterion — an empty `in` is a criterion matching
    // nothing, which would narrow the set to zero rows on load.
    expect(toClauses("region", [])).toEqual([]);
  });

  it("writes nothing without a property to filter on", () => {
    expect(toClauses("", ["north"])).toEqual([]);
  });
});

describe("reading the selection back out of the variable", () => {
  it("reads an eq clause and an in clause alike", () => {
    expect(selectedValues([{ property: "region", op: "eq", value: "north" }], "region"))
      .toEqual(["north"]);
    expect(selectedValues(
      [{ property: "region", op: "in", value: ["north", "south"] }], "region",
    )).toEqual(["north", "south"]);
  });

  it("ignores clauses about other properties", () => {
    // The variable can carry clauses this widget did not write — several
    // widgets chain through one `narrow_set` — so reading them as its own
    // would tick terms nobody chose.
    expect(selectedValues([
      { property: "status", op: "eq", value: "open" },
      { property: "region", op: "eq", value: "north" },
    ], "region")).toEqual(["north"]);
  });

  it("reads a number back as the text a term matches", () => {
    // A term's value is typed by an author and is therefore a string; a clause
    // written elsewhere may hold the number. Comparing them as they arrive
    // would leave a ticked term looking unticked.
    expect(selectedValues([{ property: "n", op: "eq", value: 40 }], "n")).toEqual(["40"]);
  });

  it("reads nothing from a variable holding nothing", () => {
    expect(selectedValues(undefined, "region")).toEqual([]);
    expect(selectedValues([], "region")).toEqual([]);
    expect(selectedValues([{ property: "region", op: "eq" }], "region")).toEqual([]);
    expect(selectedValues([{ property: "region", op: "in", value: [null] }], "region"))
      .toEqual([]);
  });
});

describe("toggling one term", () => {
  it("adds one that is off and removes one that is on", () => {
    expect(toggled([], "north")).toEqual(["north"]);
    expect(toggled(["north"], "south")).toEqual(["north", "south"]);
    expect(toggled(["north", "south"], "north")).toEqual(["south"]);
  });

  it("leaves the rest in the order they were", () => {
    expect(toggled(["a", "b", "c"], "b")).toEqual(["a", "c"]);
  });
});

describe("what a row shows where its number goes", () => {
  it("shows nothing until there is a number", () => {
    // §229's rule: a number on screen is believed, so the moment before it is
    // known must not look like an answer.
    expect(countLabel(undefined)).toBe("");
    expect(countLabel(0)).toBe("0");
  });

  it("groups a large one", () => {
    expect(countLabel(12345)).toBe((12345).toLocaleString());
  });
});
