import { describe, expect, it } from "vitest";

import {
  DEFAULT_FORMAT, DEFAULT_ROWS, MAX_ROWS, MIN_ROWS, TEXT_FORMATS,
  formatOf, rowsOf, settingsOf, submitsOnEnter, toDisplay, toStored,
} from "./text-input";

/** p.465's Text Input. */

/** **Written out by hand**, the way §201's `EXPECTED_DIRECTION` is and for the
 * same reason: a test that reads its expectation out of the catalogue under
 * test agrees with whatever the catalogue says. p.465 puts "event on enter"
 * under Single line and "initial height" under Text area, and this is the
 * second opinion that notices if either moves. */
const EXPECTED: Record<string, { submitsOnEnter: boolean; hasHeight: boolean; multiline: boolean }> = {
  line: { submitsOnEnter: true, hasHeight: false, multiline: false },
  area: { submitsOnEnter: false, hasHeight: true, multiline: true },
};

describe("TEXT_FORMATS", () => {
  it("has exactly the formats this build renders", () => {
    // Markdown is absent on purpose (p.466 describes an editor, not a format
    // flag). Offering it as a third option that drew a plain textarea is the
    // thing every catalogue in this codebase exists to avoid.
    expect(Object.keys(TEXT_FORMATS).sort()).toEqual(["area", "line"]);
  });

  it("has a hand-written expectation for every format", () => {
    expect(Object.keys(EXPECTED).sort()).toEqual(Object.keys(TEXT_FORMATS).sort());
  });

  it.each(Object.entries(EXPECTED))("configures %s as p.465 describes", (name, want) => {
    const got = TEXT_FORMATS[name]!;
    expect(got.submitsOnEnter).toBe(want.submitsOnEnter);
    expect(got.hasHeight).toBe(want.hasHeight);
    expect(got.multiline).toBe(want.multiline);
  });

  it("gives every format a label", () => {
    // The settings panel renders from this catalogue, so a format with no
    // label is an option in a dropdown with nothing written on it.
    for (const [name, format] of Object.entries(TEXT_FORMATS)) {
      expect(format.label, name).toBeTruthy();
    }
  });

  it("never offers enter-to-submit on a multiline format", () => {
    // **The rule behind the asymmetry**, stated independently of which formats
    // exist: in a text area the enter key inserts a newline, so a widget that
    // also fired an event on it would fight the person typing.
    for (const [name, format] of Object.entries(TEXT_FORMATS)) {
      if (format.multiline) expect(format.submitsOnEnter, name).toBe(false);
    }
  });
});

describe("formatOf", () => {
  it("passes a known format through", () => {
    expect(formatOf("line")).toBe("line");
    expect(formatOf("area")).toBe("area");
  });

  it("falls back to the single line specifically", () => {
    // **Named, not compared to `DEFAULT_FORMAT`.** §203's harness moved the
    // constant to `"area"` and survived, because every assertion below read
    // its expectation out of the thing under test. The fallback matters *as a
    // single line*: a document whose format this build does not know gets the
    // narrower of the two, so a module does not silently acquire paragraph
    // fields where it had one-line ones.
    expect(DEFAULT_FORMAT).toBe("line");
    expect(formatOf("markdown")).toBe("line");
  });

  it("falls back for anything it does not know", () => {
    // A saved document can name a format this build does not have - an app
    // authored against a later version, or one whose Markdown format arrives
    // before its editor. A field the viewer can type into is the failure worth
    // having; a widget that draws nothing leaves a hole where a field was.
    expect(formatOf(undefined)).toBe("line");
    expect(formatOf(null)).toBe("line");
    expect(formatOf(7)).toBe("line");
    expect(formatOf("")).toBe("line");
  });

  it("does not treat an inherited property name as a format", () => {
    // `"constructor" in TEXT_FORMATS` is true for a plain object, so a
    // document naming it would resolve to a format that is a function.
    expect(formatOf("constructor")).toBe(DEFAULT_FORMAT);
    expect(formatOf("toString")).toBe(DEFAULT_FORMAT);
  });
});

describe("settingsOf and submitsOnEnter", () => {
  it("reads the settings of the named format", () => {
    expect(settingsOf("area").hasHeight).toBe(true);
    expect(settingsOf("line").hasHeight).toBe(false);
  });

  it("answers for an unknown format the way the fallback does", () => {
    expect(submitsOnEnter("markdown")).toBe(TEXT_FORMATS[DEFAULT_FORMAT]!.submitsOnEnter);
  });

  it("says enter submits on a single line and not in a text area", () => {
    expect(submitsOnEnter("line")).toBe(true);
    expect(submitsOnEnter("area")).toBe(false);
  });
});

describe("rowsOf", () => {
  it("takes a number as given", () => {
    expect(rowsOf(6)).toBe(6);
  });

  it("defaults when there is no number", () => {
    expect(rowsOf(undefined)).toBe(DEFAULT_ROWS);
    expect(rowsOf(null)).toBe(DEFAULT_ROWS);
    expect(rowsOf("")).toBe(DEFAULT_ROWS);
    expect(rowsOf("abc")).toBe(DEFAULT_ROWS);
    expect(rowsOf(Number.NaN)).toBe(DEFAULT_ROWS);
    expect(rowsOf(Number.POSITIVE_INFINITY)).toBe(DEFAULT_ROWS);
  });

  it("reads a number written as a string", () => {
    // Which is what an `<input type="number">` in the settings panel hands
    // back, so refusing it would make the control not work at all.
    expect(rowsOf("8")).toBe(8);
  });

  it("clamps to a range a field can actually be", () => {
    expect(rowsOf(0)).toBe(MIN_ROWS);
    expect(rowsOf(-5)).toBe(MIN_ROWS);
    expect(rowsOf(9999)).toBe(MAX_ROWS);
  });

  it("rounds before clamping, not after", () => {
    // `2.6` is somebody dragging a control. Truncating it to 2 loses the row
    // they were asking for; the clamp then only applies to what is left.
    expect(rowsOf(2.6)).toBe(3);
    expect(rowsOf(1.6)).toBe(MIN_ROWS);
  });
});

describe("toStored", () => {
  it("stores what was typed", () => {
    expect(toStored("hello")).toBe("hello");
  });

  it("calls an empty field null rather than an empty string", () => {
    // Matching p.468's Numeric Input. A variable holding `""` has been *set to
    // the empty string*; one holding `null` has no value, and the difference
    // shows the moment somebody reads it in a `concat` or writes it through an
    // action.
    expect(toStored("")).toBeNull();
  });

  it("keeps whitespace", () => {
    // A field where somebody typed two spaces holds two spaces. Trimming here
    // would make the widget quietly disagree with what is on screen, and a
    // trim belongs in the transform that needs one.
    expect(toStored("  ")).toBe("  ");
    expect(toStored(" hi ")).toBe(" hi ");
  });
});

describe("toDisplay", () => {
  it("shows the stored string", () => {
    expect(toDisplay("hello")).toBe("hello");
  });

  it("shows nothing for no value", () => {
    expect(toDisplay(null)).toBe("");
    expect(toDisplay(undefined)).toBe("");
  });

  it("shows an empty string as empty", () => {
    expect(toDisplay("")).toBe("");
  });

  it("shows a non-string value rather than hiding it", () => {
    // The variable is declared `string`, but a derivation can hand back a
    // number and the server does not refuse it. Showing `0` is honest; showing
    // an empty field would say the variable had no value.
    expect(toDisplay(0)).toBe("0");
    expect(toDisplay(false)).toBe("false");
  });
});
