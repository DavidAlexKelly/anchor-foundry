"use client";

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

function plotArea() {
  return {
    x: PAD.left,
    y: PAD.top,
    w: WIDTH - PAD.left - PAD.right,
    h: HEIGHT - PAD.top - PAD.bottom,
  };
}

/** Axis ticks and the value each maps to. Zero is always included when the
 * data spans it, because a bar chart whose baseline is not zero exaggerates
 * differences — the single most common way a chart lies. */
function scale(values: number[]) {
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const span = max - min || 1;
  return {
    min,
    max,
    toY: (v: number, area: { y: number; h: number }) =>
      area.y + area.h - ((v - min) / span) * area.h,
  };
}

function Axes({ ticks, area }: { ticks: number[]; area: ReturnType<typeof plotArea> }) {
  const s = scale(ticks);
  return (
    <g>
      {ticks.map((t, i) => {
        const y = s.toY(t, area);
        return (
          <g key={i}>
            <line
              x1={area.x} x2={area.x + area.w} y1={y} y2={y}
              stroke="var(--line)" strokeWidth={1}
            />
            <text x={area.x - 6} y={y + 4} textAnchor="end" fontSize={11} fill="var(--ink-soft)">
              {niceNumber(t)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

function gridTicks(values: number[], count = 4): number[] {
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const span = max - min || 1;
  return Array.from({ length: count + 1 }, (_, i) => min + (span * i) / count);
}

function BarChart({ points, drill }: { points: ChartPoint[]; drill?: Drill }) {
  const area = plotArea();
  const values = points.map((p) => p.value);
  const s = scale(values);
  const slot = area.w / Math.max(points.length, 1);
  const barWidth = Math.max(2, slot * 0.62);
  const zeroY = s.toY(0, area);
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Bar chart" style={{ width: "100%" }}>
      <Axes ticks={gridTicks(values)} area={area} />
      {points.map((p, i) => {
        const y = s.toY(p.value, area);
        const x = area.x + slot * i + (slot - barWidth) / 2;
        return (
          <g key={i}>
            <rect
              x={x}
              y={Math.min(y, zeroY)}
              width={barWidth}
              height={Math.max(1, Math.abs(zeroY - y))}
              fill={PALETTE[i % PALETTE.length]}
              opacity={dim(drill, p.label)}
              {...markProps(drill, p.label)}
            >
              <title>{`${p.label}: ${p.value}`}</title>
            </rect>
            <text
              x={x + barWidth / 2}
              y={HEIGHT - 12}
              textAnchor="middle"
              fontSize={11}
              fill="var(--ink-soft)"
            >
              {shortLabel(p.label, Math.max(4, Math.floor(slot / 7)))}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function LineChart({ points, drill }: { points: ChartPoint[]; drill?: Drill }) {
  const area = plotArea();
  const values = points.map((p) => p.value);
  const s = scale(values);
  const step = points.length > 1 ? area.w / (points.length - 1) : 0;
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${area.x + step * i} ${s.toY(p.value, area)}`)
    .join(" ");
  // Every nth label only: a line chart with 200 points cannot show 200 of them.
  const labelEvery = Math.max(1, Math.ceil(points.length / 8));
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Line chart" style={{ width: "100%" }}>
      <Axes ticks={gridTicks(values)} area={area} />
      <path d={path} fill="none" stroke={PALETTE[0]} strokeWidth={2} />
      {points.map((p, i) => (
        <circle
          key={i}
          cx={area.x + step * i}
          cy={s.toY(p.value, area)}
          // A 2.5px dot is not a click target. Bigger when there is something
          // to click, rather than asking for a steady hand.
          r={drill ? 5 : 2.5}
          fill={PALETTE[0]}
          opacity={dim(drill, p.label)}
          {...markProps(drill, p.label)}
        >
          <title>{`${p.label}: ${p.value}`}</title>
        </circle>
      ))}
      {points.map((p, i) =>
        i % labelEvery === 0 ? (
          <text
            key={`l${i}`}
            x={area.x + step * i}
            y={HEIGHT - 12}
            textAnchor="middle"
            fontSize={11}
            fill="var(--ink-soft)"
          >
            {shortLabel(p.label, 10)}
          </text>
        ) : null,
      )}
    </svg>
  );
}

function ScatterChart({ points }: { points: ChartPoint[] }) {
  const area = plotArea();
  const values = points.map((p) => p.value);
  const s = scale(values);
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
      <Axes ticks={gridTicks(values)} area={area} />
      {points.map((p, i) => {
        const x = area.x + (((numericX ? Number(p.label) : i) - xMin) / xSpan) * area.w;
        return (
          <circle key={i} cx={x} cy={s.toY(p.value, area)} r={3} fill={PALETTE[0]} fillOpacity={0.65}>
            <title>{`${p.label}: ${p.value}`}</title>
          </circle>
        );
      })}
      {!numericX && (
        <text x={area.x} y={HEIGHT - 12} fontSize={11} fill="var(--ink-soft)">
          {points.length} points (x is ordinal — the dimension is not numeric)
        </text>
      )}
    </svg>
  );
}

function PieChart({ points, drill }: { points: ChartPoint[]; drill?: Drill }) {
  const total = points.reduce((sum, p) => sum + Math.max(0, p.value), 0);
  const cx = 130;
  const cy = HEIGHT / 2;
  const r = 96;
  let angle = -Math.PI / 2;
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Pie chart" style={{ width: "100%" }}>
      {total <= 0 && (
        <text x={cx} y={cy} textAnchor="middle" fontSize={12} fill="var(--ink-soft)">
          Nothing to show — every value is zero or negative
        </text>
      )}
      {total > 0 &&
        points.map((p, i) => {
          const share = Math.max(0, p.value) / total;
          const end = angle + share * Math.PI * 2;
          const large = share > 0.5 ? 1 : 0;
          const path =
            share >= 1
              ? // A single slice is a circle: an arc from a point back to
                // itself draws nothing at all.
                `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r} Z`
              : [
                  `M ${cx} ${cy}`,
                  `L ${cx + r * Math.cos(angle)} ${cy + r * Math.sin(angle)}`,
                  `A ${r} ${r} 0 ${large} 1 ${cx + r * Math.cos(end)} ${cy + r * Math.sin(end)}`,
                  "Z",
                ].join(" ");
          const slice = (
            <path
              key={i}
              d={path}
              fill={PALETTE[i % PALETTE.length]}
              opacity={dim(drill, p.label)}
              {...markProps(drill, p.label)}
            >
              <title>{`${p.label}: ${p.value} (${(share * 100).toFixed(1)}%)`}</title>
            </path>
          );
          angle = end;
          return slice;
        })}
      {total > 0 &&
        points.map((p, i) => (
          <g key={`k${i}`} transform={`translate(268, ${28 + i * 18})`}>
            <rect width={11} height={11} y={-9} fill={PALETTE[i % PALETTE.length]} />
            <text x={17} fontSize={11.5} fill="var(--ink)">
              {shortLabel(p.label, 22)} — {niceNumber(p.value)}
            </text>
          </g>
        ))}
    </svg>
  );
}

export function Chart({
  kind,
  points,
  drill,
}: {
  kind: string;
  points: ChartPoint[];
  drill?: Drill;
}) {
  if (points.length === 0) {
    return <p className="canvas-widget-empty">No rows match — nothing to chart.</p>;
  }
  if (kind === "line") return <LineChart points={points} drill={drill} />;
  if (kind === "pie") return <PieChart points={points} drill={drill} />;
  // Scatter takes no drill-down: its label is an X *coordinate*, so clicking a
  // point would narrow to one exact value of a continuous axis — almost never
  // the question somebody is asking. Left out rather than wired to something
  // that technically works.
  if (kind === "scatter") return <ScatterChart points={points} />;
  return <BarChart points={points} drill={drill} />;
}

/** Rows come back from the query endpoint as `[label, value]` pairs of
 * unknowns. A non-numeric measure is dropped rather than charted as zero: a
 * zero bar is a claim about the data, and "this row could not be measured" is
 * not that claim. */
export function toPoints(rows: unknown[][]): ChartPoint[] {
  const points: ChartPoint[] = [];
  for (const row of rows) {
    const value = Number(row[1]);
    if (!Number.isFinite(value)) continue;
    points.push({ label: row[0] === null || row[0] === undefined ? "∅" : String(row[0]), value });
  }
  return points;
}
