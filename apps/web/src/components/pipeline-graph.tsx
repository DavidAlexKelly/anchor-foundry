"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { FileState } from "@/lib/file-verdict";
import type { GraphViewer, PipelineGraph, PipelineNode } from "@/lib/types";
import {
  between, buildPlan, buildSummary, cascadeCount, type PlannedModel,
} from "@/lib/graph-builds";
import { clearSummary, looksLikeCron, scheduleSummary } from "@/lib/graph-schedules";
import {
  GRAPH_KINDS, columnsIn, foundByColumn, inverted, isDrag, kindsIn, outOfDateNote, relatives, search, toggleSelected, type GraphView, viewOf,
} from "@/lib/pipeline-graph";
import {
  LAYOUTS, NODE_H, NODE_W, layoutIn, layoutOf, nodesInRect, type Place,
  type Rect,
} from "@/lib/graph-layout";
import {
  durationLabel, emptyReason, placeOf, timelineFor,
} from "@/lib/build-timeline";
import {
  COLOURINGS, type Swatch, colouringIn, legendFor, swatchFor,
} from "@/lib/node-colouring";
import { svgFilename, svgFor } from "@/lib/graph-svg";

// One renderer, two entry points: the project-wide Pipeline page and a
// single dataset's lineage, which is the same endpoint with a `focus`
// (apps/api/src/services/pipeline.py). Roadmap Datasets item 5 asked for
// lineage to reuse "whatever graph-rendering approach Models item 2 settles
// on" - this file is that approach, so there is only ever one of it.
//
// The API returns each node's layer and its position within that layer
// (apps/api/src/services/pipeline.py), so laying the graph out is arithmetic
// rather than a graph-layout library — see that module's docstring for why
// the layering lives on the server.
// The card geometry and the layer arithmetic are `lib/pipeline-graph`'s,
// because §354's drag rectangle has to know where the cards are — see that
// module for why there is only one copy of them.

/** A cubic bezier from one node's right edge to the next node's left edge.
 *  Horizontal control points keep every edge reading left-to-right even when
 *  it spans several layers. */
function edgePath(from: Place, to: Place): string {
  const x1 = from.x + NODE_W;
  const y1 = from.y + NODE_H / 2;
  const x2 = to.x;
  const y2 = to.y + NODE_H / 2;
  const bend = Math.max(30, (x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
}

function subtitle(node: PipelineNode): string {
  if (node.kind === "connection") {
    // p.42's "Learn more about the different source types": the source type
    // is what tells a reader whether this is a Postgres or an S3 bucket, and
    // the name above it is only what somebody called it (§420).
    return node.slug ?? "data source";
  }
  if (node.kind === "object_type") {
    // The api_name, because that is what a person writing a transform or an
    // action against this type actually types — the display name is already
    // the line above it.
    return node.slug ?? "object type";
  }
  if (node.kind === "model") {
    const trigger =
      node.trigger_mode === "cron" ? "scheduled"
      : node.trigger_mode === "upstream" ? "on new input data"
      : "manual";
    return `${node.language === "python" ? "Python" : "SQL"} · ${trigger}`;
  }
  const rows = node.row_count === null ? "" : `${node.row_count.toLocaleString()} rows`;
  return [rows, node.origin === "model_output" ? "model output" : node.origin]
    .filter(Boolean)
    .join(" · ");
}

function NodeCard({
  node,
  place,
  selected,
  swatch,
  lit = false,
  matched = false,
  dimmed = false,
  review,
  onSelect,
}: {
  node: PipelineNode;
  /** Where this card goes, under the layout in force (§424). Passed in rather
   *  than computed here, because the edge curves, §354's drag rectangle and
   *  §423's export all have to agree with it. */
  place: Place;
  selected: boolean;
  /** p.38's colouring, already decided (§419) — `null` is p.38's "No color".
   *  Passed in rather than computed here because the legend beside the graph
   *  has to be reading the same rule as the cards, and a card that worked out
   *  its own colour is a second copy of that rule (§292). */
  swatch: Swatch | null;
  /** This dataset has the column p.55's list has highlighted. */
  lit?: boolean;
  /** `code-repositories` p.55's indicator: where the reviewer has got to with
   *  the transform file that generates this dataset, on a proposal.
   *
   *  **Absent is not "unread"**, and the two must not be drawn the same way: a
   *  node with no verdict is one the proposal does not touch, while `unread`
   *  is one it does touch and nobody has looked at. Undefined on every graph
   *  outside a review, which is most of them. */
  review?: FileState;
  /** This node is one of p.8's search results (§356). */
  matched?: boolean;
  /** Something is being looked at — a column's datasets, a search's results —
   *  and this node is not part of it. */
  dimmed?: boolean;
  /** Told whether Ctrl/Cmd was held, which is p.54's "select multiple nodes
   *  at once" — the modifier is read here rather than in the handler because
   *  only the event knows it. */
  onSelect: (additive: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={(e) => onSelect(e.ctrlKey || e.metaKey)}
      title={node.name}
      style={{
        position: "absolute",
        left: place.x,
        top: place.y,
        width: NODE_W,
        height: NODE_H,
        textAlign: "left",
        padding: "9px 11px",
        background: "var(--panel)",
        border: `${node.is_focus ? 2 : 1}px solid ${
          selected || node.is_focus
            ? "var(--accent)"
            : node.in_cycle
              ? "var(--danger)"
              : "var(--line-strong)"
        }`,
        // p.55's column highlight outranks p.38's colouring: the reader who
        // clicked a column is asking one question, and the cards answering it
        // have to be the ones that stand out.
        borderLeft: `4px solid ${
          lit ? "var(--accent)" : swatch?.token ?? "var(--line)"
        }`,
        borderRadius: "var(--radius)",
        boxShadow: selected ? "var(--shadow-card-hover)" : "var(--shadow-card)",
        cursor: "pointer",
        display: "block",
        overflow: "hidden",
        // p.55's highlight, as a *contrast* rather than a colour on the lit
        // ones alone: what the reader is looking for is which of these has the
        // column, and dimming the rest is what makes that readable on a graph
        // with forty nodes on it.
        opacity: dimmed ? 0.35 : 1,
        // A search result says so on its own as well as by everything else
        // fading, because the two are not the same picture: filter to a kind
        // that covers the whole graph and nothing is dimmed at all, and a
        // reader would be looking at forty undimmed cards wondering which
        // ones the count meant (§356).
        outline: matched ? "2px solid var(--accent)" : undefined,
        outlineOffset: 1,
      }}
      data-testid="graph-node"
      // **Which node this is, and what kind**, for the same reason the three
      // below exist: a card's identity is otherwise carried only by its text,
      // and its text is not unique — a model's output dataset takes the
      // model's own name (`models._ensure_output`), so "Clean orders" is two
      // cards and a test picking one of them by words picks whichever the DOM
      // happens to order first.
      data-node={node.id}
      data-kind={node.kind}
      // **The colouring's verdict, not its colour.** A test that asserted on
      // `var(--danger)` would be asserting on the palette; what §419 is about
      // is which bucket this card landed in, and that is the key.
      data-colour={swatch?.key}
      // Which nodes are in the selection, as an attribute rather than only a
      // border: with several selected the count says how many and the borders
      // say *which*, and a border is not something a test can read without
      // asserting on a colour (§353's note, one attribute over).
      data-selected={selected ? "true" : undefined}
      data-match={matched ? "true" : undefined}
      data-lit={lit ? "true" : undefined}
      data-review={review}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--ink-soft)",
        }}
      >
        {node.kind === "object_type" ? "object type"
          : node.kind === "connection" ? "data source"
          : node.kind}
        {node.in_cycle && <span style={{ color: "var(--danger)" }}> · in a cycle</span>}
        {/* p.55's indicator. Named rather than coloured alone: "approved" and
            "rejected" are the two a reader most needs to tell apart at a
            glance, and a red and a green dot are the one pair a sizeable
            minority of readers cannot. */}
        {review && (
          <span
            data-testid="node-review"
            style={{ color: review === "rejected" ? "var(--danger)" : "var(--ink-soft)" }}
          >
            {" · "}
            {review === "unread" ? "not reviewed" : review}
          </span>
        )}
        {/* p.51's out-of-date state (§352), beside the cycle warning because
            both answer "why does this node need my attention". `--brass` and
            not `--danger`: a stale dataset is correct data that is behind,
            which is a different thing from a build that failed. */}
        {outOfDateNote(node) && (
          <span style={{ color: "var(--brass)" }} data-testid="node-out-of-date">
            {" · "}
            {outOfDateNote(node)}
          </span>
        )}
      </div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 13.5,
          color: "var(--ink)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {node.name}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--ink-soft)" }}>{subtitle(node)}</div>
    </button>
  );
}

function Details({
  node,
  onOpen,
}: {
  node: PipelineNode;
  onOpen: () => void;
}) {
  const when = node.last_run_at ?? node.updated_at;
  return (
    <div
      style={{
        borderTop: "1px solid var(--line)",
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div>
        <div
          data-testid="details-name"
          style={{ fontFamily: "var(--font-display)", fontSize: 14 }}
        >
          {node.name}
        </div>
        <div className="slug">{node.slug ?? node.kind}</div>
      </div>
      {node.kind === "object_type" ? (
        <>
          <span
            className={
              node.last_run_status === "ok" ? "status-ok"
              : node.last_run_status === "error" ? "status-error"
              : "status-unconfigured"
            }
          >
            <span className="status-dot" />
            <span className="status-label">
              {node.last_run_status === "never_synced"
                ? "never synced"
                : node.last_run_status ?? "never synced"}
            </span>
          </span>
        </>
      ) : node.kind === "model" ? (
        <>
          <span className="chip">{node.language === "python" ? "Python" : "SQL"}</span>
          <span className="chip">{node.trigger_mode}</span>
          <span
            className={
              node.last_run_status === "succeeded" ? "status-ok"
              : node.last_run_status === "failed" ? "status-error"
              : "status-unconfigured"
            }
          >
            <span className="status-dot" />
            <span className="status-label">{node.last_run_status ?? "never run"}</span>
          </span>
        </>
      ) : (
        <>
          <span className="chip">v{node.current_version}</span>
          <span className="chip">{node.row_count?.toLocaleString()} rows</span>
          {node.health_status && <span className="chip">health: {node.health_status}</span>}
        </>
      )}
      {when && <span className="slug">{new Date(when).toLocaleString()}</span>}
      <button
        className="btn quiet"
        style={{ marginLeft: "auto" }}
        data-testid="node-open"
        onClick={onOpen}
      >
        Open {node.kind === "object_type" ? "object type"
          : node.kind === "connection" ? "data source"
          : node.kind}
      </button>
    </div>
  );
}



export function PipelineGraphView({
  graph,
  onOpen,
  maxHeight = 560,
  initialView,
  onViewChange,
  viewers,
  viewAs,
  onViewAs,
  exportTitle,
  review,
  onBuild,
  building,
  onSchedule,
  scheduling,
}: {
  graph: PipelineGraph;
  onOpen: (node: PipelineNode) => void;
  maxHeight?: number;
  /** p.82's *View as* (§422): who the Permissions colouring is answering
   *  about, and the list it may be chosen from. Optional together, for the
   *  reason `onBuild` is optional — the parameter that produces the answer is
   *  editor-gated, so a viewer's page and a review surface simply do not pass
   *  them and the control is not drawn. */
  viewers?: GraphViewer[];
  viewAs?: string | null;
  onViewAs?: (userId: string | null) => void;
  /** What p.12's exported picture is called — the project's name, where the
   *  caller has one. Absent falls back to "lineage", which is a worse
   *  filename and still a findable one. */
  exportTitle?: string;
  /** A saved or shared view to open at (§360; `data-lineage` p.12). Read once,
   *  as the name says: a prop that kept overwriting the state would make the
   *  graph un-drivable the moment somebody clicked. */
  initialView?: GraphView;
  /** The view as it stands, for whoever wants to save or share it. Not fired
   *  for pan or zoom, which are not in a saved view — see db 0089. */
  onViewChange?: (view: GraphView) => void;
  /** `code-repositories` p.55's indicators, keyed by node id — built by
   *  `lib/pipeline-review`. A node absent from the map gets none, which is
   *  how "this proposal does not touch it" is said. */
  review?: Map<string, FileState>;
  /** p.9's builds helper (§386): run what the selection builds.
   *
   * **Optional, and that is the control's own §214 rule.** The graph is drawn
   * on a project page, inside a review surface and inside the dataset
   * application; only the first is somewhere work starts. A Build button on a
   * review of a proposal would be a control that cannot do what it says, so
   * the callers that cannot build simply do not pass this and it is not
   * drawn.
   *
   * The models arrive in build order, upstream first — `buildPlan` sorts by
   * the `layer` the server already computed. */
  onBuild?: (models: PlannedModel[]) => void;
  /** A build asked for here is still going, so the button says so rather than
   *  inviting a second one. */
  building?: boolean;
  /** p.10's schedules helper (§387): set or clear a build schedule over the
   *  selection. Optional for the same reason `onBuild` is — a review surface
   *  is not somewhere work starts. A `null` expression clears the schedule,
   *  which is p.10's "edit" including turning one off. */
  onSchedule?: (models: PlannedModel[], cron: string | null) => void;
  scheduling?: boolean;
}) {
  const [selected, setSelected] = useState<string[]>(initialView?.selected ?? []);
  // What Build would run, and what it would set off afterwards. Computed here
  // rather than in the button so the summary and the button cannot disagree
  // about which nodes they mean (§386); the rules are in `lib/graph-builds`,
  // which has its own tests because vitest cannot parse `.tsx`.
  // p.57's "Force build on up-to-date datasets" (§421). Off by default,
  // because that is p.57's default: "this builds only ancestors that are out
  // of date... forcing a re-build can be expensive".
  const [force, setForce] = useState(false);
  // **Two plans, and the second is not a duplicate of the first.**
  // `selection` is which transforms this selection *means* — the question
  // §292 says has one answer, and the one the schedule control asks. `plan` is
  // which of them pressing Build would run, which p.57 makes a narrower set.
  // Scheduling off `plan` would quietly refuse to schedule a transform whose
  // output happened to be current, which is a build default leaking into a
  // control that has nothing to do with building.
  const selection = buildPlan(graph.nodes, graph.edges, selected, { force: true });
  const plan = force
    ? selection
    : buildPlan(graph.nodes, graph.edges, selected);
  const cascade = cascadeCount(graph.nodes, graph.edges, plan);
  // p.10's schedule, as typed. The default is the one the Models page offers,
  // so the two places a schedule can be set open on the same suggestion.
  const [cron, setCron] = useState("0 * * * *");
  // p.7's two modes. **Panning is the default**, as it is in Foundry: the
  // gesture a reader makes without thinking is moving the graph around, and a
  // page that opens in a mode where dragging selects would have them draw a
  // rectangle every time they meant to look further right.
  const [tool, setTool] = useState<"pan" | "select">("pan");
  // p.8's search helper, minus the half that has nowhere to go here: every
  // result is already on the graph (§355), so this finds rather than adds.
  const [query, setQuery] = useState(initialView?.query ?? "");
  const [kinds, setKinds] = useState<PipelineNode["kind"][]>(kindsIn(initialView));
  // p.55's "click one of the columns to highlight the datasets in your
  // selection that contain this column" (§353). One at a time, because the
  // question it answers is "where else is *this* column" — two highlighted at
  // once would light up a union nobody asked about.
  const [column, setColumn] = useState<string | null>(initialView?.column ?? null);
  // p.38's "several built-in options for coloring graph nodes" (§419).
  // `colouringIn` rather than the raw field: a stored view naming a colouring
  // this build does not offer opens on the default, so the picker and the
  // cards cannot disagree.
  const [colouring, setColouring] = useState(() => colouringIn(initialView));
  // p.11's Layout menu (§424). `layoutIn` narrows a stored view for the reason
  // `colouringIn` does: a `<select>` showing an option the graph is not using
  // is two controls disagreeing about one piece of state.
  const [layout, setLayout] = useState(() => layoutIn(initialView));
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  // The rectangle as drawn, in canvas coordinates, and what it is being added
  // to. `base` is captured at mousedown rather than read at mouseup because a
  // Ctrl+drag is one gesture: whether it extends the selection is decided by
  // the modifier held when it started.
  const [marquee, setMarquee] = useState<Rect | null>(null);
  const marqueeFrom = useRef<{ x: number; y: number; base: string[] } | null>(null);

  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);
  // p.11's arrangement, and the canvas it needs. **One answer**, read by the
  // cards, the edge curves, §354's marquee and §423's export — a second copy
  // of "where is that card" is a rectangle that selects the node beside the
  // one it was drawn over, and nothing on the screen says which copy is wrong
  // (§191, §424).
  const canvas = useMemo(
    () => layoutOf(
      graph.nodes.map((n) => ({
        id: n.id,
        layer: n.layer,
        position: n.position,
        group: swatchFor({ ...n, access: graph.access?.[n.id] ?? null }, colouring)?.key,
      })),
      layout,
    ),
    [graph.nodes, graph.access, colouring, layout],
  );

  // **Reported after the render that changed it, not during.** Calling a
  // parent's setter while rendering is how a graph that reports its view ends
  // up re-rendering its parent forever.
  const report = useRef(onViewChange);
  report.current = onViewChange;
  useEffect(() => {
    report.current?.(viewOf({ selected, column, query, kinds, colouring, layout }));
  }, [selected, column, query, kinds, colouring, layout]);

  // p.12's SVG export. **The picture is of the graph as it looks**, so it is
  // built at the moment of the click from the same state the cards are drawn
  // from — the colouring in force, the selection as it stands — rather than
  // from a snapshot taken when the component rendered.
  //
  // The palette is read off the live document here, which is the one thing
  // `lib/graph-svg` cannot do for itself: a `var(--…)` in a standalone file
  // resolves against nothing, so an export taken in dark mode would come out
  // black-on-black without this.
  const exportSvg = () => {
    const svg = svgFor(graph.nodes, graph.edges, {
      colours: Object.fromEntries(
        graph.nodes
          .map((n) => [
            n.id,
            swatchFor({ ...n, access: graph.access?.[n.id] ?? null }, colouring)?.token,
          ])
          .filter((pair): pair is [string, string] => pair[1] !== undefined),
      ),
      at: canvas.at,
      selected,
      styles: getComputedStyle(document.documentElement),
      title: exportTitle ?? "Lineage graph",
    });
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = svgFilename(exportTitle ?? "lineage", new Date());
    link.click();
    // Released once the click has been handled. A blob URL that is never
    // revoked keeps the whole document alive for as long as the tab is open,
    // and a reader who exports twenty times over an afternoon is the case
    // that turns into.
    URL.revokeObjectURL(url);
  };

  const chosen = useMemo(() => new Set(selected), [selected]);
  // The detail bar answers about *a* node, so it appears for exactly one.
  // Several selected is a different question, and it gets the count instead.
  const only = selected.length === 1 ? selected[0] : undefined;
  const selectedNode = only === undefined ? null : byId.get(only) ?? null;
  // p.55's histogram is "in your selection" (§354). Nothing selected is the
  // whole graph, which is the state the page opens in — see `columnsIn`.
  const columns = useMemo(
    () => columnsIn(graph.columns, selected),
    [graph.columns, selected],
  );
  const lit = useMemo(
    () => new Set(columns.find((c) => c.name === column)?.datasets ?? []),
    [columns, column],
  );
  // p.10's Gantt (§418). **Over the selection, which is what p.10 says**:
  // "actual build time for the selected datasets". Nothing selected is no
  // chart rather than the whole project, because a timeline of forty datasets
  // nobody asked about is a picture rather than an answer — and the histogram
  // above reads an empty selection as the whole graph for the opposite reason,
  // which is why the two are not sharing a rule.
  const timeline = useMemo(
    () => timelineFor(selected.map((id) => byId.get(id)).filter((n) => n !== undefined)),
    [selected, byId],
  );
  const timelineEmpty = emptyReason(timeline);
  // The key for what the cards are coloured by, over the nodes actually on the
  // graph. Memoised on the node list rather than recomputed per render: the
  // graph re-renders on every pan frame, and this walks every node.
  const legend = useMemo(
    () => legendFor(
      graph.nodes.map((n) => ({ ...n, access: graph.access?.[n.id] ?? null })),
      colouring,
    ),
    [graph.nodes, graph.access, colouring],
  );
  // p.11's other half (§417): "you can either search for the name of the node
  // or column names in datasets". The index is `graph.columns`, which §353
  // already reads off the same rows the graph draws — **the whole graph's,
  // not `columns` above**, which is narrowed to the selection for the
  // histogram. Searching only inside a selection would answer "where does
  // `site_id` live" with "wherever you were already looking".
  const found = useMemo(
    () => search(graph.nodes, query, kinds, graph.columns),
    [graph.nodes, query, kinds, graph.columns],
  );
  const viaColumn = useMemo(
    () => foundByColumn(graph.nodes, query, graph.columns),
    [graph.nodes, query, graph.columns],
  );
  const matched = useMemo(() => new Set(found), [found]);

  /** Where a pointer is on the graph, undoing the pan and the zoom the
   *  canvas is drawn with — the rectangle has to be in the same coordinates
   *  as the cards it is tested against. */
  function canvasPoint(e: React.MouseEvent<HTMLDivElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    return {
      x: (e.clientX - box.left - pan.x) / zoom,
      y: (e.clientY - box.top - pan.y) / zoom,
    };
  }

  /** Ends whichever gesture is in flight, and takes the nodes if it was a
   *  rectangle. Shared by mouse-up and leaving the viewport. */
  function endDrag() {
    const from = marqueeFrom.current;
    marqueeFrom.current = null;
    drag.current = null;
    setMarquee(null);
    // A press that barely moved is a click, and the card underneath has its
    // own handler — see `isDrag` for why letting both run would unselect the
    // node that was clicked.
    if (!from || !marquee || !isDrag(marquee)) return;
    const taken = nodesInRect(graph.nodes, marquee, canvas.at);
    setSelected(from.base.length === 0 ? taken : [...new Set([...from.base, ...taken])]);
  }

  if (graph.nodes.length === 0) {
    return (
      <div className="state">
        Nothing to draw yet — upload a dataset or create a model and it appears here.
      </div>
    );
  }

  return (
    <>
      {graph.cycles.length > 0 && (
        <div className="form-error" style={{ marginBottom: 12 }}>
          {graph.cycles.length === 1 ? "A cycle" : `${graph.cycles.length} cycles`} here:{" "}
          {graph.cycles.flat().length} resources feed each other in a loop. A model in a
          cycle set to run on new input data will re-trigger itself indefinitely.
        </div>
      )}
      {/* p.8's search helper as a row rather than a side panel, for the reason
          Frequent Columns is one: this graph is a page, not an app with six
          regions. The tree browse has nowhere to go — there is no folder
          hierarchy under a project — so the free-text half is the whole of it,
          with the Advanced tab's filters as the three kinds this graph draws. */}
      <div style={{ marginBottom: 8 }} data-testid="graph-search">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          <input
            // Styled here rather than with a class: `.field input` is the
            // repo's rule and it carries `width: 100%`, which is right inside
            // a form column and wrong in a row of chips.
            style={{
              width: 240,
              padding: "6px 9px",
              border: "1px solid var(--line-strong)",
              borderRadius: "var(--radius)",
              font: "inherit",
              fontSize: 13.5,
              background: "var(--panel)",
              color: "var(--ink)",
            }}
            placeholder="Find a node, or a column in one…"
            data-testid="search-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {GRAPH_KINDS.map((kind) => (
            <button
              key={kind}
              type="button"
              className={kinds.includes(kind) ? "chip on" : "chip"}
              data-testid={`search-kind-${kind}`}
              aria-pressed={kinds.includes(kind)}
              onClick={() =>
                setKinds((current) =>
                  current.includes(kind)
                    ? current.filter((each) => each !== kind)
                    : [...current, kind],
                )
              }
            >
              {kind === "object_type" ? "object types"
                : kind === "connection" ? "data sources"
                : `${kind}s`}
            </button>
          ))}
          {(query.trim() !== "" || kinds.length > 0) && (
            <>
              <span className="slug" data-testid="search-count">
                {found.length} of {graph.nodes.length}
                {/* §214, and the reason this count grew a second half: a card
                    that lights up for a reason nobody can see is worse than
                    one that does not light up. A reader who types a column
                    name gets datasets whose own names do not contain it, and
                    without this they cannot tell whether the graph answered
                    their question or misunderstood it. */}
                {viaColumn.length > 0 && (
                  <span data-testid="search-by-column">
                    {` · ${viaColumn.length} by column`}
                  </span>
                )}
              </span>
              {/* p.8's "buttons at the bottom of the view to add all search
                  results", which here means select them: the results are
                  already drawn, and a selection is what §354's histogram and
                  §355's expansions can carry further. */}
              <button
                className="btn quiet"
                data-testid="search-select-all"
                disabled={found.length === 0}
                onClick={() => setSelected(found)}
              >
                Select all
              </button>
            </>
          )}
        </div>
      </div>
      {columns.length > 0 && (
        /* p.54-55's Frequent Columns. **Most frequent first**, which is the
           server's ordering, and the count beside each name is what that
           ordering is *by* — a list sorted by something invisible reads as
           arbitrary. Clicking one highlights the datasets that have it and
           clicking it again clears, because a highlight nothing can turn off
           is a mode rather than a question. */
        <div style={{ marginBottom: 8 }} data-testid="frequent-columns">
          <div className="slug" style={{ marginBottom: 4 }}>
            Frequent columns
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {columns.map((c) => (
              <button
                key={c.name}
                type="button"
                className={column === c.name ? "chip on" : "chip"}
                data-testid={`column-${c.name}`}
                // The name as an attribute as well as text: the count sits
                // beside it with only CSS between them, so `inner_text` reads
                // "id3" — the DOM has no space in it (§214's note, one
                // component over).
                data-column={c.name}
                aria-pressed={column === c.name}
                onClick={() => setColumn(column === c.name ? null : c.name)}
              >
                {c.name}
                <span className="slug" style={{ marginLeft: 5 }}>
                  {c.datasets.length}
                </span>
              </button>
            ))}
          </div>
          {column !== null && (
            /* p.8's drill-down: "By clicking on the values, the matching
               nodes are highlighted. If you want to drill down to just those
               resources, click on **Update selection**." The highlight is a
               question and this is the answer being kept — everything after
               it, the histogram included, is about those datasets.

               The chip stays pressed afterwards, and every remaining node is
               lit because they all have the column: that is the drill-down
               having happened rather than a highlight that failed to dim
               anything. */
            <button
              className="btn quiet"
              data-testid="update-selection"
              style={{ marginTop: 6 }}
              onClick={() => setSelected([...lit])}
            >
              Update selection
            </button>
          )}
        </div>
      )}
      {selected.length > 0 && (
        /* p.10's build timeline. Under the histogram because both are about
           the selection, and a reader who has just narrowed to eight datasets
           asks "what is in them" and "what did they cost" in the same breath. */
        <div style={{ marginBottom: 8 }} data-testid="build-timeline">
          <div className="slug" style={{ marginBottom: 4 }}>
            Build timeline
            {timeline.without > 0 && timeline.bars.length > 0 && (
              /* §226 and §214: bars drawn for some of a selection would read
                 as a chart of all of it. The count is what stops the drawing
                 from being a claim about the selection rather than about the
                 builds in it. */
              <span data-testid="timeline-without">
                {` · ${timeline.without} not built by a model`}
              </span>
            )}
          </div>
          {timelineEmpty ? (
            <div className="slug" data-testid="timeline-empty">{timelineEmpty}</div>
          ) : (
            <div data-testid="timeline-bars">
              {timeline.bars.map((bar) => {
                const place = placeOf(bar, timeline.span);
                return (
                  <div
                    key={bar.id}
                    data-testid={`timeline-bar-${bar.id}`}
                    data-ms={bar.ms}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "10em 1fr 5em",
                      gap: 8,
                      alignItems: "center",
                      fontSize: 12,
                      marginBottom: 2,
                    }}
                  >
                    <span className="canvas-colours-use-node">{bar.name}</span>
                    <span
                      style={{
                        position: "relative",
                        height: 8,
                        background: "var(--line)",
                        borderRadius: 4,
                      }}
                    >
                      <span
                        data-testid={`timeline-fill-${bar.id}`}
                        style={{
                          position: "absolute",
                          left: `${place.left}%`,
                          width: `${place.width}%`,
                          top: 0,
                          height: 8,
                          background: "var(--accent)",
                          borderRadius: 4,
                        }}
                      />
                    </span>
                    <span className="slug">{durationLabel(bar.ms)}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      <div className="form-actions" style={{ marginBottom: 8, alignItems: "center" }}>
        {/* p.7's graph tools. Two modes and nothing else, because that is the
            whole of the choice: "Click and drag to pan around the graph when
            in the default Panning mode. To use the cursor to select multiple
            nodes, switch to Drag select mode in the graph tools or hold Shift
            while clicking and dragging." */}
        <button
          type="button"
          className={tool === "pan" ? "chip on" : "chip"}
          data-testid="tool-pan"
          aria-pressed={tool === "pan"}
          onClick={() => setTool("pan")}
        >
          Pan
        </button>
        <button
          type="button"
          className={tool === "select" ? "chip on" : "chip"}
          data-testid="tool-drag-select"
          aria-pressed={tool === "select"}
          onClick={() => setTool("select")}
        >
          Drag select
        </button>
        {/* p.38's colouring, in the graph tools because that is what it is:
            a way of reading the graph rather than a filter on it. A `select`
            rather than six chips — the options are exclusive, and six more
            chips beside three kind chips would read as nine filters. */}
        <label className="slug" htmlFor="graph-colouring" style={{ marginLeft: 10 }}>
          Colour by
        </label>
        <select
          id="graph-colouring"
          data-testid="graph-colouring"
          value={colouring}
          onChange={(e) => setColouring(e.target.value)}
          style={{
            padding: "5px 8px",
            border: "1px solid var(--line-strong)",
            borderRadius: "var(--radius)",
            font: "inherit",
            fontSize: 13,
            background: "var(--panel)",
            color: "var(--ink)",
          }}
          // What the chosen colouring is *asking*, which the label alone does
          // not say: "Resource overview" is p.38's name for it and means
          // nothing without "the way the resource was created" beside it.
          title={COLOURINGS.find((o) => o.id === colouring)?.hint}
        >
          {COLOURINGS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
        {/* p.82's *View as*, beside the colouring it answers for rather than
            in a panel of its own — the two are one question ("what can Alice
            see"), and a dropdown a screen away from the colours it changes is
            two controls for one thought.

            **Only under the Permissions colouring.** Under any other it
            changes nothing on the screen, which is §214's shape; and it costs
            an editor-gated request, so drawing it always would spend one on
            every reader who never asked. */}
        {onViewAs && colouring === "permissions" && (
          <>
            <label className="slug" htmlFor="graph-view-as">View as</label>
            <select
              id="graph-view-as"
              data-testid="graph-view-as"
              value={viewAs ?? ""}
              onChange={(e) => onViewAs(e.target.value || null)}
              style={{
                padding: "5px 8px",
                border: "1px solid var(--line-strong)",
                borderRadius: "var(--radius)",
                font: "inherit",
                fontSize: 13,
                background: "var(--panel)",
                color: "var(--ink)",
              }}
            >
              {/* **"Nobody" is a choice and stays on the list** (§210): it is
                  how somebody puts the graph back, and a picker you cannot
                  leave is a mode rather than a question. */}
              <option value="">Nobody chosen</option>
              {(viewers ?? []).map((person) => (
                <option key={person.id} value={person.id}>
                  {person.display_name || person.email}
                </option>
              ))}
            </select>
          </>
        )}
        {/* p.11's Layout menu, beside the colouring it can group by. **Not
            gated on a selection** though p.11 gates its other layouts that
            way: Foundry's graph is built up node by node, so "lay out these"
            is a sensible scope, while this graph is a project drawn whole
            (§355) — an arrangement applied to part of it would leave the rest
            where the other arrangement put them, which is two layouts
            overlapping on one canvas. */}
        <label className="slug" htmlFor="graph-layout">Layout</label>
        <select
          id="graph-layout"
          data-testid="graph-layout"
          value={layout}
          onChange={(e) => setLayout(e.target.value)}
          style={{
            padding: "5px 8px",
            border: "1px solid var(--line-strong)",
            borderRadius: "var(--radius)",
            font: "inherit",
            fontSize: 13,
            background: "var(--panel)",
            color: "var(--ink)",
          }}
          title={LAYOUTS.find((o) => o.id === layout)?.hint}
        >
          {LAYOUTS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
        {/* p.12's third save-and-share mechanism: "Export graph to SVG —
            generates a static image of your lineage graph" (§423). Beside the
            graph tools rather than with Save and the share link, because it
            is a different kind of sharing: those two hand somebody a *live*
            graph they must have access to open, and this hands them a
            picture — for the audience that cannot open the link. */}
        <button
          type="button"
          className="chip"
          data-testid="graph-export-svg"
          onClick={exportSvg}
        >
          Export SVG
        </button>
        <span style={{ marginLeft: "auto" }} />
        <button className="btn quiet" onClick={() => setZoom((z) => Math.max(0.4, z - 0.15))}>
          −
        </button>
        <button
          className="btn quiet"
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
        >
          {Math.round(zoom * 100)}%
        </button>
        <button className="btn quiet" onClick={() => setZoom((z) => Math.min(2, z + 0.15))}>
          +
        </button>
      </div>
      {legend.length > 0 && (
        /* **A colour with no legend is a code.** p.38 offers the reading; this
           is what makes it readable — "why is that card brown" has no answer a
           reader can reach by looking. The counts come with it because the
           same list then doubles as a summary of the graph, said in the place
           somebody is already looking. */
        <div
          data-testid="graph-legend"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 10,
            alignItems: "center",
            marginBottom: 6,
            fontSize: 12,
          }}
        >
          {legend.map((entry) => (
            <span
              key={entry.key}
              data-testid={`legend-${entry.key}`}
              data-count={entry.count}
              style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 2,
                  background: entry.token,
                  // A token that resolves to the page's own background would
                  // otherwise be an invisible swatch beside a label.
                  border: "1px solid var(--line-strong)",
                }}
              />
              {entry.label}
              <span className="slug">{entry.count}</span>
            </span>
          ))}
        </div>
      )}
      <div
        style={{
          border: "1px solid var(--line)",
          borderRadius: "var(--radius)",
          background: "var(--paper)",
          overflow: "hidden",
        }}
      >
        <div
          data-testid="graph-viewport"
          style={{
            // Tall enough for the graph, capped so a wide pipeline doesn't
            // push the detail bar off the screen.
            height: Math.min(maxHeight, Math.max(240, canvas.height)),
            overflow: "hidden",
            position: "relative",
            cursor:
              tool === "select" ? "crosshair"
              : drag.current ? "grabbing"
              : "grab",
          }}
          // Focusable so the graph can hear p.54's Ctrl/Cmd+A. Without this
          // the key press goes to the document and selects the page's text.
          tabIndex={0}
          onKeyDown={(e) => {
            // p.54: "use Ctrl / Command + A to select all nodes."
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
              e.preventDefault();
              setSelected(graph.nodes.map((n) => n.id));
            }
          }}
          onMouseDown={(e) => {
            if (tool === "select" || e.shiftKey) {
              const at = canvasPoint(e);
              marqueeFrom.current = {
                x: at.x,
                y: at.y,
                base: e.ctrlKey || e.metaKey ? selected : [],
              };
              setMarquee({ x1: at.x, y1: at.y, x2: at.x, y2: at.y });
              return;
            }
            drag.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
          }}
          onMouseMove={(e) => {
            const from = marqueeFrom.current;
            if (from) {
              const at = canvasPoint(e);
              setMarquee({ x1: from.x, y1: from.y, x2: at.x, y2: at.y });
              return;
            }
            if (!drag.current) return;
            setPan({
              x: drag.current.panX + (e.clientX - drag.current.x),
              y: drag.current.panY + (e.clientY - drag.current.y),
            });
          }}
          onMouseUp={endDrag}
          // Leaving the viewport mid-drag commits what was drawn rather than
          // throwing it away: the rectangle is on the screen, and a gesture
          // that silently does nothing because the pointer crossed an edge is
          // the kind of control §214 calls worse than none.
          onMouseLeave={endDrag}
        >
          <div
            style={{
              position: "absolute",
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              transformOrigin: "0 0",
              width: canvas.width,
              height: canvas.height,
            }}
          >
            <svg
              width={canvas.width}
              height={canvas.height}
              style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
            >
              <defs>
                <marker
                  id="pipeline-arrow"
                  viewBox="0 0 8 8"
                  refX="7"
                  refY="4"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto"
                >
                  <path d="M 0 0 L 8 4 L 0 8 z" fill="var(--line-strong)" />
                </marker>
              </defs>
              {graph.edges.map((e, i) => {
                const from = canvas.at.get(e.from);
                const to = canvas.at.get(e.to);
                if (!from || !to) return null;
                const touched = chosen.has(e.from) || chosen.has(e.to);
                return (
                  <path
                    key={i}
                    d={edgePath(from, to)}
                    fill="none"
                    stroke={touched ? "var(--accent)" : "var(--line-strong)"}
                    strokeWidth={touched ? 2 : 1.25}
                    markerEnd="url(#pipeline-arrow)"
                  />
                );
              })}
              {/* p.32's link types. **Dashed and un-arrowed on purpose**: an
                  arrow on this graph means data flows that way, and a link
                  type is a relationship between two object types. Drawing one
                  like an edge would say the ontology is part of the build
                  order, which is exactly what keeping them out of `edges`
                  avoids on the server. */}
              {graph.links.map((l) => {
                const from = canvas.at.get(l.from);
                const to = canvas.at.get(l.to);
                if (!from || !to) return null;
                const touched = chosen.has(l.from) || chosen.has(l.to);
                return (
                  <path
                    key={l.id}
                    d={edgePath(from, to)}
                    fill="none"
                    stroke={touched ? "var(--accent)" : "var(--line)"}
                    strokeWidth={touched ? 2 : 1.25}
                    strokeDasharray="4 3"
                    data-testid="pipeline-link"
                  >
                    <title>{`${l.name} (${l.cardinality})`}</title>
                  </path>
                );
              })}
            </svg>
            {marquee && isDrag(marquee) && (
              <div
                data-testid="graph-marquee"
                style={{
                  position: "absolute",
                  left: Math.min(marquee.x1, marquee.x2),
                  top: Math.min(marquee.y1, marquee.y2),
                  width: Math.abs(marquee.x2 - marquee.x1),
                  height: Math.abs(marquee.y2 - marquee.y1),
                  border: "1px dashed var(--accent)",
                  background: "var(--accent-wash)",
                  // The rectangle is a drawing of the gesture, not a thing to
                  // click: events have to reach the cards underneath it.
                  pointerEvents: "none",
                }}
              />
            )}
            {graph.nodes.map((n) => (
              <NodeCard
                key={n.id}
                node={n}
                place={canvas.at.get(n.id) ?? { x: 0, y: 0 }}
                selected={chosen.has(n.id)}
                // p.80's Permissions colouring reads the server's answer for
                // the person named under *View as*; every other colouring
                // reads the node alone (§422).
                swatch={swatchFor(
                  { ...n, access: graph.access?.[n.id] ?? null },
                  colouring,
                )}
                lit={lit.has(n.id)}
                matched={matched.has(n.id)}
                review={review?.get(n.id)}
                // **Dim means "not in what you are looking at", and two
                // questions at once narrow rather than compete**: a node the
                // search missed is out whether or not it has the highlighted
                // column, and vice versa. One dimming language, because a
                // second one would have a reader guessing which faded card
                // faded for which reason.
                dimmed={
                  (lit.size > 0 && !lit.has(n.id)) ||
                  (matched.size > 0 && !matched.has(n.id))
                }
                onSelect={(additive) =>
                  setSelected((current) => toggleSelected(current, n.id, additive))
                }
              />
            ))}
          </div>
        </div>
        {selectedNode && <Details node={selectedNode} onOpen={() => onOpen(selectedNode)} />}
        {selected.length > 0 && (
          /* What a selection says for itself. The count is the part that
             matters: the histogram above is now answering about these nodes,
             and a reader who cannot see how many they have has no way to tell
             a narrowed list from the graph's own.

             **From one node up, not two**, because p.52's flow starts on a
             single node — "right-click the node, then select Expand node" —
             and the expansions below are the whole reason this bar exists. */
          <div
            data-testid="selection-summary"
            style={{
              borderTop: "1px solid var(--line)",
              padding: "10px 16px",
              display: "flex",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            <span data-testid="selection-count" style={{ marginRight: 4 }}>
              {selected.length} node{selected.length === 1 ? "" : "s"} selected
            </span>
            {/* p.7's arrows on either side of a node and p.52's double arrow,
                as four buttons rather than a gesture on the card: the cards
                here are 190px wide with three lines of text on them, and
                arrows small enough to fit beside one are arrows nobody hits.
                Ordered the way the graph reads, upstream on the left. */}
            <span className="slug">Expand</span>
            {(
              [
                ["all-upstream", "All upstream", "upstream", Infinity],
                ["upstream", "Upstream", "upstream", 1],
                ["downstream", "Downstream", "downstream", 1],
                ["all-downstream", "All downstream", "downstream", Infinity],
              ] as const
            ).map(([id, label, direction, hops]) => (
              <button
                key={id}
                type="button"
                className="chip"
                data-testid={`expand-${id}`}
                onClick={() =>
                  setSelected((current) =>
                    relatives(graph.edges, current, direction, hops),
                  )
                }
              >
                {label}
              </button>
            ))}
            {/* p.9's middle strategy, and the only one of the three whose
                *selection* was not already on this bar: "build all datasets
                between the selected datasets". Its own chip rather than a
                build button of its own, because here the three strategies are
                three ways to shape a selection and the shaping is a step the
                reader can watch happen — `All upstream` beside it is p.9's
                third strategy already, and the selection itself is the first
                (§386). Two ends at least, since "between" needs them. */}
            {/* p.12's *Invert selection*: "de-selects all currently selected
                nodes and selects the rest of the nodes on the graph". The one
                of p.12's four with nothing behind it — *Select All* is §356's
                select-every-match and *Select children* / *parents* are the
                Expand chips above — because it is the only one that answers
                "what did I leave out". */}
            <button
              type="button"
              className="chip"
              data-testid="selection-invert"
              onClick={() =>
                setSelected((current) => inverted(graph.nodes, current))
              }
            >
              Invert
            </button>
            {selected.length >= 2 && (
              <button
                type="button"
                className="chip"
                data-testid="expand-between"
                onClick={() => setSelected((current) => between(graph.edges, current))}
              >
                Between
              </button>
            )}
            <button
              className="btn quiet"
              data-testid="selection-clear"
              style={{ marginLeft: "auto" }}
              onClick={() => setSelected([])}
            >
              Clear
            </button>
            {/* p.9's builds helper. **The summary is beside the button, not
                inside it**: what a reader has to know before pressing is how
                many transforms will run and which of the selected cards are
                not built by one, and a label cannot carry both. §214 is the
                whole reason the second half is there — selecting six cards and
                running four builds is the reading this prevents (§386). */}
            {onBuild && (
              <div
                data-testid="selection-build"
                style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}
              >
                <button
                  type="button"
                  className="btn"
                  data-testid="selection-build-run"
                  disabled={building || plan.models.length === 0}
                  onClick={() => onBuild(plan.models)}
                >
                  {building ? "Building…" : "Build"}
                </button>
                <span className="soft" data-testid="selection-build-summary">
                  {buildSummary(plan)}
                </span>
                {/* p.57's force option. **Shown whenever the selection
                    resolves to a transform at all**, not only when one of them
                    happens to be current.

                    The first draft hid it unless there was something to
                    force, on the §214 reasoning that a control which cannot
                    change the answer should be absent. That reasoning does not
                    fit here: this is a *policy* switch rather than an action,
                    it does exactly what it says whenever it is pressed, and
                    the summary beside it already states whether anything is
                    being skipped — so a reader is never guessing. Hiding it
                    made the control come and go as the pipeline's freshness
                    changed underneath, which is harder to find than one that
                    is simply there. */}
                {selection.models.length > 0 && (
                  <label
                    className="soft"
                    style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                  >
                    <input
                      type="checkbox"
                      data-testid="selection-build-force"
                      checked={force}
                      onChange={(e) => setForce(e.target.checked)}
                    />
                    Force up-to-date
                  </label>
                )}
                {/* §383: an ancestors build makes every upstream-triggered
                    model below it fire again on the worker's next pass, so
                    the run history will hold more builds than were asked for.
                    Said before the click rather than discovered after it. */}
                {cascade > 0 && (
                  <span className="chip" data-testid="selection-build-cascade">
                    {cascade} more will follow on their own
                  </span>
                )}
              </div>
            )}
            {/* p.10's schedules helper, beside the builds one exactly as the
                two sit beside each other on p.9-10. **The same plan**: which
                models a selection means is one question, and `buildPlan`
                answers it (§292). What differs is that scheduling is about
                *how and when* a transform runs, so an uploaded dataset in the
                selection is as irrelevant here as there and the summary says
                so the same way (§387). */}
            {onSchedule && (
              <div
                data-testid="selection-schedule"
                style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}
              >
                <input
                  aria-label="Cron schedule"
                  data-testid="selection-schedule-cron"
                  value={cron}
                  onChange={(e) => setCron(e.target.value)}
                  style={{ width: 130 }}
                />
                <button
                  type="button"
                  className="btn"
                  data-testid="selection-schedule-set"
                  // **Both halves, and each for its own reason.** No models is
                  // nothing to schedule; a box that is not five fields was
                  // never going to be a cron expression, so the button is
                  // unusable rather than earning a refusal for something the
                  // reader can already see is unfinished. Whether those five
                  // fields *mean* anything is the server's to say.
                  disabled={scheduling || selection.models.length === 0 || !looksLikeCron(cron)}
                  onClick={() => onSchedule(selection.models, cron)}
                >
                  {scheduling ? "Saving…" : "Schedule"}
                </button>
                <span className="soft" data-testid="selection-schedule-summary">
                  {scheduleSummary(selection.models)}
                </span>
                {/* Absent rather than disabled when there is nothing to clear:
                    a control offered over a selection it would not change is
                    §214's shape, and `clearSummary` returns "" for exactly
                    that case. */}
                {clearSummary(selection.models) && (
                  <button
                    type="button"
                    className="btn quiet"
                    data-testid="selection-schedule-clear"
                    disabled={scheduling}
                    onClick={() => onSchedule(selection.models, null)}
                  >
                    {clearSummary(selection.models)}
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
