/** The repository's command set (§428; `code-repositories` p.11). */
import { describe, expect, it, vi } from "vitest";
import { matching } from "./command-palette";
import type { RepositoryActions, RepositoryState } from "./repository-commands";
import { TABS, TAB_LABELS, repositoryCommands } from "./repository-commands";

const state = (over: Partial<RepositoryState> = {}): RepositoryState => ({
  tab: "files",
  branch: "main",
  branches: ["main", "feature"],
  files: ["transforms/orders.py", "README.md"],
  openFile: null,
  pinned: false,
  ...over,
});

const actions = (): RepositoryActions & { calls: string[] } => {
  const calls: string[] = [];
  return {
    calls,
    goToTab: (tab) => calls.push(`tab:${tab}`),
    switchBranch: (name) => calls.push(`branch:${name}`),
    openFile: (path) => calls.push(`file:${path}`),
    backToBranch: () => calls.push("unpin"),
  };
};

const byId = (commands: ReturnType<typeof repositoryCommands>, id: string) =>
  commands.find((c) => c.id === id)!;

describe("repositoryCommands", () => {
  it("offers every tab", () => {
    const commands = repositoryCommands(state(), actions());
    for (const tab of TABS) {
      expect(byId(commands, `tab:${tab}`).label).toBe(TAB_LABELS[tab]);
    }
  });

  it("disables the tab the reader is already on", () => {
    const commands = repositoryCommands(state({ tab: "checks" }), actions());
    expect(byId(commands, "tab:checks").enabled).toBe(false);
    expect(byId(commands, "tab:checks").note).toBe("already here");
    expect(byId(commands, "tab:files").enabled).toBe(true);
  });

  it("runs the tab it names", () => {
    const acts = actions();
    byId(repositoryCommands(state(), acts), "tab:publish").run();
    expect(acts.calls).toEqual(["tab:publish"]);
  });

  it("offers every branch but the one it is on", () => {
    const commands = repositoryCommands(state(), actions());
    expect(byId(commands, "branch:feature").enabled).toBe(true);
    expect(byId(commands, "branch:main").enabled).toBe(false);
    expect(byId(commands, "branch:main").note).toBe("already on this branch");
  });

  it("runs the branch it names", () => {
    const acts = actions();
    byId(repositoryCommands(state(), acts), "branch:feature").run();
    expect(acts.calls).toEqual(["branch:feature"]);
  });

  it("refuses every branch while a commit is pinned", () => {
    // The bar's picker is disabled here, and a palette that switched anyway
    // would be the page's second answer to the same question.
    const commands = repositoryCommands(state({ pinned: true }), actions());
    expect(byId(commands, "branch:feature").enabled).toBe(false);
    expect(byId(commands, "branch:feature").note).toBe("viewing a commit");
  });

  it("offers the way back only from a pinned commit", () => {
    expect(byId(repositoryCommands(state(), actions()), "unpin").enabled).toBe(false);
    expect(byId(repositoryCommands(state(), actions()), "unpin").note)
      .toBe("not viewing a commit");
    const pinned = repositoryCommands(state({ pinned: true }), actions());
    expect(byId(pinned, "unpin").enabled).toBe(true);
  });

  it("runs the way back", () => {
    const acts = actions();
    byId(repositoryCommands(state({ pinned: true }), acts), "unpin").run();
    expect(acts.calls).toEqual(["unpin"]);
  });

  it("offers every file in the tree", () => {
    const commands = repositoryCommands(state(), actions());
    expect(byId(commands, "file:README.md").label).toBe("README.md");
    expect(byId(commands, "file:transforms/orders.py").enabled).toBe(true);
  });

  it("still offers the file that is already open", () => {
    // Running it from another tab is how you get back to the editor.
    const commands = repositoryCommands(
      state({ tab: "history", openFile: "README.md" }), actions(),
    );
    expect(byId(commands, "file:README.md").enabled).toBe(true);
  });

  it("runs the file it names", () => {
    const acts = actions();
    byId(repositoryCommands(state(), acts), "file:README.md").run();
    expect(acts.calls).toEqual(["file:README.md"]);
  });

  it("builds nothing when nothing has loaded", () => {
    // Branches and the tree arrive from two queries; the palette has to be
    // usable in the second before they land, not throw over an empty list.
    const commands = repositoryCommands(
      state({ branches: [], files: [] }), actions(),
    );
    expect(commands.map((c) => c.id))
      .toEqual([...TABS.map((t) => `tab:${t}`), "unpin"]);
  });

  it("does not run anything merely by being built", () => {
    // Every `run` is a closure; one written as `run: actions.goToTab(tab)`
    // would fire seven navigations the moment the palette opened.
    const goToTab = vi.fn();
    repositoryCommands(state(), { ...actions(), goToTab });
    expect(goToTab).not.toHaveBeenCalled();
  });
});

/** Every word `TAB_HINTS` promises, written out here rather than walked.
 *
 * A loop over the table itself was written first and is the reason this list
 * exists: deleting a word from the source deleted its case too, and the suite
 * went on passing with one fewer test. Written out, a deleted word fails. */
const FINDS: ReadonlyArray<readonly [string, string]> = [
  ["code", "files"], ["tree", "files"], ["editor", "files"],
  ["commits", "history"], ["log", "history"],
  ["merge", "branches"],
  ["pull requests", "pulls"], ["proposals", "pulls"], ["review", "pulls"],
  ["diff", "pulls"],
  ["ci", "checks"], ["tests", "checks"],
  ["deploy", "publish"], ["release", "publish"],
  ["configuration", "settings"], ["policy", "settings"],
];

describe("every hint finds its tab", () => {
  const commands = repositoryCommands(state(), actions());

  for (const [hint, tab] of FINDS) {
    it(`finds ${tab} by "${hint}"`, () => {
      expect(matching(commands, hint).map((c) => c.id)).toContain(`tab:${tab}`);
    });
  }

  it("covers every tab", () => {
    // So a tab added without hints - or with hints nobody wrote down here -
    // fails rather than quietly having none.
    expect(new Set(FINDS.map(([, tab]) => tab))).toEqual(new Set(TABS));
  });
});

describe("the commands a query finds", () => {
  const commands = repositoryCommands(
    state({ files: ["transforms/orders.py", "README.md"] }), actions(),
  );

  it("finds a tab by a word this product does not use for it", () => {
    // "diff" is nowhere in "Pull requests", and it is what somebody who has
    // used another tool types.
    expect(matching(commands, "diff").map((c) => c.id)).toEqual(["tab:pulls"]);
  });

  it("finds a file by its name without its folder", () => {
    expect(matching(commands, "orders").map((c) => c.id))
      .toEqual(["file:transforms/orders.py"]);
  });

  it("puts the tab above the file when both match", () => {
    // "Files" starts with the query; `transforms/...` only contains it.
    expect(matching(commands, "file").map((c) => c.id)[0]).toBe("tab:files");
  });
});
