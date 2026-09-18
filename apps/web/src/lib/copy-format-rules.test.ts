/** Copying conditional formatting between properties (§388;
 *  `object-link-types` p.107). */
import { describe, expect, it } from "vitest";
import type { ConditionalRule } from "./types";
import {
  copyRulesTo, copySummary, copyTargets, willOverwrite,
} from "./copy-format-rules";

const rule = (colour: string): ConditionalRule =>
  ({ comparison: "is_null", style: { colour } } as unknown as ConditionalRule);

const prop = (api_name: string, rules: ConditionalRule[] | null = null) =>
  ({ api_name, conditional_format: rules });

const PROPS = [
  prop("status", [rule("#f00")]),
  prop("owner"),
  prop("total", [rule("#0f0")]),
  prop("  "),
];

describe("where a copy can go", () => {
  it("offers every named property except the one being copied from", () => {
    expect(copyTargets(PROPS, "status").map((p) => p.api_name)).toEqual(["owner", "total"]);
  });

  it("does not offer a property that has no name yet", () => {
    // A blank row is one somebody is part-way through adding; rules on it
    // would be rules on something nothing can refer to.
    expect(copyTargets(PROPS, "status").map((p) => p.api_name)).not.toContain("  ");
  });

  it("does not offer the source back to itself", () => {
    // The negative control: copying a property's rules onto itself is a
    // no-op dressed as an action.
    expect(copyTargets(PROPS, "owner").map((p) => p.api_name)).not.toContain("owner");
  });
});

describe("which of the chosen lose rules they already had", () => {
  it("takes only the chosen ones that have rules", () => {
    expect(willOverwrite(PROPS, ["owner", "total"]).map((p) => p.api_name)).toEqual(["total"]);
  });

  it("ignores a property with rules that was not chosen", () => {
    expect(willOverwrite(PROPS, ["owner"])).toEqual([]);
  });

  it("does not count an empty rule list as rules", () => {
    // `[]` and `null` are the same thing to a reader — nothing is painted —
    // so warning about losing an empty list would be a warning about nothing.
    expect(willOverwrite([prop("a", [])], ["a"])).toEqual([]);
  });
});

describe("what the dialog says before the copy", () => {
  it("asks for a choice when nothing is ticked", () => {
    expect(copySummary(PROPS, [])).toContain("choose the properties");
  });

  it("says where the rules are going", () => {
    expect(copySummary(PROPS, ["owner"])).toBe("copy to 1 property");
  });

  it("says what will be overwritten, and names them while it can", () => {
    // p.107 states the overwrite; §214 is why the reader is told before the
    // click rather than after.
    expect(copySummary(PROPS, ["owner", "total"]))
      .toBe("copy to 2 properties, overwriting the rules on 1 (total)");
  });

  it("stops naming them when there are too many to read", () => {
    const many = ["a", "b", "c", "d"].map((n) => prop(n, [rule("#00f")]));
    expect(copySummary(many, ["a", "b", "c", "d"]))
      .toBe("copy to 4 properties, overwriting the rules on 4");
  });
});

describe("what the copy does", () => {
  it("puts the rules on the chosen properties", () => {
    const next = copyRulesTo(PROPS, [rule("#abc")], ["owner"]);
    expect(next.find((p) => p.api_name === "owner")!.conditional_format)
      .toEqual([rule("#abc")]);
  });

  it("replaces what was there rather than adding to it", () => {
    // p.107: "they will be overwritten by the new rules" — not appended.
    const next = copyRulesTo(PROPS, [rule("#abc")], ["total"]);
    expect(next.find((p) => p.api_name === "total")!.conditional_format)
      .toEqual([rule("#abc")]);
  });

  it("leaves every property that was not chosen exactly as it was", () => {
    const next = copyRulesTo(PROPS, [rule("#abc")], ["owner"]);
    expect(next.find((p) => p.api_name === "total")!.conditional_format)
      .toEqual([rule("#0f0")]);
    expect(next.find((p) => p.api_name === "status")!.conditional_format)
      .toEqual([rule("#f00")]);
  });

  it("gives each target its own array rather than one they share", () => {
    // **The bug this prevents would look like the copy working.** Rules are
    // edited in place in this editor, so a shared array would make editing
    // one property's rules edit every property it was copied to.
    const next = copyRulesTo(PROPS, [rule("#abc")], ["owner", "total"]);
    const a = next.find((p) => p.api_name === "owner")!.conditional_format!;
    const b = next.find((p) => p.api_name === "total")!.conditional_format!;
    expect(a).not.toBe(b);
    expect(a[0]).not.toBe(b[0]);
  });
});
