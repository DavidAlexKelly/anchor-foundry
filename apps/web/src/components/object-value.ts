/** Rendering an instance property value when its declared type is not to hand.
 *
 * `PropertyValue` is the right thing when the caller knows the property's base
 * type — it renders a geopoint as a map link, an attachment as a download. The
 * Object Explorer does not: it lists instances across *several* object types at
 * once, and its columns are the union of whatever keys the current page happens
 * to carry, so there is no single type to look up.
 *
 * It used to call `String(value)`, which is correct for scalars and produces
 * **`[object Object]`** for anything structured. A geopoint is `{lat, lon}`, so
 * every geopoint column in the Explorer read as `[object Object]` — spotted in
 * a test dump while building the standard Object View, which is the only reason
 * anybody noticed.
 *
 * This is the fallback, not a second `PropertyValue`. It never links, never
 * fetches and never guesses at a type; it only makes sure a structured value
 * shows *something a person can read* instead of a JavaScript diagnostic.
 */

/** A geopoint, in either shape the platform stores one. */
function asPoint(value: unknown): { lat: number; lon: number } | null {
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    const lat = Number(record.lat ?? record.latitude);
    const lon = Number(record.lon ?? record.lng ?? record.longitude);
    if (Number.isFinite(lat) && Number.isFinite(lon)) return { lat, lon };
  }
  // The dataset form: geopoints round-trip through a column as "lat,lon".
  if (typeof value === "string" && value.includes(",")) {
    const [lat, lon] = value.split(",", 2).map((part) => Number(part.trim()));
    if (Number.isFinite(lat) && Number.isFinite(lon)) return { lat: lat!, lon: lon! };
  }
  return null;
}

const EMPTY = "∅";

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return EMPTY;

  const point = asPoint(value);
  if (point) return `${point.lat}, ${point.lon}`;

  if (Array.isArray(value)) {
    // Joined rather than JSON, because a list of names is the common case and
    // `["a","b"]` is harder to read than `a, b` for no gain.
    return value.length === 0 ? EMPTY : value.map((v) => displayValue(v)).join(", ");
  }

  if (typeof value === "object") {
    // Compact JSON. Long, sometimes — but a truncated object is a value you
    // cannot tell from a different one, and the cell already scrolls.
    try {
      return JSON.stringify(value);
    } catch {
      return "(unreadable)";
    }
  }

  return String(value);
}
