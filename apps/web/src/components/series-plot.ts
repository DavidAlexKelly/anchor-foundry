/**
 * The geometry of a time series line (parity `docs/parity/ontology.md` §4.1;
 * Foundry `object-views` p.10–11's "time series → interactive chart").
 *
 * **Pure, and its own module**, which is the boundary `canvas/pure.ts` draws:
 * where a point lands is a rule, and a rule tangled into a component is one
 * nobody can make fail. Everything here is arithmetic on numbers — no SVG, no
 * React, no dates beyond parsing.
 */

export interface SeriesPoint {
  at: unknown;
  value: unknown;
}

export interface PlottedPoint {
  x: number;
  y: number;
  /** The original values, for the tooltip and the accessible table. */
  at: number;
  value: number;
}

export interface Plot {
  points: PlottedPoint[];
  path: string;
  min: number;
  max: number;
  first: number;
  last: number;
}

/** A point the arithmetic can use, or null.
 *
 * A series arrives from DuckDB through JSON, so a timestamp is a string and a
 * value may be a string too when the column was read loosely. Anything that
 * does not parse is dropped rather than plotted as zero: a gap in a line is
 * honest, and a zero is a reading that never happened.
 */
function numeric(point: SeriesPoint): { at: number; value: number } | null {
  // **`Number(null)` is `0`, and `Number("")` is too** - both finite, so a
  // `Number.isFinite` guard alone lets a missing reading through as a real
  // zero. Caught by the test that says a gap is honest and a zero is a
  // reading that never happened; the emptiness check has to come first.
  if (point.value === null || point.value === undefined || point.value === "") return null;
  if (point.at === null || point.at === undefined || point.at === "") return null;
  const at = typeof point.at === "number" ? point.at : Date.parse(String(point.at));
  const value = typeof point.value === "number" ? point.value : Number(point.value);
  if (!Number.isFinite(at) || !Number.isFinite(value)) return null;
  return { at, value };
}

/**
 * Lay a series out inside a `width` × `height` box.
 *
 * **A flat series sits in the middle rather than dividing by zero.** A sensor
 * reading the same number all week is the most ordinary series there is, and
 * `(v - min) / (max - min)` is `0/0` for every one of its points.
 *
 * **A single point is drawn, not skipped.** One reading is a fact; an empty
 * chart would say there were none.
 */
export function plot(
  raw: SeriesPoint[],
  { width, height, padding = 4 }: { width: number; height: number; padding?: number },
): Plot | null {
  const points = raw.map(numeric).filter((p): p is { at: number; value: number } => p !== null);
  if (points.length === 0) return null;

  const values = points.map((p) => p.value);
  const times = points.map((p) => p.at);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const first = Math.min(...times);
  const last = Math.max(...times);

  const usableWidth = Math.max(1, width - padding * 2);
  const usableHeight = Math.max(1, height - padding * 2);
  const spanX = last - first;
  const spanY = max - min;

  const plotted = points.map((p) => ({
    ...p,
    // A single point, or every point at the same instant, goes to the middle
    // horizontally for the same reason a flat series does vertically.
    x: padding + (spanX === 0 ? usableWidth / 2 : ((p.at - first) / spanX) * usableWidth),
    // SVG's y grows downward, so the larger value gets the smaller y.
    y: padding + (spanY === 0 ? usableHeight / 2 : (1 - (p.value - min) / spanY) * usableHeight),
  }));

  return {
    points: plotted,
    path: plotted.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" "),
    min,
    max,
    first,
    last,
  };
}
