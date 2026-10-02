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

import {
  FILTER_WORDS, KIND_LABELS, MAX_SPAN, type FilterOperator, type SeriesTransform, type TimeUnit,
  type TransformKind,
} from "./series-transforms";
import { instantOf } from "./timeline";

/** p.393's Bollinger bands (§649), which is three plots rather than one
 * transform. */
export type PlotType = TransformKind | "bollinger";
/** The derived plot types this widget offers, as the source names them, in
 * p.393's order. */
export const PLOT_TYPES: PlotType[] = [
  "bollinger", "combine", "linear_aggregate", "cumulative", "rolling", "periodic", "derivative", "integral", "shift",
  "event_statistics", "formula", "filter", "sample",
];
export const PLOT_LABELS: Partial<Record<PlotType, string>> = {
  bollinger: "Bollinger bands",
  combine: "Combine time series",
  linear_aggregate: "Linear aggregation",
  event_statistics: "Event statistics",
  cumulative: "Cumulative aggregate",
  rolling: "Rolling aggregate",
  periodic: "Periodic aggregate",
  derivative: "Derivative",
  integral: "Integral",
  shift: "Shift time series",
  formula: "Formula time series",
  // §648: p.393's two more.
  filter: "Filter time series",
  sample: "Sample",
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
  /** p.394's display settings the reader changed (§655); `displayOf` fills
   * in the rest. */
  display?: Partial<PlotDisplay>;
  /** p.394's *Axis*: which of its canvas's axes the plot is on (§656). */
  axis?: number;
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

export function withPlotSetting<K extends "canvas" | "style" | "label" | "axis">(
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
    // The server's readings name no zone and are UTC: `Date.parse` would read
    // them in the reader's own zone (§659 found it, in a browser in Tokyo).
    const t = typeof p.at === "string" ? instantOf(p.at) ?? NaN : NaN;
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

/** The time the plots of a canvas span, together; a lone instant is given a
 * width to draw in. Null with no readings. */
export function timesOf(series: readonly (readonly Reading[])[]): { t0: number; t1: number } | null {
  let t0 = Infinity; let t1 = -Infinity;
  for (const readings of series) {
    for (const r of readings) { t0 = Math.min(t0, r.t); t1 = Math.max(t1, r.t); }
  }
  if (!Number.isFinite(t0)) return null;
  return t1 === t0 ? { t0: t0 - 1, t1: t1 + 1 } : { t0, t1 };
}

/** p.394-395's *Axis* options (§656): each canvas has axes its plots are
 * assigned to, each with "Unit", "Auto scale", "Axis min" and "Axis max",
 * and p.395's "Align axis", "Log scale" and "Invert axis". The unit is a
 * label: a time series property carries no unit to convert from. */
export const AXIS_ALIGNS = ["left", "right"] as const;
export type AxisAlign = (typeof AXIS_ALIGNS)[number];
export interface AxisSettings {
  unit: string;
  auto: boolean;
  min: number | null;
  max: number | null;
  log: boolean;
  invert: boolean;
  align: AxisAlign;
}
export const DEFAULT_AXIS: AxisSettings = {
  unit: "", auto: true, min: null, max: null, log: false, invert: false, align: "left",
};
/** Axes on one canvas. */
export const MAX_AXES = 4;
export const MAX_UNIT = 24;
/** Each canvas's axes' settings the reader changed, by `canvas:axis`. */
export type Axes = Record<string, Partial<AxisSettings>>;

export function axisOf(plot: Pick<Plot, "axis">): number {
  return plot.axis ?? 1;
}

/** The axes a canvas's plots are on, in order; the first when none is. */
export function axesOf(plots: readonly Plot[], canvas: number): number[] {
  const used = new Set(plots.filter((p) => p.canvas === canvas).map(axisOf));
  return used.size ? [...used].sort((a, b) => a - b) : [1];
}

/** The number a new axis on a canvas takes; null at the cap. */
export function newAxisOf(plots: readonly Plot[], canvas: number): number | null {
  const used = axesOf(plots, canvas);
  return used.length >= MAX_AXES ? null : Math.max(...used) + 1;
}

export function axisSettingsOf(axes: Axes, canvas: number, axis: number): AxisSettings {
  return { ...DEFAULT_AXIS, ...axes[`${canvas}:${axis}`] };
}

export function withAxisSetting<K extends keyof AxisSettings>(
  axes: Axes, canvas: number, axis: number, key: K, value: AxisSettings[K],
): Axes {
  const set = key === "unit" ? (value as string).slice(0, MAX_UNIT) : value;
  const at = `${canvas}:${axis}`;
  return { ...axes, [at]: { ...axes[at], [key]: set } };
}

/** What is wrong with an axis's fixed range; null when it is scaled to its
 * readings or the range is one. */
export function axisProblem(a: AxisSettings): string | null {
  if (a.auto) return null;
  if (a.min === null || a.max === null || !Number.isFinite(a.min) || !Number.isFinite(a.max)) {
    return "An axis not scaled automatically needs a minimum and a maximum.";
  }
  if (a.min >= a.max) return "The axis minimum must be below its maximum.";
  if (a.log && a.min <= 0) return "A log axis starts above zero.";
  return null;
}

export interface Scale { v0: number; v1: number; log: boolean; invert: boolean }

/** An axis's value range: its fixed one, or its plots' readings, padded - on
 * a log axis only the readings above zero, padded by a ratio. A fixed range
 * with a problem is scaled automatically. Null with nothing to scale to. */
export function scaleOf(series: readonly (readonly Reading[])[], a: AxisSettings = DEFAULT_AXIS): Scale | null {
  const shape = { log: a.log, invert: a.invert };
  if (!a.auto && axisProblem(a) === null) return { v0: a.min!, v1: a.max!, ...shape };
  let v0 = Infinity; let v1 = -Infinity;
  for (const readings of series) {
    for (const r of readings) {
      if (a.log && r.v <= 0) continue;
      v0 = Math.min(v0, r.v); v1 = Math.max(v1, r.v);
    }
  }
  if (!Number.isFinite(v0)) return null;
  if (a.log) {
    const ratio = v1 === v0 ? 2 : (v1 / v0) ** 0.05;
    return { v0: v0 / ratio, v1: v1 * ratio, ...shape };
  }
  const pad = v1 === v0 ? Math.max(1, Math.abs(v0) * 0.1) : (v1 - v0) * 0.05;
  return { v0: v0 - pad, v1: v1 + pad, ...shape };
}

/** How far up an axis a value sits, from 0 at its foot to 1 at its head. */
export function fractionOf(scale: Scale, v: number): number {
  const f = scale.log
    ? (Math.log10(v) - Math.log10(scale.v0)) / (Math.log10(scale.v1) - Math.log10(scale.v0))
    : (v - scale.v0) / (scale.v1 - scale.v0);
  return scale.invert ? 1 - f : f;
}

/** The value at a fraction up an axis: `fractionOf` backwards, for its
 * ticks. */
export function valueAt(scale: Scale, f: number): number {
  const up = scale.invert ? 1 - f : f;
  return scale.log
    ? 10 ** (Math.log10(scale.v0) + up * (Math.log10(scale.v1) - Math.log10(scale.v0)))
    : scale.v0 + up * (scale.v1 - scale.v0);
}

type Extent = { t0: number; t1: number } & Scale;
type Frame = { width: number; height: number };

/** Where each reading falls on a frame, over an extent; a log axis has no
 * place for a reading at or below zero. */
function placed(readings: readonly Reading[], extent: Extent, frame: Frame): { x: number; y: number }[] {
  return readings.filter((r) => !extent.log || r.v > 0).map((r) => ({
    x: ((r.t - extent.t0) / (extent.t1 - extent.t0)) * frame.width,
    y: frame.height - fractionOf(extent, r.v) * frame.height,
  }));
}

const at = (n: number) => n.toFixed(1);

/** p.395's *Interpolation* (§657): "Internal interpolation: The
 * interpolation method used to connect data points within the time series.
 * External interpolation: The interpolation method used before the first data
 * point and after the last data point." p.395 does not list the methods; these
 * are the usual time series ones. Internally a straight line, a step holding
 * each reading until the next (`previous`), a step to each reading from the
 * one before (`next`), a step half way between (`nearest`), or no line.
 * Externally nothing, or the first and last readings held to the canvas's
 * edges (`nearest`). */
export const INTERNAL_INTERPOLATIONS = ["linear", "previous", "next", "nearest", "none"] as const;
export type InternalInterpolation = (typeof INTERNAL_INTERPOLATIONS)[number];
export const EXTERNAL_INTERPOLATIONS = ["none", "nearest"] as const;
export type ExternalInterpolation = (typeof EXTERNAL_INTERPOLATIONS)[number];
type Interpolation = { internal: InternalInterpolation; external: ExternalInterpolation };
const LINEAR: Interpolation = { internal: "linear", external: "none" };

/** The corners of a plot's line, by its interpolation; none without one. */
function cornersOf(points: readonly { x: number; y: number }[], frame: Frame, how: Interpolation) {
  if (how.internal === "none" || points.length === 0) return [];
  const out: { x: number; y: number }[] = [points[0]!];
  for (const [n, p] of points.entries()) {
    if (n === 0) continue;
    const before = points[n - 1]!;
    if (how.internal === "previous") out.push({ x: p.x, y: before.y });
    else if (how.internal === "next") out.push({ x: before.x, y: p.y });
    else if (how.internal === "nearest") {
      const half = (before.x + p.x) / 2;
      out.push({ x: half, y: before.y }, { x: half, y: p.y });
    }
    out.push(p);
  }
  if (how.external === "nearest") {
    out.unshift({ x: 0, y: points[0]!.y });
    out.push({ x: frame.width, y: points.at(-1)!.y });
  }
  return out;
}

/** A plot's line as an SVG path on a frame, over an extent. */
export function pathOf(
  readings: readonly Reading[], extent: Extent, frame: Frame, how: Interpolation = LINEAR,
): string {
  return cornersOf(placed(readings, extent, frame), frame, how)
    .map((p, n) => `${n === 0 ? "M" : "L"}${at(p.x)},${at(p.y)}`).join("");
}

/** p.394's *Display* (§655): "Line width: The thickness of the plot line.
 * Gradient: Toggle gradient shading under the plot line. Point shape: The
 * shape of data points (circle, triangle, square, diamond, or none). Point
 * size: The size of data points." With p.395's *Point fill* and *Point
 * outline width*. */
export const POINT_SHAPES = ["none", "circle", "triangle", "square", "diamond"] as const;
export type PointShape = (typeof POINT_SHAPES)[number];
/** A point filled in the plot's colour, in white inside an outline of it, or
 * not at all. */
export const POINT_FILLS = ["line", "white", "none"] as const;
export type PointFill = (typeof POINT_FILLS)[number];
export const POINT_FILL_WORDS: Record<PointFill, string> = { line: "plot colour", white: "white", none: "none" };
export interface PlotDisplay {
  width: number;
  gradient: boolean;
  shape: PointShape;
  size: number;
  fill: PointFill;
  outline: number;
  /** p.395's *Interpolation* (§657). */
  internal: InternalInterpolation;
  external: ExternalInterpolation;
}
export const DEFAULT_DISPLAY: PlotDisplay = {
  width: 1.6, gradient: false, shape: "none", size: 5, fill: "line", outline: 1,
  internal: "linear", external: "none",
};
/** The least and most each number may be, in pixels. */
export const DISPLAY_BOUNDS = { width: [0.5, 8], size: [2, 16], outline: [0.5, 4] } as const;

export function displayOf(plot: Pick<Plot, "display">): PlotDisplay {
  return { ...DEFAULT_DISPLAY, ...plot.display };
}

/** The plots with one display setting of one changed; a number is held to
 * its bounds, and one that is no number changes nothing. */
export function withDisplay<K extends keyof PlotDisplay>(
  plots: readonly Plot[], id: string, key: K, value: PlotDisplay[K],
): Plot[] {
  let set: PlotDisplay[K] = value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return [...plots];
    const [lo, hi] = DISPLAY_BOUNDS[key as keyof typeof DISPLAY_BOUNDS];
    set = Math.min(hi, Math.max(lo, value)) as PlotDisplay[K];
  }
  return plots.map((p) => (p.id === id ? { ...p, display: { ...p.display, [key]: set } } : p));
}

/** p.395: point size, fill and outline are "Disabled when point shape is set
 * to none", and the outline width "when point fill is set to none or is the
 * same as the plot color" - so a point without fill keeps a thin outline, or
 * it could not be seen. */
export function pointOptions(d: PlotDisplay): { size: boolean; fill: boolean; outline: boolean } {
  const points = d.shape !== "none";
  return { size: points, fill: points, outline: points && d.fill === "white" };
}

/** The width of a point's outline as drawn. */
export function outlineOf(d: PlotDisplay): number {
  return d.fill === "white" ? d.outline : d.fill === "none" ? 1 : 0;
}

/** p.394's *Gradient*: the area under a plot's line, down to the frame's
 * foot; "" with no line. */
export function areaOf(
  readings: readonly Reading[], extent: Extent, frame: Frame, how: Interpolation = LINEAR,
): string {
  const corners = cornersOf(placed(readings, extent, frame), frame, how);
  if (corners.length === 0) return "";
  return `${pathOf(readings, extent, frame, how)}L${at(corners.at(-1)!.x)},${at(frame.height)}` +
    `L${at(corners[0]!.x)},${at(frame.height)}Z`;
}

/** The points' shape as drawn: with no line and no shape a plot would not be
 * seen, so its readings are circles. */
export function shownShape(d: PlotDisplay): PointShape {
  return d.shape === "none" && d.internal === "none" ? "circle" : d.shape;
}

/** One point's marker, `size` across and centred on it; "" for none. */
export function markerOf(shape: PointShape, x: number, y: number, size: number): string {
  const r = size / 2;
  switch (shape) {
    case "circle":
      return `M${at(x - r)},${at(y)}a${at(r)},${at(r)} 0 1,0 ${at(size)},0a${at(r)},${at(r)} 0 1,0 ${at(-size)},0Z`;
    case "triangle":
      return `M${at(x)},${at(y - r)}L${at(x + r)},${at(y + r)}L${at(x - r)},${at(y + r)}Z`;
    case "square":
      return `M${at(x - r)},${at(y - r)}h${at(size)}v${at(size)}h${at(-size)}Z`;
    case "diamond":
      return `M${at(x)},${at(y - r)}L${at(x + r)},${at(y)}L${at(x)},${at(y + r)}L${at(x - r)},${at(y)}Z`;
    case "none":
      return "";
  }
}

/** Every reading's marker, as one path. */
export function markersOf(
  readings: readonly Reading[], extent: Extent, frame: Frame, shape: PointShape, size: number,
): string {
  return placed(readings, extent, frame).map((p) => markerOf(shape, p.x, p.y, size)).join("");
}


/** p.393's *Bollinger bands*: "Plot upper and lower bands at a configurable
 * number of standard deviations around a moving average" (§649). */
export interface Bands { window: number; unit: TimeUnit; deviations: number }
export const DEFAULT_BANDS: Bands = { window: 20, unit: "day", deviations: 2 };
export const MAX_DEVIATIONS = 10;

export function bandsProblem(b: Bands): string | null {
  if (!Number.isInteger(b.window) || b.window < 1 || b.window > MAX_SPAN) {
    return `The window must be a whole number from 1 to ${MAX_SPAN.toLocaleString("en-US")}.`;
  }
  if (!Number.isFinite(b.deviations) || b.deviations <= 0 || b.deviations > MAX_DEVIATIONS) {
    return `The bands are more than 0 and at most ${MAX_DEVIATIONS} standard deviations out.`;
  }
  return null;
}

/** The plots with a moving average of `parent` and a band either side of it.
 * Each band is a formula over the parent's own series with two more inputs,
 * the same series' rolling average (`y`) and rolling standard deviation
 * (`z`): the server's formula inputs (§561), read through the parent's whole
 * chain, so a band sits on its parent's points. The first point of a window
 * has no standard deviation, so its bands are gaps. Unchanged without room
 * for all three, for a parent with no root, or for bands that say too little. */
export function withBands(plots: readonly Plot[], parent: string, bands: Bands, canvas: number): Plot[] {
  const from = byId(plots).get(parent);
  const root = rootOf(plots, parent)?.root;
  if (!from || !root || bandsProblem(bands) || plots.length + 3 > MAX_PLOTS) return [...plots];
  const rolling = (aggregate: "avg" | "stddev"): SeriesTransform =>
    ({ kind: "rolling", aggregate, window: bands.window, unit: bands.unit });
  const input = (aggregate: "avg" | "stddev") => referenceTo(plots, parent, [rolling(aggregate)])!;
  const band = (sign: "+" | "-"): SeriesTransform => ({
    kind: "formula", expression: `y ${sign} ${bands.deviations} * z`,
    inputs: { y: input("avg"), z: input("stddev") },
  });
  let n = plots.length + 1;
  const free = () => {
    while (plots.some((p) => p.id === `plot-${n}`)) n += 1;
    return `plot-${n++}`;
  };
  const made = (label: string, transforms: SeriesTransform[], style: LineStyle): Plot =>
    ({ id: free(), label: `${label} of ${from.label}`, canvas, style, root: null, parent, transforms });
  return [
    ...plots,
    made("Moving average", [rolling("avg")], "solid"),
    made("Upper Bollinger band", [band("+")], "dashed"),
    made("Lower Bollinger band", [band("-")], "dashed"),
  ];
}


/** A plot as a formula or combine input reads it (§561): its root's object and
 * property, raw, through its whole chain and then `more`. Null for a plot with
 * no root. */
export function referenceTo(
  plots: readonly Plot[], id: string, more: readonly SeriesTransform[] = [],
): Record<string, unknown> | null {
  const root = rootOf(plots, id)?.root;
  if (!root) return null;
  return {
    object_type_id: root.typeId, instance_id: root.objectId, property: root.property,
    interval: "none", aggregate: "avg", transforms: [...chainOf(plots, id), ...more],
  };
}

/** p.393's *Combine time series* (§650): at most this many other plots. */
export const MAX_COMBINED = 4;
const COMBINE_NAMES = ["y", "z", "a", "b"];

/** The plots with one combining `parent` with `others`: every point of each,
 * and where points meet, one by `aggregate` - or for p.393's *Linear
 * aggregation* (§653), each lined up on its own readings at every instant
 * first. Unchanged at the cap, without another plot, or for a plot that is
 * not there. */
export function withCombined(
  plots: readonly Plot[], parent: string, others: readonly string[],
  aggregate: "avg" | "min" | "max" | "sum", canvas: number,
  kind: "combine" | "linear_aggregate" = "combine",
): Plot[] {
  const from = byId(plots).get(parent);
  const chosen = others.filter((o) => o !== parent).slice(0, MAX_COMBINED);
  const refs = chosen.map((o) => referenceTo(plots, o));
  if (!from || chosen.length === 0 || refs.some((r) => r === null)) return [...plots];
  const inputs = Object.fromEntries(chosen.map((_, n) => [COMBINE_NAMES[n]!, refs[n]]));
  const next = withDerived(plots, parent, [{ kind, aggregate, inputs }], canvas);
  if (next.length === plots.length) return next;
  const made = next[next.length - 1]!;
  const names = chosen.map((o) => byId(plots).get(o)!.label);
  const label = kind === "combine"
    ? `${from.label} combined with ${names.join(", ")}`
    : `Linear aggregation of ${from.label} with ${names.join(", ")}`;
  return [...next.slice(0, -1), { ...made, label }];
}


/** p.392's *Time series search* (§651): an event set from a plot, the time
 * ranges where its readings meet a threshold. p.395's *Event highlight*
 * shades them on the plot's canvas. */
export type EventSet = {
  id: string;
  label: string;
  /** The plot searched, or for a linked set the plot whose root object the
   * events are linked to; shaded on that plot's canvas either way. */
  plot: string;
  highlight: boolean;
} & ({ op: FilterOperator; value: number; linked?: undefined } | { linked: LinkedEvents });

/** p.393's *Linked event set* (§654): "Create an event set from linked
 * objects in the Ontology by traversing object relationships and specifying
 * which properties hold the start and end timestamps." A link from the
 * plot's root object, which way it runs, and the linked objects' two
 * properties - no end makes each event a moment. */
export interface LinkedEvents {
  link: string;
  direction: "outbound" | "inbound";
  start: string;
  end: string | null;
}
export const MAX_EVENT_SETS = 6;

/** The event sets with one more, searching `plot`, under an id none has;
 * unchanged at the cap, for a plot that is not there, or a value that is no
 * number. */
export function withEventSet(
  sets: readonly EventSet[], plots: readonly Plot[], plot: string, op: FilterOperator, value: number,
): EventSet[] {
  const on = byId(plots).get(plot);
  if (!on || !Number.isFinite(value) || sets.length >= MAX_EVENT_SETS) return [...sets];
  let n = sets.length + 1;
  while (sets.some((e) => e.id === `events-${n}`)) n += 1;
  return [...sets, { id: `events-${n}`, label: `${on.label} ${FILTER_WORDS[op]} ${value}`, plot, op,
    value, highlight: true }];
}

/** The event sets with one more, of the objects linked to `plot`'s root
 * object, named for the link's side (§654); unchanged at the cap, for a plot
 * with no root, or without a start property. */
export function withLinkedEventSet(
  sets: readonly EventSet[], plots: readonly Plot[], plot: string, linked: LinkedEvents, side: string,
): EventSet[] {
  const root = rootOf(plots, plot);
  if (!root || !linked.link || !linked.start || sets.length >= MAX_EVENT_SETS) return [...sets];
  let n = sets.length + 1;
  while (sets.some((e) => e.id === `events-${n}`)) n += 1;
  return [...sets, { id: `events-${n}`, label: `${side} of ${root.label}`, plot, linked,
    highlight: true }];
}

/** The event sets whose plot is still there: removing a plot removes the
 * searches of it. */
export function liveEventSets(sets: readonly EventSet[], plots: readonly Plot[]): EventSet[] {
  const ids = new Set(plots.map((p) => p.id));
  return sets.filter((e) => ids.has(e.plot));
}

export interface SeriesEvent { start: number; end: number }

/** An event set's events as times, those with both ends readable. */
export function eventsOf(raw: readonly { start: unknown; end: unknown }[]): SeriesEvent[] {
  const out: SeriesEvent[] = [];
  for (const e of raw) {
    const start = typeof e.start === "string" ? instantOf(e.start) ?? NaN : NaN;
    const end = typeof e.end === "string" ? instantOf(e.end) ?? NaN : NaN;
    if (Number.isFinite(start) && Number.isFinite(end)) {
      out.push({ start: Math.min(start, end), end: Math.max(start, end) });
    }
  }
  return out;
}

/** p.396's *Add initial event sets* (§658): "Initialize the analysis with
 * event sets backed by object sets, specifying the properties to use for
 * event start and end times. Users cannot delete or edit the data
 * configuration for these series". Each object of the set is an event, as a
 * linked object is (§654): no end property, or a blank one, is a moment. */
export interface InitialEventSet { objectSetVariable: string; start: string; end: string | null; label: string }
/** The objects read of each set: an object set page at most. */
export const MAX_INITIAL_EVENTS = 200;

/** The builder's initial event sets that name a set and a start, at most
 * `MAX_EVENT_SETS`. */
export function initialEventSetsOf(raw: unknown): InitialEventSet[] {
  if (!Array.isArray(raw)) return [];
  const out: InitialEventSet[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const { objectSetVariable, start, end, label } = item as Record<string, unknown>;
    if (typeof objectSetVariable !== "string" || !objectSetVariable || typeof start !== "string" || !start) continue;
    out.push({ objectSetVariable, start, end: typeof end === "string" && end ? end : null,
      label: typeof label === "string" && label.trim() ? label.trim() : objectSetVariable });
  }
  return out.slice(0, MAX_EVENT_SETS);
}

/** Each object's event, from its start property to its end. */
export function objectEventsOf(
  objects: readonly { properties: Record<string, unknown> }[], start: string, end: string | null,
): SeriesEvent[] {
  return eventsOf(objects.map((o) => {
    const from = o.properties[start];
    const to = end ? o.properties[end] : null;
    return { start: from, end: to === null || to === undefined || to === "" ? from : to };
  }));
}

/** p.396's *Customize available event set types* (§658): "Control which
 * types of event sets can be added by the user." */
export const EVENT_SET_TYPES = ["search", "linked"] as const;
export type EventSetType = (typeof EVENT_SET_TYPES)[number];
export const EVENT_SET_TYPE_LABELS: Record<EventSetType, string> = {
  search: "Time series search", linked: "Linked event set",
};

/** p.396's *New plot placement* (§658): "Choose which canvas new plots are
 * added to by default" - the input plot's, a new one, or a numbered one. */
export type Placement = "input" | "new" | number;
/** The numbered canvases a builder may choose from. */
export const MAX_CANVASES = 8;

export function placementOf(raw: unknown): Placement {
  if (raw === "new") return "new";
  return typeof raw === "number" && Number.isInteger(raw) && raw >= 1 && raw <= MAX_CANVASES ? raw : "input";
}

/** The canvas a new plot goes on. */
export function canvasFor(placement: Placement, input: number, canvases: readonly number[]): number {
  if (placement === "input") return input;
  if (placement === "new") return Math.max(1, ...canvases) + 1;
  return placement;
}

/** p.395's *Event count*: "The number of events within the current view
 * range", counting an event that overlaps it. */
export function eventCount(events: readonly SeriesEvent[], range: { from: number; to: number } | null = null): number {
  return range ? events.filter((e) => e.end >= range.from && e.start <= range.to).length : events.length;
}

/** Where an event is shaded on a canvas: from its first reading to its last,
 * at least two pixels wide so a one-reading event can be seen, and clipped to
 * the frame. */
export function eventSpan(
  event: SeriesEvent,
  extent: { t0: number; t1: number },
  width: number,
): { x: number; width: number } | null {
  const x = (t: number) => ((t - extent.t0) / (extent.t1 - extent.t0)) * width;
  const from = Math.max(0, x(event.start));
  const to = Math.min(width, x(event.end));
  // Clipped to the frame, an event outside it ends before it starts (a test
  // for each side of the frame survived the sweep as equivalent).
  if (to < from) return null;
  const w = Math.max(2, to - from);
  return { x: Math.min(from, width - w), width: w };
}


/** p.393's *Event statistics* (§652): "Aggregate a time series over
 * intervals where an event occurs, returning one point per event." `parent`
 * is the series aggregated; the events are an event set's, found by the
 * server in that set's plot through its whole chain. Unchanged for an event
 * set or a plot that is not there. */
export function withEventStatistics(
  plots: readonly Plot[], parent: string, set: EventSet | undefined,
  aggregate: "sum" | "avg" | "min" | "max" | "count" | "stddev", canvas: number,
): Plot[] {
  const from = byId(plots).get(parent);
  // The server finds a search's events inside the query; a linked set's are
  // objects, which a series transform does not read (§654).
  if (!from || !set || set.linked) return [...plots];
  const searched = referenceTo(plots, set.plot);
  if (!searched) return [...plots];
  const next = withDerived(plots, parent, [{
    kind: "event_statistics", aggregate, op: set.op, value: set.value, inputs: { e: searched },
  }], canvas);
  if (next.length === plots.length) return next;
  const made = next[next.length - 1]!;
  return [...next.slice(0, -1), { ...made, label: `${aggregate} of ${from.label} per event of ${set.label}` }];
}


/** p.396's *Default view range* (§659): "The initial view range for time
 * series charts in the analysis … Full data range … Fixed date range: Use
 * workshop variables to define absolute start and end dates. Relative date
 * range: … a range relative to the time when the page was loaded (for
 * example, "2 weeks ago to now")." The relative range's length is the
 * builder's number and unit. With p.395's statistics and event count "within
 * the current view range", and the reader's zoom and pan. */
export interface ViewRange { from: number; to: number }
export const VIEW_RANGES = ["full", "fixed", "relative"] as const;
export type ViewRangeKind = (typeof VIEW_RANGES)[number];
const UNIT_MS: Record<TimeUnit, number> = {
  second: 1_000, minute: 60_000, hour: 3_600_000, day: 86_400_000, week: 604_800_000,
};

/** The view a chart opens on: null for the full data range, and for a fixed
 * or relative range that is not one. */
export function defaultRangeOf(
  kind: unknown, fixed: { start: number | null; end: number | null },
  amount: unknown, unit: unknown, now: number,
): ViewRange | null {
  if (kind === "fixed") {
    return fixed.start !== null && fixed.end !== null && fixed.start < fixed.end
      ? { from: fixed.start, to: fixed.end } : null;
  }
  if (kind === "relative" && typeof amount === "number" && amount > 0 && Number.isFinite(amount)
      && typeof unit === "string" && unit in UNIT_MS) {
    return { from: now - amount * UNIT_MS[unit as TimeUnit], to: now };
  }
  return null;
}

/** The narrowest view a reader may zoom to. */
export const MIN_VIEW_MS = 1_000;

/** The view `factor` times as wide about its middle - a half to zoom in, two
 * to zoom out; null, the full range, once it would cover all of `full`. */
export function zoomedRange(view: ViewRange | null, full: { t0: number; t1: number }, factor: number): ViewRange | null {
  const at = view ?? { from: full.t0, to: full.t1 };
  const middle = (at.from + at.to) / 2;
  const half = Math.max(MIN_VIEW_MS, (at.to - at.from) * factor) / 2;
  const next = { from: middle - half, to: middle + half };
  return next.from <= full.t0 && next.to >= full.t1 ? null : next;
}

/** The view moved by `by` of its own width: a half back is -0.5. */
export function pannedRange(view: ViewRange | null, full: { t0: number; t1: number }, by: number): ViewRange {
  const at = view ?? { from: full.t0, to: full.t1 };
  const step = (at.to - at.from) * by;
  return { from: at.from + step, to: at.to + step };
}

/** The readings a view shows. */
export function inView(readings: readonly Reading[], view: ViewRange | null): Reading[] {
  return view ? readings.filter((r) => r.t >= view.from && r.t <= view.to) : [...readings];
}

/** A time on the axis, as a date over more than two days and a date and
 * hour within them, `offset` minutes from UTC: p.396's *Enable UTC time
 * format* gives 0, and otherwise the reader's own offset. */
export function timeLabel(t: number, span: number, offset: number): string {
  const shifted = new Date(t + offset * 60_000).toISOString();
  return span > 2 * 86_400_000 ? shifted.slice(0, 10) : shifted.slice(5, 16).replace("T", " ");
}
