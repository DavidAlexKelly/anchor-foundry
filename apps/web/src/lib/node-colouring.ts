/** p.38-39's node colouring: what a card's colour is *about* (§419).
 *
 * > "There are several built-in options for coloring graph nodes to give you
 * > more information about your pipeline." (p.38)
 *
 * The graph has always coloured its cards, by one fixed rule living in the
 * component where vitest cannot reach it. p.38's move is to make the meaning a
 * **choice**, and that turns a colour from decoration into a reading — which
 * is the whole reason it needs a legend and a module of its own.
 *
 * ---
 *
 * **Every colouring is categorical, and that is a palette decision rather than
 * a reading of p.38.** p.39 also offers quantitative ones — row count, build
 * duration, time last built — and each wants a sequential ramp. This palette
 * declares no ramp: `--accent-wash`, `--accent` and `--accent-deep` are not
 * ordered the same way in both themes (`--accent-deep` is darker than
 * `--accent` in light mode and lighter in dark), so a scale built from them
 * would read backwards for half the readers. Inventing three tokens would be
 * a second palette nobody else shares, which is the argument
 * `BACKGROUND_PRESETS` already makes one module over. `datasets-lineage.md`
 * carries what the quantitative half would cost.
 *
 * **The legend reads the graph rather than listing the vocabulary.** A key
 * showing every value a colouring *could* take would show six rows over a
 * graph with two colours on it; showing what is actually there makes the
 * legend a summary as well as a key. It stays in a fixed order rather than by
 * count, so it does not reshuffle as the graph changes underneath it.
 */

/** Only tokens `globals.css` declares in **both** themes. A colour a reader
 * cannot see in dark mode is a colour that means nothing to them. */
const NEUTRAL = "var(--line-strong)";
const GOOD = "var(--accent)";
const WARN = "var(--brass)";
const BAD = "var(--danger)";
const QUIET = "var(--line)";

export interface ColouringOption {
  id: string;
  label: string;
  /** What the colour is answering, for the control that offers it. */
  hint: string;
}

/** p.38's list, narrowed to the questions this platform can answer.
 *
 * `status` first and default, because it is what the graph coloured by before
 * there was a choice — a picker whose default changed the page the moment it
 * appeared would be a new feature wearing a settings control.
 */
export const COLOURINGS: ColouringOption[] = [
  { id: "status", label: "Build status",
    hint: "Did the thing that writes this work" },
  { id: "out_of_date", label: "Out-of-date",
    hint: "p.39: out of date with a parent, or with something further up" },
  { id: "health", label: "Data health",
    hint: "The expectations set on each dataset" },
  { id: "kind", label: "Resource type",
    hint: "Dataset, model or object type" },
  { id: "origin", label: "Resource overview",
    hint: "p.38: the way the resource was created" },
  { id: "none", label: "No colour",
    hint: "p.38's first option: remove colouring altogether" },
];

export const DEFAULT_COLOURING = "status";

/** A node as this module reads it: the graph's shape, narrowed. */
export interface ColourableNode {
  kind: string;
  origin?: string | null;
  health_status?: string | null;
  last_run_status?: string | null;
  out_of_date?: boolean;
  out_of_date_reason?: string | null;
}

export interface Swatch {
  /** Stable across renders and unique within a colouring — the legend's key. */
  key: string;
  label: string;
  token: string;
}

const UNKNOWN: Swatch = { key: "unknown", label: "Not known", token: NEUTRAL };

function statusSwatch(node: ColourableNode): Swatch {
  // An object type's last *run* is its last sync (§351), so it colours the way
  // a model does rather than the way a dataset's health does: the question a
  // red node answers is "did the thing that writes this work", and for an
  // object type that thing is the sync.
  if (node.kind === "object_type") {
    if (node.last_run_status === "ok") return { key: "ok", label: "Synced", token: GOOD };
    if (node.last_run_status === "error") return { key: "failed", label: "Failed", token: BAD };
    return UNKNOWN;
  }
  if (node.kind === "model") {
    if (node.last_run_status === "succeeded") {
      return { key: "ok", label: "Succeeded", token: GOOD };
    }
    if (node.last_run_status === "failed") {
      return { key: "failed", label: "Failed", token: BAD };
    }
    return UNKNOWN;
  }
  // A stale dataset outranks its health: passing expectations on data that is
  // behind is exactly the reassuring half of the answer (§352).
  if (node.out_of_date) return { key: "stale", label: "Out of date", token: WARN };
  if (node.health_status === "fail") return { key: "failed", label: "Failing checks", token: BAD };
  if (node.health_status === "warn") return { key: "warn", label: "Warning", token: WARN };
  if (node.health_status === "pass") return { key: "ok", label: "Passing", token: GOOD };
  return UNKNOWN;
}

function outOfDateSwatch(node: ColourableNode): Swatch {
  // p.39 names exactly these two and this platform stores exactly these two
  // (§352) — the mapping is one-to-one rather than an interpretation.
  if (!node.out_of_date) return { key: "current", label: "Up to date", token: GOOD };
  if (node.out_of_date_reason === "input_is_newer") {
    return { key: "parent", label: "Out of date with a parent", token: BAD };
  }
  if (node.out_of_date_reason === "upstream_is_out_of_date") {
    return { key: "ancestor", label: "Out of date with an ancestor", token: WARN };
  }
  return { key: "stale", label: "Out of date", token: WARN };
}

function healthSwatch(node: ColourableNode): Swatch {
  if (node.health_status === "pass") return { key: "pass", label: "Passing", token: GOOD };
  if (node.health_status === "warn") return { key: "warn", label: "Warning", token: WARN };
  if (node.health_status === "fail") return { key: "fail", label: "Failing", token: BAD };
  // **Not "passing"**, which is the one wrong answer here: a dataset with no
  // expectations on it has not been checked, and colouring it the same as one
  // that passed would report confidence nobody established.
  return { key: "none", label: "No checks", token: NEUTRAL };
}

function kindSwatch(node: ColourableNode): Swatch {
  if (node.kind === "dataset") return { key: "dataset", label: "Dataset", token: GOOD };
  if (node.kind === "model") return { key: "model", label: "Model", token: WARN };
  if (node.kind === "object_type") {
    return { key: "object_type", label: "Object type", token: BAD };
  }
  return UNKNOWN;
}

function originSwatch(node: ColourableNode): Swatch {
  // p.38's "Resource overview... the way the resource was created". `origin`
  // is exactly that column, and it is null on everything that is not a
  // dataset — a model is not created the way its output is.
  if (node.origin === "upload") return { key: "upload", label: "Uploaded", token: WARN };
  if (node.origin === "model_output") {
    return { key: "model_output", label: "Written by a model", token: GOOD };
  }
  if (node.origin === "sync") return { key: "sync", label: "Synced", token: BAD };
  if (node.origin) return { key: node.origin, label: node.origin, token: NEUTRAL };
  return { key: "none", label: "Not a dataset", token: QUIET };
}

/** The colour one node takes under one colouring.
 *
 * An unknown colouring id falls back to the default rather than to no colour:
 * a saved view (§360) naming a colouring a later build dropped should open
 * looking like the graph, not like a graph somebody switched the colour off on.
 */
export function swatchFor(node: ColourableNode, colouring: string): Swatch | null {
  switch (colouring) {
    case "none":
      return null;
    case "out_of_date":
      return outOfDateSwatch(node);
    case "health":
      return healthSwatch(node);
    case "kind":
      return kindSwatch(node);
    case "origin":
      return originSwatch(node);
    default:
      return statusSwatch(node);
  }
}

export interface LegendEntry extends Swatch {
  count: number;
}

/** The order each colouring's legend reads in: **worst first**, because that
 * is what somebody opens a pipeline graph to find.
 *
 * Written out rather than derived from the order nodes happen to appear in. A
 * legend sorted by what the graph contained first reshuffles the moment a
 * dataset is added, which makes the key a moving target for the reader who is
 * looking between it and the cards. A key that cannot be relied on to stay
 * still is one people stop using.
 *
 * `origin` can carry a value this list does not name — the column is free text
 * as far as this module is concerned — so anything unlisted sorts last rather
 * than being dropped. */
const LEGEND_ORDER: Record<string, readonly string[]> = {
  status: ["failed", "stale", "warn", "ok", "unknown"],
  out_of_date: ["parent", "ancestor", "stale", "current"],
  health: ["fail", "warn", "pass", "none"],
  kind: ["dataset", "model", "object_type", "unknown"],
  origin: ["upload", "model_output", "sync", "none"],
};

/**
 * The key for a colouring, over the nodes actually on the graph.
 *
 * **A colour with no legend is a code**, and p.38's options are worth nothing
 * without one: "why is that card brown" has an answer the reader cannot reach
 * by looking. Counts come with it because the same list then doubles as a
 * summary — nine failing and two passing is the shape of the pipeline, said in
 * the place somebody is already looking.
 *
 * Order is `LEGEND_ORDER`'s — worst first — rather than the count or the order
 * the graph happens to hold its nodes in, so the key does not reshuffle while
 * somebody is looking between it and the cards.
 */
export function legendFor(
  nodes: readonly ColourableNode[],
  colouring: string,
): LegendEntry[] {
  if (colouring === "none") return [];
  const seen = new Map<string, LegendEntry>();
  for (const node of nodes) {
    const swatch = swatchFor(node, colouring);
    if (swatch === null) continue;
    const held = seen.get(swatch.key);
    if (held) held.count += 1;
    else seen.set(swatch.key, { ...swatch, count: 1 });
  }
  const order = LEGEND_ORDER[colouring] ?? [];
  const rank = (key: string) => {
    const at = order.indexOf(key);
    return at === -1 ? order.length : at;
  };
  return [...seen.values()].sort(
    (a, b) => rank(a.key) - rank(b.key) || a.label.localeCompare(b.label),
  );
}
