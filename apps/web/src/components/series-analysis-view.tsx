"use client";

/**
 * A saved time series analysis in its own resource view (§668; `workshop`
 * p.397).
 *
 * > "Save as a time series analysis resource: … Saved analyses can be opened
 * > in a standalone resource view or loaded into the Workshop widget using its
 * > RID." (p.397)
 *
 * Read only: the view the analysis saved - its plots, canvases, event sets
 * and axes - with its readings read now, as the widget reads them. Changing
 * it is the widget's; this is where an analysis is looked at, and where its
 * RID is found.
 */

import { useQueries } from "@tanstack/react-query";

import { objects as objApi, type SeriesAnalysis } from "@/lib/api";
import { SeriesAnalysisChart } from "@/components/canvas/SeriesAnalysisChart";
import { PALETTE } from "@/components/canvas/charts";
import {
  axesOf, axisOf, axisSettingsOf, canvasesOf, chainOf, displayOf, eventCount, eventsOf, liveEventSets,
  openedView, readingsOf, rootOf, statsOf,
} from "@/components/canvas/series-analysis";
import { transformsProblem } from "@/components/canvas/series-transforms";

export function SeriesAnalysisView({ workspaceId, analysis }: { workspaceId: string; analysis: SeriesAnalysis }) {
  // No object set controls these roots: every saved root is kept as saved.
  const view = openedView(analysis.state, []);
  const plots = view.plots;
  const readingsFor = useQueries({
    queries: plots.map((plot) => {
      const root = rootOf(plots, plot.id)?.root ?? null;
      const chain = chainOf(plots, plot.id);
      return {
        queryKey: ["canvas-series-analysis-plot", root?.objectId, root?.property, JSON.stringify(chain)],
        queryFn: () => objApi.seriesPoints(workspaceId, root!.typeId, root!.objectId, root!.property,
          { transforms: chain }),
        enabled: !!root && !transformsProblem(chain),
      };
    }),
  });
  const readings = plots.map((_, n) => readingsOf(readingsFor[n]?.data?.points ?? []));
  const sets = liveEventSets(view.eventSets, plots);
  const eventsFor = useQueries({
    queries: sets.map((set) => {
      const root = rootOf(plots, set.plot)?.root ?? null;
      return set.linked
        ? {
          queryKey: ["canvas-series-analysis-linked-events", root?.objectId, JSON.stringify(set.linked)],
          queryFn: () => objApi.linkedEvents(workspaceId, root!.typeId, root!.objectId, set.linked),
          enabled: !!root,
        }
        : {
          queryKey: ["canvas-series-analysis-events", root?.objectId, root?.property,
            JSON.stringify(chainOf(plots, set.plot)), set.op, set.value],
          queryFn: () => objApi.seriesEvents(workspaceId, root!.typeId, root!.objectId, root!.property,
            { op: set.op, value: set.value, transforms: chainOf(plots, set.plot) }),
          enabled: !!root,
        };
    }),
  });
  const events = sets.map((_, n) => eventsOf(eventsFor[n]?.data?.events ?? []));
  const colorOf = (n: number) => PALETTE[n % PALETTE.length]!;

  if (plots.length === 0) {
    return <p className="login-note" data-testid="series-analysis-view-empty">This analysis saved no plots.</p>;
  }
  return (
    <div data-testid="series-analysis-view">
      {canvasesOf(plots, view.canvases).map((canvas) => (
        <SeriesAnalysisChart key={canvas} canvas={canvas}
          axes={axesOf(plots, canvas).map((axis) => ({ axis, settings: axisSettingsOf(view.axes, canvas, axis) }))}
          events={sets.flatMap((set, n) => {
            const at = plots.findIndex((p) => p.id === set.plot);
            return set.highlight && plots[at]?.canvas === canvas
              ? [{ id: set.id, color: colorOf(at), events: events[n] ?? [] }] : [];
          })}
          plots={plots.map((plot, n) => ({ plot, n })).filter(({ plot }) => plot.canvas === canvas)
            .map(({ plot, n }) => ({ id: plot.id, label: plot.label, color: colorOf(n),
              dashed: plot.style === "dashed", display: displayOf(plot), axis: axisOf(plot),
              readings: readings[n] ?? [] }))} />
      ))}
      <table className="data-grid" data-testid="series-plots">
        <thead><tr><th>Plot</th><th>Canvas</th><th>Min</th><th>Max</th><th>Mean</th></tr></thead>
        <tbody>
          {plots.map((plot, n) => {
            const stats = statsOf(readings[n] ?? []);
            return (
              <tr key={plot.id} data-label={plot.label}>
                <td><span style={{ color: colorOf(n) }}>■</span> {plot.label}</td>
                <td>{plot.canvas}</td>
                <td data-stat="min">{stats ? Number(stats.min.toFixed(3)) : "—"}</td>
                <td data-stat="max">{stats ? Number(stats.max.toFixed(3)) : "—"}</td>
                <td data-stat="mean">{stats ? Number(stats.mean.toFixed(3)) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {sets.length > 0 && (
        <table className="data-grid" data-testid="series-event-sets" style={{ marginTop: 6 }}>
          <thead><tr><th>Event set</th><th>Events</th></tr></thead>
          <tbody>
            {sets.map((set, n) => (
              <tr key={set.id} data-label={set.label}>
                <td>{set.label}</td>
                <td data-stat="events">{eventsFor[n]?.data ? eventCount(events[n] ?? []) : "…"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
