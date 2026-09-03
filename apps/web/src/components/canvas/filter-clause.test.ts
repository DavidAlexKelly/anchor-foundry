import { describe, expect, it } from "vitest";

import {
  DEFAULT_MODE, GEO_OPERATORS, MODES, ORDERED_OPERATORS, UNIVERSAL_OPERATORS,
  canAdd, canEdit, canRemove, clauseOf, clausesOf, describe as describeClause,
  editableValue, isEditable, isRemovable, modeOf, operatorsFor, parseValue,
  sameClause, valueLabel, withValue, without,
} from "./filter-clause";

/** p.470's Exploration Filter Pills, and the browser's single copy of
 * `object_sets`' filter vocabulary. */

const DECLARED = [
  { api_name: "region", display_name: "Region", data_type: "string" },
  { api_name: "capacity", display_name: "Capacity", data_type: "integer" },
  { api_name: "opened", display_name: null, data_type: "date" },
  { api_name: "site", display_name: "Site", data_type: "geopoint" },
];

describe("the operators this language has", () => {
  it("mirrors the server's two lists", () => {
    // `object_sets.OPERATORS` and `ORDERED_OPERATORS`. An API test compares
    // these against the server's own, because a comment saying "mirrors" is
    // what all seven stale copies of this constraint also said (§231, §233).
    expect([...UNIVERSAL_OPERATORS].sort()).toEqual(["eq", "in", "neq", "starts_with"]);
    expect([...ORDERED_OPERATORS].sort()).toEqual(["gt", "gte", "lt", "lte"]);
  });

  it("offers the ordered four only on a type both stores order", () => {
    // §221 built these and §231 put the type list in one place. A property
    // whose declared type has no agreed order still gets the refusal.
    expect(operatorsFor("integer")).toContain("gte");
    expect(operatorsFor("date")).toContain("lt");
    expect(operatorsFor("string")).not.toContain("gt");
    expect(operatorsFor("geopoint")).not.toContain("gt");
    expect(operatorsFor("boolean")).not.toContain("gt");
  });

  it("gives an unresolved type the universal four rather than everything", () => {
    // **Narrower than the server, never wider.** The ordered four are exactly
    // what `object_sets` refuses without a declared type, so offering them on a
    // property the browser has not resolved produces a refusal in place of a
    // filter — and the browser cannot tell "not loaded" from "not orderable"
    // by looking at the operator list.
    expect(operatorsFor(undefined)).toEqual([...UNIVERSAL_OPERATORS]);
    expect(operatorsFor(null)).toEqual([...UNIVERSAL_OPERATORS]);
    expect(operatorsFor("")).toEqual([...UNIVERSAL_OPERATORS]);
  });

  it("never offers a bounding box to type into", () => {
    // A box is four numbers meaning a rectangle somebody drew (§230). A picker
    // offering "is inside the area" with nowhere to draw is a control that
    // looks like it works.
    for (const type of ["string", "integer", "geopoint", "date"]) {
      expect(operatorsFor(type)).not.toContain("within_box");
    }
    expect(GEO_OPERATORS).toContain("within_box");
  });
});

describe("p.470's four modes", () => {
  it("has all four, in p.470's order", () => {
    expect(Object.keys(MODES)).toEqual(["read_only", "remove", "update", "add"]);
  });

  it("falls back to the least powerful, not the most", () => {
    // A document naming a mode this build has not got should lose the ability
    // to edit rather than gain it — §214's rule pointed at the safe end.
    expect(DEFAULT_MODE).toBe("read_only");
    expect(modeOf("delete_everything")).toBe("read_only");
    expect(modeOf(undefined)).toBe("read_only");
    expect(modeOf(7)).toBe("read_only");
    expect(modeOf("constructor")).toBe("read_only");
  });

  it("escalates: each mode can do what the one before it could", () => {
    expect([canRemove("read_only"), canEdit("read_only"), canAdd("read_only")])
      .toEqual([false, false, false]);
    expect([canRemove("remove"), canEdit("remove"), canAdd("remove")])
      .toEqual([true, false, false]);
    expect([canRemove("update"), canEdit("update"), canAdd("update")])
      .toEqual([true, true, false]);
    expect([canRemove("add"), canEdit("add"), canAdd("add")])
      .toEqual([true, true, true]);
  });
});

describe("reading a clause out of a resolved set", () => {
  it("reads the three parts", () => {
    expect(clauseOf({ property: "region", op: "eq", value: "north" }))
      .toEqual({ property: "region", op: "eq", value: "north" });
  });

  it("defaults a missing operator to eq, which is what the server does", () => {
    expect(clauseOf({ property: "region", value: "north" })?.op).toBe("eq");
  });

  it("names nothing for a shape this language cannot express", () => {
    // A definition can hold what an older build or a hand-edit wrote. A pill
    // reading `[object Object]` beside a remove button is worse than absent.
    expect(clauseOf({ op: "eq", value: "north" })).toBeNull();
    expect(clauseOf({ property: "region", op: "matches", value: "n" })).toBeNull();
    expect(clauseOf(null)).toBeNull();
    expect(clauseOf("region=north")).toBeNull();
    // Not read off the prototype chain.
    expect(clauseOf({ property: "region", op: "toString" })).toBeNull();
  });

  it("keeps the ones it can read and drops the rest", () => {
    expect(clausesOf([
      { property: "region", op: "eq", value: "north" },
      { property: "region", op: "matches", value: "n" },
      { property: "capacity", op: "gte", value: 10 },
    ]).map((c) => c.op)).toEqual(["eq", "gte"]);
    expect(clausesOf(undefined)).toEqual([]);
    expect(clausesOf({ property: "region" })).toEqual([]);
  });
});

describe("what a pill says", () => {
  it("uses the ontology's display name and the operator's words", () => {
    expect(describeClause(
      { property: "capacity", op: "gte", value: 10 }, DECLARED,
    )).toBe("Capacity is at least 10");
  });

  it("falls back to the api name when the ontology has no display name", () => {
    // A pill with no subject cannot be acted on.
    expect(describeClause({ property: "opened", op: "eq", value: "2026-01-01" }, DECLARED))
      .toBe("opened is 2026-01-01");
    expect(describeClause({ property: "unknown", op: "eq", value: "x" }, DECLARED))
      .toBe("unknown is x");
  });

  it("joins a list rather than showing it as one", () => {
    expect(valueLabel({ property: "region", op: "in", value: ["north", "south"] }))
      .toBe("north, south");
  });

  it("names a bounding box's edges rather than showing an object", () => {
    // The one clause shape a viewer is least able to guess at, and the one that
    // renders as `[object Object]` if nothing handles it.
    expect(valueLabel({
      property: "site", op: "within_box",
      value: { north: 60, south: 50, east: 10, west: -5 },
    })).toBe("N 60, S 50, E 10, W -5");
  });

  it("says something for an object it does not recognise", () => {
    expect(valueLabel({ property: "x", op: "eq", value: { odd: true } })).toBe("…");
  });

  it("shows an operator with no value as just its subject and words", () => {
    expect(describeClause({ property: "region", op: "eq", value: null }, DECLARED))
      .toBe("Region is");
  });
});

describe("which pills the widget can actually remove", () => {
  const WRITTEN = [
    { property: "region", op: "eq", value: "north" },
    { property: "capacity", op: "gte", value: 10 },
  ];

  it("removes one the variable holds", () => {
    expect(isRemovable({ property: "region", op: "eq", value: "north" }, WRITTEN))
      .toBe(true);
  });

  it("refuses one that is part of what the set is", () => {
    // **The rule no other widget needs.** Pills come from the *resolved* set:
    // the base definition's own filters plus whatever `narrow_set` added. Only
    // the second kind is in the variable this widget writes; the first is
    // structural, and a remove button on it would write a list that changes
    // nothing while the pill sat there.
    expect(isRemovable({ property: "band", op: "eq", value: "new" }, WRITTEN))
      .toBe(false);
  });

  it("matches by shape, because the two lists are different objects", () => {
    // One came from a variable, the other came back from the server through
    // `narrow_set`, so identity would say no to every pill.
    expect(isRemovable({ property: "capacity", op: "gte", value: 10 }, [
      { property: "capacity", op: "gte", value: 10 },
    ])).toBe(true);
    expect(isRemovable({ property: "capacity", op: "gt", value: 10 }, WRITTEN))
      .toBe(false);
    expect(isRemovable({ property: "capacity", op: "gte", value: 11 }, WRITTEN))
      .toBe(false);
  });

  it("compares a list value by its contents and its order", () => {
    const listed = [{ property: "region", op: "in", value: ["north", "south"] }];
    expect(isRemovable({ property: "region", op: "in", value: ["north", "south"] }, listed))
      .toBe(true);
    expect(isRemovable({ property: "region", op: "in", value: ["south", "north"] }, listed))
      .toBe(false);
  });

  it("treats an absent value and a null one as the same clause", () => {
    // `narrow_set` round-trips through JSON, where an absent key and an
    // explicit null are the same fact by the time they come back.
    expect(sameClause(
      { property: "r", op: "eq", value: null },
      { property: "r", op: "eq", value: undefined },
    )).toBe(true);
  });
});

describe("removing and editing one clause", () => {
  const WRITTEN = [
    { property: "region", op: "eq", value: "north" },
    { property: "region", op: "eq", value: "north" },
    { property: "capacity", op: "gte", value: 10 },
  ];

  it("removes one match, not every equal clause", () => {
    // A variable can hold the same clause twice — two widgets, one variable —
    // and a viewer clicking one pill of two identical ones has asked to remove
    // one of them.
    expect(without(WRITTEN, { property: "region", op: "eq", value: "north" }))
      .toEqual([
        { property: "region", op: "eq", value: "north" },
        { property: "capacity", op: "gte", value: 10 },
      ]);
  });

  it("leaves the list alone when nothing matches", () => {
    expect(without(WRITTEN, { property: "band", op: "eq", value: "new" }))
      .toEqual(WRITTEN);
  });

  it("replaces one value and keeps the rest", () => {
    expect(withValue(WRITTEN, { property: "capacity", op: "gte", value: 10 }, "25"))
      .toEqual([
        { property: "region", op: "eq", value: "north" },
        { property: "region", op: "eq", value: "north" },
        { property: "capacity", op: "gte", value: "25" },
      ]);
  });

  it("replaces one of two identical clauses, not both", () => {
    const edited = withValue(WRITTEN, { property: "region", op: "eq", value: "north" }, "south");
    expect(edited.map((c) => c.value)).toEqual(["south", "north", 10]);
  });
});

describe("what a viewer typed", () => {
  it("makes a list for in and a scalar for everything else", () => {
    // An `in` whose value arrived as a bare string is refused by
    // `object_sets.parse` with a sentence about list operators.
    expect(parseValue("in", "north, south")).toEqual(["north", "south"]);
    expect(parseValue("eq", "north, south")).toBe("north, south");
    expect(parseValue("starts_with", "no")).toBe("no");
  });

  it("drops the blank a trailing comma leaves", () => {
    expect(parseValue("in", "north, south,")).toEqual(["north", "south"]);
    expect(parseValue("in", " , ")).toEqual([]);
  });

  it("does not guess that a number is a number", () => {
    // The server reads the declared type and the stores compare against it
    // (§220). Guessing here would mean a browser deciding "007" is 7 for a
    // property the ontology calls a string.
    expect(parseValue("gte", "10")).toBe("10");
    expect(parseValue("eq", "007")).toBe("007");
  });

  it("round-trips through the box a viewer edits it in", () => {
    expect(editableValue({ property: "r", op: "in", value: ["a", "b"] })).toBe("a, b");
    expect(parseValue("in", editableValue({ property: "r", op: "in", value: ["a", "b"] })))
      .toEqual(["a", "b"]);
    expect(editableValue({ property: "r", op: "eq", value: 10 })).toBe("10");
    expect(editableValue({ property: "r", op: "eq", value: null })).toBe("");
  });
});

describe("which clauses a text box can edit at all", () => {
  it("edits the ones whose value is a value", () => {
    expect(isEditable({ property: "r", op: "eq", value: "north" })).toBe(true);
    expect(isEditable({ property: "r", op: "in", value: ["a"] })).toBe(true);
  });

  it("refuses a bounding box", () => {
    // Four numbers meaning a rectangle. Offering them in one field is not the
    // interaction; the pill stays, without an editor.
    expect(isEditable({
      property: "site", op: "within_box", value: { north: 1, south: 0, east: 1, west: 0 },
    })).toBe(false);
  });
});
