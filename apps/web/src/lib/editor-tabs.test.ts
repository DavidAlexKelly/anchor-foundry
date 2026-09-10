import { describe, expect, it } from "vitest";

import {
  activeTab,
  closeLabel,
  closeTab,
  emptyViewerNote,
  initialTabs,
  isDirty,
  openTab,
  pruneTabs,
  tabLabel,
} from "./editor-tabs";

describe("the strip a reload rebuilds", () => {
  it("**opens a tab for every file with unsaved work**", () => {
    // The one invariant worth enforcing: a draft in a closed tab is work you
    // cannot see and cannot reach, which is the failure §281 was about
    // arriving by another road.
    expect(initialTabs({ "b.sql": "x", "a.sql": "y" }, undefined)).toEqual(["a.sql", "b.sql"]);
  });

  it("sorts, so two reloads of the same state give the same strip", () => {
    const drafts = { "z.sql": "1", "a.sql": "2", "m.sql": "3" };
    expect(initialTabs(drafts, undefined)).toEqual(initialTabs(drafts, undefined));
    expect(initialTabs(drafts, undefined)).toEqual(["a.sql", "m.sql", "z.sql"]);
  });

  it("adds the file the link points at, and does not add it twice", () => {
    expect(initialTabs({ "a.sql": "x" }, "b.sql")).toEqual(["a.sql", "b.sql"]);
    expect(initialTabs({ "a.sql": "x" }, "a.sql")).toEqual(["a.sql"]);
  });

  it("**leaves a deleted file out**, because its tab could show nothing", () => {
    // Still an uncommitted change, and the commit bar still counts it. The tab
    // strip is just not where a deletion can be looked at.
    expect(initialTabs({ "a.sql": "x", "gone.sql": null }, undefined)).toEqual(["a.sql"]);
  });

  it("opens nothing at all when there is nothing", () => {
    expect(initialTabs({}, undefined)).toEqual([]);
  });
});

describe("opening", () => {
  it("appends a new path", () => {
    expect(openTab(["a.sql"], "b.sql")).toEqual(["a.sql", "b.sql"]);
  });

  it("**does not move a tab that is already open**", () => {
    // Reordering the strip under somebody's cursor means the tab they just
    // clicked is never where they left it.
    expect(openTab(["a.sql", "b.sql", "c.sql"], "a.sql")).toEqual([
      "a.sql",
      "b.sql",
      "c.sql",
    ]);
  });
});

describe("closing", () => {
  it("**selects the neighbour to the right**", () => {
    // People close tabs working forwards through a list; jumping to the first
    // tab would throw them back to the start of it.
    expect(closeTab(["a.sql", "b.sql", "c.sql"], "b.sql", "b.sql")).toEqual({
      tabs: ["a.sql", "c.sql"],
      active: "c.sql",
    });
  });

  it("falls back to the left when the last tab closes", () => {
    expect(closeTab(["a.sql", "b.sql"], "b.sql", "b.sql")).toEqual({
      tabs: ["a.sql"],
      active: "a.sql",
    });
  });

  it("**leaves the active file alone when another tab closes**", () => {
    // That is the entire point of closing a tab that is not the one you are
    // looking at.
    expect(closeTab(["a.sql", "b.sql", "c.sql"], "a.sql", "c.sql")).toEqual({
      tabs: ["b.sql", "c.sql"],
      active: "c.sql",
    });
  });

  it("has nothing active when the last tab goes", () => {
    expect(closeTab(["a.sql"], "a.sql", "a.sql")).toEqual({ tabs: [], active: undefined });
  });

  it("does nothing to a path that is not open", () => {
    expect(closeTab(["a.sql"], "b.sql", "a.sql")).toEqual({
      tabs: ["a.sql"],
      active: "a.sql",
    });
  });
});

describe("files that stop existing", () => {
  it("drops their tabs and keeps the order of the rest", () => {
    // A tab pointing at nothing renders an empty editor, which looks like a
    // file whose contents failed to load.
    expect(pruneTabs(["a.sql", "gone.sql", "b.sql"], ["b.sql", "a.sql"])).toEqual([
      "a.sql",
      "b.sql",
    ]);
  });

  it("empties the strip when a branch switch brings a tree with none of them", () => {
    expect(pruneTabs(["a.sql", "b.sql"], ["other.sql"])).toEqual([]);
  });
});

describe("what a tab is called", () => {
  it("is the file name, because six full paths is a strip of ellipses", () => {
    expect(tabLabel("src/transforms/daily_orders.sql", ["src/transforms/daily_orders.sql"])).toBe(
      "daily_orders.sql",
    );
    expect(tabLabel("t.sql", ["t.sql"])).toBe("t.sql");
  });

  it("**shows the full path when another open tab has the same name**", () => {
    // Two tabs both reading `t.sql` is the one case where the short label
    // stops being a label, and it is what `main/t.sql` and `test/t.sql`
    // produce.
    const tabs = ["main/t.sql", "test/t.sql", "src/other.sql"];
    expect(tabLabel("main/t.sql", tabs)).toBe("main/t.sql");
    expect(tabLabel("test/t.sql", tabs)).toBe("test/t.sql");
    expect(tabLabel("src/other.sql", tabs)).toBe("other.sql");
  });

  it("does not consider a path to be its own clash", () => {
    expect(tabLabel("a/t.sql", ["a/t.sql"])).toBe("t.sql");
  });
});

describe("which tab is dirty", () => {
  it("is about the draft differing from the commit, not about having one", () => {
    // Typing a character and typing it back is not a change, and marking it as
    // one would leave a dot nothing can clear.
    const committed = { "a.sql": "SELECT 1" };
    expect(isDirty("a.sql", committed, {})).toBe(false);
    expect(isDirty("a.sql", committed, { "a.sql": "SELECT 1" })).toBe(false);
    expect(isDirty("a.sql", committed, { "a.sql": "SELECT 2" })).toBe(true);
  });

  it("counts a new file and a deletion", () => {
    expect(isDirty("new.sql", {}, { "new.sql": "" })).toBe(true);
    expect(isDirty("a.sql", { "a.sql": "x" }, { "a.sql": null })).toBe(true);
  });
});

describe("what the close button says", () => {
  it("**says a dirty close keeps the work**", () => {
    // The draft lives in the working set, not in the tab, so a file closed
    // with unsaved changes still goes into the next commit. Somebody who
    // closed it meaning "undo this" and was not told would commit work they
    // thought they had thrown away.
    expect(closeLabel("a.sql", true)).toContain("keeps your unsaved changes");
    expect(closeLabel("a.sql", true)).toContain("a.sql");
  });

  it("does not say it when there is nothing to keep", () => {
    expect(closeLabel("a.sql", false)).toBe("Close a.sql");
  });
});

describe("an empty editor pane", () => {
  it("**tells 'no files' apart from 'none open'**", () => {
    // Before tabs an empty pane could only mean an empty repository. Now it
    // can also mean you closed the last tab, and a repository with files needs
    // a click while a repository without needs a file.
    expect(emptyViewerNote(0, false)).toBe("No files yet.");
    expect(emptyViewerNote(3, false)).toContain("Choose one from the tree");
  });

  it("says a pinned commit is empty rather than inviting a new file", () => {
    // History that could be typed into would stop being a record of what
    // happened, so "add a file" would be an offer this pane cannot honour.
    expect(emptyViewerNote(0, true)).toBe("This commit contains no files.");
    expect(emptyViewerNote(3, true)).toContain("Choose one from the tree");
  });
});

describe("which tab is showing", () => {
  it("follows the link when the link names an open file", () => {
    expect(activeTab(["a.sql", "b.sql"], "b.sql")).toBe("b.sql");
  });

  it("**falls back to the first tab rather than showing an empty pane**", () => {
    // A URL can name a file this tree does not have: a stale bookmark, a
    // branch switch, somebody else's link.
    expect(activeTab(["a.sql", "b.sql"], "missing.sql")).toBe("a.sql");
    expect(activeTab(["a.sql"], undefined)).toBe("a.sql");
    expect(activeTab([], "a.sql")).toBeUndefined();
  });
});
