import { describe, expect, it } from "vitest";
import {
  BADGE_CAP, badgeLabel, isUnread, safeNotificationLink,
} from "./notifications";

describe("badgeLabel", () => {
  it("says nothing when there is nothing to say", () => {
    // A badge showing zero is a mark on every screen meaning "nothing has
    // happened", which is the one message it does not need to deliver.
    expect(badgeLabel(0)).toBeNull();
    expect(badgeLabel(-1)).toBeNull();
  });

  it("counts while counting is useful", () => {
    expect(badgeLabel(1)).toBe("1");
    expect(badgeLabel(BADGE_CAP)).toBe(String(BADGE_CAP));
  });

  it("stops counting before the badge changes width", () => {
    // Somebody with 47 unread and somebody with 9+ do the same thing next.
    expect(badgeLabel(BADGE_CAP + 1)).toBe(`${BADGE_CAP}+`);
    expect(badgeLabel(4700)).toBe(`${BADGE_CAP}+`);
  });
});

describe("safeNotificationLink", () => {
  it("follows a path inside this app", () => {
    expect(safeNotificationLink("/objects/A-1")).toBe("/objects/A-1");
  });

  it("refuses an absolute URL", () => {
    // **The reason this rule exists.** p.92's triple handlebars make the URL a
    // template, so part of it comes from a property value, which comes from a
    // dataset. A notification is the one surface here where somebody else's
    // data is rendered as a control the recipient is invited to click.
    expect(safeNotificationLink("https://evil.example/steal")).toBeNull();
  });

  it("refuses a protocol-relative host", () => {
    // The browser reads `//host` as a host, not as a path — which is what
    // makes it the version that slips past a naive "starts with a slash".
    expect(safeNotificationLink("//evil.example/steal")).toBeNull();
  });

  it("refuses a javascript: url", () => {
    expect(safeNotificationLink("javascript:alert(1)")).toBeNull();
  });

  it("has nothing to say about a notification with no link", () => {
    expect(safeNotificationLink(null)).toBeNull();
    expect(safeNotificationLink(undefined)).toBeNull();
    expect(safeNotificationLink("")).toBeNull();
  });
});

describe("isUnread", () => {
  it("is about the timestamp being absent, not falsy", () => {
    expect(isUnread({ read_at: null })).toBe(true);
    expect(isUnread({ read_at: "2026-01-01T00:00:00Z" })).toBe(false);
  });
});
