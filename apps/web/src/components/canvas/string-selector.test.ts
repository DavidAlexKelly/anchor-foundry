import { describe, expect, it } from "vitest";

import {
  DEFAULT_COLUMNS, DISPLAYS, LAYOUTS, MAX_COLUMNS, MIN_COLUMNS, SELECTIONS,
  chosenOf, columnsOf, displayOf, displaysFor, layoutOf, layoutStyle, modeOf,
  optionsOf, outputKind, pick, placeholderOf, selectionOf, sourceOf,
} from "./string-selector";

/** p.459–461's String Selector. */

/** **Written out by hand**, as §201's `EXPECTED_DIRECTION` and §203's
 * `EXPECTED` are: a test that reads its expectation out of the table under test
 * agrees with whatever that table says. This is p.461's matrix, transcribed
 * once more so a change to either copy shows up as a disagreement. */
const EXPECTED: Record<string, Record<string, {
  placeholder: string | null; hasLayout: boolean; hasClearing: boolean;
}>> = {
  single: {
    dropdown: { placeholder: "Select an option...", hasLayout: false, hasClearing: true },
    radio: { placeholder: null, hasLayout: true, hasClearing: false },
  },
  multiple: {
    dropdown: { placeholder: "Search options...", hasLayout: false, hasClearing: false },
    checkboxes: { placeholder: null, hasLayout: true, hasClearing: false },
  },
};

describe("the selection/display matrix", () => {
  it("has exactly p.461's two selections", () => {
    expect(Object.keys(SELECTIONS).sort()).toEqual(["multiple", "single"]);
    expect(Object.keys(DISPLAYS).sort()).toEqual(["multiple", "single"]);
  });

  it("offers radio buttons only under a single selection", () => {
    // p.461 lists them under Single and checkboxes under Multiple, and the two
    // are not interchangeable: radio buttons cannot express a list.
    expect(displaysFor("single")).toEqual(["dropdown", "radio"]);
    expect(displaysFor("multiple")).toEqual(["dropdown", "checkboxes"]);
  });

  it("has a hand-written expectation for every cell", () => {
    for (const selection of Object.keys(DISPLAYS)) {
      expect(Object.keys(DISPLAYS[selection]!).sort(), selection)
        .toEqual(Object.keys(EXPECTED[selection]!).sort());
    }
  });

  it.each(
    Object.entries(EXPECTED).flatMap(([selection, displays]) =>
      Object.entries(displays).map(([display, want]) => [selection, display, want] as const)),
  )("configures %s/%s as p.461 describes", (selection, display, want) => {
    const got = DISPLAYS[selection as "single"]![display]!;
    expect(got.placeholder).toBe(want.placeholder);
    expect(got.hasLayout).toBe(want.hasLayout);
    expect(got.hasClearing).toBe(want.hasClearing);
  });

  it("gives every display a label", () => {
    for (const [selection, displays] of Object.entries(DISPLAYS)) {
      for (const [name, mode] of Object.entries(displays)) {
        expect(mode.label, `${selection}/${name}`).toBeTruthy();
      }
    }
  });

  it("never gives a layout to something with a placeholder", () => {
    // The rule behind the table, stated independently of its contents: a
    // dropdown has a placeholder and no layout, a list of controls has a
    // layout and no placeholder. A cell with both would be a mode nothing in
    // p.461 describes.
    for (const displays of Object.values(DISPLAYS)) {
      for (const mode of Object.values(displays)) {
        expect(mode.hasLayout && mode.placeholder !== null).toBe(false);
      }
    }
  });
});

describe("outputKind", () => {
  it("is a string for single and an array for multiple", () => {
    // **p.461's sentence, and the reason this widget could not stay a mode of
    // the generic control**: "If the selection is set to Single, the output
    // variable will be a string variable. If the selection is set to Multiple,
    // the output variable will be a string array variable."
    expect(outputKind("single")).toBe("string");
    expect(outputKind("multiple")).toBe("array");
  });

  it("matches what the selection table says", () => {
    expect(SELECTIONS.single.kind).toBe("string");
    expect(SELECTIONS.multiple.kind).toBe("array");
  });

  it("treats anything unrecognised as single", () => {
    expect(outputKind(undefined)).toBe("string");
    expect(outputKind("many")).toBe("string");
  });
});

describe("displayOf", () => {
  it("passes a legal pair through", () => {
    expect(displayOf("single", "radio")).toBe("radio");
    expect(displayOf("multiple", "checkboxes")).toBe("checkboxes");
    expect(displayOf("multiple", "dropdown")).toBe("dropdown");
  });

  it("resolves a pair p.461 does not have", () => {
    // **One click in a panel produces this**: flip the selection while `radio`
    // is saved and the document holds multiple/radio. Trusting it would draw
    // radio buttons over a variable holding a list.
    expect(displayOf("multiple", "radio")).toBe("dropdown");
    expect(displayOf("single", "checkboxes")).toBe("dropdown");
  });

  it("resolves an unknown display", () => {
    expect(displayOf("single", "carousel")).toBe("dropdown");
    expect(displayOf("single", undefined)).toBe("dropdown");
    expect(displayOf("single", 7)).toBe("dropdown");
  });

  it("does not treat an inherited property name as a display", () => {
    expect(displayOf("single", "constructor")).toBe("dropdown");
  });
});

describe("placeholderOf", () => {
  it("uses p.461's default for each dropdown", () => {
    // The two differ on purpose: one picks, the other searches.
    expect(placeholderOf("single", "dropdown", "")).toBe("Select an option...");
    expect(placeholderOf("multiple", "dropdown", "")).toBe("Search options...");
  });

  it("uses the author's custom value when there is one", () => {
    expect(placeholderOf("single", "dropdown", "Pick a region")).toBe("Pick a region");
    expect(placeholderOf("single", "dropdown", "  Pick  ")).toBe("Pick");
  });

  it("is empty where p.461 gives no placeholder", () => {
    expect(placeholderOf("single", "radio", "")).toBe("");
    expect(placeholderOf("multiple", "checkboxes", "")).toBe("");
  });

  it("falls back to the default when the custom value is only whitespace", () => {
    expect(placeholderOf("single", "dropdown", "   ")).toBe("Select an option...");
  });
});

describe("optionsOf", () => {
  it("reads the static list", () => {
    expect(optionsOf("static", ["a", "b"], ["x"])).toEqual(["a", "b"]);
  });

  it("reads the dynamic variable's value", () => {
    // p.461's "a string array variable to be used to generate options".
    expect(optionsOf("dynamic", ["a", "b"], ["x", "y"])).toEqual(["x", "y"]);
  });

  it("is empty when the dynamic variable holds nothing yet", () => {
    // Which it does for the first few hundred milliseconds of every module,
    // because variables are computed on the server.
    expect(optionsOf("dynamic", ["a"], undefined)).toEqual([]);
    expect(optionsOf("dynamic", ["a"], null)).toEqual([]);
  });

  it("drops blank entries", () => {
    // A row somebody left empty is not a choice.
    expect(optionsOf("static", ["a", "", "  ", "b"], [])).toEqual(["a", "b"]);
  });

  it("collapses duplicates, keeping the first position", () => {
    // Two identical options are one choice drawn twice: indistinguishable in a
    // `<select>`, and as radio buttons they share a name and fight over which
    // is checked.
    expect(optionsOf("static", ["b", "a", "b"], [])).toEqual(["b", "a"]);
  });

  it("trims entries", () => {
    expect(optionsOf("static", [" a ", "a"], [])).toEqual(["a"]);
  });

  it("ignores entries that are not strings", () => {
    // A dynamic array can hold anything the derivation produced.
    expect(optionsOf("dynamic", [], ["a", 2, null, "b"])).toEqual(["a", "b"]);
  });
});

describe("chosenOf", () => {
  it("reads a single selection as a list of nought or one", () => {
    // One shape for the render, so the checkbox arm and the radio arm cannot
    // differ in a way nothing checks.
    expect(chosenOf("single", "a")).toEqual(["a"]);
    expect(chosenOf("single", "")).toEqual([]);
    expect(chosenOf("single", null)).toEqual([]);
  });

  it("reads a multiple selection as its list", () => {
    expect(chosenOf("multiple", ["a", "b"])).toEqual(["a", "b"]);
    expect(chosenOf("multiple", null)).toEqual([]);
  });

  it("ignores a value of the wrong shape for the selection", () => {
    // Which happens for one render after the selection changes, before the
    // variable has been rewritten.
    expect(chosenOf("multiple", "a")).toEqual([]);
    expect(chosenOf("single", ["a"])).toEqual([]);
  });
});

describe("pick", () => {
  it("replaces the value in a single selection", () => {
    expect(pick("single", "a", "b")).toBe("b");
    expect(pick("single", null, "b")).toBe("b");
  });

  it("clears a single selection when the chosen option is picked again", () => {
    expect(pick("single", "a", "a")).toBeNull();
  });

  it("toggles in a multiple selection", () => {
    expect(pick("multiple", ["a"], "b")).toEqual(["a", "b"]);
    expect(pick("multiple", ["a", "b"], "a")).toEqual(["b"]);
  });

  it("empties a multiple selection to a list, not to null", () => {
    // **The kinds differ.** A `string` variable with no value is empty; an
    // `array` variable with no value is an empty list, and a derivation reading
    // the second breaks on `null` where it handles `[]` perfectly well.
    expect(pick("multiple", ["a"], "a")).toEqual([]);
    expect(pick("single", "a", "a")).toBeNull();
  });

  it("does not mutate what it was given", () => {
    const before = ["a", "b"];
    pick("multiple", before, "c");
    expect(before).toEqual(["a", "b"]);
  });
});

describe("selectionOf and sourceOf", () => {
  it("defaults to the narrower answer", () => {
    // Single and static are the defaults a new widget gets, and the fallback
    // for a document naming something else - a widget that quietly became
    // multi-select would change what its variable has to hold.
    expect(selectionOf(undefined)).toBe("single");
    expect(selectionOf("multiple")).toBe("multiple");
    expect(sourceOf(undefined)).toBe("static");
    expect(sourceOf("dynamic")).toBe("dynamic");
    expect(sourceOf("elsewhere")).toBe("static");
  });
});

describe("layout", () => {
  it("has p.461's three", () => {
    expect(Object.keys(LAYOUTS).sort()).toEqual(["grid", "horizontal", "vertical"]);
  });

  it("defaults to vertical", () => {
    expect(layoutOf(undefined)).toBe("vertical");
    expect(layoutOf("diagonal")).toBe("vertical");
    expect(layoutOf("constructor")).toBe("vertical");
    expect(layoutOf("grid")).toBe("grid");
  });

  it("clamps the column count", () => {
    expect(columnsOf(1)).toBe(MIN_COLUMNS);
    expect(columnsOf(99)).toBe(MAX_COLUMNS);
    expect(columnsOf(4)).toBe(4);
  });

  it("defaults the column count when it is not set", () => {
    // Absence before coercion: `Number(null)` and `Number("")` are `0` and
    // finite, so coercing first reads "not set" as "no columns" (§203).
    expect(columnsOf(undefined)).toBe(DEFAULT_COLUMNS);
    expect(columnsOf(null)).toBe(DEFAULT_COLUMNS);
    expect(columnsOf("")).toBe(DEFAULT_COLUMNS);
    expect(columnsOf("abc")).toBe(DEFAULT_COLUMNS);
  });

  it("reads a column count written as a string", () => {
    expect(columnsOf("5")).toBe(5);
  });

  it("puts one option per row when vertical", () => {
    expect(layoutStyle("vertical", 4).gridTemplateColumns).toBe("1fr");
  });

  it("uses the column count only for a grid", () => {
    expect(layoutStyle("grid", 4).gridTemplateColumns).toBe("repeat(4, minmax(0, 1fr))");
    expect(layoutStyle("horizontal", 4).gridTemplateColumns).not.toContain("4");
  });

  it("clamps the count inside the grid template", () => {
    expect(layoutStyle("grid", 99).gridTemplateColumns)
      .toBe(`repeat(${MAX_COLUMNS}, minmax(0, 1fr))`);
  });
});

describe("modeOf", () => {
  it("reads the settings of a resolved pair rather than a named one", () => {
    // The pair is resolved first, so an illegal combination reads the settings
    // of what will actually be drawn.
    expect(modeOf("multiple", "radio").hasLayout).toBe(false);
    expect(modeOf("multiple", "radio").placeholder).toBe("Search options...");
  });
});
