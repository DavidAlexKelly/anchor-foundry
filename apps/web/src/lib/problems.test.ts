import { describe, expect, it } from "vitest";

import {
  counts,
  emptyNote,
  forPath,
  isSourceFile,
  location,
  revealLine,
  summary,
} from "./problems";
import type { RepositoryProblem } from "./types";

function problem(over: Partial<RepositoryProblem>): RepositoryProblem {
  return {
    path: "src/t.sql",
    line: 3,
    severity: "error",
    message: "syntax error",
    source: "sql",
    ...over,
  };
}

describe("counting", () => {
  it("**keeps errors and warnings apart**", () => {
    // The question the summary answers is "can I commit this and have it
    // publish", and only one of the two numbers bears on it.
    expect(counts([problem({}), problem({ severity: "warning" })])).toEqual({
      errors: 1,
      warnings: 1,
    });
  });

  it("counts an unrecognised severity as a warning rather than an error", () => {
    // Inventing an error the publish will not raise would send somebody
    // looking for a refusal that never comes.
    expect(counts([problem({ severity: "hint" })])).toEqual({ errors: 0, warnings: 1 });
  });
});

describe("the summary", () => {
  it("says an error will refuse a publish", () => {
    expect(summary([problem({})])).toContain("1 error");
    expect(summary([problem({})])).toContain("refuse a publish");
  });

  it("**says warnings alone will not stop anything**", () => {
    // Otherwise a panel with two warnings reads exactly like a panel with two
    // errors, and people learn to ignore both.
    const note = summary([problem({ severity: "warning" }), problem({ severity: "warning" })]);
    expect(note).toContain("2 warnings");
    expect(note).toContain("nothing here will stop a publish");
  });

  it("names both when there are both", () => {
    const note = summary([problem({}), problem({ severity: "warning" })]);
    expect(note).toContain("1 error");
    expect(note).toContain("1 warning");
    expect(note).toContain("refuse a publish");
  });

  it("says so plainly when there is nothing", () => {
    expect(summary([])).toBe("No problems found.");
  });
});

describe("where a problem points", () => {
  it("names the line when there is one", () => {
    expect(location(problem({ line: 12 }))).toBe("src/t.sql:12");
    expect(revealLine(problem({ line: 12 }))).toBe(12);
  });

  it("**does not turn 'nowhere in particular' into line 1**", () => {
    // The reader says 0 when it could not say where. Offering line 1 for that
    // sends somebody to the top of a file for no reason and teaches them the
    // line numbers are decoration.
    expect(location(problem({ line: 0 }))).toBe("src/t.sql");
    expect(revealLine(problem({ line: 0 }))).toBeUndefined();
  });
});

describe("an empty panel", () => {
  it("**tells 'nothing to check' apart from 'nothing wrong'**", () => {
    // The difference matters to somebody wondering whether the panel works at
    // all.
    expect(emptyNote(0)).toContain("nothing to check");
    expect(emptyNote(3)).toBe("No problems found.");
  });
});

describe("which files the panel looks at", () => {
  it("is the two the server checks, and nothing else", () => {
    // A README that reported "declares no transform" would bury the one file
    // that does under a list of files that never claimed to.
    expect(isSourceFile("src/t.sql")).toBe(true);
    expect(isSourceFile("src/t.py")).toBe(true);
    expect(isSourceFile("README.md")).toBe(false);
    expect(isSourceFile(".gitignore")).toBe(false);
    expect(isSourceFile("notes.sql.txt")).toBe(false);
  });
});

describe("per file", () => {
  it("**keeps the server's order rather than imposing one**", () => {
    // The server already orders errors before warnings and then by file and
    // line. Re-sorting a list somebody else has ordered is how two orders
    // start to disagree.
    const all = [
      problem({ path: "src/t.sql", line: 9, message: "second" }),
      problem({ path: "src/other.sql", line: 1 }),
      problem({ path: "src/t.sql", line: 2, message: "first" }),
    ];
    expect(forPath(all, "src/t.sql").map((p) => p.message)).toEqual(["second", "first"]);
  });

  it("returns nothing for a file with nothing wrong", () => {
    expect(forPath([problem({ path: "src/a.sql" })], "src/b.sql")).toEqual([]);
  });
});
