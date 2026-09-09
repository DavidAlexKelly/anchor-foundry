import { describe, expect, it } from "vitest";

import {
  authoredInRepository,
  authoringSummary,
  canAdopt,
  canEditBody,
  pathProblem,
  readOnlyReason,
} from "./model-authoring";

const direct = { source_repo_id: null, source_path: null };
const adopted = { source_repo_id: "r-1", source_path: "src/daily.sql" };

describe("where a transform is authored", () => {
  it("is a repository only when both halves are there", () => {
    expect(authoredInRepository(direct)).toBe(false);
    expect(authoredInRepository(adopted)).toBe(true);
  });

  it("does not trust the repository id on its own", () => {
    // db 0038 holds the two together with a CHECK constraint, so in the
    // database one implies the other. This is a browser reading JSON, where
    // the constraint is not present — and a model with a repository and no
    // path would render "authored at undefined" and link to nowhere.
    expect(authoredInRepository({ source_repo_id: "r-1", source_path: null })).toBe(false);
    expect(authoredInRepository({ source_repo_id: null, source_path: "src/x.sql" })).toBe(false);
  });
});

describe("what the screen may offer", () => {
  it("does not offer to edit the body of a repository-authored transform", () => {
    // The defect this module exists for. `ModelOut` has carried
    // `source_repo_id` since §94 and the shared type did not, so the page
    // showed an editable body and a Save button the server refuses.
    expect(canEditBody(direct)).toBe(true);
    expect(canEditBody(adopted)).toBe(false);
  });

  it("offers adoption exactly once", () => {
    expect(canAdopt(direct)).toBe(true);
    expect(canAdopt(adopted)).toBe(false);
  });

  it("names the file in the reason, because that is where the reader is going", () => {
    expect(readOnlyReason(direct)).toBeNull();
    const reason = readOnlyReason(adopted);
    expect(reason).toContain("src/daily.sql");
    // And says why rather than only that: "read-only" alone reads as a
    // permission problem, which sends the reader to an administrator.
    expect(reason).toContain("publish");
  });

  it("summarises both states in a sentence a header can hold", () => {
    expect(authoringSummary(direct)).toBe("Authored here");
    expect(authoringSummary(adopted)).toContain("src/daily.sql");
  });
});

describe("the path box", () => {
  it("treats empty as 'you choose'", () => {
    // Deliberately not a second copy of the server's slugify rule (§191): two
    // copies agree until one changes, and the disagreement would be a file
    // written where the screen did not predict.
    expect(pathProblem("", "sql")).toBeNull();
    expect(pathProblem("   ", "python")).toBeNull();
  });

  it("refuses an extension that does not match the language", () => {
    // Publishing reads the language off the path, so a Python transform in a
    // .sql file would come back as SQL and be handed to DuckDB.
    expect(pathProblem("src/thing.sql", "python")).toContain(".py");
    expect(pathProblem("src/thing.py", "sql")).toContain(".sql");
    expect(pathProblem("src/thing.py", "python")).toBeNull();
    expect(pathProblem("src/thing.sql", "sql")).toBeNull();
  });

  it("refuses a path that climbs out of the repository", () => {
    expect(pathProblem("/src/thing.sql", "sql")).toContain("without a leading slash");
    expect(pathProblem("../thing.sql", "sql")).toContain("inside the repository");
  });

  it("accepts a nested path, because a repository may have a layout", () => {
    expect(pathProblem("transforms/daily/orders.sql", "sql")).toBeNull();
  });
});
