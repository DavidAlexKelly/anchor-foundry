"use client";

/** One canvas of the Time Series Analysis widget (§647): its plots against
 * one time axis and one value axis, each in its colour and line style. The
 * geometry is `series-analysis.ts`'s. */

import {
  areaOf, eventSpan, extentOf, markersOf, outlineOf, pathOf,
  type PlotDisplay, type Reading, type SeriesEvent,
} from "./series-analysis";

const WIDTH = 640;
const HEIGHT = 200;
const LEFT = 48;
const BOTTOM = 20;

export interface CanvasPlot {
  id: string;
  label: string;
  color: string;
  dashed: boolean;
  display: PlotDisplay;
  readings: Reading[];
}

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

export function SeriesAnalysisChart({ canvas, plots, events = [] }: {
  canvas: number; plots: CanvasPlot[]; events?: CanvasEvents[];
}) {
  const extent = extentOf(plots.map((p) => p.readings));
  const frame = { width: WIDTH - LEFT, height: HEIGHT - BOTTOM };
  return (
    <figure data-testid={`series-canvas-${canvas}`} style={{ margin: "6px 0" }}>
      {extent === null ? (
        <p className="canvas-widget-empty">No readings on this canvas.</p>
      ) : (
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Canvas ${canvas}`}
             style={{ width: "100%" }}>
          {[0, 0.5, 1].map((f) => {
            const v = extent.v0 + (extent.v1 - extent.v0) * f;
            const y = frame.height - f * frame.height;
            return (
              <g key={`v${f}`}>
                <line x1={LEFT} x2={WIDTH} y1={y} y2={y} stroke="var(--border, #d8dee4)" />
                <text x={LEFT - 4} y={y + 4} fontSize={10} textAnchor="end" fill="var(--muted, #5c6670)">
                  {valueText(v)}
                </text>
              </g>
            );
          })}
          {[0, 0.5, 1].map((f) => (
            <text key={`t${f}`} x={LEFT + f * frame.width} y={HEIGHT - 4} fontSize={10}
                  textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"} fill="var(--muted, #5c6670)">
              {timeText(extent.t0 + (extent.t1 - extent.t0) * f, extent.t1 - extent.t0)}
            </text>
          ))}
          <g transform={`translate(${LEFT} 0)`}>
            {events.flatMap((set) => set.events.map((e, n) => {
              const span = eventSpan(e, extent, frame.width);
              return span && (
                <rect key={`${set.id}-${n}`} data-event-set={set.id} x={span.x} y={0}
                      width={span.width} height={frame.height} fill={set.color} fillOpacity={0.15} />
              );
            }))}
            {plots.map((p, n) => p.display.gradient && (
              <g key={`gradient-${p.id}`}>
                <defs>
                  <linearGradient id={`series-${canvas}-gradient-${n}`} x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={p.color} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={p.color} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <path data-gradient={p.id} d={areaOf(p.readings, extent, frame)} stroke="none"
                      fill={`url(#series-${canvas}-gradient-${n})`} />
              </g>
            ))}
            {plots.map((p) => (
              <path key={p.id} data-plot={p.id} d={pathOf(p.readings, extent, frame)} fill="none"
                    stroke={p.color} strokeWidth={p.display.width}
                    strokeDasharray={p.dashed ? "5 3" : undefined}>
                <title>{p.label}</title>
              </path>
            ))}
            {plots.map((p) => p.display.shape !== "none" && (
              <path key={`points-${p.id}`} data-points={p.id}
                    d={markersOf(p.readings, extent, frame, p.display.shape, p.display.size)}
                    fill={p.display.fill === "line" ? p.color : p.display.fill === "white" ? "#fff" : "none"}
                    stroke={p.color} strokeWidth={outlineOf(p.display)} />
            ))}
          </g>
        </svg>
      )}
    </figure>
  );
}
