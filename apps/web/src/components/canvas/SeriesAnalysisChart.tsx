"use client";

/** One canvas of the Time Series Analysis widget (§647): its plots against
 * one time axis and one value axis, each in its colour and line style. The
 * geometry is `series-analysis.ts`'s. */

import { useState } from "react";

import {
  DEFAULT_TOOLTIP, areaOf, axisLayout, eventSpan, fractionOf, hoveredOf, inView, markersOf, outlineOf,
  pathOf, readingAt, scaleOf, shownShape, significant, timeLabel, timesOf, valueAt,
  type AxisSettings, type PlotDisplay, type Reading, type Scale, type SeriesEvent, type TooltipOptions,
  type ViewRange,
} from "./series-analysis";

const WIDTH = 640;
const HEIGHT = 200;
const BOTTOM = 20;

export interface CanvasPlot {
  id: string;
  label: string;
  color: string;
  dashed: boolean;
  display: PlotDisplay;
  /** Which of the canvas's axes it is on (§656). */
  axis: number;
  readings: Reading[];
}

/** One of the canvas's axes and its settings (§656). */
export interface CanvasAxis { axis: number; settings: AxisSettings }

function valueText(v: number): string {
  const abs = Math.abs(v);
  return abs >= 1000 || (abs > 0 && abs < 0.01) ? v.toExponential(1) : String(Number(v.toFixed(2)));
}


/** p.395's *Event highlight* (§651): an event set's time ranges, shaded in
 * its plot's colour under the lines. */
export interface CanvasEvents { id: string; color: string; events: SeriesEvent[] }

export function SeriesAnalysisChart({
  canvas, plots, axes, events = [], view = null, utc = false,
  overlay = false, collapsed = false, boundaries = false, tooltip = DEFAULT_TOOLTIP,
}: {
  canvas: number; plots: CanvasPlot[]; axes: CanvasAxis[]; events?: CanvasEvents[];
  /** The reader's view of the time axis (§659); null is the full range. */
  view?: ViewRange | null;
  /** p.396's *Enable UTC time format*; otherwise the reader's own time. */
  utc?: boolean;
  /** p.396's Y-axis chart options (§660). */
  overlay?: boolean;
  collapsed?: boolean;
  boundaries?: boolean;
  /** p.396's *Tooltip options* (§660). */
  tooltip?: TooltipOptions;
}) {
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);
  const times = view ? { t0: view.from, t1: view.to } : timesOf(plots.map((p) => p.readings));
  const lefts = axes.filter((a) => a.settings.align === "left");
  const rights = axes.filter((a) => a.settings.align === "right");
  const layout = axisLayout(lefts.length, rights.length, { overlay, collapsed, boundaries });
  const LEFT = layout.left;
  const RIGHT = layout.right;
  const frame = { width: WIDTH - LEFT - RIGHT, height: HEIGHT - BOTTOM };
  const offsetAt = (t: number) => (utc ? 0 : -new Date(t).getTimezoneOffset());
  const scales = new Map<number, Scale | null>(axes.map((a) => [a.axis, scaleOf(
    plots.filter((p) => p.axis === a.axis).map((p) => inView(p.readings, view)), a.settings)]));
  const extentFor = (axis: number) => {
    const scale = scales.get(axis);
    return times && scale ? { ...times, ...scale } : null;
  };
  const gridded = axes.find((a) => scales.get(a.axis))?.axis;
  // p.396's tooltip (§660): the pointer's time, and each plot's reading
  // nearest it - or the hovered plot's alone.
  const at = times && pointer ? times.t0 + ((pointer.x - LEFT) / frame.width) * (times.t1 - times.t0) : null;
  const nearest = at === null ? [] : plots.flatMap((p) => {
    const reading = readingAt(inView(p.readings, view), at);
    const extent = extentFor(p.axis);
    return reading && extent
      ? [{ plot: p, reading, y: frame.height - fractionOf(extent, reading.v) * frame.height }] : [];
  });
  const hovered = pointer ? hoveredOf(nearest.map((n) => ({ id: n.plot.id, y: n.y })), pointer.y) : null;
  const shown = tooltip.values === "hovered" ? nearest.filter((n) => n.plot.id === hovered) : nearest;
  // The time of the reading shown nearest the pointer, not the pointer's own,
  // which is only as fine as a pixel.
  const shownAt = at === null ? null : readingAt(shown.map((n) => n.reading), at)?.t ?? null;
  return (
    <figure data-testid={`series-canvas-${canvas}`} style={{ margin: "6px 0", position: "relative" }}>
      {times === null ? (
        <p className="canvas-widget-empty">No readings on this canvas.</p>
      ) : (
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Canvas ${canvas}`}
             style={{ width: "100%" }}
             onMouseMove={(e) => {
               const box = e.currentTarget.getBoundingClientRect();
               const x = ((e.clientX - box.left) / box.width) * WIDTH;
               const y = ((e.clientY - box.top) / box.height) * HEIGHT;
               setPointer(x >= LEFT && x <= WIDTH - RIGHT && y <= frame.height ? { x, y } : null);
             }}
             onMouseLeave={() => setPointer(null)}>
          {axes.map((a) => {
            const scale = scales.get(a.axis);
            const left = a.settings.align === "left";
            const place = (left ? lefts : rights).indexOf(a);
            // Beside the frame, or over it, facing in (§660).
            const x = left
              ? (overlay ? LEFT + 4 + place * layout.per : LEFT - 4 - place * layout.per)
              : (overlay ? WIDTH - RIGHT - 4 - place * layout.per : WIDTH - RIGHT + 4 + place * layout.per);
            const anchor = left === overlay ? "start" : "end";
            const edge = left
              ? (overlay ? LEFT + place * layout.per : LEFT - place * layout.per)
              : (overlay ? WIDTH - RIGHT - place * layout.per : WIDTH - RIGHT + place * layout.per);
            return scale && (
              <g key={`axis-${a.axis}`} data-axis={a.axis} data-align={a.settings.align}
                 data-overlay={overlay ? "" : undefined} data-collapsed={collapsed ? "" : undefined}>
                {a.axis === gridded && [0, 0.5, 1].map((f) => (
                  <line key={`grid-${f}`} x1={LEFT} x2={WIDTH - RIGHT} y1={frame.height - f * frame.height}
                        y2={frame.height - f * frame.height} stroke="var(--border, #d8dee4)" />
                ))}
                {collapsed && (
                  <line x1={edge} x2={edge} y1={0} y2={frame.height} stroke="var(--muted, #5c6670)" />
                )}
                {layout.ticks.map((f) => {
                  const y = frame.height - f * frame.height;
                  return (
                    <text key={f} data-tick={f} x={x} y={Math.max(10, y + 4)} fontSize={10} textAnchor={anchor}
                          fill="var(--muted, #5c6670)"
                          {...(overlay ? { stroke: "var(--surface, #fff)", strokeWidth: 3, paintOrder: "stroke" } : {})}>
                      {valueText(valueAt(scale, f))}
                    </text>
                  );
                })}
                {a.settings.unit && !collapsed && (
                  <text data-unit x={x} y={frame.height / 4 + 4} fontSize={10} textAnchor={anchor}
                        fill="var(--muted, #5c6670)">
                    {a.settings.unit}
                  </text>
                )}
              </g>
            );
          })}
          {[0, 0.5, 1].map((f) => (
            <text key={`t${f}`} data-time={f} x={LEFT + f * frame.width} y={HEIGHT - 4} fontSize={10}
                  textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"} fill="var(--muted, #5c6670)">
              {(() => {
                const t = times.t0 + (times.t1 - times.t0) * f;
                const text = timeLabel(t, times.t1 - times.t0, offsetAt(t));
                return f === 1 && utc ? `${text} UTC` : text;
              })()}
            </text>
          ))}
          <defs>
            <clipPath id={`series-${canvas}-frame`}>
              <rect x={0} y={0} width={frame.width} height={frame.height} />
            </clipPath>
          </defs>
          <g transform={`translate(${LEFT} 0)`} clipPath={`url(#series-${canvas}-frame)`}>
            {events.flatMap((set) => set.events.map((e, n) => {
              const span = eventSpan(e, times, frame.width);
              return span && (
                <rect key={`${set.id}-${n}`} data-event-set={set.id} x={span.x} y={0}
                      width={span.width} height={frame.height} fill={set.color} fillOpacity={0.15} />
              );
            }))}
            {plots.map((p, n) => p.display.gradient && extentFor(p.axis) && (
              <g key={`gradient-${p.id}`}>
                <defs>
                  <linearGradient id={`series-${canvas}-gradient-${n}`} x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={p.color} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={p.color} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <path data-gradient={p.id} d={areaOf(p.readings, extentFor(p.axis)!, frame, p.display)} stroke="none"
                      fill={`url(#series-${canvas}-gradient-${n})`} />
              </g>
            ))}
            {plots.map((p) => extentFor(p.axis) && (
              <path key={p.id} data-plot={p.id} d={pathOf(p.readings, extentFor(p.axis)!, frame, p.display)} fill="none"
                    stroke={p.color} strokeWidth={p.display.width}
                    strokeDasharray={p.dashed ? "5 3" : undefined}>
                <title>{p.label}</title>
              </path>
            ))}
            {plots.map((p) => shownShape(p.display) !== "none" && extentFor(p.axis) && (
              <path key={`points-${p.id}`} data-points={p.id}
                    d={markersOf(p.readings, extentFor(p.axis)!, frame, shownShape(p.display), p.display.size)}
                    fill={p.display.fill === "line" ? p.color : p.display.fill === "white" ? "#fff" : "none"}
                    stroke={p.color} strokeWidth={outlineOf(p.display)} />
            ))}
          </g>
          {tooltip.show && pointer && (
            <line data-cursor x1={pointer.x} x2={pointer.x} y1={0} y2={frame.height}
                  stroke="var(--muted, #5c6670)" strokeDasharray="2 2" />
          )}
        </svg>
      )}
      {tooltip.show && shownAt !== null && (
        <div role="tooltip" data-testid={`series-tooltip-${canvas}`} className="card"
             style={{ position: "absolute", top: 4, left: `${(pointer!.x / WIDTH) * 100}%`, padding: "4px 6px",
               fontSize: 11, pointerEvents: "none", maxWidth: 200,
               whiteSpace: tooltip.wrap ? "normal" : "nowrap" }}>
          {tooltip.time && (
            <div data-time="">{`${timeLabel(shownAt!, 0, offsetAt(shownAt!))}${utc ? " UTC" : ""}`}</div>
          )}
          {shown.map(({ plot, reading }) => (
            <div key={plot.id} data-plot={plot.id}>
              <span style={{ color: plot.color }}>■</span> {plot.label}: {significant(reading.v, tooltip.digits)}
            </div>
          ))}
        </div>
      )}
    </figure>
  );
}
