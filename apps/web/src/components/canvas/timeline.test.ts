import { describe, expect, it } from "vitest";

import {
  COLOUR_MODES, DEFAULT_LAYER_COLOURS, DEFAULT_ORDER, DEFAULT_ORIENTATION,
  ICON_MODES, ORDERS, ORIENTATIONS, PROPERTY_MODES, TITLE_MODES,
  colourModeOf, eventProperties, eventTitle, eventsOf, gapLabel, iconModeOf,
  instantOf, labelFor,
  layerColour, layersOf, orderOf, orientationOf, propertyModeOf, showsIcon,
  sortFor, titleModeOf, toggleLayer, visibleEvents, type Layer,
} from "./timeline";

/** p.347-349's Timeline. */

const layer = (extra: Partial<Layer> = {}): Layer => ({
  label: "", objectSetVariable: "v_set", dateProperty: "seen",
  titleMode: "object", titleValue: "", propertyMode: "prominent", properties: "",
  colourMode: "default", colour: "", iconMode: "default", icon: "", ...extra,
});

describe("p.349's orientation and order", () => {
  it("has the two orientations p.349 names, defaulting to vertical", () => {
    expect(Object.keys(ORIENTATIONS).sort()).toEqual(["horizontal", "vertical"]);
    expect(DEFAULT_ORIENTATION).toBe("vertical");
    expect(orientationOf(undefined)).toBe("vertical");
    expect(orientationOf("horizontal")).toBe("horizontal");
    expect(orientationOf("diagonal")).toBe("vertical");
  });

  it("has the two orders p.349 names, defaulting to newest first", () => {
    expect(Object.keys(ORDERS).sort()).toEqual(["newest_first", "oldest_first"]);
    expect(DEFAULT_ORDER).toBe("newest_first");
    expect(orderOf(undefined)).toBe("newest_first");
    expect(orderOf("oldest_first")).toBe("oldest_first");
    expect(orderOf(7)).toBe("newest_first");
  });
});

describe("p.348's date property, as a server-side sort", () => {
  it("asks for the property descending when the newest come first", () => {
    // **The whole reason this widget waited for decision 0006**, and the
    // reason is paging: `eventsOf` re-sorts what the browser has, so this
    // decides *which* objects are on the page rather than their drawn order.
    // Without it a timeline shows the 200 most recently *changed* objects
    // where a viewer reads "the earliest 200".
    expect(sortFor("newest_first", "seen")).toBe("-seen");
    expect(sortFor("oldest_first", "seen")).toBe("seen");
  });

  it("asks for nothing when no date property is chosen", () => {
    // Rather than an ordering over a property nobody named, which the server
    // would refuse - and a refusal is a broken widget where "no layer yet" is
    // an unfinished one.
    expect(sortFor("newest_first", "")).toBeNull();
    expect(sortFor("newest_first", "  ")).toBeNull();
    expect(sortFor("newest_first", undefined)).toBeNull();
  });

  it("trims the property name before asking", () => {
    expect(sortFor("oldest_first", "  seen  ")).toBe("seen");
  });
});

describe("p.348's layers", () => {
  it("reads every setting p.348 and p.349 name", () => {
    const [read] = layersOf([{
      label: " Orders ", objectSetVariable: "v_a", dateProperty: " placed ",
      titleMode: "property", titleValue: "reference", propertyMode: "specific",
      properties: "total,status", colourMode: "static", colour: "#123456",
      iconMode: "custom", icon: "cart",
    }]);
    expect(read).toEqual({
      label: "Orders", objectSetVariable: "v_a", dateProperty: "placed",
      titleMode: "property", titleValue: "reference", propertyMode: "specific",
      properties: "total,status", colourMode: "static", colour: "#123456",
      iconMode: "custom", icon: "cart",
    });
  });

  it("drops a layer with no object set or no date property", () => {
    // Both are what a layer *is*: the set is where its events come from and the
    // date property is what puts them anywhere at all. Drawn, such a layer
    // takes a legend entry and a colour while contributing nothing - which
    // reads as "this data is absent" rather than "this layer is unfinished".
    expect(layersOf([
      { objectSetVariable: "v_a" },
      { dateProperty: "seen" },
      { objectSetVariable: "", dateProperty: "seen" },
      { objectSetVariable: "v_b", dateProperty: "  " },
    ])).toEqual([]);
  });

  it("keeps a layer with no label", () => {
    // **Unlike §219's steps**, where a label is the whole of what a step is.
    // Here the events are the content and the label names a legend entry.
    expect(layersOf([{ objectSetVariable: "v_a", dateProperty: "seen" }]))
      .toHaveLength(1);
  });

  it("is empty for anything that is not a list", () => {
    expect(layersOf(undefined)).toEqual([]);
    expect(layersOf({ objectSetVariable: "v_a" })).toEqual([]);
    expect(layersOf([null, 7, "x"])).toEqual([]);
  });

  it("falls back for every mode a document can get wrong", () => {
    const [read] = layersOf([{
      objectSetVariable: "v_a", dateProperty: "seen",
      titleMode: "poem", propertyMode: "all", colourMode: "rainbow", iconMode: "big",
    }]);
    expect(read?.titleMode).toBe("object");
    expect(read?.propertyMode).toBe("prominent");
    expect(read?.colourMode).toBe("default");
    expect(read?.iconMode).toBe("default");
  });
});

describe("the mode tables p.348 and p.349 name", () => {
  it("has three title modes, three colours, three icons and two property modes", () => {
    expect(Object.keys(TITLE_MODES).sort()).toEqual(["custom", "object", "property"]);
    expect(Object.keys(COLOUR_MODES).sort()).toEqual(["default", "dynamic", "static"]);
    expect(Object.keys(ICON_MODES).sort()).toEqual(["custom", "default", "none"]);
    expect(Object.keys(PROPERTY_MODES).sort()).toEqual(["prominent", "specific"]);
  });

  it("defaults each to the ontology's own answer", () => {
    expect(titleModeOf(undefined)).toBe("object");
    expect(propertyModeOf(undefined)).toBe("prominent");
    expect(colourModeOf(undefined)).toBe("default");
    expect(iconModeOf(undefined)).toBe("default");
  });
});

describe("p.348's event properties", () => {
  const declared = [
    { api_name: "region", visibility: "prominent" },
    { api_name: "note", visibility: "normal" },
    { api_name: "secret", visibility: "hidden" },
    { api_name: "status", visibility: "prominent" },
  ];

  it("shows the ontology's prominent properties by default", () => {
    // p.348: "**only** display the ontology-defined prominent properties".
    // This platform has that flag - `property_visibility`, db 0042 - so this is
    // a real answer rather than an approximation of one.
    expect(eventProperties(layer(), declared)).toEqual(["region", "status"]);
  });

  it("shows nothing when no property is marked prominent", () => {
    // **Not everything.** Falling back would turn an event card into a
    // property dump the moment somebody forgot to mark one, and p.348's word
    // is "only".
    expect(eventProperties(layer(), [{ api_name: "note", visibility: "normal" }]))
      .toEqual([]);
  });

  it("shows the named properties when p.348's specific mode is chosen", () => {
    expect(eventProperties(
      layer({ propertyMode: "specific", properties: "note, region" }), declared,
    )).toEqual(["note", "region"]);
  });

  it("keeps the author's order rather than the ontology's", () => {
    // p.348's "specify which object properties to be displayed" is a choice of
    // order as well as of set - the list is what an author arranged.
    expect(eventProperties(
      layer({ propertyMode: "specific", properties: "status,region" }), declared,
    )).toEqual(["status", "region"]);
  });

  it("drops a named property the type does not declare", () => {
    expect(eventProperties(
      layer({ propertyMode: "specific", properties: "region,gone" }), declared,
    )).toEqual(["region"]);
  });

  it("shows nothing when the specific list is empty", () => {
    expect(eventProperties(layer({ propertyMode: "specific" }), declared)).toEqual([]);
  });
});

describe("a layer's name", () => {
  it("is its label", () => {
    expect(labelFor(layer({ label: "Orders" }), 3)).toBe("Orders");
  });

  it("is numbered from one when it has none", () => {
    // A name a person reads. "Layer 0" is a name only a programmer would write.
    expect(labelFor(layer(), 0)).toBe("Layer 1");
    expect(labelFor(layer(), 2)).toBe("Layer 3");
  });
});

describe("p.348's colour", () => {
  it("uses the ontology's colour by default", () => {
    expect(layerColour(layer(), 0, "#abcdef")).toBe("#abcdef");
  });

  it("uses a static override when one is set", () => {
    expect(layerColour(layer({ colourMode: "static", colour: "#123456" }), 0, "#abcdef"))
      .toBe("#123456");
  });

  it("gives two layers different colours when the ontology has none", () => {
    // **The one thing p.348 says layers are for** is telling several types
    // apart on one timeline. A shared fallback would draw them identically.
    expect(layerColour(layer(), 0, null)).not.toBe(layerColour(layer(), 1, null));
    expect(layerColour(layer(), 0, "")).toBe(DEFAULT_LAYER_COLOURS[0]);
  });

  it("wraps round rather than running out", () => {
    expect(layerColour(layer(), DEFAULT_LAYER_COLOURS.length, null))
      .toBe(DEFAULT_LAYER_COLOURS[0]);
  });

  it("falls back when a static mode carries no colour", () => {
    expect(layerColour(layer({ colourMode: "static" }), 1, null))
      .toBe(DEFAULT_LAYER_COLOURS[1]);
  });

  it("answers nothing for a dynamic colour", () => {
    // p.348's Dynamic is per *object*, and this function is per *layer*.
    // Answering it here means picking one object's colour for all of them.
    expect(layerColour(layer({ colourMode: "dynamic" }), 0, "#abcdef")).toBeNull();
  });
});

describe("p.349's icon override", () => {
  it("draws one unless the layer says none", () => {
    expect(showsIcon(layer())).toBe(true);
    expect(showsIcon(layer({ iconMode: "custom", icon: "cart" }))).toBe(true);
    expect(showsIcon(layer({ iconMode: "none" }))).toBe(false);
  });
});

describe("p.348's event title", () => {
  const object = { title: "Site A", primaryKey: "S1", properties: { ref: "X-1", blank: "" } };

  it("is the object's title by default", () => {
    expect(eventTitle(layer(), object)).toBe("Site A");
  });

  it("is a named property when p.348's property title is chosen", () => {
    expect(eventTitle(layer({ titleMode: "property", titleValue: "ref" }), object))
      .toBe("X-1");
  });

  it("falls back to the object's title when that property has no value", () => {
    // A blank event is unidentifiable, and the object's own title is the
    // nearest true thing to say about it.
    expect(eventTitle(layer({ titleMode: "property", titleValue: "blank" }), object))
      .toBe("Site A");
    expect(eventTitle(layer({ titleMode: "property", titleValue: "absent" }), object))
      .toBe("Site A");
  });

  it("is the author's text when p.348's custom title is chosen", () => {
    expect(eventTitle(layer({ titleMode: "custom", titleValue: "Delivery" }), object))
      .toBe("Delivery");
  });

  it("does not rescue an empty custom title", () => {
    // **The opposite call to the property one, deliberately.** A custom title
    // is the author saying what every event in the layer is called; an empty
    // one is an author who has not finished, not a missing value - and
    // silently showing the object's title instead would hide that.
    expect(eventTitle(layer({ titleMode: "custom", titleValue: "" }), object)).toBe("");
  });

  it("falls back to the primary key when an object has no title", () => {
    expect(eventTitle(layer(), { primaryKey: "S9", properties: {} })).toBe("S9");
  });
});

describe("when an event happened", () => {
  it("reads an offset-carrying timestamp", () => {
    expect(instantOf("2026-03-01T09:00:00+00:00"))
      .toBe(instantOf("2026-03-01T11:00:00+02:00"));
  });

  it("reads a bare date as UTC", () => {
    expect(instantOf("2026-01-05")).toBe(Date.UTC(2026, 0, 5));
  });

  it("reads a naive timestamp as UTC rather than as local time", () => {
    // **`new Date("2026-01-05T09:00:00")` is *local*** while
    // `new Date("2026-01-05")` is UTC - so without this a timeline would place
    // two events from one dataset hours apart depending on where the reader was
    // sitting, and both pictures would look plausible. The same call
    // `object_sets._instant` makes on the server, for the same reason.
    expect(instantOf("2026-01-05T00:00:00")).toBe(instantOf("2026-01-05T00:00:00Z"));
    expect(instantOf("2026-01-05T00:00:00")).toBe(instantOf("2026-01-05"));
  });

  it("is nothing at all for a value that will not parse", () => {
    // Not the epoch: a date nobody can read is not the oldest event on the
    // timeline, it is not on the timeline.
    for (const bad of ["", "  ", "yesterday", "2026-13-45", null, undefined, {}]) {
      expect(instantOf(bad)).toBeNull();
    }
  });

  it("takes a number as an instant", () => {
    expect(instantOf(1_700_000_000_000)).toBe(1_700_000_000_000);
    expect(instantOf(Number.NaN)).toBeNull();
  });
});

describe("p.348's aggregation across layers", () => {
  const layers = [layer({ label: "A" }), layer({ label: "B", dateProperty: "at" })];
  const rows = [
    [{ key: "a1", title: "A one", properties: { seen: "2026-01-01" } },
     { key: "a2", title: "A two", properties: { seen: "2026-03-01" } }],
    [{ key: "b1", title: "B one", properties: { at: "2026-02-01" } }],
  ];

  it("interleaves the layers rather than concatenating them", () => {
    // **The thing a merge gets wrong by doing nothing.** Each layer is a
    // separate query, so the server orders each one and the concatenation is
    // every event of layer one then every event of layer two - which is the
    // picture p.348 says a timeline is not.
    expect(eventsOf(layers, rows, "oldest_first").map((e) => e.key))
      .toEqual(["a1", "b1", "a2"]);
  });

  it("reverses for newest first", () => {
    expect(eventsOf(layers, rows, "newest_first").map((e) => e.key))
      .toEqual(["a2", "b1", "a1"]);
  });

  it("reads each layer's own date property", () => {
    // The second layer's dates live under `at`, not `seen`. A merge reading one
    // property for every layer would silently drop the others entirely.
    expect(eventsOf(layers, rows, "oldest_first").filter((e) => e.layer === 1))
      .toHaveLength(1);
  });

  it("drops an object whose date will not parse", () => {
    const events = eventsOf(
      [layer()],
      [[{ key: "x", properties: { seen: "nonsense" } },
        { key: "y", properties: { seen: "2026-01-01" } }]],
      "oldest_first",
    );
    expect(events.map((e) => e.key)).toEqual(["y"]);
  });

  it("breaks a tie the same way every time", () => {
    // Two events at one instant is routine - a bulk import stamps them
    // identically - and without a tie-break the same data draws in a different
    // order each time it is fetched.
    const tied = [
      [{ key: "z", properties: { seen: "2026-01-01" } },
       { key: "a", properties: { seen: "2026-01-01" } }],
      [{ key: "m", properties: { at: "2026-01-01" } }],
    ];
    for (const order of ["newest_first", "oldest_first"]) {
      expect(eventsOf(layers, tied, order).map((e) => e.key)).toEqual(["a", "z", "m"]);
    }
  });

  it("carries the layer each event came from", () => {
    expect(eventsOf(layers, rows, "oldest_first").map((e) => e.layer))
      .toEqual([0, 1, 0]);
  });

  it("is empty when a layer has no rows yet", () => {
    expect(eventsOf(layers, [], "oldest_first")).toEqual([]);
  });
});

describe("p.349's legend", () => {
  const events = [
    { key: "a", layer: 0, at: 1, title: "", properties: {} },
    { key: "b", layer: 1, at: 2, title: "", properties: {} },
  ];

  it("shows everything when nothing is hidden", () => {
    expect(visibleEvents(events, new Set()).map((e) => e.key)).toEqual(["a", "b"]);
  });

  it("hides one layer's events", () => {
    expect(visibleEvents(events, new Set([1])).map((e) => e.key)).toEqual(["a"]);
  });

  it("toggles a layer both ways", () => {
    expect([...toggleLayer(new Set(), 1)]).toEqual([1]);
    expect([...toggleLayer(new Set([1]), 1)]).toEqual([]);
  });

  it("does not change the set it was given", () => {
    const hidden = new Set([0]);
    toggleLayer(hidden, 1);
    expect([...hidden]).toEqual([0]);
  });
});

describe("p.349's time between events", () => {
  const at = (iso: string) => instantOf(iso) as number;

  it("uses the largest unit that says something true", () => {
    expect(gapLabel(at("2026-01-01"), at("2026-01-04"))).toBe("3 days");
    expect(gapLabel(at("2026-01-01T00:00:00Z"), at("2026-01-01T05:00:00Z")))
      .toBe("5 hours");
    expect(gapLabel(at("2026-01-01T00:00:00Z"), at("2026-01-01T00:02:00Z")))
      .toBe("2 minutes");
  });

  it("says a year rather than a count of days", () => {
    expect(gapLabel(at("2024-01-01"), at("2026-01-01"))).toBe("2 years");
  });

  it("says less than a minute rather than zero", () => {
    // A timeline is not a stopwatch, and "0 minutes" reads as no gap at all.
    expect(gapLabel(at("2026-01-01T00:00:00Z"), at("2026-01-01T00:00:30Z")))
      .toBe("less than a minute");
    expect(gapLabel(1, 1)).toBe("less than a minute");
  });

  it("is absolute, whichever way the timeline runs", () => {
    // The two events it sits between are already in the drawn order, so a
    // signed answer would be negative for the whole of a newest-first
    // timeline - a minus sign in front of every tooltip.
    expect(gapLabel(at("2026-01-04"), at("2026-01-01"))).toBe("3 days");
  });

  it("says one without an s", () => {
    expect(gapLabel(at("2026-01-01"), at("2026-01-02"))).toBe("1 day");
    expect(gapLabel(at("2026-01-01T00:00:00Z"), at("2026-01-01T01:00:00Z")))
      .toBe("1 hour");
  });
});
