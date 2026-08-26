import { describe, expect, it } from "vitest";

import {
  canReset, isPartial, suffixText, toDisplay, toStored, type NumberFormat,
} from "./number-input";

/** p.468's Numeric Input. */

describe("toStored", () => {
  it("reads a plain number", () => {
    expect(toStored("42")).toBe(42);
    expect(toStored("-3.5")).toBe(-3.5);
    expect(toStored("  7 ")).toBe(7);
  });

  it("calls an empty field null, not zero", () => {
    // **Different answers.** A field nobody has touched has no value; one
    // somebody typed `0` into has the value zero, and a filter reading the
    // second must not behave like the first.
    expect(toStored("")).toBeNull();
    expect(toStored("   ")).toBeNull();
    expect(toStored("0")).toBe(0);
  });

  it("calls a half-typed entry undefined, which is a third answer", () => {
    // `null` means "clear the variable"; `undefined` means "do not write
    // anything yet". Collapsing them makes the field clear the variable on the
    // keystroke between `1` and `1.5`.
    expect(toStored("-")).toBeUndefined();
    expect(toStored("1.")).toBeUndefined();
    expect(toStored("1e")).toBeUndefined();
    expect(toStored("1e-")).toBeUndefined();
  });

  it("calls something that is not a number null", () => {
    expect(toStored("abc")).toBeNull();
    expect(toStored("1.2.3")).toBeNull();
    expect(toStored("Infinity")).toBeNull();
  });

  it("accepts grouping separators back", () => {
    // The field shows them, so the field has to be editable with them in
    // place — otherwise turning grouping on makes the widget reject what it
    // itself just displayed.
    expect(toStored("1,234", { grouping: true })).toBe(1234);
    expect(toStored("1,234,567", { grouping: true })).toBe(1234567);
  });

  it("divides by a hundred when the suffix is a percent sign", () => {
    // p.468: "If the percent sign is selected, the output variable of the
    // widget will be the user-entered value divided by 100."
    expect(toStored("25", { suffix: "percent" })).toBe(0.25);
    expect(toStored("100", { suffix: "percent" })).toBe(1);
    expect(toStored("0", { suffix: "percent" })).toBe(0);
  });

  it("does not divide for the other two suffix kinds", () => {
    // The arithmetic belongs to the percent *choice*, not to having a suffix.
    expect(toStored("25", { suffix: "text" })).toBe(25);
    expect(toStored("25", { suffix: "none" })).toBe(25);
    expect(toStored("25")).toBe(25);
  });

  it("rounds away the float noise that dividing by a hundred creates", () => {
    // `8.2 / 100` is `0.08199999999999999` in binary. Stored raw, the value
    // multiplied back gives `8.199999999999999`, so a number that survives a
    // round trip on paper does not survive one in a float.
    expect(toStored("8.2", { suffix: "percent" })).toBe(0.082);
    expect(toStored("2.9", { suffix: "percent" })).toBe(0.029);
  });
});

describe("toDisplay", () => {
  it("shows a plain number", () => {
    expect(toDisplay(42)).toBe("42");
    expect(toDisplay(-3.5)).toBe("-3.5");
  });

  it("shows nothing for no value", () => {
    expect(toDisplay(null)).toBe("");
    expect(toDisplay(undefined)).toBe("");
    expect(toDisplay("")).toBe("");
  });

  it("shows zero, which is a value", () => {
    expect(toDisplay(0)).toBe("0");
  });

  it("shows nothing for something that is not a number", () => {
    expect(toDisplay("abc")).toBe("");
    expect(toDisplay(Number.NaN)).toBe("");
    expect(toDisplay(Number.POSITIVE_INFINITY)).toBe("");
  });

  it("multiplies by a hundred when the suffix is a percent sign", () => {
    expect(toDisplay(0.25, { suffix: "percent" })).toBe("25");
    expect(toDisplay(0.082, { suffix: "percent" })).toBe("8.2");
  });

  it("groups thousands when asked, and not otherwise", () => {
    expect(toDisplay(1234567, { grouping: true })).toBe("1,234,567");
    expect(toDisplay(1234567)).toBe("1234567");
    expect(toDisplay(999, { grouping: true })).toBe("999");
    expect(toDisplay(1000, { grouping: true })).toBe("1,000");
  });

  it("groups the integer part only", () => {
    // A separator in the fraction would be read back as a different number.
    expect(toDisplay(1234.5678, { grouping: true })).toBe("1,234.5678");
  });

  it("keeps the sign outside the grouping", () => {
    expect(toDisplay(-1234567, { grouping: true })).toBe("-1,234,567");
  });

  it("leaves exponent form alone", () => {
    // There are no thousands to separate, and commas inserted into one produce
    // something that is not a number at all.
    expect(toDisplay(1e21, { grouping: true })).toBe("1e+21");
  });

  it("groups a percentage after multiplying, not before", () => {
    // The order matters and only one of them is right: the field shows the
    // percentage, so that is the number being grouped.
    expect(toDisplay(12345.67, { suffix: "percent", grouping: true }))
      .toBe("1,234,567");
  });
});

describe("toStored and toDisplay round-trip", () => {
  /** Asserted as a property rather than by example, because a widget where
   * typing a number and reading it back gives a different number is a widget
   * that edits its own data — and the examples that break it are exactly the
   * ones nobody thinks to write down. */
  const entries = ["0", "1", "42", "-7", "3.14", "8.2", "2.9", "1234567", "0.001", "99.99"];
  const formats: NumberFormat[] = [
    {},
    { grouping: true },
    { suffix: "percent" },
    { suffix: "percent", grouping: true },
    { suffix: "text" },
  ];

  for (const format of formats) {
    for (const entry of entries) {
      it(`survives ${entry} with ${JSON.stringify(format)}`, () => {
        const stored = toStored(entry, format);
        const shown = toDisplay(stored, format);
        // Grouping is the one thing that changes the text, so it comes back
        // out before comparing - the number has to be the same, and it is the
        // number the round trip is about.
        expect(shown.replace(/,/g, "")).toBe(String(Number(entry)));
      });
    }
  }

  it("survives a second trip through the field", () => {
    // The realistic case: somebody types, the field reformats, they edit the
    // reformatted text. If that is not stable the value walks on every edit.
    const format: NumberFormat = { suffix: "percent", grouping: true };
    const once = toStored("8.2", format);
    const shown = toDisplay(once, format);
    expect(toStored(shown, format)).toBe(once);
  });
});

describe("isPartial", () => {
  it("recognises the states of typing a number", () => {
    for (const t of ["", "  ", "-", "+", "1.", "-1.", ".", "1e", "2E-"]) {
      expect(isPartial(t), t).toBe(true);
    }
  });

  it("does not call a finished number partial", () => {
    for (const t of ["0", "1", "-1", "1.5", ".5", "1e5", "1E-5"]) {
      expect(isPartial(t), t).toBe(false);
    }
  });
});

describe("canReset", () => {
  it("is offered only when there is something to clear", () => {
    // p.468's reset button. Over an empty field it is a control that does
    // nothing, which reads as a broken one.
    expect(canReset(5)).toBe(true);
    expect(canReset(0)).toBe(true);
    expect(canReset(null)).toBe(false);
    expect(canReset(undefined)).toBe(false);
    expect(canReset("")).toBe(false);
  });
});

describe("suffixText", () => {
  it("shows a percent sign for the percent kind, whatever text is set", () => {
    expect(suffixText({ suffix: "percent" }, "kg")).toBe("%");
    expect(suffixText({ suffix: "percent" }, null)).toBe("%");
  });

  it("shows the author's text for the text kind", () => {
    expect(suffixText({ suffix: "text" }, "kg")).toBe("kg");
    expect(suffixText({ suffix: "text" }, "  kg  ")).toBe("kg");
  });

  it("shows nothing for text that is not set", () => {
    // An empty suffix box should not draw an empty suffix - a gap on the right
    // of the field with nothing in it reads as a rendering fault.
    expect(suffixText({ suffix: "text" }, "")).toBeNull();
    expect(suffixText({ suffix: "text" }, "   ")).toBeNull();
    expect(suffixText({ suffix: "text" }, null)).toBeNull();
  });

  it("shows nothing when there is no suffix", () => {
    expect(suffixText({ suffix: "none" }, "kg")).toBeNull();
    expect(suffixText({}, "kg")).toBeNull();
  });
});
