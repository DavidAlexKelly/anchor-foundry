import { describe, expect, it } from "vitest";
import {
  MAX_TABS, draftsOf, moveTab, shownTab, showsTabStrip, tabsProblem, type TabDraft,
} from "./object-view-tabs";

const tabs = [{ id: "a" }, { id: "b" }, { id: "c" }];
const tab = (over: Partial<TabDraft> = {}): TabDraft => ({
  title: "T", canvas_app_id: "app", subject_variable: "v", ...over,
});

describe("shownTab", () => {
  it("is the reader's pick while it exists", () => {
    expect(shownTab(tabs, "c", "b")?.id).toBe("c");
  });
  it("is the initial tab when nothing is picked or the pick is gone", () => {
    expect(shownTab(tabs, null, "b")?.id).toBe("b");
    expect(shownTab(tabs, "gone", "b")?.id).toBe("b");
  });
  it("is the first when the initial tab is unset or gone", () => {
    expect(shownTab(tabs, null, null)?.id).toBe("a");
    expect(shownTab(tabs, null, "gone")?.id).toBe("a");
    expect(shownTab([], null, null)).toBeUndefined();
  });
});

describe("showsTabStrip", () => {
  it("shows only for two or more tabs, unless hidden", () => {
    expect(showsTabStrip(1, false)).toBe(false);
    expect(showsTabStrip(2, false)).toBe(true);
    expect(showsTabStrip(2, true)).toBe(false);
  });
});

describe("moveTab", () => {
  it("swaps with the neighbour", () => {
    expect(moveTab(["a", "b", "c"], 1, -1)).toEqual(["b", "a", "c"]);
    expect(moveTab(["a", "b", "c"], 1, 1)).toEqual(["a", "c", "b"]);
  });
  it("leaves the ends where they are", () => {
    const list = ["a", "b"];
    expect(moveTab(list, 0, -1)).toBe(list);
    expect(moveTab(list, 1, 1)).toBe(list);
    expect(moveTab(list, 5, -1)).toBe(list);
    expect(moveTab(list, -1, 1)).toBe(list);
  });
});

describe("tabsProblem", () => {
  it("accepts a first tab with no title", () => {
    expect(tabsProblem([tab({ title: "" }), tab()])).toBeNull();
  });
  it("names the tab that is missing something", () => {
    expect(tabsProblem([])).toMatch(/Add a tab/);
    expect(tabsProblem([tab(), tab({ canvas_app_id: "" })])).toBe("Choose a module for tab 2");
    expect(tabsProblem([tab({ subject_variable: "" })])).toMatch(/object in tab 1$/);
    expect(tabsProblem([tab(), tab({ title: "  " })])).toBe("Give tab 2 a title");
  });
  it("bounds the count", () => {
    expect(tabsProblem(Array.from({ length: MAX_TABS }, () => tab()))).toBeNull();
    expect(tabsProblem(Array.from({ length: MAX_TABS + 1 }, () => tab()))).toMatch(/at most 20/);
  });
});

describe("draftsOf", () => {
  it("starts an empty first tab when there is no view", () => {
    expect(draftsOf(null)).toEqual([{ title: "", canvas_app_id: "", subject_variable: "" }]);
  });
  it("keeps the first tab's own title, blank when it follows the module", () => {
    const view = {
      title: "",
      tabs: [
        { title: "Module name", canvas_app_id: "m1", subject_variable: "v1" },
        { title: "Second", canvas_app_id: "m2", subject_variable: "v2" },
      ],
    };
    expect(draftsOf(view)).toEqual([
      { title: "", canvas_app_id: "m1", subject_variable: "v1" },
      { title: "Second", canvas_app_id: "m2", subject_variable: "v2" },
    ]);
  });
});
