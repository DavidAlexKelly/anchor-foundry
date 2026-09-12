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
/** One place for a write to go, which is the ordinary case. */
const ONE_PROJECT = [{ name: "Support" }];

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
    expect(editingUnavailable(TICKETS, [action()], true, ONE_PROJECT)).toBeNull();
  });

  it("asks for one object type when the results mix several", () => {
    // **The case p.135 does not have to mention.** Foundry's Object Explorer
    // opens one object type; this one searches the workspace, and an action
    // type belongs to one object type — so a mixed result set has no single
    // action to offer.
    const why = editingUnavailable(null, [action()], true, ONE_PROJECT);
    expect(why).toContain("one object type");
  });

  it("says a viewer may not, rather than saying nothing can be edited", () => {
    // Three states look identical on screen — a table with no editors — and
    // §214's rule is that an absent control says why. "You may not" and "there
    // is nothing here to use" send somebody to different people.
    const why = editingUnavailable(TICKETS, [action()], false, ONE_PROJECT);
    expect(why).toContain("not change them");
  });

  it("names the type when no action can back an edit", () => {
    const why = editingUnavailable(TICKETS, [], true, ONE_PROJECT);
    expect(why).toContain("Ticket");
  });

  it("refuses to choose between two projects, and names them", () => {
    // **The Explorer is workspace-scoped and a write is not** (§324). An
    // instance comes from a mapping, a mapping names a dataset, and a dataset
    // lives in a project — so a type mapped from two datasets in two projects
    // genuinely has two destinations, and silently picking one would write to
    // a dataset the reader never named.
    const why = editingUnavailable(TICKETS, [action()], true, [
      { name: "Support" }, { name: "Billing" },
    ]);
    expect(why).toContain("Support");
    expect(why).toContain("Billing");
    // And it points somewhere that does work, rather than ending on a refusal.
    expect(why).toContain("Open the object");
  });

  it("says there is nowhere to write when nothing maps the type", () => {
    // A different answer from the ambiguity above: one is a type mapped twice
    // and the other a type mapped not at all, and they are fixed by opposite
    // actions.
    const why = editingUnavailable(TICKETS, [action()], true, []);
    expect(why).toContain("no dataset");
  });

  it("gives a different answer for every reason", () => {
    // The assertion that makes the five above mean something: a function
    // returning one sentence for every unavailable state would satisfy each of
    // them on its own.
    const said = new Set([
      editingUnavailable(null, [action()], true, ONE_PROJECT),
      editingUnavailable(TICKETS, [action()], false, ONE_PROJECT),
      editingUnavailable(TICKETS, [], true, ONE_PROJECT),
      editingUnavailable(TICKETS, [action()], true, []),
      editingUnavailable(TICKETS, [action()], true,
        [{ name: "Support" }, { name: "Billing" }]),
    ]);
    expect(said.size).toBe(5);
  });

  it("checks the role before it checks the actions", () => {
    // A viewer looking at a type with no eligible action is told the thing they
    // can do something about — ask for access — rather than a fact about the
    // ontology that is not their problem.
    expect(editingUnavailable(TICKETS, [], false, ONE_PROJECT)).toContain("not change them");
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

  it("picks the same parameter however the mapping was built", () => {
    // Two parameters onto one column is a configuration nothing prevents, and
    // an arbitrary winner would draw a different editor for the same document.
    //
    // **Both insertion orders, and that is the whole test.** The first version
    // asserted one object twice and expected "alpha" — which `sort()` and
    // `reverse()` both answer for keys inserted zulu-then-alpha, so a mutant
    // swapping them survived. Object key order *is* insertion order, so the
    // only way to see an ordering rule is to feed it two orders and demand one
    // answer.
    expect(editsColumn({ zulu: "status", alpha: "status" }, "status")).toBe("alpha");
    expect(editsColumn({ alpha: "status", zulu: "status" }, "status")).toBe("alpha");
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
