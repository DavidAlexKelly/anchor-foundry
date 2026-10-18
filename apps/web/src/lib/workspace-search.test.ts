import { describe, expect, it } from "vitest";
import {
  focusesSearch, hitHref, kindLabel, objectsHref, step, whereText, workspaceOf,
} from "./workspace-search";

describe("the workspace search (§990)", () => {
  it("knows which workspace a page is in", () => {
    expect(workspaceOf("/acme/sales/datasets")).toBe("acme");
    expect(workspaceOf("/acme")).toBe("acme");
    expect(workspaceOf("/home")).toBeUndefined();
    expect(workspaceOf("/org/audit")).toBeUndefined();
    expect(workspaceOf("/")).toBeUndefined();
  });

  it("says what and where a hit is, and opens it by id", () => {
    expect(kindLabel("canvas_app")).toBe("Module");
    expect(kindLabel("something_new")).toBe("something_new");
    expect(whereText({ project_name: "Sales" })).toBe("Sales");
    expect(whereText({ project_name: null })).toBe("the workspace");
    expect(hitHref({ id: "abc" })).toBe("/r/abc");
  });

  it("is asked for with / unless somebody is typing", () => {
    expect(focusesSearch({ key: "/", target: { tagName: "BODY" } })).toBe(true);
    expect(focusesSearch({ key: "/", target: { tagName: "input" } })).toBe(false);
    expect(focusesSearch({ key: "/", target: { tagName: "DIV", isContentEditable: true } })).toBe(false);
    expect(focusesSearch({ key: "/", ctrlKey: true, target: null })).toBe(false);
    expect(focusesSearch({ key: "k", target: null })).toBe(false);
  });

  it("moves the highlight round the list", () => {
    expect(step(-1, 3, 1)).toBe(0);
    expect(step(-1, 3, -1)).toBe(2);
    expect(step(2, 3, 1)).toBe(0);
    expect(step(0, 3, -1)).toBe(2);
    expect(step(0, 0, 1)).toBe(-1);
  });

  it("hands the same words to the Object Explorer (§991)", () => {
    expect(objectsHref("acme", "heathrow t5")).toBe("/acme/explore?q=heathrow%20t5");
  });
});
