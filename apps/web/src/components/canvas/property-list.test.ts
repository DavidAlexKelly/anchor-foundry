import { describe, expect, it } from "vitest";

import {
  DEFAULT_LAYOUT, LAYOUTS, MAX_COLUMNS, MIN_COLUMNS,
  columnsOf, gridStyle, hideNullOf, isNull, layoutOf, visibleProperties,
} from "./property-list";

/** p.265-266's Property List. */

const ALL = [
  { api_name: "name", display_name: "Name" },
  { api_name: "region", display_name: "Region" },
  { api_name: "note", display_name: "Note" },
];

const VALUES = { name: "Alpha", region: "north", note: "" };

function visible(over: Partial<Parameters<typeof visibleProperties>[0]> = {}) {
  return visibleProperties({
    all: ALL, chosen: "", values: VALUES, hideNull: false, ...over,
  }).map((p) => p.api_name);
}

describe("p.265's layout", () => {
  it("has the two positions p.265 names and defaults to adjacent", () => {
    expect(Object.keys(LAYOUTS).sort()).toEqual(["adjacent", "below"]);
    expect(DEFAULT_LAYOUT).toBe("adjacent");
    expect(layoutOf("below")).toBe("below");
    expect(layoutOf(undefined)).toBe("adjacent");
  });

  it("falls back for a layout the widget does not have", () => {
    // A document can name anything — an older panel, the raw JSON editor.
    expect(layoutOf("diagonal")).toBe("adjacent");
    expect(layoutOf("constructor")).toBe("adjacent");
    expect(layoutOf(7)).toBe("adjacent");
  });
});

describe("p.266's column count", () => {
  it("reads a number and defaults to one", () => {
    expect(columnsOf(3)).toBe(3);
    expect(columnsOf("2")).toBe(2);
    expect(columnsOf(undefined)).toBe(MIN_COLUMNS);
    expect(columnsOf(null)).toBe(MIN_COLUMNS);
    expect(columnsOf("")).toBe(MIN_COLUMNS);
  });

  it("clamps what a document can name", () => {
    expect(columnsOf(0)).toBe(MIN_COLUMNS);
    expect(columnsOf(-4)).toBe(MIN_COLUMNS);
    expect(columnsOf(99)).toBe(MAX_COLUMNS);
    expect(columnsOf("abc")).toBe(MIN_COLUMNS);
    expect(columnsOf(2.9)).toBe(2);
  });

  it("becomes a grid of that many equal columns", () => {
    // `minmax(0, 1fr)` rather than `1fr`: a grid track's default minimum is its
    // content, so one long unbroken value would push the others out.
    expect(gridStyle(3).gridTemplateColumns).toBe("repeat(3, minmax(0, 1fr))");
  });
});

describe("what counts as null", () => {
  it("includes the empty string", () => {
    // **A blank CSV column arrives as `""`, not `null`.** Hiding one and
    // keeping the other would look arbitrary to a reader who cannot see which
    // of the two the store happens to hold.
    expect(isNull(null)).toBe(true);
    expect(isNull(undefined)).toBe(true);
    expect(isNull("")).toBe(true);
  });

  it("does not include values that merely look empty", () => {
    // Zero and false are answers.
    expect(isNull(0)).toBe(false);
    expect(isNull(false)).toBe(false);
    expect(isNull([])).toBe(false);
    expect(isNull(" ")).toBe(false);
  });
});

describe("which properties are drawn", () => {
  it("shows every property when none is chosen", () => {
    expect(visible()).toEqual(["name", "region", "note"]);
  });

  it("shows the chosen ones in the order they were chosen", () => {
    // p.266 calls this selecting which properties to display; an author who
    // lists three has said something about the order too.
    expect(visible({ chosen: "note,name" })).toEqual(["note", "name"]);
  });

  it("tolerates spacing in the list", () => {
    expect(visible({ chosen: " note , name " })).toEqual(["note", "name"]);
  });

  it("drops a name that matches no property", () => {
    // **A property can be removed from the object type** long after a widget
    // was pointed at it, and a blank row labelled with a name nobody
    // recognises is worse than no row.
    expect(visible({ chosen: "name,gone,region" })).toEqual(["name", "region"]);
  });

  it("hides nulls only when asked", () => {
    expect(visible({ hideNull: false })).toEqual(["name", "region", "note"]);
    expect(visible({ hideNull: true })).toEqual(["name", "region"]);
  });

  it("hides nulls within a chosen order", () => {
    expect(visible({ chosen: "note,name", hideNull: true })).toEqual(["name"]);
  });

  it("hides nothing while the object is still resolving", () => {
    // **Every value is `undefined` before the instance arrives**, so hiding
    // then would empty the widget on load and fill it a moment later — §210's
    // rule about whether a widget renders at all, one level down.
    expect(visible({ values: undefined, hideNull: true }))
      .toEqual(["name", "region", "note"]);
  });

  it("returns a list the caller may keep, on the path that returns it directly", () => {
    // **`hideNull: true` cannot test this**, which is what the harness said:
    // that path filters, and `filter` allocates whether or not anything was
    // copied. The copy only matters where the list is handed straight back —
    // blank selection, nulls kept — and there the alternative is returning the
    // object type's own property array, which a caller sorting for display
    // would reorder for everything else reading it.
    const all = [...ALL];
    const shown = visibleProperties({
      all, chosen: "", values: VALUES, hideNull: false,
    });
    shown.reverse();
    expect(all.map((p) => p.api_name)).toEqual(["name", "region", "note"]);
  });
});

describe("the hide-null toggle", () => {
  it("is off unless a document says so", () => {
    expect(hideNullOf(undefined)).toBe(false);
    expect(hideNullOf("true")).toBe(false);
    expect(hideNullOf(true)).toBe(true);
  });
});
