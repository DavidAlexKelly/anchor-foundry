import { describe, expect, it } from "vitest";

import { editedAgo } from "./recently-edited";

const NOW = Date.parse("2026-06-15T12:00:00Z");

function ago(ms: number): string {
  return editedAgo(new Date(NOW - ms).toISOString(), NOW);
}

describe("how long ago a quick link was edited", () => {
  it("says just now rather than a number of seconds", () => {
    // Seconds are noise on a list nobody is timing.
    expect(ago(0)).toBe("just now");
    expect(ago(59_000)).toBe("just now");
  });

  it("counts minutes, then hours, then days", () => {
    // The largest unit that still reads as a whole number, so a reader never
    // divides in their head.
    expect(ago(60_000)).toBe("1 minute ago");
    expect(ago(4 * 60_000)).toBe("4 minutes ago");
    expect(ago(60 * 60_000)).toBe("1 hour ago");
    expect(ago(3 * 60 * 60_000)).toBe("3 hours ago");
    expect(ago(24 * 60 * 60_000)).toBe("1 day ago");
    expect(ago(2 * 24 * 60 * 60_000)).toBe("2 days ago");
  });

  it("switches to a date after a week", () => {
    // "23 days ago" is a number a reader has to do arithmetic on; a date is
    // one they can match against something they remember.
    const said = ago(30 * 24 * 60 * 60_000);
    expect(said).not.toContain("ago");
    expect(said).toContain("2026");
  });

  it("keeps the boundary on the right side", () => {
    // Six days is still relative; seven is not. Asserted because an
    // off-by-one here shows up as one row reading differently from the rest
    // and nothing else.
    expect(ago(6 * 24 * 60 * 60_000)).toBe("6 days ago");
    expect(ago(7 * 24 * 60 * 60_000)).not.toContain("ago");
  });

  it("reads a future timestamp as just now", () => {
    // The server writes `now()` in Postgres and the browser compares against
    // its own clock. A row a second ahead is that disagreement, not an edit
    // that has not happened yet — and "in -1 minutes" would be a bug report
    // about something that is working.
    expect(ago(-5_000)).toBe("just now");
    expect(ago(-60 * 60_000)).toBe("just now");
  });

  it("says nothing at all when the timestamp is not one", () => {
    // A row whose time cannot be read is still a usable link; an "Invalid
    // Date" beside it is not.
    expect(editedAgo("not a date", NOW)).toBe("");
    expect(editedAgo("", NOW)).toBe("");
  });
});
