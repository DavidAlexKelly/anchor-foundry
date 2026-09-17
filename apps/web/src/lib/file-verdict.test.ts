/** What each reviewer thinks of one file (§366; `code-repositories` p.55). */
import { describe, expect, it } from "vitest";
import { fileState, markRequest, myMark, othersSay } from "./file-verdict";

const ME = "me-1";
const mine = (verdict?: string | null) => ({
  reviewer_id: ME, reviewer_email: "me@x", verdict,
});
const theirs = (id: string, email: string | null, verdict?: string | null) => ({
  reviewer_id: id, reviewer_email: email, verdict,
});

describe("my own mark", () => {
  it("is mine and not somebody else's", () => {
    // The distinction the surface got wrong: "has anyone read this" was being
    // used to decide what to offer *me*.
    expect(myMark([theirs("them", "ada@x")], ME)).toBeUndefined();
    expect(myMark([theirs("them", "ada@x"), mine()], ME)?.reviewer_id).toBe(ME);
  });

  it("is nobody's when I am not known yet", () => {
    // The current user arrives from a query, so "not loaded" has to read as
    // "no mark" rather than matching the first row. Carried by the comparison
    // itself rather than by a guard — an explicit `if (!myId)` was written
    // here and deleted, because no mutant could make it matter.
    expect(myMark([mine(), theirs("them", "ada@x")], undefined)).toBeUndefined();
    expect(fileState([mine("approved")], undefined)).toBe("unread");
  });
});

describe("where I have got to", () => {
  it("is unread when I have not marked it", () => {
    expect(fileState([theirs("them", "ada@x", "approved")], ME)).toBe("unread");
  });

  it("is read when I marked it without a verdict", () => {
    expect(fileState([mine(null)], ME)).toBe("read");
  });

  it("is the verdict when I gave one", () => {
    expect(fileState([mine("approved")], ME)).toBe("approved");
    expect(fileState([mine("rejected")], ME)).toBe("rejected");
  });

  it("does not trust a verdict it does not know", () => {
    // A value this build has never heard of must not be drawn as a pressed
    // control it cannot undo; read is the safe reading of "marked, somehow".
    expect(fileState([mine("maybe")], ME)).toBe("read");
  });
});

describe("what everybody else said", () => {
  it("names a verdict and who gave it", () => {
    expect(othersSay([theirs("a", "ada@x", "rejected")], ME)).toBe("ada@x rejected");
  });

  it("counts the ones who only read it", () => {
    const said = othersSay([theirs("a", "ada@x"), theirs("b", "bo@x")], ME);
    expect(said).toBe("2 others have read it");
  });

  it("is singular for one silent reader", () => {
    expect(othersSay([theirs("a", "ada@x")], ME)).toBe("1 other has read it");
  });

  it("leaves me out of it", () => {
    // The controls beside this line already show my own state; repeating it
    // makes a summary of other people something to subtract myself from.
    expect(othersSay([mine("approved")], ME)).toBe("");
  });

  it("says nothing when nobody else has", () => {
    expect(othersSay([], ME)).toBe("");
  });

  it("has a word for a reviewer with no email", () => {
    expect(othersSay([theirs("a", null, "approved")], ME)).toBe("someone approved");
  });
});

describe("what a press sends", () => {
  it("marks a file read from unread", () => {
    expect(markRequest("unread", "read")).toEqual({ read: true });
  });

  it("gives a verdict from unread in one press", () => {
    // Approving a file you have not marked should not need two clicks — the
    // verdict implies having read it.
    expect(markRequest("unread", "approved")).toEqual({ read: true, verdict: "approved" });
  });

  it("changes a verdict without passing through unread", () => {
    expect(markRequest("approved", "rejected")).toEqual({ read: true, verdict: "rejected" });
  });

  it("clears by pressing what is already pressed", () => {
    // The only way back to unread without a fourth button, and it matters: a
    // verdict you did not mean to give is worse than none.
    expect(markRequest("approved", "approved")).toEqual({ read: false });
    expect(markRequest("read", "read")).toEqual({ read: false });
  });

  it("drops a verdict by pressing read", () => {
    expect(markRequest("approved", "read")).toEqual({ read: true });
  });
});
