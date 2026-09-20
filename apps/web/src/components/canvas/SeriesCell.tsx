"use client";

/** p.583's time series column: a latest value and a sparkline (§402).
 *
 * > "The Object table widget is configured to display two visualizations for
 * > each time series: the latest value of the time series on the left, and a
 * > sparkline showing the history of the time series on the right." (p.583)
 *
 * **The raw property value is a series id, and showing it is showing nothing.**
 * Before this, a `time_series` column rendered through `PropertyValue` like
 * any other scalar, which put an opaque key in the cell — the identifier of
 * the readings rather than the readings. Both halves of p.583 replace it.
 *
 * The geometry is `sparkline.ts`'s; this file only draws.
 */
import { Sparkline } from "./Sparkline";
import { latest, type Point } from "./sparkline";
import { showNumber, type NumberFormat } from "./value-formats";

export function SeriesCell({
  points,
  /**
   * p.174's value formatting for this column, or `null` for the plain
   * localised number.
   *
   * **Module-local, and it has to be.** The comment here used to say this was
   * "the ontology's formatter (§157) when the property has one" — which was
   * wrong twice over. No call site passed anything, so every column was
   * `toLocaleString()`; and §157 permits a formatter only on an `integer` or a
   * `float`, so the `time_series` property behind this cell could never have
   * carried one. p.174 puts the formatter on the widget for exactly that
   * reason.
   */
  format = null,
  pending = false,
}: {
  points: readonly Point[] | undefined;
  format?: NumberFormat | null;
  pending?: boolean;
}) {
  const list = points ?? [];
  const value = latest(list);

  return (
    <span className="canvas-series" data-testid="series-cell">
      <span className="canvas-series-value" data-testid="series-latest">
        {pending ? "" : value === null ? "—" : showNumber(value, format)}
      </span>
      {/* The line itself is `Sparkline`'s, shared with the Metric Card
          (p.329) so the stroke, the empty wording and the non-scaling trick
          have one home. */}
      <Sparkline points={points} pending={pending} />
    </span>
  );
}
