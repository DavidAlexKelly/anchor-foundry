import { describe, expect, it } from "vitest";

import {
  DEFAULT_BUTTON_TEXT,
  UNKNOWN_ROW_LIMIT,
  automaticMapping,
  buttonTextOf,
  canStage,
  canSubmit,
  cellValue,
  editByDefaultOf,
  editing,
  eligibleActions,
  isStaged,
  limitNotice,
  mappingOf,
  oneClickOf,
  parameterForColumn,
  rowLimitOf,
  stage,
  stagedCount,
  stagedOf,
  toEdits,
  undoRow,
  type EditAction,
} from "./inline-edit";

const action = (over: Partial<EditAction> = {}): EditAction => ({
  id: "a1",
  display_name: "Edit ticket",
  parameters: [{ api_name: "status" }, { api_name: "priority" }],
  inline_edit_refusals: [],
  inline_edit_row_limit: 200,
  ...over,
});

describe("which actions are offered (p.240, §238)", () => {
  it("offers one whose refusals are empty", () => {
    expect(eligibleActions([action()]).map((a) => a.id)).toEqual(["a1"]);
  });

  it("does not offer one the server refused", () => {
    const refused = action({ inline_edit_refusals: ["'site' is a geopoint parameter"] });
    expect(eligibleActions([refused]).length).toBe(0);
  });

  it("does not offer one whose verdict is missing", () => {
    // **Absent is not eligible.** An action type from a payload that predates
    // §238 has an unknown verdict, and offering an unknown one is offering a
    // save that fails - §214's rule. Written as "present and empty" rather than
    // "not non-empty" for exactly this case.
    expect(eligibleActions([action({ inline_edit_refusals: undefined })]).length).toBe(0);
  });

  it("reads nothing as nothing", () => {
    expect(eligibleActions(undefined)).toEqual([]);
  });
});

describe("the row cap arrives on the wire (p.242)", () => {
  it("takes the action's own number", () => {
    expect(rowLimitOf(action())).toBe(200);
  });

  it("permits nothing while the action is unknown", () => {
    // Zero rather than 200: an unknown cap that permits everything is the
    // direction that writes data.
    expect(rowLimitOf(null)).toBe(UNKNOWN_ROW_LIMIT);
    expect(rowLimitOf(action({ inline_edit_row_limit: undefined }))).toBe(0);
  });

  it("refuses a cap that is not a usable number", () => {
    expect(rowLimitOf(action({ inline_edit_row_limit: 0 }))).toBe(0);
    expect(rowLimitOf(action({ inline_edit_row_limit: -5 }))).toBe(0);
    expect(rowLimitOf(action({ inline_edit_row_limit: Number.NaN }))).toBe(0);
  });
});

describe("p.241's automatic mapping", () => {
  it("matches a parameter to the column of the same name", () => {
    expect(automaticMapping(action(), ["status", "priority"])).toEqual({
      status: "status", priority: "priority",
    });
  });

  it("maps only columns the table displays", () => {
    // p.241's sentence is about the properties "displayed within the table" -
    // an editor on a column nobody can see is an editor nobody can reach.
    expect(automaticMapping(action(), ["status"])).toEqual({ status: "status" });
  });

  it("leaves a parameter whose name matches nothing unmapped", () => {
    expect(automaticMapping(action({ parameters: [{ api_name: "new_status" }] }),
      ["status"])).toEqual({});
  });
});

describe("reading a stored mapping", () => {
  it("keeps a mapping both sides still have", () => {
    expect(mappingOf({ status: "status" }, action(), ["status"])).toEqual({
      status: "status",
    });
  });

  it("drops one naming a parameter the action no longer declares", () => {
    expect(mappingOf({ gone: "status" }, action(), ["status"])).toEqual({});
  });

  it("drops one naming a column the table no longer shows", () => {
    expect(mappingOf({ status: "status" }, action(), ["priority"])).toEqual({});
  });

  it("survives whatever the document actually holds", () => {
    expect(mappingOf(null, action(), ["status"])).toEqual({});
    expect(mappingOf("status", action(), ["status"])).toEqual({});
    expect(mappingOf(["status"], action(), ["status"])).toEqual({});
    expect(mappingOf({ status: 7 }, action(), ["status"])).toEqual({});
    expect(mappingOf({ status: "" }, action(), ["status"])).toEqual({});
  });
});

describe("which parameter edits a column", () => {
  it("finds the parameter pointed at it", () => {
    expect(parameterForColumn({ new_status: "status" }, "status")).toBe("new_status");
  });

  it("says nothing for a column nothing maps to", () => {
    expect(parameterForColumn({ status: "status" }, "priority")).toBeUndefined();
  });

  it("resolves two parameters on one column the same way every time", () => {
    // Nothing prevents this configuration, and an arbitrary winner would draw a
    // different editor depending on key order.
    const both = { b_param: "status", a_param: "status" };
    expect(parameterForColumn(both, "status")).toBe("a_param");
  });
});

describe("staging (p.242)", () => {
  it("records what was typed", () => {
    expect(stage({}, "i1", "status", "closed", 200)).toEqual({
      i1: { status: "closed" },
    });
  });

  it("keeps a row's other cells when a second one is typed", () => {
    const one = stage({}, "i1", "status", "closed", 200);
    expect(stage(one, "i1", "priority", "high", 200)).toEqual({
      i1: { status: "closed", priority: "high" },
    });
  });

  it("counts rows rather than edits", () => {
    let s = stage({}, "i1", "status", "a", 200);
    s = stage(s, "i1", "priority", "b", 200);
    expect(stagedCount(s)).toBe(1);
  });

  it("refuses a new row once the cap is reached", () => {
    const full = stage({}, "i1", "status", "a", 1);
    expect(canStage(full, "i2", 1)).toBe(false);
    expect(stage(full, "i2", "status", "b", 1)).toBe(full);
  });

  it("keeps editing a row that is already staged", () => {
    // The cap is about rows. Freezing a reader halfway through correcting the
    // row in front of them is not what p.242 asks for.
    const full = stage({}, "i1", "status", "a", 1);
    expect(canStage(full, "i1", 1)).toBe(true);
    expect(stage(full, "i1", "status", "b", 1)).toEqual({ i1: { status: "b" } });
  });

  it("stages nothing at all while the cap is unknown", () => {
    expect(canStage({}, "i1", UNKNOWN_ROW_LIMIT)).toBe(false);
  });
});

describe("undo (p.242)", () => {
  it("removes the whole row", () => {
    let s = stage({}, "i1", "status", "a", 200);
    s = stage(s, "i1", "priority", "b", 200);
    expect(undoRow(s, "i1")).toEqual({});
  });

  it("leaves the other rows alone", () => {
    let s = stage({}, "i1", "status", "a", 200);
    s = stage(s, "i2", "status", "b", 200);
    expect(undoRow(s, "i1")).toEqual({ i2: { status: "b" } });
  });

  it("does nothing for a row nobody edited", () => {
    const s = stage({}, "i1", "status", "a", 200);
    expect(undoRow(s, "i2")).toBe(s);
  });
});

describe("what a cell shows", () => {
  it("shows the stored value until something is typed", () => {
    expect(cellValue({}, "i1", "status", "open")).toBe("open");
  });

  it("shows what was typed", () => {
    const s = stage({}, "i1", "status", "closed", 200);
    expect(cellValue(s, "i1", "status", "open")).toBe("closed");
  });

  it("shows a cleared cell as cleared", () => {
    // **The case a truthiness test gets wrong.** Deleting a cell's contents is
    // an edit, and falling back to the stored value would show it straight back
    // to the reader who had just removed it.
    const s = stage({}, "i1", "status", "", 200);
    expect(cellValue(s, "i1", "status", "open")).toBe("");
  });

  it("does not confuse one parameter's edit for another's", () => {
    const s = stage({}, "i1", "status", "closed", 200);
    expect(cellValue(s, "i1", "priority", "low")).toBe("low");
  });

  it("says whether a row carries any edit at all", () => {
    expect(isStaged(stage({}, "i1", "status", "x", 200), "i1")).toBe(true);
    expect(isStaged({}, "i1")).toBe(false);
  });
});

describe("reading staged edits back", () => {
  it("survives whatever it is handed", () => {
    expect(stagedOf(null)).toEqual({});
    expect(stagedOf([{ i1: {} }])).toEqual({});
    expect(stagedOf({ i1: "closed" })).toEqual({});
  });

  it("copies rather than aliasing", () => {
    const source = { i1: { status: "a" } };
    const read = stagedOf(source);
    read.i1!.status = "b";
    expect(source.i1.status).toBe("a");
  });
});

describe("the request body", () => {
  it("is one entry per staged row", () => {
    let s = stage({}, "i2", "status", "b", 200);
    s = stage(s, "i1", "status", "a", 200);
    expect(toEdits(s)).toEqual([
      { instance_id: "i1", values: { status: "a" } },
      { instance_id: "i2", values: { status: "b" } },
    ]);
  });

  it("is ordered by instance rather than by typing order", () => {
    // The server reports the first row that fails a criterion; insertion order
    // would make which row that is depend on where the reader clicked first.
    let s = stage({}, "z", "status", "1", 200);
    s = stage(s, "a", "status", "2", 200);
    expect(toEdits(s).map((e) => e.instance_id)).toEqual(["a", "z"]);
  });
});

describe("the footer's settings (p.242-243)", () => {
  it("uses p.242's own label by default", () => {
    expect(buttonTextOf(null)).toBe(DEFAULT_BUTTON_TEXT);
    expect(buttonTextOf("   ")).toBe(DEFAULT_BUTTON_TEXT);
  });

  it("uses a custom label when there is one", () => {
    expect(buttonTextOf("  Correct these  ")).toBe("Correct these");
  });

  it("reads both toggles as booleans and nothing else", () => {
    // A raw JSON editor (§117) can put the string "false" in a document, and a
    // truthiness test would read that as "yes".
    expect(editByDefaultOf("false")).toBe(false);
    expect(editByDefaultOf(1)).toBe(false);
    expect(editByDefaultOf(true)).toBe(true);
    expect(oneClickOf("false")).toBe(false);
    expect(oneClickOf(true)).toBe(true);
  });

  it("starts in edit mode only when the toggle says so", () => {
    expect(editing(null, true)).toBe(true);
    expect(editing(null, false)).toBe(false);
  });

  it("lets the button win once it has been pressed", () => {
    // Including pressing it *closed* on a table configured to open in edit
    // mode, which `||` against the toggle would make impossible.
    expect(editing(false, true)).toBe(false);
    expect(editing(true, false)).toBe(true);
  });
});

describe("when Submit may be pressed", () => {
  it("needs something staged", () => {
    expect(canSubmit({}, action())).toBe(false);
    expect(canSubmit(stage({}, "i1", "status", "x", 200), action())).toBe(true);
  });

  it("needs an action to submit to", () => {
    expect(canSubmit(stage({}, "i1", "status", "x", 200), null)).toBe(false);
  });
});

describe("the cap's notice", () => {
  it("says nothing until the cap is reached", () => {
    expect(limitNotice({}, 2)).toBeNull();
    expect(limitNotice(stage({}, "i1", "s", "x", 2), 2)).toBeNull();
  });

  it("says so once it is", () => {
    let s = stage({}, "i1", "s", "x", 2);
    s = stage(s, "i2", "s", "y", 2);
    expect(limitNotice(s, 2)).toContain("2 rows staged");
  });

  it("says nothing while the cap is unknown", () => {
    // Zero staged against an unknown cap is not "full", it is "not loaded".
    expect(limitNotice({}, UNKNOWN_ROW_LIMIT)).toBeNull();
  });
});
