import { describe, expect, it } from "vitest";
import { highlight } from "./ontology-highlight";

/** The rendered form, so a test reads like what somebody sees. */
function render(parts: (string | { mark: string })[]): string {
  return parts.map((p) => (typeof p === "string" ? p : `[${p.mark}]`)).join("");
}

describe("highlight", () => {
  it("marks the query inside the matched value", () => {
    expect(render(highlight("Ticket status", "status"))).toBe("Ticket [status]");
  });

  it("marks case-insensitively, keeping the value's own casing", () => {
    // The mark has to land on what is *there*, not on what was typed — a
    // highlight that rewrote "Status" as "status" would be editing the answer.
    expect(render(highlight("Status", "sta"))).toBe("[Sta]tus");
  });

  it("marks the first occurrence only", () => {
    expect(render(highlight("status of status", "status"))).toBe("[status] of status");
  });

  it("leaves the value alone when the query is not in it", () => {
    // Reachable: the server matched some *other* field of the same row and
    // this is drawing that one. Marking nothing is right; throwing or marking
    // the whole string would both be worse.
    expect(render(highlight("Ticket", "status"))).toBe("Ticket");
  });

  it("leaves the value alone for a blank query", () => {
    expect(render(highlight("Ticket", "   "))).toBe("Ticket");
  });

  it("drops empty segments so nothing renders an empty node", () => {
    expect(highlight("status", "status")).toEqual([{ mark: "status" }]);
  });

  it("ignores surrounding whitespace in the query", () => {
    expect(render(highlight("Ticket status", " status "))).toBe("Ticket [status]");
  });
});
