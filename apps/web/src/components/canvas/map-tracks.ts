/**
 * p.303's timeline on the Workshop Map, over geotemporal tracks (§557).
 *
 * > "Enable timeline: Display the timeline open button at the bottom of the
 * > map interface. … Selected time: Control the selected time using a
 * > Workshop variable of type Timestamp or Date." (p.303)
 *
 * A geotemporal series (§427) is where an object was over time. On the map
 * each track is drawn as a line - p.302's "map breadcrumbs" - and the object
 * stands at its position **at the selected time**: the last fix at or before
 * it, and nowhere before its first. No selected time is p.303's live "View
 * latest": every object at its last known position.
 *
 * Pure: `map.tsx` draws and the widget fetches.
 */

export interface TrackPoint {
  at: string;
  lat: number;
  lon: number;
}

/** A track's instant as milliseconds. Its dataset holds UTC without a zone,
 * so one without a zone is read as UTC rather than local time. */
export function instantOf(at: string): number {
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at : `${at}Z`);
}

/** A selected-time variable's value as milliseconds, or null for none: a
 * timestamp's ISO text, or a date's day (its start, in UTC). */
export function selectedTimeOf(value: unknown): number | null {
  // No blank check: a blank parses to nothing below (one survived the sweep
  // as equivalent).
  if (typeof value !== "string") return null;
  const text = value.trim();
  // A date is its day's start in UTC, said outright: V8 reads "2026-01-01Z"
  // the same way, so a sweep cannot tell this apart, but not every engine
  // accepts that spelling.
  const ms = /^\d{4}-\d{2}-\d{2}$/.test(text) ? Date.parse(`${text}T00:00:00Z`) : instantOf(text);
  return Number.isFinite(ms) ? ms : null;
}

/** The breadcrumb line through a track's fixes, as GeoJSON for the map's
 * shape layer ([longitude, latitude], as GeoJSON has it). None for fewer than
 * two fixes: one position is a pin, not a path. */
export function trackShape(points: readonly TrackPoint[]): { type: "LineString"; coordinates: number[][] } | null {
  if (points.length < 2) return null;
  return { type: "LineString", coordinates: points.map((p) => [p.lon, p.lat]) };
}

/** Where the object was at `at` - its last fix at or before it - or its last
 * fix of all when no time is selected. Null before its first fix: it was not
 * yet anywhere this track knows. */
export function positionAt(points: readonly TrackPoint[], at: number | null): TrackPoint | null {
  if (at === null) return points.length ? points[points.length - 1]! : null;
  let found: TrackPoint | null = null;
  for (const point of points) {
    if (instantOf(point.at) <= at) found = point;
    else break;
  }
  return found;
}

/** The span the timeline covers: the first fix of any track to the last. */
export function extentOf(tracks: readonly (readonly TrackPoint[])[]): { start: number; end: number } | null {
  const instants = tracks.flatMap((t) => t.map((p) => instantOf(p.at)));
  if (!instants.length) return null;
  return { start: Math.min(...instants), end: Math.max(...instants) };
}

/** A selected time as the variable holds it. */
export function selectedTimeText(ms: number): string {
  return new Date(ms).toISOString();
}

// ---- the rest of p.303's time configuration (§558) --------------------------

export interface TimeWindow {
  start: number | null;
  end: number | null;
}

/** p.303's "Time window: Control the time window using two Workshop variables
 * of type Timestamp or Date." Either end may be open. */
export function windowOf(start: unknown, end: unknown): TimeWindow {
  return { start: selectedTimeOf(start), end: selectedTimeOf(end) };
}

/** A track's fixes inside the window: the map shows where things were then. */
export function withinWindow(points: readonly TrackPoint[], window: TimeWindow): TrackPoint[] {
  return points.filter((p) => {
    const at = instantOf(p.at);
    return (window.start === null || at >= window.start) && (window.end === null || at <= window.end);
  });
}

/** The span the timeline covers: the window where it says, the tracks where
 * it does not. None while there is nothing to span. */
export function timelineSpan(
  extent: { start: number; end: number } | null, window: TimeWindow,
): { start: number; end: number } | null {
  const start = window.start ?? extent?.start ?? null;
  const end = window.end ?? extent?.end ?? null;
  return start !== null && end !== null && start <= end ? { start, end } : null;
}

/** Playback crosses a span in this many steps: about twenty seconds at one a
 * tenth of a second, whatever the span. */
export const PLAYBACK_STEPS = 200;

/** The next playback time, and whether it has reached the end. From no time
 * at all it starts at the beginning. */
export function nextPlayback(
  current: number | null, span: { start: number; end: number },
): { time: number; done: boolean } {
  // No floor under the step: a span of no length ends on its first step
  // either way (a floor survived the sweep as equivalent).
  const step = (span.end - span.start) / PLAYBACK_STEPS;
  const from = current === null || current >= span.end ? span.start : current;
  const next = Math.min(span.end, from + step);
  return { time: next, done: next >= span.end };
}

/** p.303's "Auto pause at: Use a timestamp array variable to automatically
 * pause playback at specific times": the first pause this step crosses, where
 * playback stops. */
export function pauseCrossed(from: number | null, to: number, pauses: readonly number[]): number | null {
  const crossed = pauses.filter((p) => (from === null || p > from) && p <= to);
  return crossed.length ? Math.min(...crossed) : null;
}

/** The pause times an array variable holds, unreadable ones left out. */
export function pausesOf(value: unknown): number[] {
  return Array.isArray(value)
    ? value.map(selectedTimeOf).filter((t): t is number => t !== null)
    : [];
}

export type TimeZone = "utc" | "local";
export type TimeFormat = "local" | "12" | "24";

/** p.303's "Time zone: Local or UTC", and for Local its "Time format of
 * 12-hour, 24-hour, or Local". UTC is ISO, as the selected time is stored. */
export function timeLabel(ms: number, zone: TimeZone = "utc", format: TimeFormat = "local"): string {
  if (zone !== "local") return new Date(ms).toISOString().replace(".000Z", "Z");
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "medium",
    ...(format === "local" ? {} : { hour12: format === "12" }),
  }).format(new Date(ms));
}
