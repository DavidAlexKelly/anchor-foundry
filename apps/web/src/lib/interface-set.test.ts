import { describe, expect, it } from "vitest";
import { MAX_DEPTH, canPage, depthNote, readSummary } from "./interface-set";

describe("readSummary", () => {
  it("names the types, because that is what an interface did", () => {
    // p.61's argument made readable: the count alone is the less interesting
    // half of "Vehicle, Equipment and Facility answered one question".
    expect(readSummary(12, ["Vehicle", "Equipment", "Facility"])).toBe(
      "12 objects across Vehicle, Equipment and Facility",
    );
  });

  it("reads as a sentence with one type", () => {
    expect(readSummary(3, ["Vehicle"])).toBe("3 objects in Vehicle");
  });

  it("agrees with itself about the singular", () => {
    expect(readSummary(1, ["Vehicle"])).toBe("1 object in Vehicle");
  });

  it("says the count when nothing was read", () => {
    expect(readSummary(0, [])).toBe("0 objects");
  });
});

describe("canPage", () => {
  it("offers a next page while one exists", () => {
    expect(canPage(0, 25, 60)).toEqual({ previous: false, next: true });
  });

  it("offers a previous page once past the first", () => {
    expect(canPage(25, 25, 60).previous).toBe(true);
  });

  it("offers no next page when the whole set is shown", () => {
    expect(canPage(0, 25, 20).next).toBe(false);
  });

  it("stops at the ceiling even though more objects match", () => {
    // §214: the server refuses past `MAX_DEPTH`, so a Next button here would
    // be a control whose only outcome is a refusal.
    expect(canPage(MAX_DEPTH - 25, 25, 500).next).toBe(false);
    // And the page below it still offers one, which is what stops this
    // passing against a `canPage` that never offers anything.
    expect(canPage(0, 25, 500).next).toBe(true);
  });
});

describe("depthNote", () => {
  it("says nothing when the whole set is on screen", () => {
    expect(depthNote(0, 25, 20)).toBeNull();
  });

  it("says nothing while a next page is still on offer", () => {
    expect(depthNote(0, 25, 60)).toBeNull();
  });

  it("explains the ceiling rather than letting the button vanish", () => {
    const note = depthNote(MAX_DEPTH - 25, 25, 500);
    expect(note).toContain(String(MAX_DEPTH));
    expect(note).toContain("500");
  });
});
