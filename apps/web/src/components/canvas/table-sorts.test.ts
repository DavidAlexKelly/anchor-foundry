import { describe, expect, it } from "vitest";

import {
  DEFAULT_SORT, FIXED_SORTS, MAX_SORTS,
  blankEntry, entryOf, labelOf, sortsOf, toRequest,
  withDirection, withFixed, withProperty,
} from "./table-sorts";

/** p.223's "one or more default sorts". */

describe("the four sorts that need no declared type", () => {
  it("mirrors the server's fixed list", () => {
    // Not a copy for convenience: `object_sets.SORTS` is the authority, and a
    // browser list that drifted wider would offer an ordering the server
    // refuses with a sentence about property types.
    expect(Object.keys(FIXED_SORTS).sort()).toEqual(["-key", "key", "oldest", "recent"]);
    expect(DEFAULT_SORT).toBe("recent");
  });

  it("reads one as fixed, with its direction already in the key", () => {
    expect(entryOf("recent")).toEqual({
      key: "recent", property: "", descending: false, fixed: true,
    });
    expect(entryOf("-key")).toEqual({
      key: "-key", property: "", descending: true, fixed: true,
    });
  });
});

describe("reading one written sort", () => {
  it("reads a property and its direction", () => {
    expect(entryOf("priority")).toEqual({
      key: "priority", property: "priority", descending: false, fixed: false,
    });
    expect(entryOf("-priority")).toEqual({
      key: "-priority", property: "priority", descending: true, fixed: false,
    });
  });

  it("trims what an author typed", () => {
    expect(entryOf("  priority  ")?.key).toBe("priority");
    expect(entryOf("-  priority  ")?.key).toBe("-priority");
  });

  it("is nothing for a blank or a bare direction", () => {
    // A lone `-` is a direction with nothing to apply it to. Sent, it would
    // come back as a sentence about property types for what is an empty field.
    for (const empty of ["", "   ", "-", "-   ", null, undefined, 7]) {
      expect(entryOf(empty)).toBeNull();
    }
  });
});

describe("the whole setting, from what a document holds", () => {
  it("reads the string a module stored before p.223", () => {
    // decision 0002: a document does not change when you open it.
    expect(sortsOf("recent").map((e) => e.key)).toEqual(["recent"]);
  });

  it("reads a list, keeping the order it was written in", () => {
    // The order *is* the setting - "status then date" and "date then status"
    // are different tables.
    expect(sortsOf(["-priority", "name"]).map((e) => e.key)).toEqual(["-priority", "name"]);
    expect(sortsOf(["name", "-priority"]).map((e) => e.key)).toEqual(["name", "-priority"]);
  });

  it("is nothing for anything that is not a string or a list", () => {
    for (const bad of [null, undefined, 7, { sort: "key" }]) {
      expect(sortsOf(bad)).toEqual([]);
    }
  });

  it("drops a repeat rather than sending a sort that cannot order anything", () => {
    // The server *refuses* a repeat, because it is validating a request the
    // author cannot see. A panel has the rows on screen, so it stops the second
    // one being sent instead.
    expect(sortsOf(["name", "name"]).map((e) => e.key)).toEqual(["name"]);
    // Opposite directions are two different sorts by key, and the second still
    // cannot fire - but it is a different string, so this pins which rule is
    // being applied: identity of the key, not of the property.
    expect(sortsOf(["name", "-name"]).map((e) => e.key)).toEqual(["name", "-name"]);
  });

  it("keeps a blank row in a list, because it is a row somebody is filling in", () => {
    // §203's rule: dropping it would delete the row on the keystroke that
    // emptied it. `toRequest` is what refuses to *send* it.
    const rows = sortsOf(["name", "", "-priority"]);
    expect(rows.map((e) => e.key)).toEqual(["name", "", "-priority"]);
    expect(toRequest(rows)).toEqual(["name", "-priority"]);
  });

  it("keeps several blank rows rather than calling them repeats", () => {
    expect(sortsOf(["", ""])).toHaveLength(2);
  });

  it("reads a blank *string* as no sort at all", () => {
    // A string is one stored ordering, not a row list - so a blank one is
    // absence, where a blank list member is an unfinished row.
    expect(sortsOf("")).toEqual([]);
    expect(sortsOf("   ")).toEqual([]);
  });

  it("stops at the cap the server enforces", () => {
    const many = Array.from({ length: MAX_SORTS + 3 }, (_, n) => `p${n}`);
    expect(sortsOf(many)).toHaveLength(MAX_SORTS);
    expect(sortsOf(many).at(-1)?.key).toBe(`p${MAX_SORTS - 1}`);
  });
});

describe("what gets sent", () => {
  it("sends one sort as the string the API always took", () => {
    expect(toRequest(sortsOf(["recent"]))).toBe("recent");
  });

  it("sends several as a list", () => {
    expect(toRequest(sortsOf(["-priority", "name"]))).toEqual(["-priority", "name"]);
  });

  it("sends nothing at all rather than an empty list", () => {
    // `[]` would be an author asking for an ordering they did not ask for; no
    // key at all lets the server apply its default.
    expect(toRequest([])).toBeUndefined();
    expect(toRequest(sortsOf(""))).toBeUndefined();
  });

  it("leaves out a row nobody has finished", () => {
    expect(toRequest([blankEntry()])).toBeUndefined();
    expect(toRequest([...sortsOf(["name"]), blankEntry()])).toBe("name");
  });
});

describe("editing a row", () => {
  it("changes a property's direction, and its key with it", () => {
    const asc = entryOf("priority")!;
    expect(withDirection(asc, true).key).toBe("-priority");
    expect(withDirection(withDirection(asc, true), false).key).toBe("priority");
  });

  it("leaves a fixed sort's direction alone, because `-key` is the direction", () => {
    // Offering a descending toggle beside "Key, Z–A" would put two answers to
    // one question on the panel.
    const fixed = entryOf("key")!;
    expect(withDirection(fixed, true)).toEqual(fixed);
  });

  it("changes a property, keeping the direction already chosen", () => {
    const desc = entryOf("-priority")!;
    expect(withProperty(desc, "name").key).toBe("-name");
    expect(withProperty(desc, "name").descending).toBe(true);
  });

  it("keeps a row that has been emptied rather than dropping it mid-keystroke", () => {
    // §203's rule: a field that clears itself between `1` and `1.5` is a field
    // nobody can type in.
    const cleared = withProperty(entryOf("priority")!, "  ");
    expect(cleared.key).toBe("");
    expect(cleared.property).toBe("");
    expect(toRequest([cleared])).toBeUndefined();
  });

  it("empties a *descending* row's key too, rather than leaving a bare minus", () => {
    // The case that separates the rule from the shortcut. On an ascending row
    // "clear the key" and "rebuild the key from an empty name" both produce
    // `""`, so an ascending row asserts nothing; a descending one produces `-`,
    // which is truthy, gets sent, and comes back as a refusal about property
    // types for what is an empty field.
    const cleared = withProperty(entryOf("-priority")!, "");
    expect(cleared.key).toBe("");
    expect(toRequest([cleared])).toBeUndefined();
  });

  it("switches a row between a fixed sort and a property", () => {
    const prop = entryOf("-priority")!;
    expect(withFixed(prop, "oldest")).toEqual({
      key: "oldest", property: "", descending: false, fixed: true,
    });
    // And back: choosing "a property" clears the fixed key rather than leaving
    // the old one behind to be sent.
    const back = withFixed(entryOf("oldest")!, "");
    expect(back.fixed).toBe(false);
    expect(back.key).toBe("");
  });
});

describe("what a row is called", () => {
  it("names a fixed sort the way the panel offers it", () => {
    expect(labelOf(entryOf("recent")!)).toBe("Last changed, newest first");
  });

  it("names a property and says which way it runs", () => {
    expect(labelOf(entryOf("priority")!)).toContain("priority");
    expect(labelOf(entryOf("priority")!)).toContain("low to high");
    expect(labelOf(entryOf("-priority")!)).toContain("high to low");
  });

  it("says a row is unfinished rather than naming nothing", () => {
    expect(labelOf(blankEntry())).toBe("No property yet");
  });
});
