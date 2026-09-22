import { describe, expect, it } from "vitest";

import {
  canShowStar,
  emptyReason,
  kindWord,
  objectsOnly,
  resourceHref,
  resourcesEmptyReason,
  resourcesOnly,
  rowLabel,
  rowSubtitle,
  starGlyph,
  starLabel,
} from "./favourites";
import type { Favourite } from "./types";

function favourite(over: Partial<Favourite> = {}): Favourite {
  return {
    id: "f-1",
    object_type_id: "t-1",
    object_type_name: "Ship",
    instance_id: "i-1",
    resource_id: null,
    resource_kind: null,
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
    // **"Shortcut" since §436**, because a row with neither a label nor a
    // type may now be a resource rather than an object — and a fallback that
    // called a Workshop module an "Object" would be worse than a vague one.
    const said = rowLabel(favourite({ label: "", object_type_name: "" }));
    expect(said).toBe("Shortcut");
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


// ---- the other subject (§436) ----------------------------------------------
function resourceFavourite(over: Partial<Favourite> = {}): Favourite {
  return {
    id: "f-2",
    object_type_id: null,
    object_type_name: null,
    instance_id: null,
    resource_id: "r-9",
    resource_kind: "dataset",
    label: "Daily orders",
    created_at: "2026-01-02T00:00:00Z",
    ...over,
  };
}

describe("telling the two kinds apart", () => {
  const both = [favourite(), resourceFavourite()];

  it("keeps the object shortcuts for the list that can open them", () => {
    expect(objectsOnly(both).map((f) => f.id)).toEqual(["f-1"]);
  });

  it("keeps the resource shortcuts for the list that can open those", () => {
    expect(resourcesOnly(both).map((f) => f.id)).toEqual(["f-2"]);
  });

  it("asks about the subject rather than about the other kind's absence", () => {
    // Both filters must be positive: a row is neither "not an object" nor
    // "not a resource", it *is* one of them (db 0100's CHECK), and a filter
    // written the other way round would keep a row with no subject at all.
    const broken = resourceFavourite({ resource_id: null });
    expect(objectsOnly([broken])).toEqual([]);
    expect(resourcesOnly([broken])).toEqual([]);
  });

  it("keeps the order it was given", () => {
    // The listing arrives newest first, and re-sorting would bury today's
    // work under a name beginning with A.
    expect(resourcesOnly([resourceFavourite({ id: "a" }), resourceFavourite({ id: "b" })])
      .map((f) => f.id)).toEqual(["a", "b"]);
  });
});

describe("kindWord", () => {
  it("says a kind in a word somebody reads", () => {
    expect(kindWord(resourceFavourite({ resource_kind: "dataset" }))).toBe("Dataset");
  });

  it("does not show a column value", () => {
    // `code_repo` is what the database calls it, not what anybody calls it.
    expect(kindWord(resourceFavourite({ resource_kind: "code_repo" }))).toBe("Repository");
  });

  it("spells out the others rather than leaving an underscore", () => {
    expect(kindWord(resourceFavourite({ resource_kind: "object_type" })))
      .toBe("Object type");
  });

  it("is null for an object shortcut, which has a type name instead", () => {
    expect(kindWord(favourite())).toBe(null);
  });
});

describe("a resource row", () => {
  it("is called what it was called when it was starred", () => {
    expect(rowLabel(resourceFavourite())).toBe("Daily orders");
  });

  it("falls back to its kind rather than to its id", () => {
    expect(rowLabel(resourceFavourite({ label: "" }))).toBe("Dataset");
  });

  it("says its kind underneath", () => {
    expect(rowSubtitle(resourceFavourite())).toBe("Dataset");
  });

  it("does not spend two lines saying one thing", () => {
    expect(rowSubtitle(resourceFavourite({ label: "Dataset" }))).toBe(null);
  });

  it("links by the stable id, not by a slug", () => {
    // Slugs move when somebody renames (§435); resource ids are why links
    // survive that.
    expect(resourceHref(resourceFavourite())).toBe("/r/r-9");
  });
});

describe("the resource list's empty state", () => {
  it("names the star and where it is", () => {
    expect(resourcesEmptyReason()).toContain("header");
  });

  it("is not the object list's sentence", () => {
    // Two lists, two stars, two places — one sentence for both would send
    // somebody to the wrong screen.
    expect(resourcesEmptyReason()).not.toBe(emptyReason());
  });
});
