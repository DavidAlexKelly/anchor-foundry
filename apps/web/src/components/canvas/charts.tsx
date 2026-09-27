"use client";

import { segmentLayout, type SegmentMode, type Segmented } from "./chart-segments";
import {
  valueScale, type AxisTitles, type ValueAxis, type ValueScale,
} from "./chart-display";
import { arcPath, percentLabel, wedges } from "./pie-chart";

/**
 * Chart rendering for canvas widgets (ROADMAP Canvas item 2) — four kinds in
 * hand-written SVG.
 *
 * **Why no chart library.** The same call §28 made for the pipeline graph,
 * where server-side layering meant the web app needed no graph library: the
 * four shapes the roadmap names (bar, line, pie, scatter) are a few dozen
 * lines of SVG each, and a charting dependency is a large surface to carry —
 * bundle size, its own theming system to fight, and a version to keep current
 * — for shapes this simple. That trade flips the moment someone wants
 * tooltips, zoom, brushing and stacked series, and this file is where to
 * notice that and reach for a library instead of growing a bad one.
 *
 * Every chart takes the same `{label, value}[]`, because that is what the
 * aggregation query returns (`chart-sql.ts`) whatever the kind — so switching
 * a chart's type in Settings never invalidates its data binding.
 */

export interface ChartPoint {
  label: string;
  value: number;
}

/** Drill-down (roadmap 1.5). Clicking a category means "narrow to this one",
 * so the chart needs to know which category is currently narrowed to and how
 * to say a new one was picked. Absent means the chart is a picture, which is
 * what a chart with nothing to drill into should be — no pointer cursor, no
 * hover affordance promising something that will not happen. */
export interface Drill {
  selected: string | null;
  onSelect: (label: string) => void;
}

/** A selected category is drawn at full strength and the rest are dimmed,
 * rather than the selection being outlined: the point of drilling in is that
 * the others are no longer what you are looking at. */
function dim(drill: Drill | undefined, label: string): number {
  if (!drill || drill.selected === null) return 1;
  return drill.selected === label ? 1 : 0.28;
}

/** What a clickable mark needs to be operable by something other than a
 * mouse. An SVG shape is not a button until it says so. */
function markProps(drill: Drill | undefined, label: string) {
  if (!drill) return {};
  return {
    role: "button",
    tabIndex: 0,
    style: { cursor: "pointer" },
    "aria-label": `Filter to ${label}`,
    "aria-pressed": drill.selected === label,
    onClick: () => drill.onSelect(label),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        drill.onSelect(label);
      }
    },
  };
}

const PALETTE = [
  "#2f6f4f", "#b07d2b", "#3d6b8f", "#8f4b6b", "#5c6b3d",
  "#7a5c8f", "#2f8f8f", "#8f5c2f", "#4f4f8f", "#6b8f3d",
  "#8f2f4f", "#3d8f6b",
];

function niceNumber(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  // Integers stay integers: an axis reading "3.0 orders" is noise.
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/** Truncate a category label to something that fits under a bar. The full
 * value stays in a <title>, so nothing is actually lost. */
function shortLabel(label: string, max = 12): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

const WIDTH = 640;
const HEIGHT = 260;
const PAD = { top: 12, right: 12, bottom: 34, left: 48 };

/** The plot inside the chart's frame. A value title takes a strip on the
 * left and a category title one along the bottom, so a chart with neither is
 * laid out exactly as it was before titles existed. */
function plotArea(titles?: AxisTitles) {
  const left = PAD.left + (titles?.value ? 18 : 0);
  const bottom = PAD.bottom + (titles?.category ? 16 : 0);
  return {
    x: left,
    y: PAD.top,
    w: WIDTH - left - PAD.right,
    h: HEIGHT - PAD.top - bottom,
  };
}

type Area = ReturnType<typeof plotArea>;

/** Zero is always included when the axis is calculated, because a bar chart
 * whose baseline is not zero exaggerates differences — the single most common
 * way a chart lies. A builder who fixes a bound above zero has chosen that
 * (p.283), and the bar then starts at the bottom of the axis. */
const CALCULATED: ValueAxis = { scale: "linear", min: null, max: null };

/** Where a value is drawn, or null when it cannot be (`valueScale`). */
function yOf(s: ValueScale, value: number, area: { y: number; h: number }): number | null {
  const at = s.at(value);
  return at === null ? null : area.y + area.h - at * area.h;
}

/** Inside the axis's bounds, so worth a label: a value a fixed bound cuts off
 * would have its number written in the margin, over nothing. */
function shown(s: ValueScale, value: number): boolean {
  const at = s.at(value);
  return at !== null && at >= -1e-9 && at <= 1 + 1e-9;
}

/** A logarithmic axis's small ticks read as themselves: niceNumber's two
 * decimals would print 0.001 as "0.00". */
function tickFormat(axis: ValueAxis): (value: number) => string {
  return axis.scale === "log"
    ? (v) => (Math.abs(v) < 1 ? String(Number(v.toPrecision(3))) : niceNumber(v))
    : niceNumber;
}

function Axes({ scale: s, area, format = niceNumber }: {
  scale: ValueScale;
  area: Area;
  format?: (value: number) => string;
}) {
  return (
    <g>
      {s.ticks.map((t, i) => {
        const y = yOf(s, t, area) ?? area.y + area.h;
        return (
          <g key={i}>
            <line
              x1={area.x} x2={area.x + area.w} y1={y} y2={y}
              stroke="var(--line)" strokeWidth={1}
            />
            <text
              data-testid="chart-value-tick"
              x={area.x - 6} y={y + 4} textAnchor="end" fontSize={11} fill="var(--ink-soft)"
            >
              {format(t)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

/** p.283's titles: the value axis's up the left edge and the categorical
 * axis's along the bottom, or the other way round on a horizontal bar chart,
 * whose values run along the bottom. */
function AxisTitleMarks({ titles, area, horizontal = false, belowY = HEIGHT - 4 }: {
  titles?: AxisTitles;
  area: { x: number; y: number; w: number; h: number };
  horizontal?: boolean;
  /** Above a segmented chart's legend, which has the bottom edge. */
  belowY?: number;
}) {
  if (!titles) return null;
  const left = horizontal ? titles.category : titles.value;
  const below = horizontal ? titles.value : titles.category;
  const kind = (isValue: boolean) => (isValue ? "chart-value-title" : "chart-category-title");
  return (
    <>
      {left && (
        <text
          data-testid={kind(!horizontal)}
          transform={`translate(12, ${area.y + area.h / 2}) rotate(-90)`}
          textAnchor="middle"
          fontSize={11}
          fill="var(--ink-soft)"
        >
          {left}
        </text>
      )}
      {below && (
        <text
          data-testid={kind(horizontal)}
          x={area.x + area.w / 2}
          y={belowY}
          textAnchor="middle"
          fontSize={11}
          fill="var(--ink-soft)"
        >
          {below}
        </text>
      )}
    </>
  );
}

/** The marks, cut at the plot's edges when a bound is fixed: a bar taller
 * than the maximum stops at it rather than running over the title. A nested
 * viewport rather than a clipPath, whose own rect would be one more `rect` in
 * every count of a chart's bars. Nothing is cut on a calculated axis, where
 * nothing overflows and a dot on the top line would lose its upper half. */
function Plot({ area, axis, children }: {
  area: { x: number; y: number; w: number; h: number };
  axis: ValueAxis;
  children: React.ReactNode;
}) {
  if (axis.min === null && axis.max === null) return <>{children}</>;
  return (
    <svg
      data-testid="chart-plot-clip"
      x={area.x} y={area.y} width={area.w} height={area.h}
      viewBox={`${area.x} ${area.y} ${area.w} ${area.h}`}
      overflow="hidden"
    >
      {children}
    </svg>
  );
}

/** p.281's Labels and p.284's orientation (§468), and p.283's value axis and
 * titles (§536). */
export interface ChartDisplay {
  horizontal?: boolean;
  labels?: boolean;
  axis?: ValueAxis;
  titles?: AxisTitles;
  /** p.281's Area, on a line chart (§537). */
  shaded?: boolean;
  /** p.283's numerical formatting of each axis (§538), when enabled. */
  valueText?: (value: number) => string;
  categoryText?: (label: string) => string;
}

interface Drawn {
  points: ChartPoint[];
  drill?: Drill;
  labels?: boolean;
  axis: ValueAxis;
  titles?: AxisTitles;
  /** How a value axis tick, a value label and a category key are written. */
  tickText: (value: number) => string;
  labelText: (value: number) => string;
  keyText: (label: string) => string;
}

/** p.284's horizontal bar chart: categories down the left, values along the
 * bottom. The same bars and the same drill-down as the vertical one, turned. */
function HorizontalBarChart({
  points, drill, labels, axis, titles, tickText, labelText, keyText,
}: Drawn) {
  const left = 110 + (titles?.category ? 14 : 0);
  const below = titles?.value ? 16 : 0;
  const area = { x: left, y: PAD.top, w: WIDTH - left - 40, h: HEIGHT - PAD.top - 24 - below };
  const s = valueScale(points.map((p) => p.value), axis);
  const toX = (v: number) => {
    const at = s.at(v);
    return at === null ? null : area.x + at * area.w;
  };
  const slot = area.h / Math.max(points.length, 1);
  const barHeight = Math.max(2, slot * 0.62);
  const baseX = area.x + s.base * area.w;
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="Horizontal bar chart"
      style={{ width: "100%" }}
    >
      {s.ticks.map((t, i) => {
        const x = toX(t) ?? area.x;
        return (
          <g key={i}>
            <line
              x1={x} x2={x} y1={area.y} y2={area.y + area.h}
              stroke="var(--line)" strokeWidth={1}
            />
            <text
              data-testid="chart-value-tick"
              x={x} y={HEIGHT - 8 - below} textAnchor="middle" fontSize={11}
              fill="var(--ink-soft)"
            >
              {tickText(t)}
            </text>
          </g>
        );
      })}
      <AxisTitleMarks titles={titles} area={area} horizontal />
      {points.map((p, i) => {
        const x = toX(p.value);
        const y = area.y + slot * i + (slot - barHeight) / 2;
        return (
          <g key={i}>
            {x !== null && (
              <Plot area={area} axis={axis}>
                <rect
                  x={Math.min(x, baseX)}
                  y={y}
                  width={Math.max(1, Math.abs(x - baseX))}
                  height={barHeight}
                  fill={PALETTE[i % PALETTE.length]}
                  opacity={dim(drill, p.label)}
                  {...markProps(drill, p.label)}
                >
                  <title>{`${p.label}: ${p.value}`}</title>
                </rect>
              </Plot>
            )}
            <text
              x={area.x - 6}
              y={y + barHeight / 2 + 4}
              textAnchor="end"
              fontSize={11}
              fill="var(--ink-soft)"
            >
              {shortLabel(keyText(p.label), 16)}
            </text>
            {labels && x !== null && shown(s, p.value) && (
              <text
                data-testid="chart-value-label"
                x={Math.max(x, baseX) + 4}
                y={y + barHeight / 2 + 4}
                fontSize={11}
                fill="var(--ink)"
              >
                {labelText(p.value)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function BarChart({
  points, drill, labels, axis, titles, tickText, labelText, keyText,
}: Drawn) {
  const area = plotArea(titles);
  const s = valueScale(points.map((p) => p.value), axis);
  const slot = area.w / Math.max(points.length, 1);
  const barWidth = Math.max(2, slot * 0.62);
  const baseY = area.y + area.h - s.base * area.h;
  const labelY = HEIGHT - 12 - (titles?.category ? 16 : 0);
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Bar chart" style={{ width: "100%" }}>
      <Axes scale={s} area={area} format={tickText} />
      <AxisTitleMarks titles={titles} area={area} />
      {points.map((p, i) => {
        const y = yOf(s, p.value, area);
        const x = area.x + slot * i + (slot - barWidth) / 2;
        return (
          <g key={i}>
            {y !== null && (
              <Plot area={area} axis={axis}>
                <rect
                  x={x}
                  y={Math.min(y, baseY)}
                  width={barWidth}
                  height={Math.max(1, Math.abs(baseY - y))}
                  fill={PALETTE[i % PALETTE.length]}
                  opacity={dim(drill, p.label)}
                  {...markProps(drill, p.label)}
                >
                  <title>{`${p.label}: ${p.value}`}</title>
                </rect>
              </Plot>
            )}
            <text
              x={x + barWidth / 2}
              y={labelY}
              textAnchor="middle"
              fontSize={11}
              fill="var(--ink-soft)"
            >
              {shortLabel(keyText(p.label), Math.max(4, Math.floor(slot / 7)))}
            </text>
            {labels && y !== null && shown(s, p.value) && (
              <text
                data-testid="chart-value-label"
                x={x + barWidth / 2}
                y={Math.min(y, baseY) - 4}
                textAnchor="middle"
                fontSize={11}
                fill="var(--ink)"
              >
                {labelText(p.value)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function LineChart({
  points, drill, labels, axis, titles, tickText, labelText, keyText, shaded = false,
}: Drawn & {
  shaded?: boolean;
}) {
  const area = plotArea(titles);
  const s = valueScale(points.map((p) => p.value), axis);
  const step = points.length > 1 ? area.w / (points.length - 1) : 0;
  // A value that cannot be drawn - p.282's gap, or anything at or below zero
  // on a logarithmic axis - breaks the line rather than joining its
  // neighbours across it, which would claim a reading between.
  const runs: [number, number][][] = [];
  let open = false;
  points.forEach((p, i) => {
    const y = yOf(s, p.value, area);
    if (y === null) {
      open = false;
      return;
    }
    if (!open) runs.push([]);
    runs[runs.length - 1]!.push([area.x + step * i, y]);
    open = true;
  });
  const path = runs
    .map((run) => run.map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x} ${y}`).join(" "))
    .join(" ");
  // p.281's Area: each run shaded down to where a bar would start, so a gap
  // is a gap in the shading too.
  const baseY = area.y + area.h - s.base * area.h;
  const shade = shaded
    ? runs.map((run) => {
        const first = run[0]!;
        const last = run[run.length - 1]!;
        return `M ${first[0]} ${baseY} ${run.map(([x, y]) => `L ${x} ${y}`).join(" ")} L ${last[0]} ${baseY} Z`;
      }).join(" ")
    : "";
  const labelY = HEIGHT - 12 - (titles?.category ? 16 : 0);
  // Every nth label only: a line chart with 200 points cannot show 200 of them.
  const labelEvery = Math.max(1, Math.ceil(points.length / 8));
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Line chart" style={{ width: "100%" }}>
      <Axes scale={s} area={area} format={tickText} />
      <AxisTitleMarks titles={titles} area={area} />
      <Plot area={area} axis={axis}>
        {shaded && (
          <path data-testid="chart-area" d={shade} fill={PALETTE[0]} fillOpacity={0.22} stroke="none" />
        )}
        <path data-testid="chart-line" d={path} fill="none" stroke={PALETTE[0]} strokeWidth={2} />
        {points.map((p, i) => {
          const y = yOf(s, p.value, area);
          return y === null ? null : (
            <circle
              key={i}
              cx={area.x + step * i}
              cy={y}
              // A 2.5px dot is not a click target. Bigger when there is
              // something to click, rather than asking for a steady hand.
              r={drill ? 5 : 2.5}
              fill={PALETTE[0]}
              opacity={dim(drill, p.label)}
              {...markProps(drill, p.label)}
            >
              <title>{`${p.label}: ${p.value}`}</title>
            </circle>
          );
        })}
      </Plot>
      {labels && points.map((p, i) => {
        const y = yOf(s, p.value, area);
        return y === null || !shown(s, p.value) ? null : (
          <text
            key={`v${i}`}
            data-testid="chart-value-label"
            x={area.x + step * i}
            y={y - 8}
            textAnchor="middle"
            fontSize={11}
            fill="var(--ink)"
          >
            {labelText(p.value)}
          </text>
        );
      })}
      {points.map((p, i) =>
        i % labelEvery === 0 ? (
          <text
            key={`l${i}`}
            x={area.x + step * i}
            y={labelY}
            textAnchor="middle"
            fontSize={11}
            fill="var(--ink-soft)"
          >
            {shortLabel(keyText(p.label), 10)}
          </text>
        ) : null,
      )}
    </svg>
  );
}

function ScatterChart({ points, axis, titles, tickText }: Drawn) {
  const area = plotArea(titles);
  const s = valueScale(points.map((p) => p.value), axis);
  // The dimension is the x axis. It is numeric when it can be and ordinal
  // otherwise, because a scatter of two categorical columns is a grid of dots
  // that says nothing - and pretending otherwise would draw it anyway.
  const xs = points.map((p) => Number(p.label));
  const numericX = xs.every((x) => Number.isFinite(x));
  const xMin = numericX ? Math.min(...xs) : 0;
  const xMax = numericX ? Math.max(...xs) : Math.max(points.length - 1, 1);
  const xSpan = xMax - xMin || 1;
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Scatter chart" style={{ width: "100%" }}>
      <Axes scale={s} area={area} format={tickText} />
      <AxisTitleMarks titles={titles} area={area} />
      <Plot area={area} axis={axis}>
        {points.map((p, i) => {
          const x = area.x + (((numericX ? Number(p.label) : i) - xMin) / xSpan) * area.w;
          const y = yOf(s, p.value, area);
          return y === null ? null : (
            <circle key={i} cx={x} cy={y} r={3} fill={PALETTE[0]} fillOpacity={0.65}>
              <title>{`${p.label}: ${p.value}`}</title>
            </circle>
          );
        })}
      </Plot>
      {!numericX && (
        <text x={area.x} y={HEIGHT - 12 - (titles?.category ? 16 : 0)} fontSize={11} fill="var(--ink-soft)">
          {points.length} points (x is ordinal — the dimension is not numeric)
        </text>
      )}
    </svg>
  );
}

/** p.309-310's pie, and Chart XY's.
 *
 * **One renderer, two widgets.** The angle arithmetic used to live inline in
 * this function, where nothing but a browser could reach it — so "does a 30%
 * slice cover 30%" was a question no test had asked. It is `pie-chart.ts` now,
 * and the options p.310 adds (an inner radius, a legend that can move or go,
 * per-segment colours and labels) are parameters with Chart XY's old behaviour
 * as their defaults.
 */
export function PieChart({
  points,
  counts,
  drill,
  inner = 0,
  legend = "right",
  showLegend = true,
  colors,
}: {
  points: ChartPoint[];
  /** How many objects are behind each point, keyed by label, when that is a
   * *different* number from the one the wedge is drawn from.
   *
   * Only p.310's Aggregation makes them differ: a pie sized by total capacity
   * has a slice worth 400 holding 12 objects. Chart XY plots a series of values
   * and has no second number, so it passes none — and where there is none the
   * legend and the title say one thing, which is what every pie before §228
   * did. */
  counts?: Record<string, number>;
  drill?: Drill;
  /** p.310's Radius, as a fraction of the outer radius. */
  inner?: number;
  /** p.310's legend position. */
  legend?: string;
  showLegend?: boolean;
  /** p.310's per-segment colours, keyed by the *label* drawn. */
  colors?: Record<string, string | null>;
}) {
  // `size` is what a wedge is drawn from; `count` is how many objects are
  // behind it, which is the same number unless p.310's Aggregation made it
  // otherwise. Both go through the same `wedges`, which is §218's point — one
  // pie, two widgets.
  const slices = points.map((p) => ({
    value: p.label, label: p.label,
    count: counts?.[p.label] ?? Math.max(0, p.value),
    size: Math.max(0, p.value),
    color: colors?.[p.label] ?? null,
  }));
  const drawn = wedges(slices);
  const total = slices.reduce((sum, s) => sum + s.size, 0);
  // The legend takes a side, so the pie's centre moves with it. Beside it the
  // chart keeps its half; above or below, the pie centres and gives up height.
  const beside = legend === "left" || legend === "right";
  const keyed = showLegend && drawn.length > 0;
  const cx = keyed && beside ? (legend === "left" ? WIDTH - 190 : 130) : WIDTH / 2;
  const cy = keyed && !beside ? (legend === "top" ? HEIGHT / 2 + 16 : HEIGHT / 2 - 16)
    : HEIGHT / 2;
  const r = keyed && !beside ? 84 : 96;
  const colourOf = (index: number, slice: { color: string | null }) =>
    slice.color ?? PALETTE[index % PALETTE.length];

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Pie chart" style={{ width: "100%" }}>
      {total <= 0 && (
        <text x={WIDTH / 2} y={HEIGHT / 2} textAnchor="middle" fontSize={12} fill="var(--ink-soft)">
          Nothing to show — every value is zero or negative
        </text>
      )}
      {drawn.map((wedge, i) => (
        <path
          key={i}
          data-testid="pie-slice"
          data-label={wedge.slice.label}
          d={arcPath({ cx, cy, r, inner, start: wedge.start, end: wedge.end })}
          fill={colourOf(i, wedge.slice)}
          opacity={dim(drill, wedge.slice.value)}
          {...markProps(drill, wedge.slice.value)}
        >
          {/* **`size`, not `count`** — the number a share is a share *of*.
              With p.310's Aggregation set to a sum, a title reading "north: 12
              (25.0%)" would state a count beside a percentage of a total, which
              are two different numbers wearing one sentence. They are the same
              value for a count pie, which is every pie before §228. */}
          {/* **`size`, then the count when it is a different number.** With
              p.310's Aggregation set to a sum, "north: 400 (25.0%)" states the
              share's own total, and "12 objects" says what is behind it —
              which a reader of a sum-pie wants and cannot get anywhere else.
              For a count pie they are one number and it is said once. */}
          <title>
            {`${wedge.slice.label}: ${wedge.slice.size} (${percentLabel(wedge.share)})`}
            {wedge.slice.count === wedge.slice.size
              ? ""
              : ` — ${niceNumber(wedge.slice.count)} objects`}
          </title>
        </path>
      ))}
      {keyed &&
        drawn.map((wedge, i) => (
          <g
            key={`k${i}`}
            data-testid="pie-legend-entry"
            transform={beside
              ? `translate(${legend === "left" ? 24 : 268}, ${28 + i * 18})`
              : `translate(24, ${legend === "top" ? 20 + i * 18 : HEIGHT - 12 - (drawn.length - i - 1) * 18})`}
          >
            <rect width={11} height={11} y={-9} fill={colourOf(i, wedge.slice)} />
            <text x={17} fontSize={11.5} fill="var(--ink)">
              {/* The legend shows what the wedge is drawn from, so the two
                  agree. p.310's Aggregation is the label above the chart, not
                  a thing to re-explain on every row. */}
              {shortLabel(wedge.slice.label, 22)} — {niceNumber(wedge.slice.size)}
            </text>
          </g>
        ))}
    </svg>
  );
}

/**
 * p.281–282's segmented bar chart (§467): each category's bar split by a
 * second property, stacked, as percentages of the bar, or grouped side by side
 * (`chart-segments.ts`). A segment is coloured by its position in the legend,
 * so one segment is one colour across every bar.
 *
 * A click on any part of a bar drills into its *category*: the drill-down
 * writes one clause on the X axis property, and a segment is a second property
 * that clause does not name.
 */
export function SegmentedBarChart({
  data, mode, drill, showLegend = true, titles, valueText, categoryText,
}: {
  data: Segmented;
  mode: SegmentMode;
  drill?: Drill;
  showLegend?: boolean;
  titles?: AxisTitles;
  /** p.283's numerical formatting (§538). A percentage axis keeps its own. */
  valueText?: (value: number) => string;
  categoryText?: (label: string) => string;
}) {
  // Six entries to a row, and as many rows as the segments need: the
  // cross-tab returns up to twelve columns.
  const legendRows = showLegend ? Math.ceil(data.segments.length / 6) : 0;
  const legendHeight = legendRows > 0 ? legendRows * 16 + 6 : 0;
  const area = { ...plotArea(titles), h: plotArea(titles).h - legendHeight };
  const { bars, max } = segmentLayout(data, mode);
  // Calculated, always: a stack's height is the sum of its segments, which a
  // logarithmic axis would not show, and a percentage's bound is 100%, not a
  // number a builder types (§536).
  const s = valueScale([0, max], CALCULATED);
  const slot = area.w / Math.max(data.categories.length, 1);
  const barWidth = Math.max(2, slot * 0.72);
  const percent = mode === "percentage";
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="Segmented bar chart"
      style={{ width: "100%" }}
    >
      <Axes
        scale={s}
        area={area}
        format={percent ? (v) => `${Math.round(v * 100)}%` : valueText ?? niceNumber}
      />
      <AxisTitleMarks titles={titles} area={area} belowY={area.y + area.h + 30} />
      {bars.map((bar, i) => {
        const category = data.categories[bar.category] ?? "";
        const segment = data.segments[bar.segment] ?? "";
        const top = yOf(s, bar.to, area) ?? area.y;
        const bottom = yOf(s, bar.from, area) ?? area.y + area.h;
        const x = area.x + slot * bar.category + (slot - barWidth) / 2 + barWidth * bar.offset;
        return (
          <rect
            key={i}
            data-testid="chart-segment"
            data-category={category}
            data-segment={segment}
            x={x}
            y={top}
            width={Math.max(1, barWidth * bar.width - (bar.width < 1 ? 1 : 0))}
            height={Math.max(1, bottom - top)}
            fill={PALETTE[bar.segment % PALETTE.length]}
            opacity={dim(drill, category)}
            {...markProps(drill, category)}
          >
            <title>{`${category} · ${segment}: ${bar.value}`}</title>
          </rect>
        );
      })}
      {data.categories.map((category, i) => (
        <text
          key={`c${i}`}
          x={area.x + slot * i + slot / 2}
          y={area.y + area.h + 16}
          textAnchor="middle"
          fontSize={11}
          fill="var(--ink-soft)"
        >
          {shortLabel(categoryText ? categoryText(category) : category,
            Math.max(4, Math.floor(slot / 7)))}
        </text>
      ))}
      {showLegend && data.segments.map((segment, i) => (
        <g
          key={`k${i}`}
          data-testid="chart-legend-entry"
          transform={`translate(${area.x + (i % 6) * 96}, ${
            HEIGHT - 6 - (legendRows - 1 - Math.floor(i / 6)) * 16})`}
        >
          <rect width={10} height={10} y={-9} fill={PALETTE[i % PALETTE.length]} />
          <text x={15} fontSize={11} fill="var(--ink)">{shortLabel(segment, 12)}</text>
        </g>
      ))}
    </svg>
  );
}

export function Chart({
  kind,
  points,
  drill,
  display = {},
}: {
  kind: string;
  points: ChartPoint[];
  drill?: Drill;
  display?: ChartDisplay;
}) {
  if (points.length === 0) {
    return <p className="canvas-widget-empty">No rows match — nothing to chart.</p>;
  }
  const axis = display.axis ?? CALCULATED;
  const drawn = {
    points, drill, labels: display.labels, axis, titles: display.titles,
    tickText: display.valueText ?? tickFormat(axis),
    labelText: display.valueText ?? niceNumber,
    keyText: display.categoryText ?? ((label: string) => label),
  };
  const s = valueScale(points.map((p) => p.value), axis);
  let chart: React.ReactNode;
  if (kind === "line") chart = <LineChart {...drawn} shaded={display.shaded === true} />;
  else if (kind === "pie") return <PieChart points={points} drill={drill} />;
  // Scatter takes no drill-down: its label is an X *coordinate*, so clicking a
  // point would narrow to one exact value of a continuous axis — almost never
  // the question somebody is asking. Left out rather than wired to something
  // that technically works.
  else if (kind === "scatter") chart = <ScatterChart {...drawn} drill={undefined} />;
  else if (display.horizontal) chart = <HorizontalBarChart {...drawn} />;
  else chart = <BarChart {...drawn} />;
  return (
    <>
      {chart}
      {/* Said rather than dropped in silence: a logarithm has no zero, and a
          chart that quietly lost a bar reads as a category with no data. */}
      {s.undrawn > 0 && (
        <p className="canvas-widget-empty" data-testid="chart-undrawn">
          {s.undrawn === 1 ? "1 value is" : `${s.undrawn} values are`} zero or below, which
          a logarithmic axis cannot draw.
        </p>
      )}
    </>
  );
}

/** Rows come back from the query endpoint as `[label, value]` pairs of
 * unknowns. A non-numeric measure is dropped rather than charted as zero: a
 * zero bar is a claim about the data, and "this row could not be measured" is
 * not that claim. A null one is kept as missing, for `withMissing`. */
export function toPoints(rows: unknown[][]): ChartPoint[] {
  const points: ChartPoint[] = [];
  for (const row of rows) {
    // An aggregate over nothing is null: a category with no value, which
    // p.282's null display decides the fate of (§537). NaN carries it.
    const missing = row[1] === null || row[1] === undefined;
    const value = missing ? NaN : Number(row[1]);
    if (!missing && !Number.isFinite(value)) continue;
    points.push({ label: row[0] === null || row[0] === undefined ? "∅" : String(row[0]), value });
  }
  return points;
}
