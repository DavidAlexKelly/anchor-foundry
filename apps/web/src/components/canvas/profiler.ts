/** What the Performance Profiler says about a module's load (§394; p.177-178).
 *
 * > "Workshop's Performance Profiler gives builders the ability to capture and
 * > view the performance of their applications, providing a tool to diagnose
 * > where high load times may be occurring." (p.177)
 *
 * > "The profiler will display: The total module load time. The timeline view
 * > as widget and variables load or reload. The breakdown of load time by
 * > widgets and variables." (p.178)
 *
 * The recorder collects events; this decides what they *mean*. Same division
 * as `test-runs.ts` and `preview-runs.ts`: something else owns what happened,
 * and a pure module owns the wording.
 *
 * **Two things here are ours rather than Foundry's, and both are consequences
 * of how this platform loads.**
 *
 * p.177 records *network requests*. This platform resolves the whole visible
 * closure of a module's variables in **one** request, so a network measurement
 * could only ever report a single number for every variable at once. The
 * evaluator times each one instead (`workshop_variables.evaluate`), which
 * makes the variable half of p.178's breakdown exact rather than apportioned.
 *
 * And a widget's load is a *query*, not a component. Sixteen widget types share
 * one query cache, and a cache key names the request rather than the widget
 * that asked for it — so a row here says what loaded rather than who wanted
 * it. Saying "Object Table" over a number that is really "every object-set
 * read on the page" would be the more comfortable lie.
 */

/** One thing that loaded, as the recorder saw it. */
export interface LoadEvent {
  /** Stable within a session: the variable id, or the query's key. */
  id: string;
  kind: "variable" | "request";
  /** What to show in a row. A variable's label, or a readable form of a key. */
  name: string;
  /** Milliseconds this load took. */
  ms: number;
  /** When it started, relative to the module's initialisation. */
  at: number;
  /** How many times this has loaded since profiling started. p.178 counts
   * reloads as events of their own ("widget and variable load *and reload*
   * events"), and a row that collapsed them would hide the thing most worth
   * finding: something loading forty times. */
  loads: number;
}

/**
 * p.178's "total module load time".
 *
 * **The wall clock from initialisation to the last load that finished**, not
 * the sum of the parts. Variables resolve in one request and widgets query in
 * parallel, so adding the rows would report several seconds for a module that
 * took one — the number would grow with concurrency, which is backwards.
 *
 * Zero events is `0` rather than null: profiling started, nothing has loaded
 * yet, and a panel saying "—" there is indistinguishable from one that failed.
 */
export function totalMs(events: readonly LoadEvent[]): number {
  let end = 0;
  for (const e of events) end = Math.max(end, e.at + e.ms);
  return Math.round(end);
}

/**
 * The breakdown, worst first.
 *
 * Sorted by time rather than by name, because p.177 says what this is for:
 * *"diagnose where high load times may be occurring"*. A reader opens this
 * with a slow module and wants the first row to be the answer.
 *
 * Ties break on name so the order is stable between renders — a list that
 * reshuffled on every reload would be unreadable exactly when it is busiest.
 */
export function breakdown(events: readonly LoadEvent[]): LoadEvent[] {
  return [...events].sort((a, b) => (b.ms - a.ms) || a.name.localeCompare(b.name));
}

/**
 * The timeline, in the order things happened.
 *
 * p.178 lists this *separately* from the breakdown, and they are different
 * questions: the breakdown asks what was expensive, the timeline asks what was
 * waiting on what. A module whose three slowest things ran in parallel and one
 * whose three fastest ran in series look identical in a breakdown.
 */
export function timeline(events: readonly LoadEvent[]): LoadEvent[] {
  return [...events].sort((a, b) => (a.at - b.at) || a.name.localeCompare(b.name));
}

/** Where a row sits on the timeline, as percentages of the total. */
export function span(event: LoadEvent, total: number): { left: number; width: number } {
  if (total <= 0) return { left: 0, width: 100 };
  const left = Math.max(0, Math.min(100, (event.at / total) * 100));
  // A load that took no measurable time still needs to be findable, so a bar
  // has a floor. Without it every fast row is invisible and the timeline looks
  // like it lost them.
  const width = Math.max(1, Math.min(100 - left, (event.ms / total) * 100));
  return { left, width };
}

/** How a duration reads. Sub-millisecond loads are the majority and "0ms" on
 * forty rows is noise, so they say `<1ms` — which is information, where `0ms`
 * is a number somebody will try to explain. */
export function durationLabel(ms: number): string {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * The sentence above the panel.
 *
 * **"Nothing recorded yet" is not "this module is fast."** Profiler mode
 * reloads the page to record from initialisation (p.177), so there is always a
 * moment with the banner up and no rows, and a panel reporting `0ms` there
 * would be a measurement of nothing wearing the clothes of a good result.
 */
export function summary(events: readonly LoadEvent[]): string {
  if (events.length === 0) return "Nothing has loaded yet.";
  const total = totalMs(events);
  const variables = events.filter((e) => e.kind === "variable").length;
  const requests = events.length - variables;
  const parts: string[] = [];
  if (variables > 0) parts.push(`${variables} variable${variables === 1 ? "" : "s"}`);
  if (requests > 0) parts.push(`${requests} request${requests === 1 ? "" : "s"}`);
  return `${durationLabel(total)} · ${parts.join(", ")}`;
}

/**
 * Whether a load is worth drawing attention to.
 *
 * A threshold rather than a colour scale: p.177's purpose is finding the slow
 * one, and shading forty rows by degree makes the slowest indistinguishable
 * from the second slowest at a glance. 500ms is where a load stops feeling
 * instant to somebody using the module, which is the judgement being made.
 */
export const SLOW_MS = 500;

export function isSlow(event: LoadEvent): boolean {
  return event.ms >= SLOW_MS;
}


// ---- profiler mode, and what the recorder does with an event -----------------

/** The URL flag. One spelling, because the button that sets it and the hook
 * that reads it must agree and a second one is a mode nobody can leave.
 *
 * **It is in the URL because the reload is the feature.** p.177: "Entering
 * Profiler mode will refresh the module's web browser page to allow the
 * profiler to record network requests, starting from the module's
 * initialization." A recorder switched on by a button would miss everything a
 * module does on the way up, which is the part worth profiling.
 */
export const PROFILER_PARAM = "profiler";

/** Whether this page was loaded in profiler mode. Read from the address rather
 * than from state, for the reason above: state cannot survive the reload that
 * makes the recording start at initialisation. */
export function profilerOn(search: string): boolean {
  return new URLSearchParams(search).get(PROFILER_PARAM) === "1";
}

/**
 * The address to navigate to in order to enter or leave profiler mode.
 *
 * Returned rather than applied so the decision is testable without a router —
 * the shape `routingParams` takes one module over. **Every other parameter is
 * kept**, which is not tidiness: a module reached through a routed link
 * (p.197) carries its variable values in the address, and dropping them on the
 * way into the profiler would profile a different module state than the one
 * the reader was looking at.
 */
export function profilerHref(current: string, on: boolean): string {
  const [path, query = ""] = current.split("?");
  const params = new URLSearchParams(query);
  if (on) params.set(PROFILER_PARAM, "1");
  else params.delete(PROFILER_PARAM);
  const rest = params.toString();
  return rest ? `${path}?${rest}` : (path ?? "");
}

/**
 * A readable name for a query cache key.
 *
 * The first segment is the read's name (`canvas-object-set`, `object-type`);
 * the rest identify the thing read. Shown as the name plus the first
 * identifying segment, because a key rendered whole is a line of UUIDs and a
 * key rendered as its head alone collapses twenty different reads into one row
 * — which would make the breakdown say "object set" over a number that is
 * really every object-set read on the page.
 */
export function keyName(key: readonly unknown[]): string {
  const head = String(key[0] ?? "read").replace(/^canvas-/, "").replace(/-/g, " ");
  const next = key.slice(1).find((part) => typeof part === "string" && part.length > 0);
  return next === undefined ? head : `${head} · ${String(next).slice(0, 12)}`;
}

/**
 * Fold a new load into the list.
 *
 * **A reload replaces the row and counts, rather than adding one.** p.178
 * captures "widget and variable load *and reload* events", and a module where
 * a filter moves ten times would otherwise be a list of a hundred rows with no
 * way to see that ten of them are one thing. The time shown is the most recent
 * one, because that is the load the reader can still do something about; the
 * *start* stays at the first, so the timeline keeps saying when this thing
 * first appeared rather than sliding right on every recompute.
 */
export function merge(current: readonly LoadEvent[], row: LoadEvent): LoadEvent[] {
  const at = current.findIndex((e) => e.id === row.id && e.kind === row.kind);
  if (at < 0) return [...current, row];
  const previous = current[at]!;
  const next = [...current];
  next[at] = { ...row, loads: previous.loads + 1, at: previous.at };
  return next;
}
