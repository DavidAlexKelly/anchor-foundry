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
import { emptyReason, latest, path, type Point } from "./sparkline";

/** The drawing box, in the SVG's own units.
 *
 * A `viewBox` rather than pixels: the cell decides how wide the column is and
 * the path is computed once, so a resized column re-scales rather than
 * re-asking the server.
 */
const BOX = { width: 100, height: 20 };

export function SeriesCell({
  points,
  /** How the latest value is written. The ontology's formatter (§157) when the
   * property has one, so a column of readings is punctuated the way the same
   * property is everywhere else. */
  format = (n: number) => n.toLocaleString(),
  pending = false,
}: {
  points: readonly Point[] | undefined;
  format?: (value: number) => string;
  pending?: boolean;
}) {
  if (pending) {
    // Distinct from "no readings", which is a fact about the object rather
    // than about the request. A cell that said "No readings" while the answer
    // was still coming would be wrong for as long as the read took.
    return <span className="soft canvas-series-pending">…</span>;
  }
  const list = points ?? [];
  const value = latest(list);
  const empty = emptyReason(list);
  const d = path(list, BOX);

  return (
    <span className="canvas-series" data-testid="series-cell">
      <span className="canvas-series-value" data-testid="series-latest">
        {value === null ? "—" : format(value)}
      </span>
      {d ? (
        <svg
          className="canvas-series-spark"
          viewBox={`0 0 ${BOX.width} ${BOX.height}`}
          preserveAspectRatio="none"
          aria-hidden="true"
          data-testid="series-spark"
        >
          {/* `vector-effect` keeps the stroke one pixel however the box is
              stretched — without it a column twice as wide draws a line twice
              as thick, because `preserveAspectRatio="none"` scales strokes
              with the geometry. */}
          <path d={d} fill="none" vectorEffect="non-scaling-stroke" />
        </svg>
      ) : (
        // Said rather than left blank: "this object has no series" and "this
        // series has one reading" are different answers, and an empty cell
        // gives neither.
        <span className="soft canvas-series-empty" data-testid="series-empty">{empty}</span>
      )}
    </span>
  );
}
