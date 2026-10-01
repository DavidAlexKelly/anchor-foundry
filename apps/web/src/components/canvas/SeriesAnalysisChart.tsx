"use client";

/** One canvas of the Time Series Analysis widget (§647): its plots against
 * one time axis and one value axis, each in its colour and line style. The
 * geometry is `series-analysis.ts`'s. */

import {
  areaOf, eventSpan, markersOf, outlineOf, pathOf, scaleOf, timesOf, valueAt,
  type AxisSettings, type PlotDisplay, type Reading, type Scale, type SeriesEvent,
} from "./series-analysis";

const WIDTH = 640;
const HEIGHT = 200;
/** Each axis's room beside the frame, and the least a side is given. */
const AXIS_WIDTH = 48;
const EDGE = 8;
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

function timeText(t: number, span: number): string {
  const d = new Date(t);
  return span > 2 * 86_400_000 ? d.toISOString().slice(0, 10) : d.toISOString().slice(5, 16).replace("T", " ");
}

/** p.395's *Event highlight* (§651): an event set's time ranges, shaded in
 * its plot's colour under the lines. */
export interface CanvasEvents { id: string; color: string; events: SeriesEvent[] }

export function SeriesAnalysisChart({ canvas, plots, axes, events = [] }: {
  canvas: number; plots: CanvasPlot[]; axes: CanvasAxis[]; events?: CanvasEvents[];
}) {
  const times = timesOf(plots.map((p) => p.readings));
  const lefts = axes.filter((a) => a.settings.align === "left");
  const rights = axes.filter((a) => a.settings.align === "right");
  const LEFT = Math.max(EDGE, lefts.length * AXIS_WIDTH);
  const RIGHT = Math.max(EDGE, rights.length * AXIS_WIDTH);
  const frame = { width: WIDTH - LEFT - RIGHT, height: HEIGHT - BOTTOM };
  const scales = new Map<number, Scale | null>(axes.map((a) => [a.axis, scaleOf(
    plots.filter((p) => p.axis === a.axis).map((p) => p.readings), a.settings)]));
  const extentFor = (axis: number) => {
    const scale = scales.get(axis);
    return times && scale ? { ...times, ...scale } : null;
  };
  const gridded = axes.find((a) => scales.get(a.axis))?.axis;
  return (
    <figure data-testid={`series-canvas-${canvas}`} style={{ margin: "6px 0" }}>
      {times === null ? (
        <p className="canvas-widget-empty">No readings on this canvas.</p>
      ) : (
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Canvas ${canvas}`}
             style={{ width: "100%" }}>
          {axes.map((a) => {
            const scale = scales.get(a.axis);
            const side = a.settings.align === "left" ? lefts : rights;
            const place = side.indexOf(a);
            const x = a.settings.align === "left"
              ? LEFT - 4 - place * AXIS_WIDTH : WIDTH - RIGHT + 4 + place * AXIS_WIDTH;
            const anchor = a.settings.align === "left" ? "end" : "start";
            return scale && (
              <g key={`axis-${a.axis}`} data-axis={a.axis} data-align={a.settings.align}>
                {[0, 0.5, 1].map((f) => {
                  const y = frame.height - f * frame.height;
                  return (
                    <g key={f}>
                      {a.axis === gridded && (
                        <line x1={LEFT} x2={WIDTH - RIGHT} y1={y} y2={y} stroke="var(--border, #d8dee4)" />
                      )}
                      <text data-tick={f} x={x} y={Math.max(10, y + 4)} fontSize={10} textAnchor={anchor}
                            fill="var(--muted, #5c6670)">
                        {valueText(valueAt(scale, f))}
                      </text>
                    </g>
                  );
                })}
                {a.settings.unit && (
                  <text data-unit x={x} y={frame.height / 4 + 4} fontSize={10} textAnchor={anchor}
                        fill="var(--muted, #5c6670)">
                    {a.settings.unit}
                  </text>
                )}
              </g>
            );
          })}
          {[0, 0.5, 1].map((f) => (
            <text key={`t${f}`} x={LEFT + f * frame.width} y={HEIGHT - 4} fontSize={10}
                  textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"} fill="var(--muted, #5c6670)">
              {timeText(times.t0 + (times.t1 - times.t0) * f, times.t1 - times.t0)}
            </text>
          ))}
          <g transform={`translate(${LEFT} 0)`}>
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
                <path data-gradient={p.id} d={areaOf(p.readings, extentFor(p.axis)!, frame)} stroke="none"
                      fill={`url(#series-${canvas}-gradient-${n})`} />
              </g>
            ))}
            {plots.map((p) => extentFor(p.axis) && (
              <path key={p.id} data-plot={p.id} d={pathOf(p.readings, extentFor(p.axis)!, frame)} fill="none"
                    stroke={p.color} strokeWidth={p.display.width}
                    strokeDasharray={p.dashed ? "5 3" : undefined}>
                <title>{p.label}</title>
              </path>
            ))}
            {plots.map((p) => p.display.shape !== "none" && extentFor(p.axis) && (
              <path key={`points-${p.id}`} data-points={p.id}
                    d={markersOf(p.readings, extentFor(p.axis)!, frame, p.display.shape, p.display.size)}
                    fill={p.display.fill === "line" ? p.color : p.display.fill === "white" ? "#fff" : "none"}
                    stroke={p.color} strokeWidth={outlineOf(p.display)} />
            ))}
          </g>
        </svg>
      )}
    </figure>
  );
}
