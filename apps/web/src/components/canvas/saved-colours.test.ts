import { describe, expect, it } from "vitest";

import {
  REF_PREFIX, type SavedColour, added, byId, freeName, nextId, paletteOf,
  refIn, refTo, resolveColour, updated,
} from "./saved-colours";

const PALETTE: SavedColour[] = [
  { id: "c1", name: "Brand", light: "#112233", dark: "#ddeeff" },
  { id: "c2", name: "Accent", light: "#aabbcc", dark: "#aabbcc" },
];

describe("paletteOf", () => {
  it("reads a stored palette", () => {
    expect(paletteOf([{ id: "c1", name: "Brand", light: "#112233", dark: "#ddeeff" }]))
      .toEqual([{ id: "c1", name: "Brand", light: "#112233", dark: "#ddeeff" }]);
  });

  it("normalises so one colour is one colour", () => {
    // `#FFF` and `#ffffff` are the same value, and two rows for it would make
    // the palette a list of near-duplicates nobody can tell apart.
    expect(paletteOf([{ id: "c1", name: "White", light: "#FFF" }])[0]!)
      .toEqual({ id: "c1", name: "White", light: "#ffffff", dark: "#ffffff" });
  });

  it("gives a colour with no dark value the light one", () => {
    // p.214 offers the pair; a module that has not set the dark half is not a
    // module with no colour in dark mode.
    expect(paletteOf([{ id: "c1", name: "Brand", light: "#112233" }])[0]!.dark)
      .toBe("#112233");
  });

  it("drops an entry with no usable colour rather than repairing it", () => {
    // §212: a raw document can hold anything, and an entry resolving to
    // nothing would blank every widget that referenced it.
    expect(paletteOf([
      { id: "c1", name: "Broken", light: "not a colour" },
      { id: "", name: "Nameless", light: "#112233" },
      { name: "No id", light: "#112233" },
      "not an entry", null, 7,
      { id: "c9", name: "Fine", light: "#123456" },
    ])).toEqual([{ id: "c9", name: "Fine", light: "#123456", dark: "#123456" }]);
  });

  it("keeps the first of two entries sharing an id", () => {
    // A reference names one colour. Two rows answering to `c1` is a document
    // where which one you get depends on order.
    const out = paletteOf([
      { id: "c1", name: "First", light: "#111111" },
      { id: "c1", name: "Second", light: "#222222" },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]!.name).toBe("First");
  });

  it("names a colour after its id when it has no name", () => {
    expect(paletteOf([{ id: "c4", name: "  ", light: "#123456" }])[0]!.name).toBe("c4");
  });

  it("reads anything that is not a list as an empty palette", () => {
    for (const raw of [undefined, null, {}, "palette", 7]) {
      expect(paletteOf(raw)).toEqual([]);
    }
  });
});

describe("references", () => {
  it("round-trips an id", () => {
    expect(refIn(refTo("c1"))).toBe("c1");
  });

  it("is not a hex, a preset or a CSS colour", () => {
    // The prefix has to be unmistakable, because every one of these arrives in
    // the same slot.
    for (const value of ["#112233", "112233", "shade-2", "transparent", "red", ""]) {
      expect(refIn(value)).toBeNull();
    }
  });

  it("is not a reference to nothing", () => {
    expect(refIn(REF_PREFIX)).toBeNull();
    expect(refIn(`${REF_PREFIX}   `)).toBeNull();
  });

  it("reads only strings", () => {
    for (const value of [null, undefined, 7, {}, ["c1"]]) {
      expect(refIn(value)).toBeNull();
    }
  });
});

describe("resolveColour", () => {
  it("gives the light value in light mode and the dark one in dark", () => {
    expect(resolveColour(refTo("c1"), PALETTE, "light")).toBe("#112233");
    expect(resolveColour(refTo("c1"), PALETTE, "dark")).toBe("#ddeeff");
  });

  it("answers null for a value that is not a reference", () => {
    // Not a colour and not a failure: the caller has its own rules for a hex,
    // a preset and a free CSS colour, and this says "not mine".
    expect(resolveColour("#112233", PALETTE, "light")).toBeNull();
    expect(resolveColour("shade-2", PALETTE, "light")).toBeNull();
  });

  it("answers undefined for a reference naming nothing", () => {
    // §210: the palette entry has gone — a reverted version can do that — and
    // substituting a colour would make a real loss look like a setting.
    expect(resolveColour(refTo("c9"), PALETTE, "light")).toBeUndefined();
  });

  it("tells a missing entry apart from a value it does not own", () => {
    // The two would collapse into one if either were `null`, and the panel
    // would have no way to say which happened.
    expect(resolveColour(refTo("c9"), PALETTE, "light"))
      .not.toBe(resolveColour("#112233", PALETTE, "light"));
  });
});

describe("nextId", () => {
  it("counts up from the highest in use", () => {
    expect(nextId(PALETTE)).toBe("c3");
    expect(nextId([])).toBe("c1");
  });

  it("does not reuse an id a removed colour had", () => {
    // Reusing `c2` would silently recolour every widget still referencing it.
    expect(nextId([PALETTE[1]!])).toBe("c3");
  });

  it("ignores ids that are not counted", () => {
    expect(nextId([{ id: "brand", name: "Brand", light: "#111111", dark: "#111111" }]))
      .toBe("c1");
  });
});

describe("freeName", () => {
  it("keeps a name nothing is using", () => {
    expect(freeName(PALETTE, "Surface")).toBe("Surface");
  });

  it("numbers a name that is taken", () => {
    // Two colours called "Brand" is a picker where the right choice is
    // unguessable.
    expect(freeName(PALETTE, "Brand")).toBe("Brand 2");
  });

  it("does not care about case", () => {
    expect(freeName(PALETTE, "brand")).toBe("brand 2");
  });

  it("keeps counting past a number already taken", () => {
    const palette = [...PALETTE, { id: "c3", name: "Brand 2", light: "#1", dark: "#1" }];
    expect(freeName(palette, "Brand")).toBe("Brand 3");
  });

  it("names an empty request something", () => {
    expect(freeName([], "   ")).toBe("Colour");
  });
});

describe("added", () => {
  it("appends a colour seeded from a hex", () => {
    const out = added(PALETTE, "#ABCDEF", "Surface");
    expect(out).toHaveLength(3);
    expect(out[2]!).toEqual({
      id: "c3", name: "Surface", light: "#abcdef", dark: "#abcdef",
    });
  });

  it("starts the dark value equal rather than guessing one", () => {
    // p.214 offers the pair so a builder can choose; a computed opposite is a
    // choice they never made turning up in their module.
    const out = added([], "#112233");
    expect(out[0]!.dark).toBe(out[0]!.light);
  });

  it("does not modify the palette it was given", () => {
    const palette = [...PALETTE];
    added(palette, "#112233");
    expect(palette).toHaveLength(2);
  });

  it("falls back to black rather than storing an unusable colour", () => {
    // An entry `paletteOf` would drop is an entry that blanks every widget
    // referencing it.
    expect(added([], "not a colour")[0]!.light).toBe("#000000");
  });
});

describe("updated", () => {
  it("changes one colour and leaves the rest", () => {
    const out = updated(PALETTE, "c1", { light: "#FFFFFF" });
    expect(out[0]!.light).toBe("#ffffff");
    expect(out[0]!.dark).toBe("#ddeeff");
    expect(out[1]!).toEqual(PALETTE[1]!);
  });

  it("renames", () => {
    expect(updated(PALETTE, "c1", { name: "Primary" })[0]!.name).toBe("Primary");
  });

  it("lets a colour keep its own name", () => {
    // Renaming against the whole palette including itself would turn every
    // save of an unchanged field into "Brand 2".
    expect(updated(PALETTE, "c1", { name: "Brand" })[0]!.name).toBe("Brand");
  });

  it("does not let a rename take another colour's name", () => {
    expect(updated(PALETTE, "c1", { name: "Accent" })[0]!.name).toBe("Accent 2");
  });

  it("ignores a colour that is not a colour", () => {
    // The field is typed into, so it is unusable for most of the time somebody
    // is filling it in. Writing each intermediate value would mean a palette
    // that flickers to black while a builder types.
    expect(updated(PALETTE, "c1", { light: "#11" })[0]!.light).toBe("#112233");
  });

  it("changes nothing for an id the palette does not have", () => {
    expect(updated(PALETTE, "c9", { name: "Ghost" })).toEqual(PALETTE);
  });

  it("does not modify the palette it was given", () => {
    const palette: SavedColour[] = [{ ...PALETTE[0]! }];
    updated(palette, "c1", { light: "#ffffff" });
    expect(palette[0]!.light).toBe("#112233");
  });
});

describe("byId", () => {
  it("keys the palette for a resolver that asks repeatedly", () => {
    expect(byId(PALETTE).c2!.name).toBe("Accent");
    expect(byId([])).toEqual({});
  });
});
