/** Filtering the Pull requests tab (§429; `code-repositories` p.18). */
import { describe, expect, it } from "vitest";
import type { CodeProposal } from "./types";
import {
  BUCKETS,
  BUCKET_LABELS,
  DEFAULT_BUCKET,
  bucketOf,
  filtered,
  matches,
  searchEmptyNote,
  switchLabel,
} from "./proposal-filters";

const proposal = (over: Partial<CodeProposal> = {}): CodeProposal => ({
  id: "p1",
  project_id: "proj",
  source_repo_id: "repo",
  source_commit_id: "c0ffee00",
  summary: "Publish main (c0ffee00)",
  description: "",
  state: "open",
  change_set_id: null,
  created_by: "u1",
  created_by_email: "ada@acme.dev.local",
  created_at: "2026-01-01T00:00:00Z",
  files_updated_at: "2026-01-01T00:00:00Z",
  file_count: 0,
  ...over,
});

describe("bucketOf", () => {
  it("puts an open proposal in Open", () => {
    expect(bucketOf("open")).toBe("open");
  });

  it("puts both endings in Closed", () => {
    // Two buckets over three states: how it ended is on the row, not in the
    // button. A bucket that meant `applied` would hide every withdrawal.
    expect(bucketOf("applied")).toBe("closed");
    expect(bucketOf("withdrawn")).toBe("closed");
  });

  it("has a label for every bucket", () => {
    expect(BUCKETS.map((b) => BUCKET_LABELS[b])).toEqual(["Open", "Closed"]);
  });

  it("starts on Open", () => {
    // The list somebody wants on arriving is the one with work in it.
    expect(DEFAULT_BUCKET).toBe("open");
  });
});

describe("matches", () => {
  const p = proposal({ summary: "Publish orders", created_by_email: "ada@acme.dev.local" });

  it("matches a word in the title", () => {
    expect(matches(p, "orders")).toBe(true);
  });

  it("matches the middle of the title", () => {
    expect(matches(p, "rder")).toBe(true);
  });

  it("matches the author", () => {
    expect(matches(p, "ada")).toBe(true);
  });

  it("matches the author's domain, because that is on the row too", () => {
    expect(matches(p, "acme")).toBe(true);
  });

  it("ignores case on both sides", () => {
    expect(matches(p, "ORDERS")).toBe(true);
    expect(matches(proposal({ summary: "ORDERS" }), "orders")).toBe(true);
  });

  it("ignores the space a reader leaves behind", () => {
    expect(matches(p, "  orders  ")).toBe(true);
  });

  it("matches everything on a blank query", () => {
    expect(matches(p, "")).toBe(true);
    expect(matches(p, "   ")).toBe(true);
  });

  it("does not match the description", () => {
    // p.18 names title and author. A row that matched on text the reader
    // cannot see is a result they cannot account for.
    expect(matches(proposal({ description: "about widgets" }), "widgets")).toBe(false);
  });

  it("survives an author nobody knows", () => {
    // `created_by_email` is null for a user that has been removed.
    expect(matches(proposal({ created_by_email: null }), "ada")).toBe(false);
    expect(matches(proposal({ created_by_email: null }), "")).toBe(true);
  });

  it("does not match on the id", () => {
    expect(matches(proposal({ id: "abc123" }), "abc123")).toBe(false);
  });
});

describe("filtered", () => {
  const rows = [
    proposal({ id: "a", summary: "Publish orders", created_by_email: "ada@acme.dev.local" }),
    proposal({ id: "b", summary: "Publish returns", created_by_email: "grace@acme.dev.local" }),
    proposal({ id: "c", summary: "Fix orders join", created_by_email: "grace@acme.dev.local" }),
  ];

  it("keeps the matching rows", () => {
    expect(filtered(rows, "orders").map((p) => p.id)).toEqual(["a", "c"]);
  });

  it("keeps the order it was given", () => {
    // The list arrives newest first, and a search is a narrowing rather than
    // a re-sort: rows that jumped around as somebody typed would be unreadable.
    expect(filtered(rows, "grace").map((p) => p.id)).toEqual(["b", "c"]);
  });

  it("keeps everything on a blank query", () => {
    expect(filtered(rows, "").map((p) => p.id)).toEqual(["a", "b", "c"]);
  });

  it("is empty when nothing matches", () => {
    expect(filtered(rows, "zzz")).toEqual([]);
  });
});

describe("searchEmptyNote", () => {
  it("says nothing while the search is finding things", () => {
    expect(searchEmptyNote("orders", 2, 0, "open")).toBe(null);
  });

  it("says nothing when the query is blank", () => {
    // The bucket's own empty state says where a repository's proposals are,
    // which is a better sentence than one about a search nobody ran.
    expect(searchEmptyNote("", 0, 3, "open")).toBe(null);
    expect(searchEmptyNote("   ", 0, 3, "open")).toBe(null);
  });

  it("names the query, so a typo is visible", () => {
    expect(searchEmptyNote("ordrs", 0, 0, "open")).toContain("ordrs");
  });

  it("does not show the space a reader left behind", () => {
    expect(searchEmptyNote("ordrs ", 0, 0, "open"))
      .toBe(searchEmptyNote("ordrs", 0, 0, "open"));
  });

  it("points at the other bucket when the answer is there", () => {
    const note = searchEmptyNote("orders", 0, 3, "open")!;
    expect(note).toContain("3 closed proposals match");
  });

  it("counts one in the singular", () => {
    expect(searchEmptyNote("orders", 0, 1, "open")).toContain("1 closed proposal matches");
  });

  it("does not mention a place with nothing in it", () => {
    expect(searchEmptyNote("orders", 0, 0, "open")).not.toContain("closed proposal");
  });

  it("points the other way from the closed list", () => {
    expect(searchEmptyNote("orders", 0, 2, "closed")).toContain("2 open proposals match");
  });

  it("says which list it searched", () => {
    // "Nothing matches" over a bucket the reader cannot see named is how
    // somebody concludes a proposal was deleted.
    expect(searchEmptyNote("orders", 0, 0, "closed")).toContain("closed");
    expect(searchEmptyNote("orders", 0, 0, "open")).toContain("open");
  });
});

describe("switchLabel", () => {
  it("offers the other bucket when it has matches", () => {
    expect(switchLabel(3, "open")).toBe("Search closed proposals");
    expect(switchLabel(1, "closed")).toBe("Search open proposals");
  });

  it("offers nothing when there is nothing there", () => {
    // A button that switched to an empty list would be a control that looks
    // like it works (§214).
    expect(switchLabel(0, "open")).toBe(null);
  });
});
