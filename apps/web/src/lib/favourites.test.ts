import { describe, expect, it } from "vitest";

import {
  canShowStar,
  emptyReason,
  rowLabel,
  rowSubtitle,
  starGlyph,
  starLabel,
} from "./favourites";
import type { ObjectFavourite } from "./types";

function favourite(over: Partial<ObjectFavourite> = {}): ObjectFavourite {
  return {
    id: "f-1",
    object_type_id: "t-1",
    object_type_name: "Ship",
    instance_id: "i-1",
    label: "IMO 9074729",
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("the star", () => {
  it("says what pressing it does, not what the state is", () => {
    // "Favourite" leaves somebody working out whether that is a description
    // or an instruction.
    expect(starLabel(false)).toBe("Add to favourites");
    expect(starLabel(true)).toBe("Remove from favourites");
  });

  it("is filled once it is kept", () => {
    expect(starGlyph(true)).toBe("★");
    expect(starGlyph(false)).toBe("☆");
  });

  it("is not drawn while the answer is unknown", () => {
    // An unfilled star means "not a favourite", so drawing one before the
    // server has said would tell somebody their shortcut is gone — and the
    // press that follows would remove one they still had.
    expect(canShowStar(false)).toBe(false);
    expect(canShowStar(true)).toBe(true);
  });
});

describe("what a row is called", () => {
  it("uses the label stored when it was starred", () => {
    expect(rowLabel(favourite())).toBe("IMO 9074729");
  });

  it("falls back to the type rather than to a UUID", () => {
    // A shortcut reading `aabbccdd-…` is one nobody can choose between.
    expect(rowLabel(favourite({ label: "" }))).toBe("Ship");
    expect(rowLabel(favourite({ label: "   " }))).toBe("Ship");
  });

  it("never shows the instance id", () => {
    const said = rowLabel(favourite({ label: "", object_type_name: "" }));
    expect(said).toBe("Object");
    expect(said).not.toContain("i-1");
  });

  it("says the type underneath, so two of one name are tellable apart", () => {
    expect(rowSubtitle(favourite())).toBe("Ship");
  });

  it("does not spend two lines saying one thing", () => {
    // A row reading "Ship / Ship" has.
    expect(rowSubtitle(favourite({ label: "Ship" }))).toBeNull();
    expect(rowSubtitle(favourite({ label: "" }))).toBeNull();
  });

  it("says nothing underneath when there is no type name", () => {
    expect(rowSubtitle(favourite({ object_type_name: "" }))).toBeNull();
  });
});

describe("the empty list", () => {
  it("names the verb and where to find it", () => {
    // A star on an object view is not something somebody finds by looking at
    // an empty panel.
    const said = emptyReason();
    expect(said).toContain("star");
    expect(said).toContain("object");
  });
});
