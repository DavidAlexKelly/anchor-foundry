/** The command palette's arithmetic (§428; `code-repositories` p.11). */
import { describe, expect, it } from "vitest";
import type { Command } from "./command-palette";
import {
  emptyNote,
  keepHighlight,
  matching,
  opensPalette,
  rank,
  step,
  subsequence,
} from "./command-palette";

const command = (
  id: string, label: string, group: string, over: Partial<Command> = {},
): Command => ({ id, label, group, run: () => {}, ...over });

describe("subsequence", () => {
  it("matches characters spread through the text", () => {
    expect(subsequence("Open file", "opf")).toBe(true);
  });

  it("wants them in order", () => {
    // The same three letters, backwards. A palette that ignored order would
    // answer every query with most of its list.
    expect(subsequence("Open file", "fpo")).toBe(false);
  });

  it("does not reuse one character for two", () => {
    // One "l" in the text, two in the query: `indexOf` has to resume *after*
    // the match it just took, and a version that did not would call this one.
    expect(subsequence("Reload", "ll")).toBe(false);
  });

  it("ignores case on both sides", () => {
    expect(subsequence("Open File", "OF")).toBe(true);
  });

  it("matches the empty query", () => {
    expect(subsequence("Commit", "")).toBe(true);
  });
});

describe("rank", () => {
  const commit = command("commit", "Commit", "Repository", {
    hints: ["save", "check in"],
  });

  it("puts a prefix first", () => {
    expect(rank(commit, "com")).toBe(0);
  });

  it("ranks a word inside the label below a prefix", () => {
    expect(rank(commit, "mit")).toBe(1);
  });

  it("ranks a subsequence below a substring", () => {
    expect(rank(command("of", "Open file", "File"), "opf")).toBe(2);
  });

  it("matches the group as well as the label", () => {
    // "Branch switch" is not in either string on its own.
    expect(rank(command("sw", "Switch", "Branch"), "brsw")).toBe(2);
  });

  it("ranks a hint last", () => {
    expect(rank(commit, "check in")).toBe(3);
  });

  it("matches the middle of a hint, not only its start", () => {
    // "remove" finding "Delete file" is the case hints exist for, and it is
    // rarely the whole word somebody types. Nothing visible on this row
    // contains "eck": the label is "Commit" and the group "Repository".
    expect(rank(commit, "eck")).toBe(3);
  });

  it("is null when nothing matches", () => {
    expect(rank(commit, "zzz")).toBe(null);
  });

  it("matches everything at the top rank on an empty query", () => {
    expect(rank(commit, "")).toBe(0);
    expect(rank(commit, "   ")).toBe(0);
  });

  it("ignores the space a reader leaves behind", () => {
    // Typing "com " and getting nothing is the palette looking broken for the
    // length of one keystroke.
    expect(rank(commit, "com ")).toBe(0);
  });
});

describe("matching", () => {
  const commands = [
    command("commit", "Commit", "Repository", { hints: ["save"] }),
    command("compare", "Compare branches", "Branch"),
    command("open", "Open file", "File"),
    command("delete", "Delete file", "File", { hints: ["remove"] }),
  ];

  it("orders by rank, best first", () => {
    // "Compare branches" starts with it; "Commit" only contains the letters
    // as a subsequence (c-o-m ... p? no) - so prefix beats the rest.
    expect(matching(commands, "comp").map((c) => c.id)).toEqual(["compare"]);
  });

  it("puts a prefix above a substring", () => {
    const hits = matching(
      [command("a", "Take file", "x"), command("b", "File tree", "x")],
      "file",
    );
    expect(hits.map((c) => c.id)).toEqual(["b", "a"]);
  });

  it("keeps the given order between equal matches", () => {
    // Both are "File <something>" prefixed by neither; both match as a
    // subsequence, so nothing but the author's order can separate them.
    const hits = matching(commands, "fl");
    expect(hits.map((c) => c.id)).toEqual(["open", "delete"]);
  });

  it("returns everything, in order, for an empty query", () => {
    expect(matching(commands, "").map((c) => c.id))
      .toEqual(["commit", "compare", "open", "delete"]);
  });

  it("finds a command by a word that is not on screen", () => {
    expect(matching(commands, "remove").map((c) => c.id)).toEqual(["delete"]);
  });

  it("keeps a disabled command in the list", () => {
    // The claim in `enabled`'s docstring: a greyed row says "nothing to
    // commit", an absent one says the palette is broken (§214).
    const off = [command("commit", "Commit", "Repository", { enabled: false })];
    expect(matching(off, "commit").map((c) => c.id)).toEqual(["commit"]);
  });

  it("is empty when nothing matches", () => {
    expect(matching(commands, "zzzz")).toEqual([]);
  });
});

describe("keepHighlight", () => {
  const rows = [
    command("a", "Alpha", "g"),
    command("b", "Bravo", "g"),
    command("c", "Charlie", "g"),
  ];

  it("keeps a command that is still in the list", () => {
    expect(keepHighlight(rows, "c")).toBe("c");
  });

  it("follows the command rather than the row it was in", () => {
    // The one bug a palette must not have: the reader is looking at "Charlie"
    // in row 3, types a letter that removes "Alpha", and Enter runs whatever
    // moved into row 3. By id, "Charlie" stays highlighted at row 2.
    expect(keepHighlight([rows[1]!, rows[2]!], "c")).toBe("c");
  });

  it("falls back to the first row when the command is gone", () => {
    expect(keepHighlight(rows, "gone")).toBe("a");
  });

  it("highlights the first row when nothing was highlighted", () => {
    expect(keepHighlight(rows, null)).toBe("a");
  });

  it("is null on an empty list", () => {
    expect(keepHighlight([], "a")).toBe(null);
  });
});

describe("step", () => {
  const rows = [
    command("a", "Alpha", "g"),
    command("b", "Bravo", "g"),
    command("c", "Charlie", "g"),
  ];

  it("moves down", () => {
    expect(step(rows, "a", 1)).toBe("b");
  });

  it("moves up", () => {
    expect(step(rows, "b", -1)).toBe("a");
  });

  it("wraps past the end", () => {
    expect(step(rows, "c", 1)).toBe("a");
  });

  it("wraps past the start", () => {
    expect(step(rows, "a", -1)).toBe("c");
  });

  it("starts at the top on the way down from nothing", () => {
    expect(step(rows, null, 1)).toBe("a");
  });

  it("starts at the bottom on the way up from nothing", () => {
    // Up from nowhere is the last row, not the first: a reader who presses Up
    // as the palette opens wants the end of the list.
    expect(step(rows, null, -1)).toBe("c");
  });

  it("is null on an empty list", () => {
    expect(step([], null, 1)).toBe(null);
  });
});

describe("opensPalette", () => {
  it("opens on F1", () => {
    expect(opensPalette({ key: "F1" })).toBe(true);
  });

  it("does not open on another key", () => {
    expect(opensPalette({ key: "F2" })).toBe(false);
    expect(opensPalette({ key: "k" })).toBe(false);
  });

  it("leaves a modified F1 to whatever owns it", () => {
    expect(opensPalette({ key: "F1", ctrlKey: true })).toBe(false);
    expect(opensPalette({ key: "F1", metaKey: true })).toBe(false);
    expect(opensPalette({ key: "F1", altKey: true })).toBe(false);
    expect(opensPalette({ key: "F1", shiftKey: true })).toBe(false);
  });

  it("does not open an event something has already handled", () => {
    // Monaco's own palette handles F1 when the editor has focus, and calls
    // `preventDefault`. Two palettes over one keystroke is the bug this line
    // exists to avoid.
    expect(opensPalette({ key: "F1", defaultPrevented: true })).toBe(false);
  });
});

describe("emptyNote", () => {
  it("names the query, so a typo is visible", () => {
    expect(emptyNote("comit")).toContain("comit");
  });

  it("does not show the space a reader left behind", () => {
    expect(emptyNote("comit ")).toBe(emptyNote("comit"));
  });
});
