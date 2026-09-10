import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DRAFT_LIMIT_BYTES,
  clearDrafts,
  discardQuestion,
  draftKey,
  readDrafts,
  saveWarning,
  writeDrafts,
} from "./editor-drafts";

/** A `localStorage` this test owns, so the cases below can make it misbehave. */
function fakeStorage() {
  const map = new Map<string, string>();
  return {
    map,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
  };
}

beforeEach(() => {
  vi.stubGlobal("window", { localStorage: fakeStorage() });
});
afterEach(() => vi.unstubAllGlobals());

describe("the key", () => {
  it("**separates branches**, because the same path on two is two files", () => {
    // A draft that followed somebody across a branch switch would paste one
    // branch's work onto another's, which is the one outcome worse than
    // losing it.
    expect(draftKey("r-1", "main")).not.toBe(draftKey("r-1", "sandbox"));
    expect(draftKey("r-1", "main")).not.toBe(draftKey("r-2", "main"));
  });

  it("survives a branch name holding the separator", () => {
    // Git refs can hold dots and slashes; nothing parses this key back out,
    // which is why the branch goes last.
    const key = draftKey("r-1", "feature/a.b:c");
    expect(key).toContain("feature/a.b:c");
    expect(readDrafts(key)).toEqual({});
  });
});

describe("round trip", () => {
  it("keeps a draft, including a deletion", () => {
    const key = draftKey("r-1", "main");
    // `null` is a real value: it is how the editor records a deleted file.
    expect(writeDrafts(key, { "a.sql": "SELECT 1", "b.sql": null })).toBe("saved");
    expect(readDrafts(key)).toEqual({ "a.sql": "SELECT 1", "b.sql": null });
  });

  it("**removes the key for an empty map rather than storing `{}`**", () => {
    const key = draftKey("r-1", "main");
    writeDrafts(key, { "a.sql": "x" });
    expect(writeDrafts(key, {})).toBe("cleared");
    // A repository somebody edited and then reverted leaves nothing behind,
    // so "has drafts" stays answerable by the presence of a key.
    expect(window.localStorage.getItem(key)).toBeNull();
  });

  it("clears on request", () => {
    const key = draftKey("r-1", "main");
    writeDrafts(key, { "a.sql": "x" });
    clearDrafts(key);
    expect(readDrafts(key)).toEqual({});
  });
});

describe("everything unreadable is 'no drafts'", () => {
  it("survives absent, corrupt, and wrongly-shaped values", () => {
    // An editor that opened with half a draft in it would be worse than one
    // that opened clean.
    const key = draftKey("r-1", "main");
    expect(readDrafts(key)).toEqual({});

    window.localStorage.setItem(key, "{not json");
    expect(readDrafts(key)).toEqual({});

    window.localStorage.setItem(key, '["a.sql"]');
    expect(readDrafts(key)).toEqual({});

    window.localStorage.setItem(key, "null");
    expect(readDrafts(key)).toEqual({});
  });

  it("drops entries that are not a draft, and keeps the ones that are", () => {
    const key = draftKey("r-1", "main");
    window.localStorage.setItem(
      key,
      JSON.stringify({ "a.sql": "SELECT 1", "b.sql": 42, "c.sql": null }),
    );
    expect(readDrafts(key)).toEqual({ "a.sql": "SELECT 1", "c.sql": null });
  });

  it("**does not throw when storage itself throws**", () => {
    // A private window, or a browser set to block site data, throws on
    // *access* rather than returning null. A draft store that took the editor
    // down with it would cost more than it saves.
    vi.stubGlobal("window", {
      get localStorage(): Storage {
        throw new Error("blocked");
      },
    });
    expect(readDrafts("k")).toEqual({});
    expect(writeDrafts("k", { "a.sql": "x" })).toBe("unavailable");
    expect(() => clearDrafts("k")).not.toThrow();
  });
});

describe("the size cap", () => {
  it("refuses rather than attempting a write that would blow the quota", () => {
    // A quota error arrives *after* the write is attempted and takes the whole
    // key with it, losing drafts that were previously safe. A refusal keeps
    // what is stored and can be reported.
    const key = draftKey("r-1", "main");
    writeDrafts(key, { "small.sql": "SELECT 1" });
    expect(writeDrafts(key, { "big.sql": "x".repeat(DRAFT_LIMIT_BYTES + 1) })).toBe(
      "too-large",
    );
    expect(readDrafts(key)).toEqual({ "small.sql": "SELECT 1" });
  });

  it("**counts bytes, not characters**", () => {
    // A file of CJK or accented text is two to three times its length once
    // encoded, and a cap that counted characters would let through what the
    // quota then refuses.
    const key = draftKey("r-1", "main");
    const chars = Math.floor(DRAFT_LIMIT_BYTES / 2);
    expect(writeDrafts(key, { "a.sql": "あ".repeat(chars) })).toBe("too-large");
  });
});

describe("what to tell somebody", () => {
  it("warns only when work is actually at risk", () => {
    // Narrating a successful save would train people to ignore the line that
    // matters.
    expect(saveWarning("saved")).toBeNull();
    expect(saveWarning("cleared")).toBeNull();
    expect(saveWarning("too-large")).toContain("too large");
    expect(saveWarning("unavailable")).toContain("not storing drafts");
  });

  it("says what will happen rather than what went wrong", () => {
    // "will be lost if you reload before committing" is actionable; "storage
    // error" is not.
    expect(saveWarning("unavailable")).toContain("reload before committing");
    expect(saveWarning("too-large")).toContain("reload before committing");
  });
});

describe("discarding", () => {
  it("**counts the files, because the answer depends on it**", () => {
    // "Discard your changes?" and "discard changes to 7 files?" are answered
    // differently by the same person.
    expect(discardQuestion(1)).toContain("1 file?");
    expect(discardQuestion(7)).toContain("7 files?");
  });

  it("**says it cannot be undone**, because it cannot", () => {
    // Drafts persist, so what is being thrown away may be days of work rather
    // than this session's - and the button sits beside the one that saves it.
    expect(discardQuestion(2)).toContain("cannot be undone");
    expect(discardQuestion(2)).toContain("not saved anywhere else");
  });
});
