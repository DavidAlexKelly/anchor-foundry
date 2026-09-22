import { describe, expect, it } from "vitest";

import {
  README_PATH, emptyReason, fileHref, linkify, mentionedResources, readmeFrom,
} from "./readme";

const ID = "aabbccdd-1122-3344-5566-77889900aabb";
const OTHER = "11111111-2222-3333-4444-555555555555";
const REPO = "repo-1";

const link = (source: string, names: Record<string, string> = {}) =>
  linkify(source, { repositoryId: REPO, names });

describe("readmeFrom", () => {
  it("finds the file p.67 names", () => {
    expect(readmeFrom({ [README_PATH]: "# Hello" })).toBe("# Hello");
  });

  it("answers null when there is none", () => {
    expect(readmeFrom({})).toBeNull();
    expect(readmeFrom({ "src/a.sql": "SELECT 1" })).toBeNull();
  });

  it("is the one at the root, by the name p.67 gives", () => {
    // Two documentation pages and no way to say which is shown is worse than
    // one that has to be spelled correctly.
    expect(readmeFrom({ "docs/README.md": "# Hello" })).toBeNull();
    expect(readmeFrom({ "readme.md": "# Hello" })).toBeNull();
  });

  it("keeps an empty README as an empty README", () => {
    // Present and blank is not the same as absent: one is a file somebody
    // made, and the empty-state sentence would be wrong about it.
    expect(readmeFrom({ [README_PATH]: "" })).toBe("");
  });
});

describe("linkify — p.68's repo:// protocol", () => {
  it("turns a path into a link that opens the file", () => {
    expect(link("see repo://transforms/daily.sql for the logic")).toBe(
      `see [transforms/daily.sql](/r/${REPO}?tab=files&file=transforms%2Fdaily.sql)`
      + " for the logic",
    );
  });

  it("stops the path at the end of the sentence", () => {
    // Without a bound the link swallows the rest of the line, which is how a
    // README's prose disappears into an href.
    expect(link("(repo://a/b.sql)")).toContain("[a/b.sql]");
    expect(link("(repo://a/b.sql)")).toContain(")");
    expect(link("repo://a/b.sql and more")).toContain(" and more");
  });

  it("links every mention, not only the first", () => {
    const out = link("repo://a.sql and repo://b.sql");
    expect(out).toContain("[a.sql]");
    expect(out).toContain("[b.sql]");
  });
});

describe("linkify — p.68's pasted resource ids", () => {
  it("links an id by its name where the name is known", () => {
    expect(link(`built from ${ID}`, { [ID]: "Orders" }))
      .toBe(`built from [Orders](/r/${ID})`);
  });

  it("links an id that could not be named rather than leaving it bare", () => {
    // A reference that rendered as text because a lookup failed reads as a
    // typo rather than as a resource somebody cannot see.
    expect(link(`built from ${ID}`)).toBe(`built from [${ID}](/r/${ID})`);
  });

  it("matches the name case-insensitively against the id as written", () => {
    expect(link(`from ${ID.toUpperCase()}`, { [ID]: "Orders" }))
      .toContain("[Orders]");
  });

  it("leaves an id inside a longer token alone", () => {
    // A filename or an href that already contains one is not a reference.
    expect(link(`/r/${ID}x`)).toBe(`/r/${ID}x`);
    expect(link(`${ID}-old`)).toBe(`${ID}-old`);
  });

  it("is not fooled by something that only looks like an id", () => {
    expect(link("aabbccdd-1122-3344-5566-77889900aabz")).not.toContain("](/r/");
    expect(link("aabbccdd-1122-3344-5566")).not.toContain("](/r/");
  });
});

describe("linkify — the two forms do not rewrite each other", () => {
  it("does not turn the repository id inside a repo:// link into a link", () => {
    // **The defect the browser suite found.** A repository id *is* a resource
    // id, so a second pass rewrote the href the first pass had just written
    // and produced a link nested inside a link, pointing nowhere. The two
    // forms are one alternation now, and one pass cannot see its own output.
    const out = linkify("see repo://a.sql", { repositoryId: ID });
    expect(out).toBe(`see [a.sql](/r/${ID}?tab=files&file=a.sql)`);
    expect(out).not.toContain("](/r/" + ID + ")");
  });

  it("still links a resource id written after a repo:// path", () => {
    const out = linkify(`repo://a.sql writes ${OTHER}`, { repositoryId: ID });
    expect(out).toContain("[a.sql]");
    expect(out).toContain(`[${OTHER}](/r/${OTHER})`);
  });
});

describe("linkify — code is left alone", () => {
  it("does not rewrite inside a fenced block", () => {
    // p.67's own page is a document that contains these examples.
    const source = "```\nrepo://a.sql\n```";
    expect(link(source)).toBe(source);
  });

  it("does not rewrite inside a tilde fence", () => {
    const source = "~~~\nrepo://a.sql\n~~~";
    expect(link(source)).toBe(source);
  });

  it("does not rewrite inside an inline span", () => {
    expect(link("write `repo://a.sql` to link a file"))
      .toBe("write `repo://a.sql` to link a file");
    expect(link(`paste \`${ID}\` to link a resource`))
      .toBe(`paste \`${ID}\` to link a resource`);
  });

  it("still rewrites the prose around the code", () => {
    // The failure the other way: a README with one example must not lose every
    // real link in it.
    const out = link("see `repo://a.sql`, or repo://b.sql");
    expect(out).toContain("`repo://a.sql`");
    expect(out).toContain("[b.sql]");
  });

  it("does not let an inline rule reach into a fenced block", () => {
    // A fence may contain backticks; a span may not contain a newline. Doing
    // the spans first would pair a backtick inside the fence with one after it.
    const source = "```\nconst a = `x`;\nrepo://a.sql\n```\nrepo://b.sql";
    const out = link(source);
    expect(out).toContain("const a = `x`;\nrepo://a.sql");
    expect(out).toContain("[b.sql]");
  });
});

describe("mentionedResources", () => {
  it("lists each id once, however often it appears", () => {
    expect(mentionedResources(`${ID} then ${OTHER} then ${ID}`))
      .toEqual([ID, OTHER]);
  });

  it("is empty when the README mentions none", () => {
    expect(mentionedResources("# Hello")).toEqual([]);
  });

  it("folds case, so one resource is asked about once", () => {
    expect(mentionedResources(`${ID} and ${ID.toUpperCase()}`)).toEqual([ID]);
  });
});

describe("fileHref", () => {
  it("encodes the path so a folder does not end the query", () => {
    expect(fileHref("r1", "a/b.sql")).toBe("/r/r1?tab=files&file=a%2Fb.sql");
  });
});

describe("emptyReason", () => {
  it("names the file and where to make it", () => {
    expect(emptyReason()).toContain(README_PATH);
    expect(emptyReason()).toContain("Files");
  });
});
