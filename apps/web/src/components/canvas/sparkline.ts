/** p.583's sparkline: a time series as a thumbnail (§402).
 *
 * > "The Object table widget is configured to display two visualizations for
 * > each time series: the latest value of the time series on the left, and a
 * > sparkline showing the history of the time series on the right." (p.583)
 *
 * Geometry only, in the shape `pie-chart.ts` set: the arithmetic is what a
 * wrong line lives in, and none of it needs a browser to check. The widget
 * draws the path this returns.
 */

/** One reading. `at` is an ISO instant as the API sends it. */
export interface Point {
  at: string;
  value: number | null;
}

export interface Box {
  width: number;
  height: number;
}

/** A reading worth drawing: a finite number at a usable instant.
 *
 * **Nulls are dropped rather than plotted as zero**, which is the difference
 * between "no reading" and "a reading of nothing" - a gap in a sensor's
 * history drawn as a dive to zero is a false claim about the sensor. They are
 * dropped rather than left as gaps in the line for a thumbnail's reason: a
 * sparkline a centimetre wide cannot show a gap, so the honest options are a
 * continuous line through what is known or no line at all.
 */
export function usable(points: readonly Point[]): Point[] {
  return points.filter(
    (p) => typeof p.value === "number" && Number.isFinite(p.value)
      && !Number.isNaN(Date.parse(p.at)),
  );
}

/** The low and high of a series, as drawn.
 *
 * **A flat series gets a band rather than a zero-height range**, because
 * dividing by that range is how every point lands on the same pixel or on
 * NaN. A line that is genuinely flat should be drawn flat - through the
 * middle - and that is what a band around the value produces.
 */
export function range(points: readonly Point[]): { low: number; high: number } {
  const values = points.map((p) => p.value as number);
  if (values.length === 0) return { low: 0, high: 1 };
  const low = Math.min(...values);
  const high = Math.max(...values);
  if (low === high) return { low: low - 0.5, high: high + 0.5 };
  return { low, high };
}

/**
 * The SVG path for a series inside a box, or `""` when there is nothing to draw.
 *
 * **Spaced by time, not by index.** Readings do not arrive evenly - a sensor
 * that went quiet for a week and then reported twice in an hour would, on
 * index spacing, draw that week as one step and the hour as another. The
 * shape of a history is the shape of *when*, which is the whole reason the
 * points carry an instant rather than an order.
 *
 * **A single point draws nothing.** One reading has no shape, and a dot in a
 * column of lines reads as a different kind of thing rather than as a shorter
 * history.
 */
export function path(points: readonly Point[], box: Box): string {
  const drawn = usable(points);
  if (drawn.length < 2) return "";
  const times = drawn.map((p) => Date.parse(p.at));
  // `drawn.length >= 2` is checked above, so both ends exist; the `?? 0` is
  // for the type checker rather than for a case that can happen.
  const first = times[0] ?? 0;
  const span = (times[times.length - 1] ?? first) - first;
  const { low, high } = range(drawn);
  const height = high - low;
  return drawn
    .map((p, i) => {
      // Every instant identical (several readings at one timestamp) would
      // divide by zero; they stack at the left, which is where they are.
      const x = span === 0 ? 0 : (((times[i] ?? first) - first) / span) * box.width;
      // Inverted, because SVG's y grows downwards and a value's does not.
      const y = box.height - ((p.value as number) - low) / height * box.height;
      return `${i === 0 ? "M" : "L"}${round(x)} ${round(y)}`;
    })
    .join(" ");
}

/** Two decimals. A path string is markup, and sixteen digits of float noise
 * per point is bytes on the wire for pixels nobody can see. */
function round(n: number): number {
  return Math.round(n * 100) / 100;
}

/**
 * p.583's "latest value of the time series", or `null` when there is none.
 *
 * The last *usable* reading rather than the last row: a series whose final
 * point is null has a latest value, and it is the one before.
 */
export function latest(points: readonly Point[]): number | null {
  const drawn = usable(points);
  return drawn.length === 0 ? null : (drawn[drawn.length - 1]?.value ?? null);
}

/** Why a column shows no line, or `null` when it shows one.
 *
 * Three states rather than two, because "this object has no series" and "this
 * series has one reading" are different answers and an empty cell gives
 * neither. */
export function emptyReason(points: readonly Point[]): string | null {
  const drawn = usable(points);
  if (drawn.length === 0) return "No readings";
  if (drawn.length === 1) return "One reading";
  return null;
}
