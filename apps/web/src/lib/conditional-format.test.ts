/**
 * Evaluating conditional formatting rules (Foundry `object-link-types`
 * p.102–109).
 *
 * The server refuses a rule that cannot be evaluated, and that is tested in
 * `apps/api/tests/test_conditional_format.py`. This is the other half: given
 * rules that saved, which one wins on which object.
 *
 * p.102's own example type is the fixture — an aircraft with a `type`, a
 * `wifi` flag and a performance number — because p.103 and p.106 both work
 * through it, and matching the spec's example makes it obvious when a rule
 * here means something different from the rule there.
 */
import { describe, expect, it } from "vitest";

import type { ConditionalRule } from "@/lib/types";
import { conditionalStyle } from "./conditional-format";

const GREEN = { colour: "#1a7f37" };
const RED = { colour: "#b91c1c" };
const GREY = { colour: "#6b7280" };

/** An aircraft, as p.102 pictures one. Values are strings because that is how
 * a CSV sync stores them — the untyped-property fact this whole file has to
 * survive. */
const A320 = { type: "A320", wifi: "true", performance: "0.95" };
const A321 = { type: "A321", wifi: "false", performance: "0.6" };

function style(rules: ConditionalRule[], properties: Record<string, unknown>) {
  return conditionalStyle(rules, properties);
}

describe("nothing configured", () => {
  it("has no opinion", () => {
    expect(conditionalStyle(null, A320)).toBeNull();
    expect(conditionalStyle([], A320)).toBeNull();
  });

  it("is null rather than an empty style when no rule matches", () => {
    // A caller has to tell "no rule applied" from "a rule applied" — the
    // second always carries something, because the server refuses a rule that
    // changes nothing.
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "type", comparison: "string",
        operator: "is_exactly", value: "A380", ...GREEN },
    ];
    expect(style(rules, A320)).toBeNull();
  });
});

describe("p.103's own rules", () => {
  const wifi: ConditionalRule[] = [
    { kind: "standard", property: "wifi", comparison: "boolean", value: true, ...GREEN },
    { kind: "standard", property: "wifi", comparison: "boolean", value: false, ...RED },
  ];

  it("greens a true flag and reds a false one", () => {
    expect(style(wifi, A320)).toEqual(GREEN);
    expect(style(wifi, A321)).toEqual(RED);
  });

  it("reads a boolean that arrived as text", () => {
    // The fixture's "true" is what a CSV sync stores. A comparison that only
    // handled a real boolean would leave every synced row unpainted, which is
    // the case this rule is actually for.
    expect(style(wifi, { wifi: true })).toEqual(GREEN);
    expect(style(wifi, { wifi: "TRUE" })).toEqual(GREEN);
    expect(style(wifi, { wifi: "yes" })).toBeNull();
  });

  it("matches an exact string", () => {
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "type", comparison: "string",
        operator: "is_exactly", value: "A320", ...GREEN },
    ];
    expect(style(rules, A320)).toEqual(GREEN);
    expect(style(rules, A321)).toBeNull();
  });
});

describe("first match wins, and the fallback goes last (p.105 label A)", () => {
  const rules: ConditionalRule[] = [
    { kind: "standard", property: "type", comparison: "string",
      operator: "is_exactly", value: "A320", ...GREEN },
    { kind: "always", ...GREY },
  ];

  it("takes the earlier rule when both would match", () => {
    // The always-true rule matches this object too. If order did not decide,
    // this would be grey — which is the whole of what "fallback" means.
    expect(style(rules, A320)).toEqual(GREEN);
  });

  it("falls back when nothing earlier matched", () => {
    expect(style(rules, A321)).toEqual(GREY);
  });
});

describe("comparisons", () => {
  it("does p.106's Starts with, and only at the start", () => {
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "type", comparison: "string",
        operator: "starts_with", value: "A32", ...GREEN },
    ];
    expect(style(rules, A320)).toEqual(GREEN);
    expect(style(rules, A321)).toEqual(GREEN);
    expect(style(rules, { type: "B737" })).toBeNull();
    // The case that tells `starts_with` apart from `contains`: the substring
    // is there, and not where the operator says. Without it the two operators
    // are the same function as far as any test can tell.
    expect(style(rules, { type: "XA320" })).toBeNull();
  });

  it("does contains and ends with, each only where it says", () => {
    const contains: ConditionalRule[] = [
      { kind: "standard", property: "type", comparison: "string",
        operator: "contains", value: "32", ...GREEN },
    ];
    const ends: ConditionalRule[] = [
      { kind: "standard", property: "type", comparison: "string",
        operator: "ends_with", value: "21", ...GREEN },
    ];
    expect(style(contains, A320)).toEqual(GREEN);
    expect(style(contains, { type: "XA320" })).toEqual(GREEN);
    expect(style(ends, A320)).toBeNull();
    expect(style(ends, A321)).toEqual(GREEN);
    // Present, but not at the end.
    expect(style(ends, { type: "A321X" })).toBeNull();
  });

  it("bounds a numeric range inclusively at both ends", () => {
    // p.105's example is a threshold a value "drops underneath", and an author
    // who types 0.8 as a max means 0.8 is still in.
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "performance", comparison: "numeric_range",
        max: 0.8, ...RED },
    ];
    expect(style(rules, A321)).toEqual(RED);       // 0.6
    expect(style(rules, A320)).toBeNull();          // 0.95
    expect(style(rules, { performance: "0.8" })).toEqual(RED);

    // And the same at the other end, which is its own branch: a rule written
    // with only a max never exercises the min comparison at all.
    const atLeast: ConditionalRule[] = [
      { kind: "standard", property: "performance", comparison: "numeric_range",
        min: 0.6, ...GREEN },
    ];
    expect(style(atLeast, A321)).toEqual(GREEN);    // exactly the bound
    expect(style(atLeast, { performance: "0.59" })).toBeNull();
  });

  it("compares numbers as numbers, not as text", () => {
    // The trap this whole platform keeps: "250" sorts before "40" as text.
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "performance", comparison: "numeric_range",
        min: 100, ...RED },
    ];
    expect(style(rules, { performance: "250" })).toEqual(RED);
    expect(style(rules, { performance: "40" })).toBeNull();
  });

  it("matches an exact number across the string/number divide", () => {
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "performance", comparison: "numeric_exact",
        value: 1, ...GREEN },
    ];
    expect(style(rules, { performance: "1.0" })).toEqual(GREEN);
    expect(style(rules, { performance: 1 })).toEqual(GREEN);
    expect(style(rules, { performance: "1.5" })).toBeNull();
  });
});

describe("reading one property to paint another (p.105–106 label B)", () => {
  it("colours by a property other than its own", () => {
    // "assume we want to color the value for Type in red when the value of
    // Performance factor drops underneath a certain threshold … the color
    // would still show on Type."
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "performance", comparison: "numeric_range",
        max: 0.8, ...RED },
    ];
    expect(style(rules, A321)).toEqual(RED);
    expect(style(rules, A320)).toBeNull();
  });

  it("compares against another property's value (label E)", () => {
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "type", comparison: "string",
        operator: "is_exactly", value_property: "preferred", ...GREEN },
    ];
    expect(style(rules, { ...A320, preferred: "A320" })).toEqual(GREEN);
    expect(style(rules, { ...A320, preferred: "A321" })).toBeNull();
  });
});

describe("null, and negation (p.105 label F)", () => {
  const grey: ConditionalRule[] = [
    { kind: "standard", property: "type", comparison: "is_null", ...GREY },
  ];

  it("does p.106's colour-it-grey-if-null", () => {
    expect(style(grey, { type: null })).toEqual(GREY);
    expect(style(grey, {})).toEqual(GREY);
    // The empty string counts: a CSV sync writes one for a blank cell, so a
    // stricter reading would make the rule useless on the data it is for.
    expect(style(grey, { type: "" })).toEqual(GREY);
    expect(style(grey, A320)).toBeNull();
  });

  it("inverts a rule", () => {
    // "To color all planes in blue that are not A320, switch this to False."
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "type", comparison: "string",
        operator: "is_exactly", value: "A320", negate: true, colour: "#1d4ed8" },
    ];
    expect(style(rules, A321)).toEqual({ colour: "#1d4ed8" });
    expect(style(rules, A320)).toBeNull();
  });

  it("does not let a negated rule paint the rows it knows nothing about", () => {
    /**
     * The one that is easy to get wrong. "Is not exactly A320" is *true* of an
     * object with no type at all, if the comparison is evaluated on the empty
     * value and then flipped — so an inverted rule would quietly colour every
     * incomplete row. Absence is not a match, before negation; `is_null` is
     * the comparison for asking about absence.
     */
    const rules: ConditionalRule[] = [
      { kind: "standard", property: "type", comparison: "string",
        operator: "is_exactly", value: "A320", negate: true, colour: "#1d4ed8" },
    ];
    expect(style(rules, { type: null })).toBeNull();
    expect(style(rules, {})).toBeNull();
  });
});

describe("what a matching rule asks for", () => {
  it("carries colour, background and alignment through", () => {
    const rules: ConditionalRule[] = [
      { kind: "always", colour: "#111111", background: "#eeeeee", align: "right" },
    ];
    expect(style(rules, A320)).toEqual({
      colour: "#111111", background: "#eeeeee", align: "right",
    });
  });

  it("carries only what the rule set", () => {
    expect(style([{ kind: "always", align: "right" }], A320)).toEqual({ align: "right" });
  });
});
