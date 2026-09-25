/**
 * p.399–401's Data Freshness widget (§469): when each configured object type
 * and datasource was last indexed, said the way p.400 says it.
 *
 * > "If the last index time exceeds 24 hours, the timestamp renders an absolute
 * > format ( Thu, Jul 17, 2025, 1:52 PM ). If the last index time is within 24
 * > hours, the timestamp renders a relative format ( 2 hours ago or 30 min
 * > ago )." (p.400)
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const ABSOLUTE = new Intl.DateTimeFormat("en-US", {
  weekday: "short", month: "short", day: "numeric", year: "numeric",
  hour: "numeric", minute: "2-digit",
});

/**
 * p.400's two formats, and what neither covers.
 *
 * **Never indexed is said, not dated**: a source that has not synced has no
 * time to show, and "Thu, Jan 1, 1970" would be a claim about it. **A time in
 * the future reads as just now** rather than "in 3 min": the clocks of the
 * browser and the server differ by a little, and a freshness widget should not
 * report data from the future.
 */
export function freshnessLabel(iso: string | null | undefined, now: number): string {
  // One check covers both: nothing parses as NaN, as junk does. A separate
  // `!iso` check here could not change an answer, which the sweep showed.
  const at = Date.parse(iso ?? "");
  if (Number.isNaN(at)) return "Never indexed";
  const age = now - at;
  if (age >= DAY) return ABSOLUTE.format(new Date(at));
  if (age < MINUTE) return "just now";
  if (age < HOUR) {
    const minutes = Math.floor(age / MINUTE);
    return `${minutes} min ago`;
  }
  const hours = Math.floor(age / HOUR);
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
}

/** Whether a time is past p.400's 24 hours - which is also the point at which
 * the widget marks it stale, since that is the line p.400 draws. */
export function isStale(iso: string | null | undefined, now: number): boolean {
  const at = Date.parse(iso ?? "");
  return Number.isNaN(at) || now - at >= DAY;
}

/** One of p.401's items: an object type and the sources shown under it. */
export interface FreshnessItem {
  id: string;
  objectTypeId: string;
  sources: FreshnessSource[];
}

/** p.401's "Add source … Override resource name". */
export interface FreshnessSource {
  datasetId: string;
  name?: string;
}

export function itemsOf(raw: unknown): FreshnessItem[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((i): i is Record<string, unknown> =>
      !!i && typeof i === "object"
      && typeof (i as FreshnessItem).id === "string" && !!(i as FreshnessItem).id
      && typeof (i as FreshnessItem).objectTypeId === "string"
      && !!(i as FreshnessItem).objectTypeId)
    .map((i) => ({
      id: i.id as string,
      objectTypeId: i.objectTypeId as string,
      sources: (Array.isArray(i.sources) ? i.sources : [])
        .filter((s): s is FreshnessSource =>
          !!s && typeof s === "object" && typeof (s as FreshnessSource).datasetId === "string"
          && !!(s as FreshnessSource).datasetId)
        .map((s) => ({
          datasetId: s.datasetId,
          ...(typeof s.name === "string" && s.name.trim() ? { name: s.name } : {}),
        })),
    }));
}

/** The first `d_N` no item has. */
export function newItemId(items: readonly FreshnessItem[]): string {
  const taken = new Set(items.map((i) => i.id));
  let n = items.length + 1;
  while (taken.has(`d_${n}`)) n += 1;
  return `d_${n}`;
}
