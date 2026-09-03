import { describe, expect, it } from "vitest";

import {
  DEFAULT_MODE, SELECTION_MODES,
  allowClearOf, groupIdsOf, isMultiple, labelOf, modeOf, pickedSingle,
  placeholderOf, selectedIds, shouldAsk, summaryOf, textOf, toOutput, toggled,
  usersOf,
} from "./user-select";

/** p.477–478's User Select. The widget is `CanvasUserSelect`; every rule it
 * applies is here, so each can be made to fail on its own. */

const DIRECTORY = [
  { id: "u1", email: "ada@acme.dev", display_name: "Ada Lovelace", status: "active" },
  { id: "u2", email: "grace@acme.dev", display_name: null, status: "active" },
  { id: "u3", email: "gone@acme.dev", display_name: "Gone Away", status: "disabled" },
];

describe("p.477's two selection modes", () => {
  it("has both, and defaults to the one whose output is a single value", () => {
    expect(Object.keys(SELECTION_MODES)).toEqual(["single", "multiple"]);
    expect(DEFAULT_MODE).toBe("single");
    expect(modeOf(undefined)).toBe("single");
    expect(modeOf("many")).toBe("single");
    expect(modeOf(7)).toBe("single");
    // Not read off the prototype chain.
    expect(modeOf("constructor")).toBe("single");
  });

  it("knows which one it is in", () => {
    expect(isMultiple("multiple")).toBe(true);
    expect(isMultiple("single")).toBe(false);
    expect(isMultiple("nonsense")).toBe(false);
  });
});

describe("who the dropdown offers", () => {
  it("keeps the active users in the order the directory gave them", () => {
    // `list_users` orders by display name, which is the order a person scans.
    // Re-sorting here would be a second opinion, and sorting by a name some
    // rows do not have would put those rows somewhere arbitrary.
    expect(usersOf(DIRECTORY).map((u) => u.id)).toEqual(["u1", "u2"]);
  });

  it("drops a disabled user rather than showing one who cannot act", () => {
    expect(usersOf(DIRECTORY).some((u) => u.id === "u3")).toBe(false);
  });

  it("drops a status this build has not heard of", () => {
    // Guessing towards *offering* somebody is the wrong direction: a status
    // whose meaning is unknown is not evidence that the person can act.
    expect(usersOf([{ id: "u9", status: "suspended" }])).toEqual([]);
    expect(usersOf([{ id: "u9", status: "invited" }])).toEqual([]);
  });

  it("keeps a row with no status at all", () => {
    // Absence here is the server not saying, which is different from saying
    // something this build does not recognise.
    expect(usersOf([{ id: "u9" }]).map((u) => u.id)).toEqual(["u9"]);
  });

  it("reads nothing from what is not a list of users", () => {
    expect(usersOf(undefined)).toEqual([]);
    expect(usersOf({ id: "u1" })).toEqual([]);
    expect(usersOf([null, "u1", { email: "no@id" }, { id: 7 }])).toEqual([]);
  });
});

describe("what a user is called", () => {
  it("prefers the display name", () => {
    expect(labelOf(DIRECTORY[0]!)).toBe("Ada Lovelace");
  });

  it("falls back to the email, then to the id", () => {
    // An invited user has no display name until they sign in, and an option
    // with no text is one nobody can pick on purpose.
    expect(labelOf({ id: "u2", email: "grace@acme.dev", display_name: null }))
      .toBe("grace@acme.dev");
    expect(labelOf({ id: "u4" })).toBe("u4");
    expect(labelOf({ id: "u4", display_name: "   ", email: "  " })).toBe("u4");
  });
});

describe("reading the selection back", () => {
  it("reads a string and a list alike", () => {
    expect(selectedIds("u1", "single")).toEqual(["u1"]);
    expect(selectedIds(["u1", "u2"], "multiple")).toEqual(["u1", "u2"]);
  });

  it("reads both shapes whatever the mode says", () => {
    // **The mode is a setting somebody can change on a document that already
    // holds a selection.** A widget that only understood its current mode would
    // show nothing selected and then overwrite it on the next click.
    expect(selectedIds(["u1", "u2"], "single")).toEqual(["u1"]);
    expect(selectedIds("u1", "multiple")).toEqual(["u1"]);
  });

  it("drops blanks, repeats and things that are not ids", () => {
    expect(selectedIds(["u1", "u1", "", "  ", null, 7], "multiple")).toEqual(["u1"]);
    expect(selectedIds(null, "multiple")).toEqual([]);
    expect(selectedIds(undefined, "single")).toEqual([]);
  });
});

describe("what gets written", () => {
  it("writes p.478's two shapes", () => {
    expect(toOutput(["u1"], "single")).toBe("u1");
    expect(toOutput(["u1", "u2"], "multiple")).toEqual(["u1", "u2"]);
  });

  it("writes an empty string rather than null for a cleared single", () => {
    // A string variable holds a string, and `null` is what an *unbound*
    // variable reads as — writing it would make "cleared" and "never set" the
    // same fact for everything downstream.
    expect(toOutput([], "single")).toBe("");
    expect(toOutput([], "multiple")).toEqual([]);
  });

  it("writes only the first when the mode is single", () => {
    expect(toOutput(["u1", "u2"], "single")).toBe("u1");
  });

  it("round-trips through the variable in both modes", () => {
    for (const mode of ["single", "multiple"]) {
      const written = toOutput(["u1"], mode);
      expect(selectedIds(written, mode)).toEqual(["u1"]);
    }
  });
});

describe("picking", () => {
  it("replaces in single mode rather than toggling", () => {
    // p.478 gives clearing its own control, so a click that sometimes selected
    // and sometimes cleared would be two behaviours on one gesture.
    expect(pickedSingle("u1")).toEqual(["u1"]);
    expect(pickedSingle("")).toEqual([]);
  });

  it("toggles in multiple mode, keeping the rest in order", () => {
    expect(toggled([], "u1")).toEqual(["u1"]);
    expect(toggled(["u1"], "u2")).toEqual(["u1", "u2"]);
    expect(toggled(["u1", "u2", "u3"], "u2")).toEqual(["u1", "u3"]);
  });
});

describe("p.477's label and placeholder", () => {
  it("treats whitespace as nothing at all", () => {
    expect(textOf("  Owner  ")).toBe("Owner");
    expect(textOf("   ")).toBeNull();
    expect(textOf("")).toBeNull();
    expect(textOf(undefined)).toBeNull();
  });

  it("says something sensible with no placeholder, per mode", () => {
    expect(placeholderOf("", "single")).toBe("Select a user...");
    expect(placeholderOf("", "multiple")).toBe("Select users...");
    expect(placeholderOf("  Pick one  ", "single")).toBe("Pick one");
  });
});

describe("p.478's Allow clear", () => {
  it("is off unless the document says true", () => {
    expect(allowClearOf(true)).toBe(true);
    expect(allowClearOf(false)).toBe(false);
    expect(allowClearOf(undefined)).toBe(false);
    // Read from a document, so a truthy string must not enable it.
    expect(allowClearOf("false")).toBe(false);
    expect(allowClearOf(1)).toBe(false);
  });
});

describe("what the closed control says", () => {
  const users = usersOf(DIRECTORY);

  it("shows the placeholder, a name, then a count", () => {
    expect(summaryOf([], users, "Select a user...")).toBe("Select a user...");
    expect(summaryOf(["u1"], users, "x")).toBe("Ada Lovelace");
    expect(summaryOf(["u1", "u2"], users, "x")).toBe("2 selected");
  });

  it("still reads as a selection when the directory does not hold the id", () => {
    // The user may have been disabled since, or the group filter may have
    // narrowed them out. Reporting "none selected" would invite an author to
    // overwrite a value that is still in the variable.
    expect(summaryOf(["u3"], users, "Select a user...")).toBe("1 selected");
  });
});

describe("p.478's group filter", () => {
  it("tells no filter from a filter naming nobody", () => {
    // `null` is "nobody configured one"; `[]` is "one is configured and it
    // currently names nobody". Over HTTP those two are the same request, which
    // is why the difference has to survive this far.
    expect(groupIdsOf(undefined)).toBeNull();
    expect(groupIdsOf(null)).toBeNull();
    expect(groupIdsOf([])).toEqual([]);
  });

  it("reads a list, a bare string, and drops the rest", () => {
    expect(groupIdsOf(["g1", "g2"])).toEqual(["g1", "g2"]);
    expect(groupIdsOf("g1")).toEqual(["g1"]);
    expect(groupIdsOf(["g1", "g1", "", "  ", 7, null])).toEqual(["g1"]);
  });

  it("asks the directory when nothing is filtering it", () => {
    expect(shouldAsk(false, null)).toBe(true);
    // A stale group list on an unbound variable is still no filter.
    expect(shouldAsk(false, [])).toBe(true);
  });

  it("waits when a filter is configured but names nobody yet", () => {
    // **The rule the server cannot enforce.** A repeated query parameter has no
    // empty form, so "no groups" and "no filter" are the same request and that
    // request answers with the whole organisation. A filtered picker that asked
    // anyway would flash every user in the org before narrowing.
    expect(shouldAsk(true, null)).toBe(false);
    expect(shouldAsk(true, [])).toBe(false);
    expect(shouldAsk(true, ["g1"])).toBe(true);
  });
});
