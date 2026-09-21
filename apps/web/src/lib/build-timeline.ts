/** p.10's build timeline: a Gantt of what a selection's builds actually cost.
 *
 * > "Build timelines: A Gantt chart of actual build time for the selected
 * > datasets." (`data-lineage` p.10)
 *
 * **Actual, which is the word the whole thing turns on.** The graph already
 * says when a dataset was built (§352's `built_at`) and how it is doing; what
 * it cannot say is where the time went. A pipeline that takes forty minutes
 * takes it *somewhere*, and a list of finish times cannot tell a reader
 * whether that is one slow build or twelve quick ones waiting on each other.
 * A Gantt can, because it draws the gaps as well as the bars.
 *
 * Each bar's window is the run that produced **the version the dataset
 * currently holds** — paired with `built_at` at the source, so the bar and the
 * timestamp beside it can never be about different builds.
 */

/** A node as this module needs it: the graph's shape, narrowed. */
export interface TimelineNode {
  id: string;
  name: string;
  kind: string;
  build_started_at?: string | null;
  build_finished_at?: string | null;
}

export interface TimelineBar {
  id: string;
  name: string;
  /** Milliseconds from the window's start to this bar's start. */
  offset: number;
  /** How long the build took, in milliseconds. Never negative. */
  ms: number;
}

export interface Timeline {
  bars: TimelineBar[];
  /** The whole window, in milliseconds: the first start to the last finish. */
  span: number;
  /** How many of the asked-about nodes had no build to draw. */
  without: number;
}

function windowOf(node: TimelineNode): { from: number; to: number } | null {
  const from = Date.parse(node.build_started_at ?? "");
  const to = Date.parse(node.build_finished_at ?? "");
  if (Number.isNaN(from) || Number.isNaN(to)) return null;
  // **A finish before its start is not a short build.** Clocks move and rows
  // can be edited; drawing a negative bar would put a rectangle to the left of
  // the axis, and drawing `abs()` would invent a duration nobody measured.
  // Refusing is the honest reading, and it counts as a node with no build.
  if (to < from) return null;
  return { from, to };
}

/**
 * The bars for a set of nodes, in the order they ran.
 *
 * **Chronological, not the graph's order.** A Gantt is read left to right and
 * top to bottom at once; sorting by anything but start time makes the diagonal
 * that shows a pipeline's shape disappear, and that diagonal is the only thing
 * this chart says that a table of durations does not.
 *
 * Ties break on name, so two builds that started in the same millisecond come
 * back in an order that does not change between renders.
 *
 * **Nodes with no build are counted, not dropped silently** (§226 and §214). A
 * selection of twelve datasets where nine were uploaded draws three bars, and
 * a chart that showed three without saying so would read as "three datasets
 * selected" — the count is what stops the drawing from being a claim about the
 * selection rather than about the builds in it.
 */
export function timelineFor(nodes: readonly TimelineNode[]): Timeline {
  const windows: { node: TimelineNode; from: number; to: number }[] = [];
  let without = 0;
  for (const node of nodes) {
    const window = windowOf(node);
    if (window === null) without += 1;
    else windows.push({ node, ...window });
  }
  if (windows.length === 0) return { bars: [], span: 0, without };

  const first = Math.min(...windows.map((w) => w.from));
  const last = Math.max(...windows.map((w) => w.to));
  const bars = windows
    .sort((a, b) => a.from - b.from || a.node.name.localeCompare(b.node.name))
    .map((w) => ({
      id: w.node.id,
      name: w.node.name,
      offset: w.from - first,
      ms: w.to - w.from,
    }));
  return { bars, span: last - first, without };
}

/**
 * A bar's share of the window, as a percentage, and where it starts.
 *
 * **A zero-length span is one bar, drawn full width.** A single instantaneous
 * build would otherwise divide by zero, and a bar of no width is a build the
 * reader cannot see or click — the chart would be empty for a selection that
 * definitely built something.
 */
export function placeOf(bar: TimelineBar, span: number): { left: number; width: number } {
  if (span <= 0) return { left: 0, width: 100 };
  return {
    left: (bar.offset / span) * 100,
    // A build that took no measurable time still gets a sliver, for the reason
    // the profiler's bars do: a row with a real duration and no bar reads as a
    // row with no duration.
    width: Math.max((bar.ms / span) * 100, 0.5),
  };
}

/** How long a build took, as a person would say it. */
export function durationLabel(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds - minutes * 60);
  // 90 seconds is "1m 30s" and not "1.5m": a Gantt is read against a clock,
  // and minutes with a decimal point have to be converted before they mean
  // anything.
  return rest === 0 ? `${minutes}m` : `${minutes}m ${rest}s`;
}

/**
 * The sentence for a selection with nothing to chart.
 *
 * **Not "no builds".** A selection of uploaded datasets is a perfectly ordinary
 * thing to have selected, and it has no builds because nothing built it —
 * which is a fact about where the data came from rather than a fault.
 */
export function emptyReason(timeline: Timeline): string | null {
  if (timeline.bars.length > 0) return null;
  if (timeline.without === 0) return "Select datasets to see how long they took to build.";
  return timeline.without === 1
    ? "This dataset was not built by a model, so there is no build to time."
    : "None of these datasets was built by a model, so there is nothing to time.";
}
