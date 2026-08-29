import { describe, expect, it } from "vitest";

import {
  PRIMARY_KEY, autoSelectKey, hasSelection, keysOf, selectionClauses, toggle,
} from "./object-table-selection";

/** p.224's Selection block. */

function rows(...keys: string[]) {
  return keys.map((primary_key) => ({ primary_key }));
}

describe("the clauses a selection writes", () => {
  it("addresses the primary key by the name the server uses", () => {
    // **The same string as `PRIMARY_KEY_FILTER` in `services/object_sets.py`.**
    // A clause naming anything else is a filter on a property that happens not
    // to exist, which narrows to nothing and looks exactly like an empty
    // selection — so this would fail as a silent wrong answer rather than as
    // an error.
    expect(PRIMARY_KEY).toBe("$primary_key");
    expect(selectionClauses(["a"])[0]!.property).toBe("$primary_key");
  });

  it("writes one `in` clause whatever the size of the selection", () => {
    // One shape, so a downstream `narrow_set` never sees the clause list
    // change structure as rows are checked and unchecked.
    expect(selectionClauses(["a", "b"])).toEqual([
      { property: PRIMARY_KEY, op: "in", value: ["a", "b"] },
    ]);
    expect(selectionClauses(["a"])).toEqual([
      { property: PRIMARY_KEY, op: "in", value: ["a"] },
    ]);
  });

  it("writes an empty list for an empty selection rather than no clause", () => {
    // **The whole reason the server had to accept `in []`.** No clause means
    // no narrowing, so every downstream widget would receive the entire table
    // the moment a viewer unchecked the last row — decision 0002's failure,
    // arrived at from the other direction.
    expect(selectionClauses([])).toEqual([
      { property: PRIMARY_KEY, op: "in", value: [] },
    ]);
    expect(selectionClauses([])).toHaveLength(1);
  });

  it("copies the keys rather than aliasing them", () => {
    // The clause list goes into a variable and is compared as a value; a live
    // reference would let a later `toggle` mutate what was already written.
    const keys = ["a"];
    const clause = selectionClauses(keys)[0]!;
    keys.push("b");
    expect(clause.value).toEqual(["a"]);
  });
});

describe("reading a selection back", () => {
  it("returns the keys of a clause it wrote", () => {
    expect(keysOf(selectionClauses(["a", "b"]))).toEqual(["a", "b"]);
    expect(keysOf(selectionClauses([]))).toEqual([]);
  });

  it("is empty for anything that is not a clause list", () => {
    // A variable holds whatever an effect or a saved state put in it.
    expect(keysOf(undefined)).toEqual([]);
    expect(keysOf(null)).toEqual([]);
    expect(keysOf("a")).toEqual([]);
    expect(keysOf([null, 7, "x"])).toEqual([]);
    expect(keysOf([{}])).toEqual([]);
  });

  it("ignores a clause about something other than the key", () => {
    // A `narrow_set` variable can carry a Filter List's clauses too, and
    // reading a region filter as a list of selected keys would tick rows
    // nobody chose.
    expect(keysOf([{ property: "region", op: "in", value: ["north"] }])).toEqual([]);
    expect(keysOf([
      { property: "region", op: "in", value: ["north"] },
      { property: PRIMARY_KEY, op: "in", value: ["a"] },
    ])).toEqual(["a"]);
  });

  it("ignores a key clause using a different operator", () => {
    // `eq` on the key is a legal set — a traversal writes one — and it is not
    // a selection this widget made.
    expect(keysOf([{ property: PRIMARY_KEY, op: "eq", value: "a" }])).toEqual([]);
    // **With a list value, so the operator check is what refuses it.** The
    // line above is refused by the *shape* check below it either way, so on
    // its own it says nothing about the operator — the harness caught exactly
    // that, and it is §202's shape: a guard tested only by its neighbour. A
    // variable can hold this: an `array` variable takes whatever a
    // `set_variable` effect puts there, and the refusal happens later, at the
    // server, long after these checkboxes have been drawn.
    expect(keysOf([{ property: PRIMARY_KEY, op: "eq", value: ["a"] }])).toEqual([]);
    expect(keysOf([{ property: PRIMARY_KEY, op: "starts_with", value: ["a"] }])).toEqual([]);
  });

  it("ignores a key clause whose value is not a list", () => {
    // The other half of the pair above, and the one that would *throw* rather
    // than answer wrongly: `"S1".map` is a TypeError, and a widget that throws
    // during render takes the module with it.
    expect(keysOf([{ property: PRIMARY_KEY, op: "in", value: "S1" }])).toEqual([]);
    expect(keysOf([{ property: PRIMARY_KEY, op: "in", value: 7 }])).toEqual([]);
    expect(keysOf([{ property: PRIMARY_KEY, op: "in" }])).toEqual([]);
  });

  it("reads keys as strings, because a primary key can look numeric", () => {
    // The server compares on the *text* of a value (`object_sets._text`), and
    // a row whose key is `7` would otherwise never match the number 7 held in
    // a variable that has been through JSON.
    expect(keysOf([{ property: PRIMARY_KEY, op: "in", value: [7, "8"] }])).toEqual(["7", "8"]);
  });
});

describe("stated versus unstated", () => {
  /** **The distinction the server forces, and the one `keysOf` cannot make.**
   *
   * An empty *clause list* means no narrowing — `narrow_set` returns the base
   * set unchanged, which is right for a Filter List nobody has touched. A
   * clause list holding `in []` means the empty set. Both read as "no keys",
   * and handing the first one downstream gives every consumer the whole table.
   */
  it("is false for a variable nothing has written", () => {
    expect(hasSelection(undefined)).toBe(false);
    expect(hasSelection(null)).toBe(false);
    expect(hasSelection([])).toBe(false);
  });

  it("is true for an explicitly empty selection", () => {
    expect(hasSelection(selectionClauses([]))).toBe(true);
    // Which `keysOf` reads identically to the unstated case above — so the two
    // functions answer different questions and both are needed.
    expect(keysOf(selectionClauses([]))).toEqual(keysOf([]));
  });

  it("is true once keys are selected", () => {
    expect(hasSelection(selectionClauses(["a"]))).toBe(true);
  });

  it("ignores clauses about anything else", () => {
    expect(hasSelection([{ property: "region", op: "in", value: [] }])).toBe(false);
    expect(hasSelection([{ property: PRIMARY_KEY, op: "eq", value: "a" }])).toBe(false);
    expect(hasSelection([{ property: PRIMARY_KEY, op: "in", value: "a" }])).toBe(false);
  });
});

describe("toggling", () => {
  it("adds a key that is not there and removes one that is", () => {
    expect(toggle([], "a")).toEqual(["a"]);
    expect(toggle(["a"], "a")).toEqual([]);
    expect(toggle(["a", "b"], "b")).toEqual(["a"]);
  });

  it("keeps the order stable, so an unchanged set compares unchanged", () => {
    // The clause list is written into a variable and compared as a value.
    // Reordering on every click would re-resolve everything downstream for a
    // selection that did not actually change.
    expect(toggle(["a", "b", "c"], "d")).toEqual(["a", "b", "c", "d"]);
    expect(toggle(["a", "b", "c"], "b")).toEqual(["a", "c"]);
  });

  it("does not mutate what it was given", () => {
    const keys = ["a"];
    toggle(keys, "b");
    expect(keys).toEqual(["a"]);
  });
});

describe("p.224's auto-selection", () => {
  it("picks the first row at load", () => {
    expect(autoSelectKey({
      rows: rows("a", "b"), current: [], enabled: true, visible: true,
    })).toBe("a");
  });

  it("picks nothing when it is disabled", () => {
    // p.224: "results in an empty active object at load time".
    expect(autoSelectKey({
      rows: rows("a", "b"), current: [], enabled: false, visible: true,
    })).toBeNull();
  });

  it("picks nothing while the widget is not visible", () => {
    // p.224: "auto-selection only triggers when the widget is visible; if the
    // Object Table is within a collapsed section, auto-selection will not
    // occur until the section is expanded".
    //
    // **Not free, and that is why it is a parameter.** A collapsed section
    // keeps its children mounted — deliberately, so a table inside one does
    // not refetch every time somebody folds it away — so the table is running
    // and would otherwise select a row for a viewer who cannot see it, and
    // open the drawer p.224 describes on a row nobody chose.
    expect(autoSelectKey({
      rows: rows("a", "b"), current: [], enabled: true, visible: false,
    })).toBeNull();
  });

  it("never overwrites a choice somebody already made", () => {
    // Rows arrive again constantly: a refetch, a page turn, a filter
    // narrowing. Each one would otherwise drag the active object back to the
    // first row under a viewer who picked the fourth.
    expect(autoSelectKey({
      rows: rows("a", "b"), current: ["b"], enabled: true, visible: true,
    })).toBeNull();
  });

  it("picks nothing when there are no rows to pick", () => {
    expect(autoSelectKey({
      rows: [], current: [], enabled: true, visible: true,
    })).toBeNull();
    expect(autoSelectKey({
      rows: undefined, current: [], enabled: true, visible: true,
    })).toBeNull();
  });

  it("picks the first row of the page it is actually showing", () => {
    // Not a remembered first row: after paging, "the first row" is the first
    // of what is on screen.
    expect(autoSelectKey({
      rows: rows("c", "d"), current: [], enabled: true, visible: true,
    })).toBe("c");
  });
});
