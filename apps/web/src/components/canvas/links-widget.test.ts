import { describe, expect, it } from "vitest";

import {
  LINK_MODES, MAX_DEFAULT_EXPAND,
  chosenOf, defaultExpandOf, initiallyExpanded, labelFor, linkKey, modeOf,
  toggleExpanded, visibleLinks,
} from "./links-widget";

/** p.268-272's Links widget. */

function group(over: Partial<Parameters<typeof linkKey>[0]> & {
  side_name?: string; total?: number;
} = {}) {
  return {
    link_type_id: "lt_manages", direction: "outbound",
    side_name: "Reports", total: 3, ...over,
  };
}

/** A self-link — Person manages Person — as the server returns it: **twice**,
 * once per end, same `link_type_id`. */
const MANAGES_DOWN = group({ direction: "outbound", side_name: "Reports" });
const MANAGES_UP = group({ direction: "inbound", side_name: "Manager", total: 1 });
const EMPLOYER = group({
  link_type_id: "lt_employer", direction: "outbound",
  side_name: "Employer", total: 1,
});
const GROUPS = [MANAGES_DOWN, MANAGES_UP, EMPLOYER];

describe("what identifies a link row", () => {
  it("is the type and the end, not the type", () => {
    // **The two directions of a self-link share a `link_type_id`.** Keying on
    // the id would make configuring "my reports" silently configure "my
    // manager" too, and nothing on screen would look wrong.
    expect(linkKey(MANAGES_DOWN)).not.toBe(linkKey(MANAGES_UP));
    expect(linkKey(MANAGES_DOWN)).toBe("lt_manages:outbound");
    expect(linkKey(MANAGES_UP)).toBe("lt_manages:inbound");
  });

  it("distinguishes two different types on the same end", () => {
    expect(linkKey(MANAGES_DOWN)).not.toBe(linkKey(EMPLOYER));
  });
});

describe("p.270's link types to display", () => {
  it("offers the two modes p.270 names and defaults to all", () => {
    expect(Object.keys(LINK_MODES).sort()).toEqual(["all", "specify"]);
    expect(modeOf(undefined)).toBe("all");
    expect(modeOf("specify")).toBe("specify");
  });

  it("falls back to all for anything else a document can hold", () => {
    expect(modeOf("Specify")).toBe("all");
    expect(modeOf(true)).toBe("all");
    expect(modeOf("constructor")).toBe("all");
  });
});

describe("reading a saved selection", () => {
  it("keeps the keys and the overrides", () => {
    expect(chosenOf([{ key: "a", label: "Direct reports" }, { key: "b" }]))
      .toEqual([{ key: "a", label: "Direct reports" }, { key: "b" }]);
  });

  it("is empty when the prop is not a list", () => {
    expect(chosenOf(undefined)).toEqual([]);
    expect(chosenOf("a,b")).toEqual([]);
    expect(chosenOf({ key: "a" })).toEqual([]);
  });

  it("drops entries that cannot name a link", () => {
    // The raw JSON editor can put anything in an array prop. An entry with no
    // key would render a row that nothing on the server can fill.
    expect(chosenOf([null, "a", 7, { label: "no key" }, { key: "" }, { key: "b" }]))
      .toEqual([{ key: "b" }]);
  });

  it("drops a blank override rather than labelling a row with nothing", () => {
    // p.272's override is optional; an empty string in the document must fall
    // through to the side's own name, not blank the row out.
    expect(chosenOf([{ key: "a", label: "   " }, { key: "b", label: 7 }]))
      .toEqual([{ key: "a" }, { key: "b" }]);
  });
});

describe("p.270's which rows are drawn", () => {
  it("shows every link the server returned, in its order, by default", () => {
    expect(visibleLinks(GROUPS, undefined, []).map(linkKey))
      .toEqual(["lt_manages:outbound", "lt_manages:inbound", "lt_employer:outbound"]);
  });

  it("ignores a selection while the mode is all", () => {
    // A widget switched back to "All link types" must not keep filtering by a
    // selection the author can no longer see.
    expect(visibleLinks(GROUPS, "all", [{ key: "lt_employer:outbound" }]).length).toBe(3);
  });

  it("shows only the chosen links, in the order they were chosen", () => {
    expect(visibleLinks(GROUPS, "specify", [
      { key: "lt_employer:outbound" }, { key: "lt_manages:inbound" },
    ]).map(linkKey)).toEqual(["lt_employer:outbound", "lt_manages:inbound"]);
  });

  it("chooses one end of a self-link without the other", () => {
    // **The case the whole keying exists for.** Both rows carry
    // `lt_manages`; only the outbound one was asked for.
    expect(visibleLinks(GROUPS, "specify", [{ key: "lt_manages:outbound" }]))
      .toEqual([MANAGES_DOWN]);
  });

  it("drops a chosen link the object type no longer has", () => {
    // A link type can be deleted long after a widget was pointed at it.
    expect(visibleLinks(GROUPS, "specify", [
      { key: "lt_gone:outbound" }, { key: "lt_employer:outbound" },
    ])).toEqual([EMPLOYER]);
  });

  it("shows nothing when specify is on and nothing is chosen", () => {
    // Not "everything": an author who switched to specify and has not picked
    // yet should see the empty widget that tells them so.
    expect(visibleLinks(GROUPS, "specify", [])).toEqual([]);
  });

  it("returns a list the caller may keep", () => {
    const groups = [...GROUPS];
    const shown = visibleLinks(groups, "all", []);
    shown.reverse();
    expect(groups.map(linkKey)).toEqual([
      "lt_manages:outbound", "lt_manages:inbound", "lt_employer:outbound",
    ]);
  });
});

describe("p.272's link type label override", () => {
  it("falls back to the side's own name", () => {
    // **`side_name`, not the link type's display name.** The server has
    // already resolved which end is being traversed to; a link called
    // "manages" reads backwards on the inbound side.
    expect(labelFor(MANAGES_UP, [])).toBe("Manager");
    expect(labelFor(MANAGES_DOWN, [])).toBe("Reports");
  });

  it("uses the override configured for that end", () => {
    const chosen = [{ key: "lt_manages:inbound", label: "Reports to" }];
    expect(labelFor(MANAGES_UP, chosen)).toBe("Reports to");
    // And the *other* end of the same type keeps its own name.
    expect(labelFor(MANAGES_DOWN, chosen)).toBe("Reports");
  });

  it("keeps the side name when the override belongs to another link", () => {
    expect(labelFor(EMPLOYER, [{ key: "lt_manages:outbound", label: "Team" }]))
      .toBe("Employer");
  });
});

describe("p.271's default link expand", () => {
  it("reads a number and defaults to none open", () => {
    expect(defaultExpandOf(2)).toBe(2);
    expect(defaultExpandOf("3")).toBe(3);
    expect(defaultExpandOf(undefined)).toBe(0);
    expect(defaultExpandOf("abc")).toBe(0);
  });

  it("clamps what a document can name", () => {
    // The cap is asserted as a literal as well as by name: `toBe(MAX)` alone
    // derives the expectation from its own subject and would follow the
    // constant anywhere it moved (§201).
    expect(MAX_DEFAULT_EXPAND).toBe(20);
    expect(defaultExpandOf(-1)).toBe(0);
    expect(defaultExpandOf(999)).toBe(MAX_DEFAULT_EXPAND);
    expect(defaultExpandOf(21)).toBe(20);
    expect(defaultExpandOf(2.7)).toBe(2);
  });

  it("opens the first n of what is shown, not of what the server returned", () => {
    // **The distinction the harness would otherwise not see**: with `specify`
    // hiding the first server row, expanding "the first one" must open the
    // first *visible* row. Expanding a hidden row opens nothing at all.
    const visible = visibleLinks(GROUPS, "specify", [
      { key: "lt_employer:outbound" }, { key: "lt_manages:outbound" },
    ]);
    expect(initiallyExpanded(visible, 1)).toEqual(["lt_employer:outbound"]);
    expect(initiallyExpanded(GROUPS, 1)).toEqual(["lt_manages:outbound"]);
  });

  it("opens none and opens more than there are", () => {
    expect(initiallyExpanded(GROUPS, 0)).toEqual([]);
    expect(initiallyExpanded(GROUPS, 99).length).toBe(3);
  });
});

describe("opening and closing a row", () => {
  it("opens one that was closed and closes one that was open", () => {
    expect(toggleExpanded(["a"], "b")).toEqual(["a", "b"]);
    expect(toggleExpanded(["a", "b"], "a")).toEqual(["b"]);
  });

  it("leaves the rest in the order they were opened", () => {
    // Order is stable so React does not remount the sections that stayed open.
    expect(toggleExpanded(["a", "b", "c"], "b")).toEqual(["a", "c"]);
  });

  it("does not mutate the list it was given", () => {
    const open = ["a"];
    toggleExpanded(open, "b");
    toggleExpanded(open, "a");
    expect(open).toEqual(["a"]);
  });
});
