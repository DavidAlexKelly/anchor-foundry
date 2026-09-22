/** Renaming a dataset (§435; `dataset-preview` p.2). */
import { describe, expect, it } from "vitest";
import {
  MAX_NAME,
  NOTHING_NAMES_IT,
  fileHref,
  nameToSend,
  renameProblem,
} from "./dataset-rename";

describe("the maximum", () => {
  it("is the column's own limit", () => {
    // **A literal, not `MAX_NAME` compared to itself.** The number is a
    // promise about `datasets.name text CHECK (length BETWEEN 1 AND 200)` —
    // a browser rule that drifted below it would refuse names the server
    // accepts, which is the browser inventing a rule of its own (§191).
    expect(MAX_NAME).toBe(200);
  });
});

describe("renameProblem", () => {
  it("allows a different, non-empty name", () => {
    expect(renameProblem("orders", "daily_orders")).toBe(null);
  });

  it("refuses an empty name", () => {
    expect(renameProblem("orders", "")).toContain("needs a name");
    expect(renameProblem("orders", "   ")).toContain("needs a name");
  });

  it("refuses the name it already has", () => {
    // A live button that sent a request changing nothing and reported success
    // teaches a reader that the button does nothing.
    expect(renameProblem("orders", "orders")).toContain("already its name");
  });

  it("treats a name that only gained spaces as unchanged", () => {
    expect(renameProblem("orders", "  orders  ")).toContain("already its name");
  });

  it("refuses a name longer than the column", () => {
    const long = "x".repeat(MAX_NAME + 1);
    const said = renameProblem("orders", long);
    expect(said).toContain(String(MAX_NAME));
    expect(said).toContain(String(MAX_NAME + 1));
  });

  it("allows a name of exactly the maximum", () => {
    // The boundary the database allows, and an off-by-one here would refuse a
    // name the server accepts — a browser inventing a rule of its own.
    expect(renameProblem("orders", "x".repeat(MAX_NAME))).toBe(null);
  });
});

describe("nameToSend", () => {
  it("trims", () => {
    // A trailing space is invisible on a screen and very visible in a
    // `-- input:` line that has to match it exactly.
    expect(nameToSend("  daily_orders ")).toBe("daily_orders");
  });

  it("leaves an inner space alone", () => {
    expect(nameToSend(" Daily Orders ")).toBe("Daily Orders");
  });
});

describe("fileHref", () => {
  it("links to the file on the branch it was found on", () => {
    expect(fileHref({ resource_id: "r-1", branch: "main", path: "src/t.sql" }))
      .toBe("/r/r-1?tab=files&branch=main&file=src%2Ft.sql");
  });

  it("escapes a branch name that needs it", () => {
    expect(fileHref({ resource_id: "r-1", branch: "feat/one", path: "a.sql" }))
      .toContain("branch=feat%2Fone");
  });
});

describe("the sentence for a dataset nothing names", () => {
  it("says renaming is safe rather than saying nothing", () => {
    // A warning that appears only sometimes is one a reader learns to look
    // for; its absence has to mean something too.
    expect(NOTHING_NAMES_IT).toContain("breaks nothing");
  });
});
