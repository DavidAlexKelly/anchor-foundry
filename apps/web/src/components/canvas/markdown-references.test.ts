import { describe, expect, it } from "vitest";

import {
  isLit, numberReferences, referenceTypesOf, selectionBehaviorOf, keysToColor, referenceColorOf, newReferenceTypeId, overridingTypes, selectionItemOfType,
  type ReferenceType,
} from "./markdown-references";
import { parse, parseInline, referenceAttributes } from "./markdown";

/** p.319-320's inline references (§632). */

const STATIC = { colorMode: "static", colorProperty: null, colorRules: null, overrideSelection: false,
  id: null } as const;

describe("p.319's anchor syntax", () => {
  const source = 'Two delays: :objectreference[Alert A00150]{objectType="flight_alert" '
    + 'primaryKey="A00150"} and more.';

  it("is an anchor only when the widget asks for references", () => {
    const on = parseInline(source, true);
    expect(on).toEqual([
      { kind: "text", text: "Two delays: " },
      { kind: "objectref", objectType: "flight_alert", primaryKey: "A00150",
        children: [{ kind: "text", text: "Alert A00150" }] },
      { kind: "text", text: " and more." },
    ]);
    // Standard Markdown, and every other caller, keeps the characters.
    expect(parseInline(source)).toEqual([{ kind: "text", text: source }]);
  });

  it("formats the anchor text, and reaches every block kind", () => {
    const [bold] = parseInline(':objectreference[**A1**]{objectType="t" primaryKey="A1"}', true);
    expect(bold).toMatchObject({ kind: "objectref", children: [{ kind: "strong" }] });
    const blocks = parse([
      '# :objectreference[H]{objectType="t" primaryKey="1"}',
      '- :objectreference[L]{objectType="t" primaryKey="2"}',
      '| :objectreference[T]{objectType="t" primaryKey="5"} |', "|---|",
      '| :objectreference[C]{objectType="t" primaryKey="3"} |',
      "",
      'x **:objectreference[B]{objectType="t" primaryKey="4"}**',
    ].join("\n"), { references: true });
    // A table's header as well as its rows.
    expect(JSON.stringify(blocks).match(/"objectref"/g)).toHaveLength(5);
  });

  it("needs both attributes, in either order and any spacing", () => {
    expect(referenceAttributes('primaryKey="7"  objectType = "ship"'))
      .toEqual({ objectType: "ship", primaryKey: "7" });
    expect(referenceAttributes('objectType="ship"')).toBeNull();
    expect(referenceAttributes('primaryKey="7"')).toBeNull();
    expect(referenceAttributes('objectType=" " primaryKey="7"')).toBeNull();
    expect(referenceAttributes('objectType="ship" primaryKey=""')).toBeNull();
    // An anchor naming no object is its own source text.
    const broken = ':objectreference[X]{objectType="ship"}';
    expect(parseInline(broken, true)).toEqual([{ kind: "text", text: broken }]);
  });
});

describe("p.320's configuration", () => {
  it("keeps each named type once, with a colour only when it is one", () => {
    expect(referenceTypesOf([
      { objectType: " ship ", color: "#ff0000" },
      { objectType: "ship", color: "#00ff00" },
      { objectType: "port", color: "red" },
      { objectType: "" }, null, 3,
    ])).toEqual([
      { objectType: "ship", color: "#ff0000", ...STATIC },
      { objectType: "port", color: null, ...STATIC },
    ]);
    expect(referenceTypesOf("ship")).toEqual([]);
  });

  it("highlights the last selected anchor by default", () => {
    expect(selectionBehaviorOf(undefined)).toBe("last");
    expect(selectionBehaviorOf("none")).toBe("none");
    expect(selectionBehaviorOf("selected")).toBe("selected");
  });

  it("lights an anchor by each behaviour's own rule", () => {
    const a = { index: 0, primaryKey: "A1" };
    const b = { index: 1, primaryKey: "A1" };
    expect(isLit("none", a, 0, ["A1"])).toBe(false);
    // The anchor clicked, not every anchor naming the same object.
    expect(isLit("last", a, 0, [])).toBe(true);
    expect(isLit("last", b, 0, ["A1"])).toBe(false);
    expect(isLit("last", a, null, ["A1"])).toBe(false);
    // Whatever the set holds, clicked here or not.
    expect(isLit("selected", b, null, ["A1"])).toBe(true);
    expect(isLit("selected", a, 0, ["B2"])).toBe(false);
  });
});

describe("numberReferences", () => {
  it("numbers every anchor in reading order, nested and quoted ones included", () => {
    const ref = (k: string) => `:objectreference[${k}]{objectType="t" primaryKey="${k}"}`;
    const blocks = parse([
      `# ${ref("a")}`, "", `**${ref("b")}** ${ref("b")}`, "", `> ${ref("c")}`,
      `- ${ref("d")}`, "", "| h |", "|---|", `| ${ref("e")} |`,
    ].join("\n"), { references: true });
    expect(numberReferences(blocks)).toBe(6);
    const found: [number | undefined, string][] = [];
    JSON.stringify(blocks, (key, value) => {
      if (value && value.kind === "objectref") found.push([value.index, value.primaryKey]);
      return value;
    });
    expect(found).toEqual([[0, "a"], [1, "b"], [2, "b"], [3, "c"], [4, "d"], [5, "e"]]);
  });
});

describe("p.320's Highlight color from the object (§664)", () => {
  const red = { kind: "standard" as const, property: "severity", comparison: "string" as const,
    operator: "is_exactly" as const, value: "high", colour: "#ffffff", background: "#dc2626" };
  const amber = { kind: "standard" as const, property: "severity", comparison: "string" as const,
    operator: "is_exactly" as const, value: "low", colour: "#b45309" };

  it("reads a type's colour mode, its property and its rules", () => {
    expect(referenceTypesOf([
      { objectType: "alert", color: "#123456", colorMode: "property", colorProperty: " severity " },
      { objectType: "ship", colorMode: "rules", colorRules: [red] },
      { objectType: "port", colorMode: "sparkly", colorProperty: "", colorRules: [{ kind: "junk" }] },
    ])).toEqual([
      { objectType: "alert", color: "#123456", colorMode: "property", colorProperty: "severity", colorRules: null,
        overrideSelection: false, id: null },
      { objectType: "ship", color: null, colorMode: "rules", colorProperty: null, colorRules: [red],
        overrideSelection: false, id: null },
      { objectType: "port", color: null, ...STATIC },
    ]);
  });

  it("names each object to read once, for the types coloured by their objects alone", () => {
    const blocks = parse([
      ':objectreference[A]{objectType="alert" primaryKey="1"} :objectreference[B]{objectType="alert" primaryKey="2"}',
      '- :objectreference[A again]{objectType="alert" primaryKey="1"}',
      '| :objectreference[S]{objectType="ship" primaryKey="9"} |', "|---|",
      '| :objectreference[P]{objectType="port" primaryKey="3"} |',
    ].join("\n"), { references: true });
    const types = referenceTypesOf([
      { objectType: "alert", colorMode: "property", colorProperty: "severity" },
      { objectType: "ship", colorMode: "rules", colorRules: [red] }, { objectType: "port" },
    ]);
    expect([...keysToColor(blocks, types)]).toEqual([["alert", ["1", "2"]], ["ship", ["9"]]]);
  });

  it("paints with the fill before the text, and falls back to the static colour", () => {
    const byProperty: ReferenceType = { objectType: "alert", color: "#123456", colorMode: "property",
      colorProperty: "severity", colorRules: null, overrideSelection: false, id: null };
    expect(referenceColorOf(byProperty, { severity: "high" }, [red, amber])).toBe("#dc2626");
    expect(referenceColorOf(byProperty, { severity: "low" }, [red, amber])).toBe("#b45309");
    expect(referenceColorOf(byProperty, { severity: "none" }, [red, amber])).toBe("#123456");
    expect(referenceColorOf(byProperty, undefined, [red])).toBe("#123456");
    expect(referenceColorOf(byProperty, { severity: "high" }, null)).toBe("#123456");
    const byRules = { ...byProperty, colorMode: "rules" as const, colorRules: [amber] };
    expect(referenceColorOf(byRules, { severity: "low" }, [red])).toBe("#b45309");
    // Switched back to static, a type keeps its rules, and they paint nothing.
    expect(referenceColorOf({ ...byRules, colorMode: "static" }, { severity: "low" }, [red])).toBe("#123456");
  });
});

describe("p.320's Override event on selection (§665)", () => {
  it("names a type by an id no type has, and fires as it only when it overrides", () => {
    const types = referenceTypesOf([
      { objectType: "ship", id: "rt_2", overrideSelection: true },
      { objectType: "port", id: "rt_1", overrideSelection: false },
      { objectType: "dock", overrideSelection: true },
      { objectType: "pier", id: "nope", overrideSelection: true },
      { objectType: "quay", id: "rt_5", overrideSelection: "yes" },
    ]);
    expect(types.map((t) => [t.id, t.overrideSelection])).toEqual([
      ["rt_2", true], ["rt_1", false], [null, true], [null, true], ["rt_5", false]]);
    expect(types.map(selectionItemOfType)).toEqual(["rt_2", null, null, null, null]);
    expect(overridingTypes(types)).toEqual([{ id: "rt_2", label: "ship" }]);
    expect(newReferenceTypeId(types)).toBe("rt_6");
    expect(newReferenceTypeId(types.slice(0, 1))).toBe("rt_3");
    expect(newReferenceTypeId([])).toBe("rt_1");
  });
});
