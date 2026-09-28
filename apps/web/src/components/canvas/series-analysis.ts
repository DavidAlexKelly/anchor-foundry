/**
 * The Time Series Analysis widget's plots (§647; `workshop` p.392-398).
 *
 * > "Add time series data from the Ontology … then derive new plots by
 * > selecting New Plot. Plots can be organized across multiple canvases
 * > within the same analysis." (p.392)
 *
 * > "Control series with object sets: Initialize the analysis with a
 * > controlled set of time series by specifying object sets and time series
 * > properties. Users cannot delete or edit the data configuration for these
 * > series but can customize the display from the Plot Details panel."
 * > (p.396)
 *
 * A **root plot** is one object's time series property, from the widget's
 * object set. A **derived plot** is another plot with one more of p.583-586's
 * transforms (§524, §525, §532) at the end of its chain: *Cumulative
 * aggregate*, *Rolling aggregate*, *Periodic aggregate*, *Derivative*,
 * *Integral*, *Shift time series*, and a *Formula time series* over its one
 * input. So a derived plot's points are asked for as its root's series
 * through its whole chain, which is the server's own transform machinery,
 * and a plot derived from a derived plot is a longer chain rather than a
 * computation here.
 *
 * Pure: the widget reads each plot's points and draws them.
 */

import { KIND_LABELS, type SeriesTransform, type TransformKind } from "./series-transforms";

/** The derived plot types this widget offers, as the source names them. */
export const PLOT_TYPES: TransformKind[] = [
  "cumulative", "rolling", "periodic", "derivative", "integral", "shift", "formula",
];
export const PLOT_LABELS: Partial<Record<TransformKind, string>> = {
  cumulative: "Cumulative aggregate",
  rolling: "Rolling aggregate",
  periodic: "Periodic aggregate",
  derivative: "Derivative",
  integral: "Integral",
  shift: "Shift time series",
  formula: "Formula time series",
};
/** Roots are read one object each; more than this is a table, not an analysis. */
export const MAX_ROOTS = 10;
/** Plots in one analysis, roots included. */
export const MAX_PLOTS = 24;
export const LINE_STYLES = ["solid", "dashed"] as const;
export type LineStyle = (typeof LINE_STYLES)[number];

export interface Root {
  objectId: string;
  typeId: string;
  property: string;
  objectLabel: string;
}

export interface Plot {
  id: string;
  label: string;
  canvas: number;
  style: LineStyle;
  /** A root plot's object; null on a derived plot, whose root is its parent's. */
  root: Root | null;
  parent: string | null;
  /** What a derived plot adds to its parent's chain, in order; empty on a
   * root. */
  transforms: SeriesTransform[];
}

/** One root plot per object, on the first canvas. */
export function rootPlots(
  objects: readonly { id: string; label: string }[],
  typeId: string,
  property: string,
): Plot[] {
  return objects.slice(0, MAX_ROOTS).map((o) => ({
    id: `root:${o.id}`,
    label: o.label,
    canvas: 1,
    style: "solid",
    root: { objectId: o.id, typeId, property, objectLabel: o.label },
    parent: null,
    transforms: [],
  }));
}

/** The roots now in the set, with the derived plots whose roots are still
 * there. A derived plot keeps its canvas and style; a root keeps the reader's
 * canvas and style when its object is still in the set. */
export function withRoots(plots: readonly Plot[], roots: readonly Plot[]): Plot[] {
  const kept = new Map(plots.filter((p) => p.root).map((p) => [p.id, p]));
  const nextRoots = roots.map((r) => {
    const was = kept.get(r.id);
    return was ? { ...r, canvas: was.canvas, style: was.style } : r;
  });
  const ids = new Set(nextRoots.map((r) => r.id));
  const derived = plots.filter((p) => !p.root && rootOf(plots, p.id) !== null
    && ids.has(rootOf(plots, p.id)!.id));
  return [...nextRoots, ...derived];
}

function byId(plots: readonly Plot[]): Map<string, Plot> {
  return new Map(plots.map((p) => [p.id, p]));
}

/** The root plot a plot descends from, or null for one whose chain is broken. */
export function rootOf(plots: readonly Plot[], id: string): Plot | null {
  const all = byId(plots);
  const seen = new Set<string>();
  let at = all.get(id);
  while (at && !at.root) {
    if (seen.has(at.id) || !at.parent) return null;
    seen.add(at.id);
    at = all.get(at.parent);
  }
  return at ?? null;
}

/** A plot's transforms, from its root's series to itself. */
export function chainOf(plots: readonly Plot[], id: string): SeriesTransform[] {
  const all = byId(plots);
  const chain: SeriesTransform[] = [];
  const seen = new Set<string>();
  let at = all.get(id);
  while (at && !at.root && !seen.has(at.id)) {
    seen.add(at.id);
    chain.unshift(...at.transforms);
    at = at.parent ? all.get(at.parent) : undefined;
  }
  return chain;
}

/** The plots with one derived from `parent` by `transforms`, on `canvas`,
 * under an id none has, named for its first transform; unchanged at the cap,
 * for a parent that is not there, or with no transform. */
export function withDerived(
  plots: readonly Plot[], parent: string, transforms: readonly SeriesTransform[], canvas: number,
): Plot[] {
  const from = byId(plots).get(parent);
  const first = transforms[0];
  if (!from || !first || plots.length >= MAX_PLOTS) return [...plots];
  let n = plots.length + 1;
  while (plots.some((p) => p.id === `plot-${n}`)) n += 1;
  const kind = PLOT_LABELS[first.kind] ?? KIND_LABELS[first.kind];
  return [...plots, {
    id: `plot-${n}`, label: `${kind} of ${from.label}`, canvas, style: "solid",
    root: null, parent, transforms: [...transforms],
  }];
}

/** The plots without one, and without every plot derived from it: a plot
 * whose input is gone has nothing to be computed from. A root cannot be
 * removed, since the object set controls it. */
export function withoutPlot(plots: readonly Plot[], id: string): Plot[] {
  const target = byId(plots).get(id);
  if (!target || target.root) return [...plots];
  const gone = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const p of plots) {
      if (!gone.has(p.id) && p.parent && gone.has(p.parent)) {
        gone.add(p.id);
        grew = true;
      }
    }
  }
  return plots.filter((p) => !gone.has(p.id));
}

export function withPlotSetting<K extends "canvas" | "style" | "label">(
  plots: readonly Plot[], id: string, key: K, value: Plot[K],
): Plot[] {
  return plots.map((p) => (p.id === id ? { ...p, [key]: value } : p));
}

/** The canvases to draw: the first always, every one a plot is on, and any
 * the reader added and has not put a plot on yet, in order. */
export function canvasesOf(plots: readonly Plot[], added: number): number[] {
  const used = new Set(plots.map((p) => p.canvas));
  const last = Math.max(1, added, ...used);
  return Array.from({ length: last }, (_, n) => n + 1)
    .filter((c) => c === 1 || used.has(c) || c <= added);
}

export interface Reading { t: number; v: number }

/** A series' points as readings: those with a time and a finite value, in
 * time order. A reading with no value is a gap and is left out. */
export function readingsOf(points: readonly { at: unknown; value: unknown }[]): Reading[] {
  const out: Reading[] = [];
  for (const p of points) {
    const t = typeof p.at === "string" ? Date.parse(p.at) : NaN;
    const v = p.value === null || p.value === "" ? NaN : Number(p.value);
    if (Number.isFinite(t) && Number.isFinite(v)) out.push({ t, v });
  }
  return out.sort((a, b) => a.t - b.t);
}

/** p.395's *Statistics*: "The minimum … maximum … mean value of the
 * plot within the current view range." Null for a plot with no readings in
 * it. */
export function statsOf(
  readings: readonly Reading[], range: { from: number; to: number } | null = null,
): { min: number; max: number; mean: number; count: number } | null {
  const inside = range ? readings.filter((r) => r.t >= range.from && r.t <= range.to) : readings;
  if (inside.length === 0) return null;
  let min = Infinity;
  let max = -Infinity;
  let sum = 0;
  for (const r of inside) {
    min = Math.min(min, r.v);
    max = Math.max(max, r.v);
    sum += r.v;
  }
  return { min, max, mean: sum / inside.length, count: inside.length };
}

/** The extent of several plots' readings, time and value, padded so a flat
 * line is not drawn on the frame's edge. Null when there is nothing. */
export function extentOf(series: readonly (readonly Reading[])[]): {
  t0: number; t1: number; v0: number; v1: number;
} | null {
  let t0 = Infinity; let t1 = -Infinity; let v0 = Infinity; let v1 = -Infinity;
  for (const readings of series) {
    for (const r of readings) {
      t0 = Math.min(t0, r.t); t1 = Math.max(t1, r.t);
      v0 = Math.min(v0, r.v); v1 = Math.max(v1, r.v);
    }
  }
  if (!Number.isFinite(t0)) return null;
  if (t1 === t0) { t0 -= 1; t1 += 1; }
  const pad = v1 === v0 ? Math.max(1, Math.abs(v0) * 0.1) : (v1 - v0) * 0.05;
  return { t0, t1, v0: v0 - pad, v1: v1 + pad };
}

/** A plot's line as an SVG path on a frame, over an extent. */
export function pathOf(
  readings: readonly Reading[],
  extent: { t0: number; t1: number; v0: number; v1: number },
  frame: { width: number; height: number },
): string {
  const x = (t: number) => ((t - extent.t0) / (extent.t1 - extent.t0)) * frame.width;
  const y = (v: number) => frame.height - ((v - extent.v0) / (extent.v1 - extent.v0)) * frame.height;
  return readings.map((r, n) => `${n === 0 ? "M" : "L"}${x(r.t).toFixed(1)},${y(r.v).toFixed(1)}`).join("");
}
