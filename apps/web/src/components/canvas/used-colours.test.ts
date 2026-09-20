import { describe, expect, it } from "vitest";
import { BACKGROUND_PRESETS } from "./style";
import { emptyReason, referenceUses, usageLabel, usedColours } from "./used-colours";

function node(props: Record<string, unknown>) {
  return { type: { resolvedName: "CanvasSection" }, props };
}

describe("which colours count", () => {
  it("finds a custom hex on a background", () => {
    const found = usedColours({ s1: node({ background: "#ff0000" }) });
    expect(found).toEqual([{ hex: "#ff0000", uses: [{ node: "s1", prop: "background" }] }]);
  });

  it("does not list an intent colour", () => {
    // p.213: "usage of intent colors will not be displayed in the Used colors
    // panel." Our presets are those - `shade-2` names a role, not a value
    // somebody chose - and listing them would fill the panel with things
    // nobody typed and nobody wants to swap.
    //
    // Every preset, not one of them: this is the assertion that keeps the
    // exclusion true if somebody adds a preset later, and it is the only
    // thing standing between p.213 and a panel that lists the platform's own
    // palette back at its author. What *does* the excluding is the hex test -
    // see the note in `record` - so this also pins the claim that the two
    // cannot come apart.
    for (const preset of Object.keys(BACKGROUND_PRESETS)) {
      expect(usedColours({ s1: node({ background: preset }) })).toEqual([]);
    }
  });

  it("does not list a free-text CSS colour", () => {
    // `resolveBackground` passes `red` and `var(--panel)` through because
    // modules hold them, but p.214 offers "the hex code… to copy" - a row
    // whose value is not a hex does not do what the panel says it does.
    const found = usedColours({
      a: node({ background: "red" }),
      b: node({ background: "var(--panel)" }),
    });
    expect(found).toEqual([]);
  });

  it("ignores an empty or missing value", () => {
    expect(usedColours({ a: node({ background: "" }), b: node({}) })).toEqual([]);
  });

  it("survives a document that is not one", () => {
    // A module whose definition has never been saved arrives as `undefined`,
    // and the panel renders before the first save like every other panel.
    expect(usedColours(undefined)).toEqual([]);
    expect(usedColours(null)).toEqual([]);
    expect(usedColours({ a: "not a node", b: node({ background: "#123456" }) }))
      .toHaveLength(1);
  });
});

describe("one colour, one row", () => {
  it("treats #FFF and #ffffff as the same colour", () => {
    // **Or a module with four colours reports twelve.** The hex is what a
    // reader copies and compares, so two spellings of one value being two rows
    // is the panel disagreeing with itself.
    const found = usedColours({
      a: node({ background: "#FFF" }),
      b: node({ background: "#ffffff" }),
    });
    expect(found).toHaveLength(1);
    expect(found[0]?.hex).toBe("#ffffff");
    expect(found[0]?.uses).toHaveLength(2);
  });
});

describe("nested colours", () => {
  it("finds a Timeline layer's colour, with its index", () => {
    // The index is what makes the answer usable: "used by the Timeline" is
    // not enough to find which layer to change.
    const found = usedColours({
      tl: node({ layers: [{ title: "One" }, { title: "Two", colour: "#0a0" }] }),
    });
    expect(found[0]?.uses).toEqual([{ node: "tl", prop: "layers[1].colour" }]);
  });

  it("finds a pie segment's colour, spelled the way the pie spells it", () => {
    // p.310's override is `color` and p.348's layer is `colour`, and the two
    // live in the same document. A walker that knew one spelling would pass
    // the layer test above and still miss every pie in the corpus - which is
    // the shape of bug this pair exists to catch.
    const found = usedColours({
      p: node({ segments: [{ value: "north", color: "#123456" }] }),
    });
    expect(found[0]?.uses).toEqual([{ node: "p", prop: "segments[0].color" }]);
  });

  it("does not read a layer's colour under the pie's spelling", () => {
    // The mirror: `layers[].color` is not a prop anything writes, so finding
    // one would mean the walker is matching on the field name alone.
    expect(usedColours({ tl: node({ layers: [{ color: "#123456" }] }) })).toEqual([]);
    expect(usedColours({ p: node({ segments: [{ colour: "#123456" }] }) })).toEqual([]);
  });

  it("finds both of the Stepper's colours, not just the first", () => {
    // p.313 has a Completed colour *and* an Active one, and a list that
    // stopped at the first would leave half a widget's colours unfindable -
    // which is exactly the shape of gap this panel exists to close.
    const found = usedColours({
      st: node({ completedColour: "#0a0b0c", activeColour: "#0d0e0f" }),
    });
    expect(found.map((c) => c.hex)).toEqual(["#0a0b0c", "#0d0e0f"]);
    expect(found[1]?.uses).toEqual([{ node: "st", prop: "activeColour" }]);
  });

  it("takes the Stepper's pair from the widget, not from its steps", () => {
    // p.313's Completed and Active colours are props of the Stepper itself.
    // Reading them off each step would find nothing in a real document.
    const found = usedColours({
      st: node({
        steps: [{ label: "One", completedColour: "#abcdef" }],
        completedColour: "#0a0b0c",
      }),
    });
    expect(found).toHaveLength(1);
    expect(found[0]?.uses).toEqual([{ node: "st", prop: "completedColour" }]);
  });

  it("is not confused by a list of something else", () => {
    // `null` is in here on purpose: it is the one entry that makes the guard
    // load-bearing rather than decorative, because reading a field off a
    // string or a number is merely undefined while reading one off `null`
    // throws (§212 - the raw JSON editor can put anything in this array).
    expect(usedColours({ p: node({ layers: ["not an object", 7, null] }) })).toEqual([]);
  });
});

describe("the order", () => {
  it("puts the most widely used first, because that is what you swap", () => {
    const found = usedColours({
      a: node({ background: "#111111" }),
      b: node({ background: "#222222" }),
      c: node({ background: "#222222" }),
    });
    expect(found.map((c) => c.hex)).toEqual(["#222222", "#111111"]);
  });

  it("breaks ties on the hex so the list does not reshuffle", () => {
    const found = usedColours({
      a: node({ background: "#bbbbbb" }),
      b: node({ background: "#aaaaaa" }),
    });
    expect(found.map((c) => c.hex)).toEqual(["#aaaaaa", "#bbbbbb"]);
  });
});

describe("what a row says", () => {
  it("counts places rather than props", () => {
    // Two colours on one widget is one place to go and look.
    expect(usageLabel({
      hex: "#000000",
      uses: [{ node: "s1", prop: "completedColour" }, { node: "s1", prop: "activeColour" }],
    })).toBe("1 place");
  });

  it("pluralises properly", () => {
    expect(usageLabel({
      hex: "#000000",
      uses: [{ node: "a", prop: "background" }, { node: "b", prop: "background" }],
    })).toBe("2 places");
  });
});

describe("an empty panel", () => {
  it("does not report a themed module as having no colours", () => {
    // A module using only presets is fully coloured and has nothing to tidy -
    // a good state, not an empty one.
    expect(emptyReason([])).toContain("standard shades");
    expect(emptyReason([{ hex: "#fff", uses: [] }])).toBeNull();
  });
});

describe("documents that arrived from anywhere", () => {
  it("answers nothing for a layout that is not a map", () => {
    expect(usedColours(null)).toEqual([]);
    expect(usedColours("nope")).toEqual([]);
  });

  it("survives a node with no props", () => {
    expect(usedColours({ a: { type: { resolvedName: "X" } } })).toEqual([]);
  });
});

describe("referenceUses (p.214; §414)", () => {
  it("finds a saved colour wherever a colour prop sits", () => {
    // The same walk as `usedColours`, which is the point of extracting it: a
    // saved colour that worked on a section and not on a Timeline layer would
    // read as "that widget does not support it" and go unreported.
    const uses = referenceUses({
      page: { props: { background: "saved:c1" } },
      chart: { props: { segments: [{ color: "saved:c1" }, { color: "#112233" }] } },
      stepper: { props: { completedColour: "saved:c2" } },
    });
    expect(uses.c1).toEqual([
      { node: "page", prop: "background" },
      { node: "chart", prop: "segments[0].color" },
    ]);
    expect(uses.c2).toEqual([{ node: "stepper", prop: "completedColour" }]);
  });

  it("keys by id, not by name", () => {
    // A rename must not change where a colour is used, which is the whole
    // reason a reference names an id.
    expect(Object.keys(referenceUses({ p: { props: { background: "saved:c1" } } })))
      .toEqual(["c1"]);
  });

  it("reports a colour nothing references as absent, not as zero", () => {
    // §226: the caller needs to tell "no uses" from "never asked", and an
    // empty array for every id in the palette would be a guess about ids this
    // walk has never seen.
    expect(referenceUses({ p: { props: { background: "#112233" } } })).toEqual({});
  });

  it("ignores a hex, a preset and a reference to nothing", () => {
    expect(referenceUses({
      a: { props: { background: "#112233" } },
      b: { props: { background: "shade-2" } },
      c: { props: { background: "saved:" } },
    })).toEqual({});
  });
});
