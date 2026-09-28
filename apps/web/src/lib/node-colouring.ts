/** p.38-40's node colouring: what a card's colour is *about* (§419).
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
 * **p.39's quantitative colourings are built (§622)**: row count and time
 * last built. They were held back on a palette argument that was right about
 * the tokens and wrong about the answer: `--accent-wash`, `--accent` and
 * `--accent-deep` are not ordered the same way in both themes, so a ramp built
 * *from them* reads backwards for half the readers - and inventing three
 * tokens would be a second palette. `RAMP` is neither. It is one token,
 * `--accent`, mixed with `transparent` at rising strengths, so each step is
 * further from *whatever the page is* than the last, in either theme. Build
 * duration is ○: no node carries one (`datasets-lineage.md`).
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
  { id: "permissions", label: "Permissions",
    hint: "p.80: what one person can see, chosen under View as" },
  { id: "rows", label: "Row count",
    hint: "p.39: how many rows each dataset holds, in quarters of this graph" },
  { id: "built", label: "Time last built",
    hint: "p.39: how long ago each was built, in quarters of this graph" },
  { id: "none", label: "No colour",
    hint: "p.38's first option: remove colouring altogether" },
];

export const DEFAULT_COLOURING = "status";

/** A node as this module reads it: the graph's shape, narrowed.
 *
 * **Every field required, nullable where `PipelineNode` is nullable**, which
 * is what actually arrives — `services/pipeline.py` sets all six on every node
 * it builds, and the wire type says so. They were optional here at first, and
 * that was a fiction with a cost: it let this module's own tests build a node
 * the graph can never draw, and then asserted something about it. A sweep
 * found the seam — `!node.out_of_date` and `node.out_of_date === false`
 * differ only on a node with no `out_of_date` at all — and the honest answer
 * was not a test for the missing field but a type that stops claiming it can
 * be missing. */
export interface ColourableNode {
  kind: string;
  /** p.80-84's *Permissions* (§422): what the person named under *View as*
   *  holds on the scope that decides this node, and which scope that was.
   *  Absent on every colouring but that one, and absent under that one until
   *  somebody has been chosen — which `permissionSwatch` reads as "nobody
   *  asked" rather than as "no access" (§210). */
  access?: { role: string | null; via: string } | null;
  origin: string | null;
  health_status: string | null;
  last_run_status: string | null;
  out_of_date: boolean;
  out_of_date_reason: string | null;
  /** p.39's quantitative colourings (§622): a dataset's rows, and when a
   *  dataset or model output was last built. */
  row_count: number | null;
  built_at: string | null;
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
  // A data source's last run is its last sync too (§420), and it uses
  // `sync_runs`' vocabulary rather than an object type's — which is why it is
  // its own branch and not a value added to the one above.
  if (node.kind === "connection") {
    if (node.last_run_status === "succeeded") {
      return { key: "ok", label: "Synced", token: GOOD };
    }
    if (node.last_run_status === "failed") {
      return { key: "failed", label: "Sync failed", token: BAD };
    }
    if (node.last_run_status === "running") {
      return { key: "warn", label: "Syncing", token: WARN };
    }
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
  // p.39 names two, "out of date with a parent" and "with an ancestor", and
  // this platform stores those two (§352) — one-to-one rather than an
  // interpretation. §583 adds p.51's third, a source that has not delivered,
  // which p.39's list does not name and is the more urgent: no rebuild fixes it.
  if (!node.out_of_date) return { key: "current", label: "Up to date", token: GOOD };
  // p.51's third (§583): its source has not delivered, which no rebuild fixes.
  if (node.out_of_date_reason === "source_is_behind") {
    return { key: "source", label: "Out of date with its source", token: BAD };
  }
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
  if (node.kind === "connection") {
    return { key: "connection", label: "Data source", token: QUIET };
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
  // A data source has no `origin` of its own, and "Not a dataset" is the
  // honest label for it as much as for a model (§420).
  if (node.origin) return { key: node.origin, label: node.origin, token: NEUTRAL };
  return { key: "none", label: "Not a dataset", token: QUIET };
}

/** p.83's *Resource access*: "the role (such as Editor, Viewer, etc.) that is
 *  set for the selected user on the selected resource" (§422).
 *
 * **Three states, not two.** A node nobody has been asked about is not a node
 * somebody cannot see, and drawing them alike would report a permissions
 * problem before anybody had named a person (§210). p.83's other type — *Data
 * access in datasets* — is Markings propagated down the lineage, and this
 * platform has none; the parity row carries that rather than a second option
 * that would paint one colour. */
function permissionSwatch(node: ColourableNode): Swatch {
  const access = node.access;
  if (access === undefined || access === null) {
    return { key: "unasked", label: "Nobody chosen", token: QUIET };
  }
  if (access.role === null) {
    // p.84's own point: the scope is part of the answer. "No access" is
    // useless to somebody debugging without "at which door".
    return {
      key: "none", label: `No access (${access.via})`, token: BAD,
    };
  }
  if (access.role === "viewer") {
    return { key: "viewer", label: `Viewer (${access.via})`, token: WARN };
  }
  return { key: access.role, label: `${access.role} (${access.via})`, token: GOOD };
}

/** The colour one node takes under one colouring.
 *
 * An unknown colouring id falls back to the default rather than to no colour:
 * a saved view (§360) naming a colouring a later build dropped should open
 * looking like the graph, not like a graph somebody switched the colour off on.
 */
export function swatchFor(
  node: ColourableNode, colouring: string, scale?: Scale | null,
): Swatch | null {
  switch (colouring) {
    case "none":
      return null;
    case "rows":
    case "built":
      return quantitySwatch(node, colouring, scale ?? null);
    case "out_of_date":
      return outOfDateSwatch(node);
    case "health":
      return healthSwatch(node);
    case "kind":
      return kindSwatch(node);
    case "origin":
      return originSwatch(node);
    case "permissions":
      return permissionSwatch(node);
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
  out_of_date: ["source", "parent", "ancestor", "stale", "current"],
  health: ["fail", "warn", "pass", "none"],
  kind: ["dataset", "model", "object_type", "connection", "unknown"],
  origin: ["upload", "model_output", "sync", "none"],
  // Worst first. `unasked` is here at all only so it has a place; it never
  // shares a graph with a real verdict, because either somebody has been
  // chosen or nobody has. A role this build does not name — the server's
  // `effective_project_role` could grow one — sorts after everything rather
  // than being dropped, which is the rule every colouring here follows.
  permissions: ["none", "viewer", "editor", "owner", "unasked"],
  // Most first - the biggest datasets, the longest since built - then the
  // nodes with nothing to measure.
  rows: ["q3", "q2", "q1", "q0", "none"],
  built: ["q3", "q2", "q1", "q0", "none"],
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
  now: number = Date.now(),
): LegendEntry[] {
  if (colouring === "none") return [];
  const scale = scaleFor(nodes, colouring, now);
  const seen = new Map<string, LegendEntry>();
  for (const node of nodes) {
    const swatch = swatchFor(node, colouring, scale);
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

/**
 * The colouring a stored view names, or the default if it names nothing this
 * build offers.
 *
 * **`swatchFor` already falls back, and this is not the same fallback.** That
 * one keeps the *cards* looking like a graph when a saved view (§360) names a
 * colouring a later build dropped. This one keeps the *control* honest: the
 * picker is a `<select>`, and a value no `<option>` carries leaves the browser
 * showing the first option while the graph draws the default — two controls
 * disagreeing about the same state, which is §214 exactly. Narrowing here
 * means the select, the legend and the cards are all reading one id.
 */
export function colouringIn(view: { colouring?: string } | undefined): string {
  const named = view?.colouring;
  if (named === undefined) return DEFAULT_COLOURING;
  return COLOURINGS.some((option) => option.id === named) ? named : DEFAULT_COLOURING;
}


// ---- p.39's quantitative colourings (§622) ----------------------------------
/** Four steps of one token, each further from the page than the last in
 * either theme - see the header. Lightest is least. */
export const RAMP = [30, 55, 80, 100].map(
  (strength) => `color-mix(in srgb, var(--accent) ${strength}%, transparent)`,
);

/** Where a graph's values split into quarters: the three inner edges, over the
 * values the graph actually holds. A quarter nothing falls in is simply not
 * drawn, so a graph of equal values is one colour rather than four. */
export interface Scale {
  colouring: string;
  now: number;
  edges: number[];
}

/** What a node measures under a quantitative colouring, or `null` for none:
 * rows for a dataset only (a model or a type holds no rows of its own), and
 * the time since it was built for anything that has been. */
export function quantityOf(node: ColourableNode, colouring: string, now: number): number | null {
  if (colouring === "rows") {
    return node.kind === "dataset" && node.row_count !== null ? node.row_count : null;
  }
  if (colouring === "built" && node.built_at) {
    const at = Date.parse(node.built_at);
    return Number.isNaN(at) ? null : Math.max(0, now - at);
  }
  return null;
}

/** The quarters of one graph under one colouring, or `null` for a colouring
 * that is not quantitative. */
export function scaleFor(
  nodes: readonly ColourableNode[], colouring: string, now: number = Date.now(),
): Scale | null {
  if (colouring !== "rows" && colouring !== "built") return null;
  const values = nodes.map((n) => quantityOf(n, colouring, now))
    .filter((v): v is number => v !== null).sort((a, b) => a - b);
  const at = (q: number) => values[Math.min(values.length - 1, Math.floor(q * values.length))]!;
  return { colouring, now, edges: values.length ? [at(0.25), at(0.5), at(0.75)] : [] };
}

/** Which quarter a value is in: the first whose edge it does not pass. */
export function quarterOf(value: number, edges: readonly number[]): number {
  const at = edges.findIndex((edge) => value < edge);
  return at === -1 ? edges.length : at;
}

const NO_VALUE: Record<string, string> = { rows: "No rows counted", built: "Never built" };

function quantitySwatch(node: ColourableNode, colouring: string, scale: Scale | null): Swatch {
  // No scale is no value, so one check covers both (§622's sweep).
  const value = scale ? quantityOf(node, colouring, scale.now) : null;
  if (value === null) return { key: "none", label: NO_VALUE[colouring]!, token: QUIET };
  const q = quarterOf(value, scale!.edges);
  return { key: `q${q}`, label: quarterLabel(colouring, q, scale!.edges), token: RAMP[q]! };
}

/** A quarter in words: its bounds, as rows or as an age. */
export function quarterLabel(colouring: string, q: number, edges: readonly number[]): string {
  const say = colouring === "rows" ? rowsText : ageText;
  const low = q === 0 ? null : edges[q - 1]!;
  const high = q === edges.length ? null : edges[q]!;
  if (low === null && high === null) return colouring === "rows" ? "Any rows" : "Any time";
  if (low === null) return `Under ${say(high!)}`;
  if (high === null) return `${say(low)} or more`;
  return `${say(low)} to ${say(high)}`;
}

function rowsText(n: number): string {
  return `${Math.round(n).toLocaleString("en")} rows`;
}

/** An age in the largest whole unit that fits. */
export function ageText(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.floor(hours / 24)} days`;
}
