/** Reading a time series set variable's points (§403).
 *
 * > "Time series set: Stores a time series property of a single object,
 * > optionally allowing the application of time series transforms to it."
 * > (p.76)
 *
 * **The variable resolves to a *question*, never to points** (decision 0009:
 * the readings stay in the dataset they arrived in), so a widget bound to one
 * asks it. That resolution — unwrap the reference, fetch, hand back points —
 * was written inline in the Chart, and the Metric Card's sparkline (p.329)
 * needs it identically. One implementation, imported by both (§292): two
 * would be two places for the interval, the aggregate and the
 * nothing-picked-yet case to drift.
 */
import { useQuery } from "@tanstack/react-query";

import { objects as objApi } from "@/lib/api";
import { useCanvasVariable } from "./context";
import { toPoints, type Point } from "./sparkline";

/** What a `time_series_set` variable holds: where to look, not what was found. */
export interface SeriesRef {
  object_type_id: string;
  instance_id: string;
  property: string;
  interval: string;
  aggregate: string;
}

export interface SeriesRead {
  points: Point[] | undefined;
  /** The reference itself, for a widget that wants to caption what it drew. */
  ref: SeriesRef | null;
  isPending: boolean;
  isError: boolean;
  /** True while the variable has not resolved to a reference yet.
   *
   * Distinct from "no points": nothing has been asked, so an empty chart here
   * would be the widget claiming a reading it never took. The Chart says
   * "nothing picked yet" on this and the Metric Card draws no line. */
  unresolved: boolean;
}

export function useSeriesPoints(
  workspaceId: string,
  seriesVariable: string | null | undefined,
): SeriesRead {
  const ref = useCanvasVariable(seriesVariable ?? null) as SeriesRef | null;
  const bound = !!seriesVariable;
  const result = useQuery({
    // Keyed on the reference rather than the variable id: the same variable
    // pointing at a different object is a different question, and a key that
    // did not say so would show the previous object's line.
    queryKey: ["canvas-series-points", JSON.stringify(ref ?? null)],
    queryFn: () =>
      objApi.seriesPoints(
        workspaceId, ref!.object_type_id, ref!.instance_id, ref!.property,
        { interval: ref!.interval, aggregate: ref!.aggregate },
      ),
    enabled: bound && !!ref,
  });
  return {
    points: result.data ? toPoints(result.data.points) : undefined,
    ref,
    isPending: bound && !!ref && result.isPending,
    isError: result.isError,
    unresolved: bound && !ref,
  };
}
