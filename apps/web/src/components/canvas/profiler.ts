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
  /** p.178's "the page or overlay that triggered them" (§395): the layout node
   * that was on screen when this load started, or null when nothing was.
   *
   * **The page at the time, captured rather than looked up.** A load's
   * triggering page is a fact about a moment, and by the time somebody filters
   * the panel the reader is usually somewhere else entirely - asking "which
   * page is showing" then would attribute every earlier load to wherever they
   * happen to be standing. */
  page: string | null;
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
  // A load that took no measurable time still needs to be findable, so a bar
  // has a floor. Without it every fast row is invisible and the timeline looks
  // like it lost them.
  const width = Math.max(1, Math.min(100, (event.ms / total) * 100));
  // **The floor has to push the bar back, not off the end.** The width is
  // settled first and `left` then makes room for it, because the common case
  // is the one that broke: a variable resolving in under a millisecond at the
  // very end of the run puts `at / total` at 100%, and a 1% bar starting there
  // is a bar nobody can see. A browser test caught it - the row was in the
  // DOM, correct, and outside the track.
  const left = Math.max(0, Math.min(100 - width, (event.at / total) * 100));
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


// ---- p.178's interaction list (§395) ----------------------------------------
//
// > "You can also filter widget and variable loads based on the page or
// > overlay that triggered them, search for captured load events by widget or
// > variable name, and clear all captured load events in the profiler." (p.178)
//
// Clearing is the recorder's (§394). These two are decisions about what a
// reader is asking for, so they are here.

/** How the filter is set: a layout node id, or every page. */
export type PageFilter = string | null;

/**
 * The pages and overlays that actually triggered something, for the picker.
 *
 * **Derived from the events rather than from the layout**, which is the whole
 * design of this control. A module with twelve pages that has only ever loaded
 * on two offers two, because p.178 filters *loads* — and a picker listing ten
 * choices that all yield an empty panel is a control that looks like it works
 * (§214). It also means the list grows as a reader navigates, which is exactly
 * the interaction p.178 describes.
 *
 * Ordered by first appearance, so the entry a reader arrived through is first.
 */
export function triggeringPages(events: readonly LoadEvent[]): string[] {
  const seen: string[] = [];
  for (const event of events) {
    if (event.page !== null && !seen.includes(event.page)) seen.push(event.page);
  }
  return seen;
}

/**
 * p.178's two narrowings, applied together.
 *
 * **One function rather than two composed at the call site**, because they are
 * one question — "which of these am I looking at" — and a panel that filtered
 * in one place and searched in another would eventually disagree about which
 * came first, which matters for the count shown beside them.
 *
 * The search is over the *name*, which is what p.178 says ("by widget or
 * variable name") and what the reader can see. Matching an id would let a
 * search succeed against a string nowhere on screen.
 *
 * Case-insensitive and trimmed: a reader typing a variable's label copies it
 * from a panel that title-cases, and a search that missed on capitalisation
 * would read as the event not being recorded.
 */
export function narrow(
  events: readonly LoadEvent[],
  { page = null, search = "" }: { page?: PageFilter; search?: string } = {},
): LoadEvent[] {
  const needle = search.trim().toLowerCase();
  return events.filter((event) => {
    if (page !== null && event.page !== page) return false;
    if (needle === "" ) return true;
    return event.name.toLowerCase().includes(needle);
  });
}

/**
 * What the panel says when a narrowing has hidden everything.
 *
 * **Not the same sentence as "nothing has loaded yet"**, and the difference is
 * the whole point: one means the module is still starting, the other means the
 * reader is looking through a filter they set. Showing the first for the
 * second sends somebody to diagnose a module that is fine.
 *
 * Null when there is something to show, so the caller draws the table instead.
 */
export function emptyReason(
  all: readonly LoadEvent[],
  shown: readonly LoadEvent[],
): string | null {
  if (shown.length > 0) return null;
  if (all.length === 0) return "Nothing has loaded yet.";
  return "No load events match this filter.";
}
