"use client";

/** A time series drawn as a thumbnail line (§402, §403).
 *
 * The SVG half of `sparkline.ts`, split out of `SeriesCell` when the Metric
 * Card needed the same line without the value beside it (p.329's "Show
 * visualization?"). One drawing, two widgets (§292) - two would be two places
 * for the stroke, the empty wording and the non-scaling trick to drift.
 */
import { emptyReason, path, type Point } from "./sparkline";

/** The drawing box, in the SVG's own units.
 *
 * A `viewBox` rather than pixels: the caller decides how much room the line
 * gets and the path is computed once, so a resize re-scales rather than
 * re-asking the server.
 */
const BOX = { width: 100, height: 20 };

export function Sparkline({
  points,
  pending = false,
  testId = "series-spark",
}: {
  points: readonly Point[] | undefined;
  pending?: boolean;
  testId?: string;
}) {
  if (pending) {
    // Distinct from "no readings", which is a fact about the data rather than
    // about the request. A line that said "No readings" while the answer was
    // still coming would be wrong for as long as the read took.
    return <span className="soft canvas-series-pending">…</span>;
  }
  const list = points ?? [];
  const d = path(list, BOX);
  if (!d) {
    // Said rather than left blank: "there are no readings" and "there is one
    // reading" are different answers, and an empty box gives neither.
    return (
      <span className="soft canvas-series-empty" data-testid={`${testId}-empty`}>
        {emptyReason(list)}
      </span>
    );
  }
  return (
    <svg
      className="canvas-series-spark"
      viewBox={`0 0 ${BOX.width} ${BOX.height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      data-testid={testId}
    >
      {/* `vector-effect` keeps the stroke one pixel however the box is
          stretched - without it a wider box draws a thicker line, because
          `preserveAspectRatio="none"` scales strokes with the geometry. */}
      <path d={d} fill="none" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
