"use client";

/**
 * The map (ROADMAP Canvas item 4) — pins on the bundled world outline, with
 * pan, zoom and clustering, in hand-written SVG.
 *
 * **Why no mapping library.** The same call `charts.tsx` made, for a sharper
 * reason: every mapping library's reason to exist is tile handling, and this
 * map has no tiles (see `basemap.ts` — a tile request is an outbound call from
 * the viewer's browser carrying the viewport of the customer's own data). What
 * is left once tiles are gone is an affine transform, a drag handler and a
 * grid clustering pass, which is this file. If configurable tile sources ever
 * land, that is the moment to reach for a library rather than grow one.
 *
 * **What the map refuses to do quietly.** Points it cannot place (a malformed
 * geopoint, coordinates out of range) are counted and reported, never dropped
 * silently or clamped onto the edge of the world; points scrolled out of view
 * are counted too, because "no pins here" and "you have panned away from your
 * data" look identical otherwise.
 */

import React, { useCallback, useMemo, useRef, useState } from "react";
import { WORLD_OUTLINE } from "./basemap";

export interface MapPoint {
  id: string;
  label: string;
  lat: number;
  lon: number;
}

const WIDTH = 640;
const HEIGHT = 340;
const ASPECT = HEIGHT / WIDTH;
/** Screen-space cell for clustering. About two pin diameters: closer than
 * this and the pins are a blob rather than a count. */
const CELL_PX = 30;
/** Zoom limits in degrees of longitude across the view. The whole world at
 * one end; at the other, roughly a town — there is no basemap detail past
 * that, so zooming further would only make the blankness larger. */
const MAX_SPAN = 360;
const MIN_SPAN = 0.05;
/** Below this span the outline stops telling the viewer anything: the source
 * data is 1:110m, so a few degrees across a 640px view is already past its
 * resolution and the coastline becomes a decorative polygon. */
const DETAIL_LIMIT = 8;

export interface MapView {
  x: number; // left edge, in degrees of longitude
  y: number; // top edge, in -latitude (SVG's y grows downward)
  w: number; // width in degrees; height is w * ASPECT
}

/**
 * Parse whatever a geopoint arrives as into a point, or null.
 *
 * The accepted shapes mirror the API's `_coerce_geopoint` deliberately — the
 * platform's own sync path writes a geopoint property back to a dataset
 * column as `"lat,lon"`, and its API returns `{lat, lon}`, so a widget that
 * only understood one of them would work against object types and fail
 * against the datasets those same objects came from.
 *
 * Out-of-range coordinates are rejected rather than clamped: a pin at exactly
 * 90°N because the value was 910 is a wrong answer drawn confidently, and the
 * usual cause — lon/lat sent the other way round — produces exactly that.
 */
export function toLatLon(value: unknown): { lat: number; lon: number } | null {
  let v = value;
  if (typeof v === "string") {
    const text = v.trim();
    if (!text) return null;
    if (text.startsWith("{") || text.startsWith("[")) {
      try {
        v = JSON.parse(text);
      } catch {
        return null;
      }
    } else {
      const parts = text.split(",");
      if (parts.length !== 2) return null;
      v = [Number(parts[0]), Number(parts[1])];
    }
  }
  let lat: number;
  let lon: number;
  if (Array.isArray(v)) {
    if (v.length !== 2) return null;
    lat = Number(v[0]);
    lon = Number(v[1]);
  } else if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    lat = Number(o.lat ?? o.latitude);
    lon = Number(o.lon ?? o.lng ?? o.longitude);
  } else {
    return null;
  }
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

/** The view that shows every point, padded so pins are not on the edge. A
 * single point gets a span rather than an infinite zoom, and everything is
 * clamped to the world — panning off the end of the map is not a view of
 * anything. */
export function fitView(points: MapPoint[]): MapView {
  if (points.length === 0) return { x: -180, y: -90, w: 360 };
  const lons = points.map((p) => p.lon);
  const lats = points.map((p) => p.lat);
  const minX = Math.min(...lons);
  const maxX = Math.max(...lons);
  const minY = Math.min(...lats.map((l) => -l));
  const maxY = Math.max(...lats.map((l) => -l));
  // The floor is set by the basemap, not by the data: fitting tightly around
  // three sites in one city would open on a view where the outline is a
  // meaningless polygon. Ten degrees keeps recognisable geography behind the
  // pins, and zooming closer stays one scroll away (with the widget saying
  // what it can no longer show).
  const spanX = Math.max(maxX - minX, (maxY - minY) / ASPECT, 10) * 1.4;
  const w = Math.min(MAX_SPAN, Math.max(MIN_SPAN, spanX));
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  return clampView({ x: cx - w / 2, y: cy - (w * ASPECT) / 2, w });
}

function clampView(view: MapView): MapView {
  const w = Math.min(MAX_SPAN, Math.max(MIN_SPAN, view.w));
  const h = w * ASPECT;
  return {
    w,
    x: Math.min(180 - w, Math.max(-180, view.x)),
    // 180 degrees of latitude is taller than the world when the view is wide,
    // so centre vertically instead of clamping to an impossible top edge.
    y: h >= 180 ? -h / 2 : Math.min(90 - h, Math.max(-90, view.y)),
  };
}

interface Placed {
  key: string;
  x: number;
  y: number;
  members: MapPoint[];
}

/** Group pins that would overlap into one bubble. Grid rather than
 * hierarchical clustering: at widget size the difference is invisible, and a
 * grid is stable under panning — a bubble that re-forms differently every
 * time the mouse moves is worse than a slightly uneven one. */
export function clusterPoints(points: MapPoint[], view: MapView): { placed: Placed[]; offscreen: number } {
  const h = view.w * ASPECT;
  const cells = new Map<string, MapPoint[]>();
  let offscreen = 0;
  for (const p of points) {
    const px = ((p.lon - view.x) / view.w) * WIDTH;
    const py = ((-p.lat - view.y) / h) * HEIGHT;
    if (px < 0 || px > WIDTH || py < 0 || py > HEIGHT) {
      offscreen += 1;
      continue;
    }
    const key = `${Math.floor(px / CELL_PX)}:${Math.floor(py / CELL_PX)}`;
    const bucket = cells.get(key);
    if (bucket) bucket.push(p);
    else cells.set(key, [p]);
  }
  const placed: Placed[] = [];
  for (const [key, members] of cells) {
    const lon = members.reduce((s, m) => s + m.lon, 0) / members.length;
    const lat = members.reduce((s, m) => s + m.lat, 0) / members.length;
    placed.push({
      key,
      x: ((lon - view.x) / view.w) * WIDTH,
      y: ((-lat - view.y) / h) * HEIGHT,
      members,
    });
  }
  return { placed, offscreen };
}

export function MapCanvas({
  points,
  unplaceable = 0,
  total,
  atLimit = false,
  onSelect,
}: {
  points: MapPoint[];
  /** Rows whose location could not be read. Reported, never hidden. */
  unplaceable?: number;
  /** Matching rows, when the source knows how many there are. A map that
   * plots the first page of a larger answer looks exactly like a map of the
   * whole answer, which is the one thing it must not do silently. */
  total?: number;
  /** The query came back full, so there may be more rows than were asked
   * for — true even when nothing can say how many more. */
  atLimit?: boolean;
  onSelect?: (point: MapPoint) => void;
}) {
  const [view, setView] = useState<MapView | null>(null);
  const [panning, setPanning] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ px: number; py: number; view: MapView } | null>(null);

  // The fitted view is recomputed from the data until the viewer moves; after
  // that it is theirs. A filter changing under a map that keeps snapping back
  // to fit is unusable, and one that never fits at all opens on the wrong
  // continent.
  const fitted = useMemo(() => fitView(points), [points]);
  const current = view ?? fitted;
  const { placed, offscreen } = useMemo(() => clusterPoints(points, current), [points, current]);

  const zoomBy = useCallback((factor: number, anchor?: { x: number; y: number }) => {
    setView((previous) => {
      const from = previous ?? fitted;
      const w = from.w * factor;
      const ax = anchor ? anchor.x / WIDTH : 0.5;
      const ay = anchor ? anchor.y / HEIGHT : 0.5;
      // Keep whatever is under the pointer under the pointer.
      return clampView({
        w,
        x: from.x + (from.w - w) * ax,
        y: from.y + (from.w - w) * ASPECT * ay,
      });
    });
  }, [fitted]);

  // Panning listens on the window, and suppresses the native drag while it
  // does. Both halves were found in a browser rather than reasoned out: the
  // Craft.js editor makes the block around this SVG an HTML5 drag source, and
  // `dragstart` fires on *that* element, not on the SVG under the pointer -
  // so no handler here could see it, and once a native drag begins the
  // browser stops sending mousemove entirely. The symptom was a map that
  // panned by exactly one frame and then froze. Listening on the window also
  // means a drag that continues past the edge of the map keeps panning
  // instead of sticking where the pointer left.
  React.useEffect(() => {
    if (!panning) return;
    const noDrag = (e: Event) => e.preventDefault();
    document.addEventListener("dragstart", noDrag, true);
    const onMove = (e: MouseEvent) => {
      const d = drag.current;
      const rect = svgRef.current?.getBoundingClientRect();
      if (!d || !rect) return;
      const degPerPx = d.view.w / rect.width;
      setView(clampView({
        w: d.view.w,
        x: d.view.x - (e.clientX - d.px) * degPerPx,
        y: d.view.y - (e.clientY - d.py) * degPerPx,
      }));
    };
    const onUp = () => {
      drag.current = null;
      setPanning(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("dragstart", noDrag, true);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [panning]);

  const svgPoint = (e: React.MouseEvent | React.WheelEvent) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { x: WIDTH / 2, y: HEIGHT / 2 };
    return {
      x: ((e.clientX - rect.left) / rect.width) * WIDTH,
      y: ((e.clientY - rect.top) / rect.height) * HEIGHT,
    };
  };

  const k = WIDTH / current.w;

  return (
    <div className="canvas-map">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="Map"
        style={{ width: "100%", touchAction: "none", cursor: panning ? "grabbing" : "grab" }}
        onMouseDown={(e) => {
          // The widget's own Craft.js drag connector sits on the block around
          // this SVG, and in the editor it would otherwise pick the map up and
          // carry it across the canvas the moment somebody tried to pan.
          // Panning wins inside the map; the block's border still drags it.
          e.stopPropagation();
          drag.current = { px: e.clientX, py: e.clientY, view: current };
          setPanning(true);
        }}
        onWheel={(e) => {
          zoomBy(e.deltaY > 0 ? 1.25 : 1 / 1.25, svgPoint(e));
        }}
      >
        <rect width={WIDTH} height={HEIGHT} fill="var(--map-sea, #eef2f4)" />
        <g transform={`scale(${k}) translate(${-current.x} ${-current.y})`}>
          <path
            d={WORLD_OUTLINE}
            fill="var(--map-land, #d9e0da)"
            stroke="var(--map-border, #a9b6ad)"
            strokeWidth={0.8}
            vectorEffect="non-scaling-stroke"
          />
        </g>
        {placed.map((group) => {
          const only = group.members.length === 1 ? group.members[0] : undefined;
          return only ? (
            <circle
              key={group.key}
              cx={group.x}
              cy={group.y}
              r={5}
              fill="var(--accent, #2f6f4f)"
              stroke="#fff"
              strokeWidth={1.5}
              style={{ cursor: onSelect ? "pointer" : "inherit" }}
              onClick={() => onSelect?.(only)}
            >
              <title>{`${only.label} (${only.lat.toFixed(4)}, ${only.lon.toFixed(4)})`}</title>
            </circle>
          ) : (
            <g key={group.key} style={{ cursor: "zoom-in" }} onClick={() => zoomBy(0.4, group)}>
              <circle
                cx={group.x}
                cy={group.y}
                r={Math.min(20, 8 + Math.sqrt(group.members.length) * 2)}
                fill="var(--accent, #2f6f4f)"
                fillOpacity={0.82}
                stroke="#fff"
                strokeWidth={1.5}
              />
              <text
                x={group.x}
                y={group.y + 4}
                textAnchor="middle"
                fontSize={11}
                fill="#fff"
                style={{ pointerEvents: "none" }}
              >
                {group.members.length}
              </text>
              <title>
                {`${group.members.length} here: ${group.members.slice(0, 6).map((m) => m.label).join(", ")}` +
                  (group.members.length > 6 ? ", …" : "")}
              </title>
            </g>
          );
        })}
      </svg>
      <div className="canvas-map-bar">
        <button type="button" onClick={() => zoomBy(1 / 1.6)} aria-label="Zoom in">+</button>
        <button type="button" onClick={() => zoomBy(1.6)} aria-label="Zoom out">−</button>
        <button type="button" onClick={() => setView(null)}>Fit to data</button>
        <span className="canvas-map-note">
          {points.length.toLocaleString()} placed
          {offscreen > 0
            ? offscreen === points.length
              ? ", all of them outside the view"
              : `, ${offscreen.toLocaleString()} of them outside the view`
            : ""}
          {unplaceable > 0 ? `, ${unplaceable.toLocaleString()} without a usable location` : ""}
          {total !== undefined && total > points.length + unplaceable
            ? `, of ${total.toLocaleString()} matching`
            : atLimit
              ? ", and possibly more beyond the widget's limit"
              : ""}
          {current.w < DETAIL_LIMIT ? " — country outlines only, no detail at this zoom" : ""}
        </span>
      </div>
    </div>
  );
}
