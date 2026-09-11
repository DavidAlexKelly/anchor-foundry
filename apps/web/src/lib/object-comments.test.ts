import { describe, expect, it } from "vitest";

import {
  EMPTY_THREAD,
  authorLabel,
  buttonLabel,
  isEmpty,
  segments,
} from "./object-comments";
import type { ObjectComment } from "./types";

function comment(over: Partial<ObjectComment> = {}): ObjectComment {
  return {
    id: "c-1",
    object_type_id: "t-1",
    instance_id: "i-1",
    author_id: "u-1",
    author_name: "Ada Lovelace",
    author_email: "ada@example.com",
    body: "looks wrong",
    mentions: [],
    attachments: [],
    created_at: "2026-06-01T00:00:00Z",
    ...over,
  };
}

describe("p.137's View comments button", () => {
  it("says how many there are", () => {
    // A button that says nothing about whether there is anything behind it is
    // one people stop pressing — and "has anybody said anything about this"
    // is answerable in the label without opening anything.
    expect(buttonLabel(3)).toBe("3 comments");
  });

  it("counts one in the singular", () => {
    expect(buttonLabel(1)).toBe("1 comment");
  });

  it("invites rather than reporting zero", () => {
    // "0 comments" is a true sentence that reads as a dead end. The button is
    // also how you *add* one.
    expect(buttonLabel(0)).toBe("Comment");
  });
});

describe("an empty thread", () => {
  it("is recognised", () => {
    expect(isEmpty([])).toBe(true);
    expect(isEmpty([comment()])).toBe(false);
  });

  it("teaches the mention syntax", () => {
    // **A feature nobody can discover is one nobody uses.** There is no other
    // place in the product that would teach somebody to type `@`, and p.137
    // names mentions as one of three things this is for.
    expect(EMPTY_THREAD).toContain("@");
  });
});

describe("cutting a comment at its mentions", () => {
  it("marks the span the server named", () => {
    const body = "thanks @Ada Lovelace for this";
    const parts = segments(comment({
      body,
      mentions: [{ user_id: "u-2", label: "Ada Lovelace", start: 7, end: 20 }],
    }));
    expect(parts).toEqual([
      { kind: "text", text: "thanks " },
      { kind: "mention", text: "@Ada Lovelace", userId: "u-2" },
      { kind: "text", text: " for this" },
    ]);
  });

  it("rebuilds the body exactly", () => {
    // **The invariant worth pinning**: however the runs are cut, joining them
    // is the comment. A renderer that dropped or duplicated a character would
    // be changing what somebody said.
    const body = "@Ada Lovelace and @Grace Hopper";
    const parts = segments(comment({
      body,
      mentions: [
        { user_id: "u-2", label: "Ada Lovelace", start: 0, end: 13 },
        { user_id: "u-3", label: "Grace Hopper", start: 18, end: 31 },
      ],
    }));
    expect(parts.map((p) => p.text).join("")).toBe(body);
    expect(parts.filter((p) => p.kind === "mention")).toHaveLength(2);
  });

  it("handles a comment that is nothing but a mention", () => {
    const parts = segments(comment({
      body: "@Ada Lovelace",
      mentions: [{ user_id: "u-2", label: "Ada Lovelace", start: 0, end: 13 }],
    }));
    expect(parts).toEqual([
      { kind: "mention", text: "@Ada Lovelace", userId: "u-2" },
    ]);
  });

  it("is one run of text when nobody is mentioned", () => {
    expect(segments(comment({ body: "just a note" }))).toEqual([
      { kind: "text", text: "just a note" },
    ]);
  });

  it("takes the mentions in position order however they arrive", () => {
    // The server returns them in order; this does not depend on that, because
    // a sort is cheaper than a rule two files apart.
    const body = "@Ada and @Bob";
    const parts = segments(comment({
      body,
      mentions: [
        { user_id: "u-3", label: "Bob", start: 9, end: 13 },
        { user_id: "u-2", label: "Ada", start: 0, end: 4 },
      ],
    }));
    expect(parts.map((p) => p.text).join("")).toBe(body);
    expect(parts[0]).toEqual({ kind: "mention", text: "@Ada", userId: "u-2" });
  });

  it("drops a span that would slice the body into nonsense", () => {
    // Read back out of `jsonb`, so the shape is not guaranteed by a type. A
    // range past the end, or one overlapping the run before it, is dropped
    // rather than allowed to mangle what somebody said — and the body still
    // rebuilds exactly.
    const body = "short";
    for (const bad of [
      { user_id: "u-2", label: "x", start: 0, end: 99 },
      { user_id: "u-2", label: "x", start: -1, end: 2 },
      { user_id: "u-2", label: "x", start: 3, end: 3 },
    ]) {
      const parts = segments(comment({ body, mentions: [bad] }));
      expect(parts.map((p) => p.text).join(""), JSON.stringify(bad)).toBe(body);
    }
  });

  it("drops a mention that overlaps the one before it", () => {
    const body = "@Ada Lovelace";
    const parts = segments(comment({
      body,
      mentions: [
        { user_id: "u-2", label: "Ada Lovelace", start: 0, end: 13 },
        { user_id: "u-3", label: "Ada", start: 1, end: 4 },
      ],
    }));
    expect(parts.map((p) => p.text).join("")).toBe(body);
    expect(parts.filter((p) => p.kind === "mention")).toHaveLength(1);
  });
});

describe("who said it", () => {
  it("uses the name", () => {
    expect(authorLabel(comment())).toBe("Ada Lovelace");
  });

  it("falls back to the address", () => {
    expect(authorLabel(comment({ author_name: null }))).toBe("ada@example.com");
  });

  it("names a departed author as gone rather than as nobody", () => {
    // The comment stays — somebody leaving does not unsay what they said — and
    // a blank byline would read as a bug in the page rather than as a fact
    // about the person.
    const said = authorLabel(
      comment({ author_id: null, author_name: null, author_email: null }),
    );
    expect(said).toBe("Former member");
  });
});
