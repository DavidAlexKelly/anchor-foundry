import { describe, expect, it } from "vitest";

import {
  hasChanges,
  headline,
  isGap,
  versionLabel,
  versionsEmptyNote,
  withContext,
} from "./file-changes";
import type { RepositoryFileChangeRow, RepositoryFileChanges } from "./types";

function changes(over: Partial<RepositoryFileChanges>): RepositoryFileChanges {
  return {
    path: "src/t.sql",
    state: "modified",
    added: 1,
    removed: 1,
    rows: [],
    ...over,
  };
}

function row(kind: string, n: number): RepositoryFileChangeRow {
  return {
    kind,
    live_line: kind === "added" ? null : n,
    live_text: kind === "added" ? null : `line ${n}`,
    proposed_line: kind === "removed" ? null : n,
    proposed_text: kind === "removed" ? null : `line ${n}`,
  };
}

describe("the header", () => {
  it("**counts both directions, never one total**", () => {
    // "Two lines changed" hides whether a file grew or shrank, which is most
    // of what somebody wants from a glance.
    expect(headline(changes({ added: 3, removed: 1 }))).toBe("+3 −1");
  });

  it("names a new file and a deleted one rather than showing a count alone", () => {
    expect(headline(changes({ state: "added", added: 4, removed: 0 }))).toContain("New file");
    expect(headline(changes({ state: "added", added: 4 }))).toContain("4 lines");
    expect(headline(changes({ state: "deleted", removed: 1, added: 0 }))).toContain("Deleted");
    expect(headline(changes({ state: "deleted", removed: 1, added: 0 }))).toContain("1 line");
  });

  it("says there is nothing rather than showing +0 −0", () => {
    expect(headline(changes({ state: "unchanged", added: 0, removed: 0 }))).toBe(
      "No uncommitted changes to this file.",
    );
  });
});

describe("whether there is a diff to show", () => {
  it("**asks the state, not the row count**", () => {
    // An unchanged file has rows and they are all `same`; rendering them is a
    // whole file in a panel sized for a diff.
    const unchanged = changes({
      state: "unchanged",
      rows: [row("same", 1), row("same", 2)],
    });
    expect(hasChanges(unchanged)).toBe(false);
    expect(hasChanges(changes({ state: "modified", rows: [] }))).toBe(true);
  });
});

describe("context around a change", () => {
  const rows = [
    ...Array.from({ length: 10 }, (_, i) => row("same", i + 1)),
    row("changed", 11),
    ...Array.from({ length: 10 }, (_, i) => row("same", i + 12)),
  ];

  it("**keeps three lines either side**, matching what difflib shows", () => {
    // A changed row three hundred lines into a file, shown alone, tells you
    // what the line says and nothing about what it is part of.
    const shown = withContext(rows);
    expect(shown).toHaveLength(7);
    expect(shown.map((r) => r.live_line)).toEqual([8, 9, 10, 11, 12, 13, 14]);
    expect(shown.map((r) => r.kind)).toEqual([
      "same", "same", "same", "changed", "same", "same", "same",
    ]);
  });

  it("does not run off either end of the file", () => {
    const atStart = withContext([row("changed", 1), row("same", 2)]);
    expect(atStart).toHaveLength(2);
  });

  it("shows nothing at all when nothing changed", () => {
    expect(withContext([row("same", 1), row("same", 2)])).toEqual([]);
  });

  it("**merges overlapping context rather than repeating it**", () => {
    // Two changes four lines apart share their context, and a panel that
    // showed the shared lines twice would read as a file with a repeat in it.
    const near = [
      row("changed", 1),
      ...Array.from({ length: 4 }, (_, i) => row("same", i + 2)),
      row("changed", 6),
    ];
    const shown = withContext(near);
    expect(shown).toHaveLength(6);
    expect(new Set(shown.map((r) => r.live_line)).size).toBe(6);
  });
});

describe("the elision marker", () => {
  it("**says when lines were skipped**", () => {
    // A diff that silently skips two hundred lines and shows the next change
    // flush against the last one reads as one hunk.
    const rows = [
      row("changed", 1),
      ...Array.from({ length: 20 }, (_, i) => row("same", i + 2)),
      row("changed", 22),
    ];
    const shown = withContext(rows);
    expect(isGap(rows, shown, 0)).toBe(false);
    const gapAt = shown.findIndex((_, i) => isGap(rows, shown, i));
    expect(gapAt).toBeGreaterThan(0);
  });

  it("says nothing when the rows are consecutive", () => {
    const rows = [row("changed", 1), row("same", 2), row("changed", 3)];
    const shown = withContext(rows);
    expect(shown.every((_, i) => !isGap(rows, shown, i))).toBe(true);
  });
});

describe("a version in the picker", () => {
  function version(over: Record<string, unknown> = {}) {
    return {
      id: "c-1",
      parent_id: null,
      message: "Add the transform",
      created_by: null,
      created_at: "2026-01-02T03:04:00Z",
      sha: "abc",
      state: "added",
      ...over,
    } as never;
  }

  it("leads with the message, because that is what a person remembers", () => {
    expect(versionLabel(version())).toContain("Add the transform");
  });

  it("**says 'no message' rather than showing an empty label**", () => {
    // A commit may have none, and a picker row that was just a date would be
    // indistinguishable from the row above it.
    expect(versionLabel(version({ message: "   " }))).toContain("no message");
  });
});

describe("an empty version list", () => {
  it("**tells 'never committed' apart from 'this branch has none'**", () => {
    // The second is what a new sandbox looks like before anybody commits.
    expect(versionsEmptyNote("added")).toContain("not committed yet");
    expect(versionsEmptyNote("modified")).toContain("No commits on this branch");
  });
});
