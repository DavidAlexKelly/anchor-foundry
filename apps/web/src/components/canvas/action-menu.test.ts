import { describe, expect, it } from "vitest";

import {
  actionItemsOf, activeIndexOf, menuLabelOf, moreActionsOf, withAddedAction,
  withMoreAction, withoutMoreAction,
} from "./action-menu";

describe("p.512's several actions in one widget (§556)", () => {
  it("makes the widget's own action the first item, unchanged", () => {
    expect(actionItemsOf({ actionTypeId: "close", title: "Close it",
      parameterDefaults: { note: "x" } }, undefined)).toEqual([
      { actionTypeId: "close", title: "Close it", parameterDefaults: { note: "x" } }]);
    expect(actionItemsOf({ actionTypeId: null }, [])).toEqual([]);
  });

  it("adds each further action with its own configuration", () => {
    const more = [{ actionTypeId: "reopen", title: "" }, { actionTypeId: null, title: "wip" },
      { actionTypeId: "tag", title: "Tag", parameterDefaults: { label: "a" } }, "junk"];
    expect(actionItemsOf({ actionTypeId: "close" }, more).map((i) => i.actionTypeId))
      .toEqual(["close", "reopen", "tag"]);
    expect(actionItemsOf({ actionTypeId: "close" }, more)[2]!.parameterDefaults)
      .toEqual({ label: "a" });
    expect(actionItemsOf({ actionTypeId: null }, more).map((i) => i.actionTypeId))
      .toEqual(["reopen", "tag"]);
  });

  it("reads the stored list defensively and keeps an unfinished item for the panel", () => {
    expect(moreActionsOf([{ actionTypeId: "", title: 3 }, null, { parameterDefaults: [] }]))
      .toEqual([{ actionTypeId: null, title: "" },
                { actionTypeId: null, title: "", parameterDefaults: {} }]);
    expect(moreActionsOf("x")).toEqual([]);
  });

  it("keeps the showing item inside the list", () => {
    expect(activeIndexOf(2, 2)).toBe(1);
    expect(activeIndexOf(-1, 3)).toBe(0);
    expect(activeIndexOf(1, 3)).toBe(1);
    expect(activeIndexOf(0, 0)).toBe(0);
  });

  it("labels an item by its title, else its action's name", () => {
    const types = [{ id: "close", display_name: "Close alert" }];
    const item = { actionTypeId: "close", title: "", parameterDefaults: {} };
    expect(menuLabelOf(item, types)).toBe("Close alert");
    expect(menuLabelOf({ ...item, title: " Shut " }, types)).toBe("Shut");
    expect(menuLabelOf({ ...item, actionTypeId: "gone" }, types)).toBe("Action");
  });

  it("adds, changes and removes further actions", () => {
    const one = withAddedAction(undefined);
    expect(one).toEqual([{ actionTypeId: null, title: "" }]);
    const set = withMoreAction(withAddedAction(one), 1, { actionTypeId: "tag" });
    expect(set).toEqual([{ actionTypeId: null, title: "" }, { actionTypeId: "tag", title: "" }]);
    expect(withoutMoreAction(set, 0)).toEqual([{ actionTypeId: "tag", title: "" }]);
    const three = [...set, { actionTypeId: "close", title: "" }];
    expect(withoutMoreAction(three, 1).map((m) => m.actionTypeId)).toEqual([null, "close"]);
  });
});
