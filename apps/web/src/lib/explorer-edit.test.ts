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
  backingActions,
  batchesOf,
  editLimitFor,
  editingUnavailable,
  failureMessage,
  inlineColumns,
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
    // p.136's configuration is per property, so that is where it points.
    expect(why).toContain("No property of Ticket has an inline action");
  });

  it("names the projects in a stated order however they arrive", () => {
    // **The claim the server's `ORDER BY` could not be tested for.** Two rows
    // from Postgres come back in whatever order the plan produces, which
    // coincides with alphabetical about half the time — so a test asserting
    // the order passed or failed by luck. Here it is exact: the same two
    // projects in either order give one sentence, and a reader refreshing the
    // page sees the same ambiguity rather than a different-looking one.
    const forwards = editingUnavailable(TICKETS, [action()], true,
      [{ name: "Billing" }, { name: "Support" }]);
    const backwards = editingUnavailable(TICKETS, [action()], true,
      [{ name: "Support" }, { name: "Billing" }]);
    expect(forwards).toBe(backwards);
    expect(forwards).toContain("(Billing, Support)");
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

describe("which columns take an editor (§600, p.136's per-property inline edit)", () => {
  const writes = (property: string, parameter: string) =>
    ({ kind: "modify_object", config: { property, parameter } });
  const actions = [
    { ...action({ id: "a1" }), object_type_id: "t", rules: [writes("status", "new_status")] },
    { ...action({ id: "a2", inline_edit_row_limit: 20 }), object_type_id: "t",
      rules: [writes("priority", "priority"), writes("owner", "who")] },
    { ...action({ id: "a3", inline_edit_refusals: ["no"] }), object_type_id: "t",
      rules: [writes("note", "note")] },
  ];
  const properties = [
    { api_name: "status", inline_action_type_id: "a1" },
    { api_name: "priority", inline_action_type_id: "a2" },
    { api_name: "owner", inline_action_type_id: "a2" },
    { api_name: "note", inline_action_type_id: "a3" },
    { api_name: "title", inline_action_type_id: "a1" },
    { api_name: "size", inline_action_type_id: null },
  ];

  it("is each property's own action, through the parameter it writes the property from", () => {
    expect(inlineColumns(properties, actions,
      ["status", "priority", "owner", "note", "title", "size", "gone"])).toEqual({
      status: { actionId: "a1", parameter: "new_status" },
      priority: { actionId: "a2", parameter: "priority" },
      owner: { actionId: "a2", parameter: "who" },
    });
    expect(inlineColumns(properties, actions, ["priority"])).toEqual({
      priority: { actionId: "a2", parameter: "priority" } });
    expect(inlineColumns(properties, undefined, ["status"])).toEqual({});
    expect(inlineColumns([{ api_name: "status", inline_action_type_id: "a9" }], actions,
      ["status"])).toEqual({});
  });

  it("counts the actions behind the columns once each, and caps rows at the smallest", () => {
    const columns = inlineColumns(properties, actions, ["status", "priority", "owner"]);
    expect(backingActions(columns, actions).map((a) => a.id)).toEqual(["a1", "a2"]);
    expect(editLimitFor(backingActions(columns, actions))).toBe(20);
    expect(editLimitFor([])).toBe(0);
  });

  it("submits one batch per action, each row's columns as that action's parameters", () => {
    const columns = inlineColumns(properties, actions, ["status", "priority", "owner"]);
    expect(batchesOf({
      i2: { status: "closed" },
      i1: { priority: "high", status: "open", owner: "ana", stray: 1 },
    }, columns)).toEqual([
      { actionId: "a1", edits: [
        { instance_id: "i1", values: { new_status: "open" } },
        { instance_id: "i2", values: { new_status: "closed" } }] },
      { actionId: "a2", edits: [
        { instance_id: "i1", values: { priority: "high", who: "ana" } }] },
    ]);
    expect(batchesOf({}, columns)).toEqual([]);
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
