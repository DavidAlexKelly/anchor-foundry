/**
 * Editing an object from the Explorer's results (§324; `action-types` p.135-137).
 *
 * The eligibility is decided on the server and tested in
 * `apps/api/tests/test_action_inline_edits.py`; the round trip is in
 * `e2e/test_explorer_edit.py`. What is here is the half neither can reach:
 * whether the reasons the Explorer gives for not offering an editor are
 * distinguishable from each other.
 */
import { describe, expect, it } from "vitest";
import type { EditAction } from "../components/canvas/inline-edit";
import {
  editableColumns,
  editingUnavailable,
  editsColumn,
  failureMessage,
  savedMessage,
  submitLabel,
} from "./explorer-edit";

const TICKETS = { display_name: "Ticket" };

const action = (over: Partial<EditAction> = {}): EditAction => ({
  id: "a1",
  display_name: "Set status",
  parameters: [{ api_name: "status" }, { api_name: "priority" }],
  inline_edit_refusals: [],
  inline_edit_hidden_parameters: [],
  inline_edit_row_limit: 200,
  ...over,
});

describe("why the Explorer is not offering an editor", () => {
  it("offers one when a single type, a write role and an action all line up", () => {
    expect(editingUnavailable(TICKETS, [action()], true)).toBeNull();
  });

  it("asks for one object type when the results mix several", () => {
    // **The case p.135 does not have to mention.** Foundry's Object Explorer
    // opens one object type; this one searches the workspace, and an action
    // type belongs to one object type — so a mixed result set has no single
    // action to offer.
    const why = editingUnavailable(null, [action()], true);
    expect(why).toContain("one object type");
  });

  it("says a viewer may not, rather than saying nothing can be edited", () => {
    // Three states look identical on screen — a table with no editors — and
    // §214's rule is that an absent control says why. "You may not" and "there
    // is nothing here to use" send somebody to different people.
    const why = editingUnavailable(TICKETS, [action()], false);
    expect(why).toContain("not change them");
  });

  it("names the type when no action can back an edit", () => {
    const why = editingUnavailable(TICKETS, [], true);
    expect(why).toContain("Ticket");
  });

  it("gives a different answer for every reason", () => {
    // The assertion that makes the four above mean something: a function
    // returning one sentence for every unavailable state would satisfy each of
    // them on its own.
    const said = new Set([
      editingUnavailable(null, [action()], true),
      editingUnavailable(TICKETS, [action()], false),
      editingUnavailable(TICKETS, [], true),
    ]);
    expect(said.size).toBe(3);
  });

  it("checks the role before it checks the actions", () => {
    // A viewer looking at a type with no eligible action is told the thing they
    // can do something about — ask for access — rather than a fact about the
    // ontology that is not their problem.
    expect(editingUnavailable(TICKETS, [], false)).toContain("not change them");
  });
});

describe("which columns take an editor (p.241's automatic mapping)", () => {
  it("matches a parameter to the column of the same name", () => {
    expect(editableColumns(action(), ["status", "priority"])).toEqual({
      status: "status", priority: "priority",
    });
  });

  it("offers nothing for a column the results do not show", () => {
    expect(editableColumns(action(), ["status"])).toEqual({ status: "status" });
  });

  it("offers nothing for a parameter whose name matches nothing", () => {
    expect(editableColumns(action({ parameters: [{ api_name: "new_status" }] }),
      ["status"])).toEqual({});
  });

  it("leaves a hidden parameter out even when the name matches", () => {
    // §324: p.137 makes visibility allowed rather than disqualifying, so a
    // hidden parameter is a column not offered — and a name match would
    // otherwise walk it straight onto an editor.
    expect(editableColumns(action({ inline_edit_hidden_parameters: ["priority"] }),
      ["status", "priority"])).toEqual({ status: "status" });
  });

  it("offers nothing at all when no action is chosen", () => {
    expect(editableColumns(null, ["status"])).toEqual({});
  });
});

describe("asking per column, the way a row asks", () => {
  it("names the parameter that edits this column", () => {
    expect(editsColumn({ status: "status" }, "status")).toBe("status");
  });

  it("is null for a column with no editor", () => {
    expect(editsColumn({ status: "status" }, "priority")).toBeNull();
  });

  it("picks the same parameter every time when two point at one column", () => {
    // Two parameters onto one column is a configuration nothing prevents, and
    // an arbitrary winner would draw a different editor on each render.
    const twice = { zulu: "status", alpha: "status" };
    expect(editsColumn(twice, "status")).toBe("alpha");
    expect(editsColumn(twice, "status")).toBe("alpha");
  });
});

describe("what Submit says", () => {
  it("counts the rows about to change", () => {
    // p.138 makes a submission whole or nothing, so the blast radius is the
    // one fact somebody needs before pressing it.
    expect(submitLabel(3)).toBe("Save 3 objects");
  });

  it("does not pluralise one", () => {
    expect(submitLabel(1)).toBe("Save 1 object");
  });

  it("says there is nothing rather than offering to save nothing", () => {
    expect(submitLabel(0)).toBe("Nothing to save");
  });
});

describe("what the reader is told afterwards", () => {
  it("keeps the server's own refusal", () => {
    // p.138's refusals name the row or the rule that stopped it, and that is
    // the only part somebody can act on.
    expect(failureMessage("row 2 names an object this project cannot reach"))
      .toContain("row 2");
  });

  it("has something to say when the failure has no message", () => {
    for (const nothing of [null, undefined, "", "   "]) {
      expect(failureMessage(nothing)).toBe("Couldn't save these edits.");
    }
  });

  it("reports a save as one outcome for every row", () => {
    expect(savedMessage(4)).toBe("Saved 4 objects.");
    expect(savedMessage(1)).toBe("Saved 1 object.");
  });
});
