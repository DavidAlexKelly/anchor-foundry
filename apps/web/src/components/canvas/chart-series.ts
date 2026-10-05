/**
 * p.281's **multiple series** on Chart XY, and p.282's **Display override**
 * naming each one (§541).
 *
 * > "Use single / multiple series: Allows either one or more chart series to
 * > be plotted for the selected X axis property. For instance, if "Alert Type"
 * > was selected as the X axis property, multiple series would allow the
 * > plotting of both the count of each "Alert Type" and also the sum of the
 * > "# of Hours Delayed" for each "Alert Type"." (p.281)
 * >
 * > "Display override: Optional. Overrides the legend display name of the
 * > current series." (p.282)
 *
 * The chart's own Measure is the first series; these are the rest. Each is
 * one more `/object-sets/group` question, and the answers are laid side by
 * side as a grid - the shape a segmented chart already draws, with a series
 * where a segment was.
 *
 * **A series may read its own object set, grouped by its own property**
 * (§625): p.280's layers, each with its own "Data input" ("The Object set
 * option allows a Workshop object set variable to be used as input") and its
 * own "X axis property". Categories are matched by their label, so alerts by
 * airport and flights by origin airport meet on one axis. Unset, a series
 * reads the chart's set by the chart's property, which is every series saved
 * before.
 */

import type { ChartPoint } from "./charts";
import { defaultValueTitle } from "./chart-display";
import { segmentName, type Segmented } from "./chart-segments";
import { aggregationOf, aggregationRequest } from "./pie-chart";
import { functionLayerOf, type FunctionLayer } from "./function-layers";

export interface SeriesSpec {
  /** p.280's layer **Title** (§757): "not visible to module users, but is
   * intended to help builders organize and manage complex Chart XY
   * configurations that use multiple Layers". The panel's alone. */
  title: string;
  aggregate: string;
  measure: string | null;
  /** p.282's display override, or "" for the default. */
  name: string;
  /** p.283's value axis for this series, when the chart has two (§542). */
  axis: AxisSide;
  /** p.280's layer Data input (§625): an object set variable, or null for the
   * chart's own set. */
  objectSetVariable: string | null;
  /** p.280's layer X axis property (§625), or null for the chart's own. */
  dimension: string | null;
  /** p.280's **Layer type** (§626): drawn as bars, a line or dots (§757)
   * whatever the chart's own type is, or null for the chart's. */
  kind: LayerKind | null;
  /** p.282's **Selection as filter** for this layer (§628): an array
   * variable a click on its marks writes a clause into, on the layer's own
   * property. Null for the chart's own drill-down. */
  drilldownVariable: string | null;
  /** p.282's **Segment by** for this layer (§678): a second property its
   * bars are split by, or null for none. */
  segmentBy: string | null;
  /** p.280's **Function aggregation** Data input (§771): the layer is the
   * function's buckets rather than an object set's groups. */
  fn: FunctionLayer | null;
}

/** p.280's three: "Bar Chart, Line Chart, and Scatter Chart". A scatter layer
 * over the chart's categories is each category's value as a dot, with no line
 * joining them (§757). */
export type LayerKind = "bar" | "line" | "scatter";

export const LAYER_KINDS: readonly LayerKind[] = ["bar", "line", "scatter"];

export type AxisSide = "left" | "right";

/** A bar's worth of series is plenty: past it the groups are slivers. */
export const MAX_SERIES = 6;

/** The extra series a chart holds, each read defensively: a saved document
 * is data, and an entry that is not an object is no series. */
export function seriesOf(raw: unknown): SeriesSpec[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((s): s is Record<string, unknown> => typeof s === "object" && s !== null)
    .slice(0, MAX_SERIES - 1)
    .map((s) => ({
      title: typeof s.title === "string" ? s.title.slice(0, 100) : "",
      aggregate: aggregationOf(s.aggregate),
      measure: typeof s.measure === "string" && s.measure !== "" ? s.measure : null,
      name: typeof s.name === "string" ? s.name : "",
      axis: s.axis === "left" ? "left" : "right",
      objectSetVariable: nonEmpty(s.objectSetVariable),
      dimension: nonEmpty(s.dimension),
      kind: (LAYER_KINDS as readonly unknown[]).includes(s.kind) ? (s.kind as LayerKind) : null,
      drilldownVariable: nonEmpty(s.drilldownVariable),
      segmentBy: nonEmpty(s.segmentBy),
      fn: functionLayerOf(s.fn),
    }));
}

/**
 * p.280's **Layer type** for every series, the chart's own first (§626).
 *
 * > "Layer type: Selects the type of chart displayed. Current options include
 * > Bar Chart, Line Chart, and Scatter Chart." (p.280)
 *
 * A series that names none is drawn as the chart is.
 */
export function layerKinds(chart: LayerKind, specs: readonly SeriesSpec[]): LayerKind[] {
  return [chart, ...specs.map((s) => s.kind ?? chart)];
}

/** Whether layers of more than one kind meet on the chart, which is what
 * draws them together over the grouped bars: a chart all of bars, or all of
 * lines, has a layout of its own. */
export function mixedKinds(kinds: readonly LayerKind[]): boolean {
  return kinds.some((k) => k !== "bar") && kinds.some((k) => k !== "line");
}

/**
 * A grid of series split into what is drawn as bars and what across them, as
 * a line or as dots, each keeping its place in the legend (§626, §757).
 * `bars` is the grid of the bar series alone, for the grouped layout;
 * `barAt[i]` and `lineAt[i]` are the legend positions of its i-th bar and
 * line-or-dots series, which is what colours, names and places each on an
 * axis.
 */
export function splitLayers(data: Segmented, kinds: readonly LayerKind[]): {
  bars: Segmented;
  barAt: number[];
  lineAt: number[];
} {
  const barAt: number[] = [];
  const lineAt: number[] = [];
  data.segments.forEach((_, i) => ((kinds[i] ?? "bar") === "bar" ? barAt : lineAt).push(i));
  return {
    bars: {
      categories: data.categories,
      segments: barAt.map((i) => data.segments[i]!),
      values: data.values.map((row) => barAt.map((i) => row[i] ?? NaN)),
    },
    barAt,
    lineAt,
  };
}

function nonEmpty(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

/** What a series is asked of (§625): its own set by its own property, or the
 * chart's, each half falling back on its own. A set of its own gets no
 * inherited property - the chart's property names a different type's column -
 * so such a series waits for one. `null` while there is nothing to ask. */
export function seriesSource(
  spec: SeriesSpec,
  chart: { objectSetVariable: string | null; dimension: string | null },
  resolved: Readonly<Record<string, unknown>>,
): { key: string; definition: unknown; dimension: string } | null {
  const own = spec.objectSetVariable !== null && spec.objectSetVariable !== chart.objectSetVariable;
  const variable = own ? spec.objectSetVariable : chart.objectSetVariable;
  const dimension = spec.dimension ?? (own ? null : chart.dimension);
  const definition = variable ? resolved[variable] : undefined;
  if (!variable || !dimension || definition === undefined || definition === null) return null;
  return { key: variable, definition, dimension };
}

/** A series' name in the legend: its override, else what it plots - and,
 * for one reading a set of its own (§625), which set, since "Count" twice
 * names nothing. */
export function seriesName(spec: SeriesSpec, setLabel?: string): string {
  const plotted = defaultValueTitle("bar", spec.aggregate, spec.measure);
  return spec.name.trim() || (setLabel ? `${plotted} · ${setLabel}` : plotted);
}

/** What to ask the server for each series, or null for one still being
 * filled in, which is left out of the chart rather than asked and refused. */
export function seriesRequests(specs: readonly SeriesSpec[]) {
  return specs.map((s) => aggregationRequest(s.aggregate, s.measure));
}

/**
 * The series side by side, as a grid of categories by series.
 *
 * The first series' categories come first and in its order, which is the
 * order p.283's Sort by put them in; a category only a later series has
 * follows. A series with no value for a category has a missing one (NaN),
 * which is not the zero a count of nothing would be.
 */
export function mergeSeries(
  first: readonly ChartPoint[],
  rest: readonly (readonly ChartPoint[])[],
  names: readonly string[],
): Segmented {
  const categories = first.map((p) => p.label);
  for (const series of rest) {
    for (const p of series) if (!categories.includes(p.label)) categories.push(p.label);
  }
  const all = [first, ...rest];
  return {
    categories,
    segments: [...names],
    values: categories.map((category) =>
      all.map((series) => series.find((p) => p.label === category)?.value ?? NaN)),
  };
}

/**
 * p.283's **Use multiple value axes** (§542).
 *
 * > "Use multiple value axes: Only available if multiple chart series have
 * > been configured and allows value axes to be configured on a per series
 * > basis. This can be helpful when different series on a chart have
 * > substantially different value scales." (p.283)
 *
 * Which axis each series is drawn against, the first series' included. The
 * first is always on the left, which is the axis every other setting (scale,
 * bounds, title, format) describes; a further series is on the right unless
 * it says left, since a second axis nobody is drawn against is not one. With
 * the option off, or one series, everything is on the left.
 */
export function axisSides(specs: readonly SeriesSpec[], twoAxes: boolean): AxisSide[] {
  if (!twoAxes || specs.length === 0) return ["left", ...specs.map((): AxisSide => "left")];
  return ["left", ...specs.map((s) => s.axis)];
}

/**
 * Which category a drill-down variable is narrowed to on a property: the
 * value of its `eq` clause on that property, or null. Read back from the
 * variable rather than held as a second copy, so a chart shows the document's
 * state, including a clause something else set (§628 shares it between the
 * chart's drill-down and each layer's).
 */
export function drilledLabel(clauses: unknown, property: string | null): string | null {
  // A null property matches no clause a filter writes, so it needs no case.
  if (!Array.isArray(clauses)) return null;
  for (const clause of clauses) {
    const c = clause as { property?: unknown; op?: unknown; value?: unknown } | null;
    if (c && c.property === property && c.op === "eq") return String(c.value);
  }
  return null;
}

/** What a click on `label` writes: the clause narrowing to it, or nothing
 * when it is already the one drilled into - clicking it again clears it. */
export function drillClauses(
  property: string, label: string, selected: string | null,
): { property: string; op: "eq"; value: string }[] {
  return label === selected ? [] : [{ property, op: "eq", value: label }];
}


/**
 * p.282's **Segment by** on a layer (§678).
 *
 * > "Segment by: Optional. Enables each plotted value to be segmented by a
 * > secondary property type." (p.282)
 *
 * Whether this layer is drawn split by its segments: a bar layer that counts,
 * which is what a segment is here (the chart's own Segment by counts too).
 */
export function segmentsLayer(spec: SeriesSpec, chart: LayerKind): boolean {
  return !!spec.segmentBy && canSegment(spec, chart);
}

/** Whether a layer could be segmented, for the panel to offer Segment by. */
export function canSegment(spec: SeriesSpec, chart: LayerKind): boolean {
  return spec.aggregate === "count" && (spec.kind ?? chart) === "bar";
}

/** One layer of a chart whose layers may be segmented: its values by category,
 * or its grid of categories by segments, with the names p.282's Display
 * override gives those segments. */
export interface Layer {
  name: string;
  points?: readonly ChartPoint[];
  grid?: Segmented;
  segmentNames?: unknown;
}

/**
 * Layers side by side, each segmented one as a stack of its segments (§678):
 * one column per plain layer and per segment, with `stacks[column]` the layer
 * it belongs to. The first layer's categories come first and in its order, as
 * `mergeSeries` keeps them; a missing value is NaN.
 */
export function layeredGrid(layers: readonly Layer[]): { data: Segmented; stacks: number[] } {
  const categories: string[] = [];
  const add = (label: string) => { if (!categories.includes(label)) categories.push(label); };
  for (const layer of layers) {
    if (layer.grid) layer.grid.categories.forEach(add);
    else (layer.points ?? []).forEach((p) => add(p.label));
  }
  const segments: string[] = [];
  const stacks: number[] = [];
  const columns: ((category: string) => number)[] = [];
  layers.forEach((layer, at) => {
    const grid = layer.grid;
    if (grid) {
      grid.segments.forEach((segment, j) => {
        segments.push(`${layer.name} · ${segmentName(segment, layer.segmentNames)}`);
        stacks.push(at);
        columns.push((category) => {
          const row = grid.categories.indexOf(category);
          return row === -1 ? NaN : grid.values[row]?.[j] ?? NaN;
        });
      });
      return;
    }
    segments.push(layer.name);
    stacks.push(at);
    columns.push((category) => layer.points?.find((p) => p.label === category)?.value ?? NaN);
  });
  return {
    data: { categories, segments, values: categories.map((c) => columns.map((read) => read(c))) },
    stacks,
  };
}
