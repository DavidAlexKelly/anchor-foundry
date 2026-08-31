/** p.347-349's Timeline: "used to visualize temporal data, rendering objects as
 * events in a chronologically ordered timeline".
 *
 * > "**Multiple timeline layers** can be used to aggregate temporal data across
 * > multiple object types as events on a single timeline widget… **Layer
 * > label**… **Object set**: inputted object set definition that will be
 * > displayed for a timeline layer. The object set definition must be of a
 * > single object type. … **Date / timestamp property**: select the date or
 * > timestamp property to be used for visualizing **and ordering** the objects
 * > by." (p.348)
 *
 * > "**Timeline orientation**: … Vertical or Horizontal. **Timeline events
 * > order**: … Newest First or Oldest first. **Show legend**: toggle on an
 * > interactive legend card that can be toggled to show or hide selected
 * > timeline layers. **Show time between events in tooltip on hover**." (p.349)
 *
 * ---
 *
 * **This widget is why §220 and §221 exist.** p.348's date property is
 * "visualizing *and ordering*", and ordering by a property was refused until
 * decision 0006 was built. A Timeline on the old platform would have fetched a
 * page ordered by *when a row last changed* and drawn it against the property's
 * dates — showing "the 200 most recently changed objects" where a viewer reads
 * "the earliest 200". So the sort here is a real `object_sets` sort on the
 * chosen property, and `sortFor` is the one place p.349's Newest/Oldest is
 * turned into one.
 *
 * **A layer is not a widget.** p.348 makes layers repeat, each with its own set,
 * date property, title rule, properties, colour and icon — so a layer's
 * `objectSetVariable` is a binding *inside an array*, which is §219's
 * `NESTED_REFERENCE_PROPS` case for the second time. That catalogue was written
 * so the next one would find a list to be added to rather than a precedent to
 * copy, and this is the next one.
 */

/** p.349's Timeline orientation. */
export const ORIENTATIONS: Record<string, string> = {
  vertical: "Vertical",
  horizontal: "Horizontal",
};

export const DEFAULT_ORIENTATION = "vertical";

export function orientationOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(ORIENTATIONS, raw)
    ? raw
    : DEFAULT_ORIENTATION;
}

/** p.349's Timeline events order. */
export const ORDERS: Record<string, string> = {
  newest_first: "Newest first",
  oldest_first: "Oldest first",
};

export const DEFAULT_ORDER = "newest_first";

export function orderOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(ORDERS, raw) ? raw : DEFAULT_ORDER;
}

/** p.349's order, as an `object_sets` sort on p.348's date property.
 *
 * **The whole reason this widget waited for decision 0006** — and the reason is
 * *paging*, precisely. `-name` is descending and `name` ascending, the shape
 * `parse_sort` takes. `eventsOf` re-sorts everything the browser has, so on a
 * page holding the whole set this changes nothing anybody can see; what it
 * decides is **which objects are on the page**. That is the difference between
 * "the earliest twenty events" and "twenty events, and here are their dates" —
 * and a server that could not order by a property could only answer the second
 * while looking like it had answered the first.
 *
 * `null` when there is no date property, so a caller asks the server for
 * nothing rather than asking it for an ordering over a property nobody chose.
 */
export function sortFor(order: unknown, dateProperty: unknown): string | null {
  const name = typeof dateProperty === "string" ? dateProperty.trim() : "";
  if (!name) return null;
  return orderOf(order) === "newest_first" ? `-${name}` : name;
}

/** p.348's Event title. */
export const TITLE_MODES: Record<string, string> = {
  object: "Object title",
  property: "Property title",
  custom: "Custom title",
};

export const DEFAULT_TITLE_MODE = "object";

export function titleModeOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(TITLE_MODES, raw)
    ? raw
    : DEFAULT_TITLE_MODE;
}

/** Which properties an event shows (p.348's Event properties).
 *
 * **`prominent` reads the ontology rather than meaning "all"**, which is what
 * p.348 says: "only display the ontology-defined prominent properties". This
 * platform has that flag - `property_visibility` since db 0042, one of
 * `normal`, `prominent`, `hidden` - so "prominent" is a real answer here and
 * not an approximation of one.
 *
 * A type with no prominent property shows **nothing** rather than everything.
 * Falling back to all of them would turn an event card into a property dump
 * the moment somebody forgot to mark one, and p.348's word is "only".
 */
export function eventProperties(
  layer: Layer, declared: readonly { api_name: string; visibility?: string }[],
): string[] {
  if (propertyModeOf(layer.propertyMode) === "specific") {
    const wanted = layer.properties.split(",").map((n) => n.trim()).filter(Boolean);
    const known = new Set(declared.map((p) => p.api_name));
    // Ordered by the author's list rather than by the ontology: p.348's
    // "specify which object properties" is a choice of order as well as of set.
    return wanted.filter((name) => known.has(name));
  }
  return declared.filter((p) => p.visibility === "prominent").map((p) => p.api_name);
}

export const PROPERTY_MODES: Record<string, string> = {
  prominent: "Prominent properties",
  specific: "Specific properties",
};

export const DEFAULT_PROPERTY_MODE = "prominent";

export function propertyModeOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(PROPERTY_MODES, raw)
    ? raw
    : DEFAULT_PROPERTY_MODE;
}

/** p.348's Color. */
export const COLOUR_MODES: Record<string, string> = {
  default: "Ontology default",
  static: "Static",
  dynamic: "Conditional formatting",
};

export const DEFAULT_COLOUR_MODE = "default";

export function colourModeOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(COLOUR_MODES, raw)
    ? raw
    : DEFAULT_COLOUR_MODE;
}

/** p.349's Icon override. */
export const ICON_MODES: Record<string, string> = {
  default: "Ontology default",
  none: "No icon",
  custom: "Custom",
};

export const DEFAULT_ICON_MODE = "default";

export function iconModeOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(ICON_MODES, raw)
    ? raw
    : DEFAULT_ICON_MODE;
}

export interface Layer {
  /** p.348's Layer label. */
  label: string;
  /** p.348's Object set — a variable id. See `NESTED_REFERENCE_PROPS`. */
  objectSetVariable: string;
  /** p.348's Date / timestamp property. */
  dateProperty: string;
  titleMode: string;
  /** The property `titleMode: "property"` reads, or the text `"custom"` shows. */
  titleValue: string;
  propertyMode: string;
  /** Comma-separated api names, the shape `visibleProperties` already takes. */
  properties: string;
  colourMode: string;
  colour: string;
  iconMode: string;
  icon: string;
}

/** p.348's layers, as a saved document can hold them.
 *
 * **A layer with no object set or no date property is dropped**, not drawn
 * empty. Both are what a layer *is*: p.348's set is where its events come from
 * and its date property is what puts them anywhere at all. A layer missing
 * either would occupy a legend entry and a colour while contributing nothing,
 * which reads as "this data is absent" rather than "this layer is unfinished".
 *
 * A missing **label** is not the same and does not drop the layer — unlike
 * §219's steps, where the label is the whole of what a step is. Here the events
 * are the content and the label names a legend entry, so an unlabelled layer
 * still draws its events; `labelFor` gives it a name to be listed under.
 */
export function layersOf(raw: unknown): Layer[] {
  if (!Array.isArray(raw)) return [];
  const out: Layer[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const item = entry as Partial<Layer>;
    const set = text(item.objectSetVariable);
    const date = text(item.dateProperty);
    if (!set || !date) continue;
    out.push({
      label: text(item.label),
      objectSetVariable: set,
      dateProperty: date,
      titleMode: titleModeOf(item.titleMode),
      titleValue: text(item.titleValue),
      propertyMode: propertyModeOf(item.propertyMode),
      properties: text(item.properties),
      colourMode: colourModeOf(item.colourMode),
      colour: text(item.colour),
      iconMode: iconModeOf(item.iconMode),
      icon: text(item.icon),
    });
  }
  return out;
}

function text(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
}

/** What a layer is called, in the legend and in a settings row.
 *
 * Numbered from 1 rather than 0: this is a name a person reads, and "Layer 0"
 * is a name only a programmer would write.
 */
export function labelFor(layer: Layer, index: number): string {
  return layer.label || `Layer ${index + 1}`;
}

export const DEFAULT_LAYER_COLOURS = [
  "#14646e", "#8a6d3b", "#6d3b8a", "#3b6d8a", "#8a3b4d", "#4d8a3b",
];

/** The colour a layer's events take (p.348's Color).
 *
 * p.348's three modes, and the *default* one is the interesting call: it says
 * "the default color set in the ontology for the object's icon", and this
 * platform's object types carry one. A layer whose type has none falls back to
 * a per-layer colour from the palette rather than to a single shared colour —
 * two layers drawn identically on one timeline is the widget failing at the one
 * thing p.348 says layers are for.
 *
 * `dynamic` returns `null`, because a conditional colour is per *object* and
 * this function is per *layer*. Answering it here would mean picking one
 * object's answer for the whole layer, which is worse than saying the question
 * belongs elsewhere.
 */
export function layerColour(
  layer: Layer, index: number, ontologyColour?: string | null,
): string | null {
  const mode = colourModeOf(layer.colourMode);
  if (mode === "dynamic") return null;
  if (mode === "static") return layer.colour || fallbackColour(index);
  return (ontologyColour || "").trim() || fallbackColour(index);
}

function fallbackColour(index: number): string {
  return DEFAULT_LAYER_COLOURS[index % DEFAULT_LAYER_COLOURS.length] as string;
}

/** Whether a layer draws an icon at all (p.349's Icon override). */
export function showsIcon(layer: Layer): boolean {
  return iconModeOf(layer.iconMode) !== "none";
}

/** p.348's Event title, for one object.
 *
 * `object` is the object's own title (what §210's Object Set Title resolves),
 * `properties` its values. The fallbacks are deliberate and each is a different
 * question: a **property title** naming a property the object does not carry
 * falls back to the object's title, because a blank event is unidentifiable; a
 * **custom title** does not, because a custom title is the author saying what
 * every event in this layer is called and an empty one is an author who has not
 * finished rather than a missing value.
 */
export function eventTitle(
  layer: Layer,
  object: { title?: string; primaryKey?: string; properties?: Record<string, unknown> },
): string {
  const mode = titleModeOf(layer.titleMode);
  const fallback = text(object.title) || text(object.primaryKey);
  if (mode === "custom") return layer.titleValue;
  if (mode === "property") {
    const value = (object.properties ?? {})[layer.titleValue];
    const shown = value === null || value === undefined ? "" : String(value).trim();
    return shown || fallback;
  }
  return fallback;
}

export interface Event {
  key: string;
  /** The layer this event came from, so a legend can hide it. */
  layer: number;
  /** The comparable instant, for ordering and for gaps. `null` never reaches
   * here — `eventsOf` drops what it cannot place. */
  at: number;
  title: string;
  properties: Record<string, unknown>;
}

/** An ISO-8601 date or timestamp as a comparable instant, or `null`.
 *
 * The browser half of `object_sets.comparable` for the one type this widget
 * orders by, and it makes the same two calls for the same reasons: a value that
 * will not parse is **not on the timeline** rather than at one end of it, and a
 * naive value is **UTC** rather than the viewer's local zone. The second is the
 * one that would have been missed — `new Date("2026-01-05")` is already UTC but
 * `new Date("2026-01-05T09:00:00")` is *local*, so a timeline would place two
 * events from one dataset hours apart depending on where the reader was
 * sitting, and both would look plausible.
 */
export function instantOf(raw: unknown): number | null {
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : null;
  const value = text(raw);
  if (!value) return null;
  const normalised = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) || !value.includes("T")
    ? value
    : `${value}Z`;
  const parsed = Date.parse(normalised);
  return Number.isNaN(parsed) ? null : parsed;
}

/** Every layer's objects, as events on one timeline (p.348's "aggregate
 * temporal data across multiple object types").
 *
 * Ordered here rather than trusted from the server, and that is not a
 * contradiction of `sortFor`: **each layer is a separate query**, so the server
 * orders each one and something has to merge them. A merge that trusted the
 * concatenation would interleave nothing at all — every event of layer one,
 * then every event of layer two — which is exactly the picture p.348 says a
 * timeline is not.
 *
 * The tie-break is `(layer, key)`, for the reason every page in this codebase
 * has one: two events at the same instant are routine (a bulk import stamps
 * them identically), and without it the same data draws in a different order
 * each time it is fetched.
 */
export function eventsOf(
  layers: readonly Layer[],
  rows: readonly (readonly { key: string; title?: string; primaryKey?: string;
    properties?: Record<string, unknown> }[])[],
  order: unknown,
): Event[] {
  const events: Event[] = [];
  layers.forEach((layer, index) => {
    for (const row of rows[index] ?? []) {
      const at = instantOf((row.properties ?? {})[layer.dateProperty]);
      if (at === null) continue;
      events.push({
        key: row.key,
        layer: index,
        at,
        title: eventTitle(layer, row),
        properties: row.properties ?? {},
      });
    }
  });
  const newest = orderOf(order) === "newest_first";
  return events.sort((a, b) =>
    (newest ? b.at - a.at : a.at - b.at)
    || a.layer - b.layer
    || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}

/** Which layers a viewer has not hidden (p.349's "interactive legend card that
 * can be toggled to show or hide selected timeline layers").
 *
 * `hidden` is a set of layer indexes. An **empty set shows everything**, which
 * is the same rule every filter in this codebase follows: a viewer who has
 * touched nothing sees the whole thing.
 */
export function visibleEvents(
  events: readonly Event[], hidden: ReadonlySet<number>,
): Event[] {
  return events.filter((event) => !hidden.has(event.layer));
}

export function toggleLayer(hidden: ReadonlySet<number>, layer: number): Set<number> {
  const next = new Set(hidden);
  if (next.has(layer)) next.delete(layer);
  else next.add(layer);
  return next;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** p.349's "calculated time between two events", in words.
 *
 * The largest unit that says something true, rather than a fixed one: "3 days"
 * beats "72 hours" for a reader scanning a timeline, and "2 minutes" beats
 * "0 days". A gap under a minute is "less than a minute" rather than a count of
 * seconds — a timeline is not a stopwatch, and rounding it to "0 minutes" would
 * read as no gap at all.
 *
 * Absolute, because the two events it sits between are already in the order the
 * timeline drew them: a signed answer would be negative for the whole of a
 * newest-first timeline, which is a minus sign in front of every tooltip.
 */
export function gapLabel(a: number, b: number): string {
  const ms = Math.abs(a - b);
  if (ms < MINUTE) return "less than a minute";
  if (ms < HOUR) return plural(Math.floor(ms / MINUTE), "minute");
  if (ms < DAY) return plural(Math.floor(ms / HOUR), "hour");
  const days = Math.floor(ms / DAY);
  if (days < 365) return plural(days, "day");
  return plural(Math.floor(days / 365), "year");
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}
