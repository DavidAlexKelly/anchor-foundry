/** p.142's geospatial operations, as the Variables panel offers them (§568).
 * The server evaluates them (`services/variable_geo.py`). Pure. */

export const GEO_TRANSFORMS = new Set(["geohash", "latitude", "longitude", "mgrs"]);
/** A geohash's characters: 12 by default, about 4 cm. */
export const MAX_GEOHASH = 12;

export function isGeo(transform: string): boolean {
  return GEO_TRANSFORMS.has(transform);
}

/** A geohash precision as the server takes it, or null. */
export function geohashPrecisionOf(text: string): number | null {
  if (text.trim() === "") return null;
  const n = Number(text);
  return Number.isInteger(n) && n >= 1 && n <= MAX_GEOHASH ? n : null;
}
