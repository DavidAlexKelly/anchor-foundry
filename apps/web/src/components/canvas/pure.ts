/** The arithmetic and formatting the canvas widgets do, with no React in it.
 *
 * **Why this module exists at all.** These functions were private to
 * `widgets.tsx`, where the only thing that could reach them was a browser
 * driving the whole application. That is the right way to check that a click
 * narrows a table; it is a wasteful and imprecise way to check that a month
 * bucket is labelled with its year. A pixel is a lossy way to ask about a
 * number.
 *
 * **The boundary is deliberate and worth keeping.** Nothing here imports
 * React, touches the DOM, or renders anything — so nothing here *can* grow
 * into a second, weaker imitation of the browser suite. Component and
 * interaction testing stays in `e2e/`, which drives real servers in a real
 * browser, because that is where the defects this project actually hits have
 * lived: a widget reading the right data and drawing the wrong thing, a filter
 * sent when it should have been dropped, a section laying out in one column.
 * A jsdom test that passes while the real thing is broken is worse than no
 * test, and this file is arranged so that one cannot be written in it.
 */

// ---- pivot table (roadmap 1.5) ---------------------------------------------

export type PivotPick = { row: string | null; column: string | null };

export type Clause = { property: string; op: string; value: string };

/** The clause list for a pivot selection — the whole list, so clearing one
 *  axis is the *absence* of its clause rather than a clause with an empty
 *  value. A widget that wrote `value: ""` would narrow to the objects whose
 *  property is the empty string, which is a different set and usually none. */
export function pivotClauses(
  pick: PivotPick,
  rowProperty: string,
  columnProperty: string,
): Clause[] {
  const out: Clause[] = [];
  if (pick.row !== null) out.push({ property: rowProperty, op: "eq", value: pick.row });
  if (pick.column !== null) {
    out.push({ property: columnProperty, op: "eq", value: pick.column });
  }
  return out;
}

// ---- time series (roadmap 1.5) ---------------------------------------------

/** A bucket's label, formatted **in UTC** — the boundary the server pinned.
 *
 * Rendering in local time would put a viewer six hours west a day behind the
 * bucket they are looking at: the same disagreement UTC was chosen to remove,
 * reintroduced in the browser. The locale is the viewer's; only the zone is
 * fixed.
 */
export function seriesLabel(iso: string, interval: string): string {
  const when = new Date(iso);
  const opts: Intl.DateTimeFormatOptions =
    interval === "month"
      ? { year: "numeric", month: "short", timeZone: "UTC" }
      : { day: "numeric", month: "short", timeZone: "UTC" };
  const formatted = new Intl.DateTimeFormat(undefined, opts).format(when);
  return interval === "week" ? `w/c ${formatted}` : formatted;
}

// ---- section proportions (roadmap 1.4) -------------------------------------

/** The least of a section a part may be dragged to, as a fraction of the pair
 *  being resized. A part dragged to nothing has no handle left to grab and no
 *  way back except the Settings field — an unrecoverable state reached by an
 *  ordinary gesture, which is the kind worth preventing rather than
 *  documenting. */
export const MIN_SHARE = 0.08;

/** Weights are rounded so the document stays something a person can read and
 *  edit. `2.33,0.67` is describable; sixteen decimal places of float noise is
 *  not, and the roadmap's whole reason for typing proportions first was that
 *  the saved layout should be describable. */
export function roundWeight(value: number): number {
  return Math.round(value * 100) / 100;
}

/** A section's proportions as numbers, one per child.
 *
 * Anything unparseable, negative or zero is dropped rather than honoured: the
 * string is typed by hand, and a section should lay out sensibly before
 * anybody has configured it — and *keep* laying out sensibly halfway through
 * somebody typing. Short lists fall back to 1 per missing child.
 */
export function parseWeights(weights: string | null | undefined, count: number): number[] {
  const parsed = String(weights || "")
    .split(",")
    .map((w) => Number(w.trim()))
    .filter((w) => Number.isFinite(w) && w > 0);
  return Array.from({ length: count }, (_, index) => parsed[index] ?? 1);
}

/** Move the boundary between `index` and `index + 1` so the first takes
 *  `share` of the pair, keeping their combined share fixed.
 *
 * **Only the two either side of a handle move.** Dragging one divider must not
 * shuffle a column at the far end of the section — the parts beyond the pair
 * are not the author's concern when they grab a particular boundary.
 *
 * Clamped to `MIN_SHARE` at both ends, so neither part can be driven to
 * nothing.
 */
export function resizeWeights(current: number[], index: number, share: number): number[] {
  const next = [...current];
  const pair = (next[index] ?? 1) + (next[index + 1] ?? 1);
  const clamped = Math.min(Math.max(share, MIN_SHARE), 1 - MIN_SHARE);
  next[index] = pair * clamped;
  next[index + 1] = pair - (next[index] ?? 0);
  return next;
}

/** What a section's `weights` prop becomes after a resize. */
export function formatWeights(weights: number[]): string {
  return weights.map(roundWeight).join(",");
}

// ---- the module interface, initialised from a URL (Foundry p.165) -----------
/**
 * Query parameters, read as starting values for interface variables.
 *
 * > "Append `?` to the URL … followed by the external ID, `=`, and the value
 * > you would like to set. For instance, `?interfaceVariable=123`." (p.165)
 *
 * The same external ID that an embedding module maps, which is the whole point
 * of §3.4: one name, three consumers. Deliberately narrow:
 *
 * **Only interface variables.** An external ID with the interface toggle off is
 * a stable name for state saving and nothing else; honouring it here would make
 * every such variable settable by anyone who can write a link.
 *
 * **Values are seeds, not bindings.** Foundry initialises from the URL; it does
 * not hold the variable there. A binding would mean the first click on a filter
 * fought the address bar and lost.
 *
 * **Unparseable is skipped, not defaulted.** `?count=banana` on a number
 * variable leaves the variable alone rather than setting 0 — a wrong number is
 * indistinguishable from a chosen one once it is on screen, and blank is not.
 */
export function seedFromQuery(
  variables: Record<string, { id: string; kind: string; external_id?: string; interface?: unknown }>,
  query: URLSearchParams | Record<string, string>,
): Record<string, unknown> {
  const get = (name: string) =>
    query instanceof URLSearchParams ? query.get(name) : (query[name] ?? null);
  const seed: Record<string, unknown> = {};
  for (const variable of Object.values(variables)) {
    if (!variable.interface || !variable.external_id) continue;
    const raw = get(variable.external_id);
    if (raw === null) continue;
    const value = coerce(raw, variable.kind);
    if (value !== undefined) seed[variable.id] = value;
  }
  return seed;
}

function coerce(raw: string, kind: string): unknown {
  switch (kind) {
    case "string":
    case "date":
    case "timestamp":
      return raw;
    case "number": {
      const n = Number(raw);
      return Number.isFinite(n) ? n : undefined;
    }
    case "boolean":
      if (raw === "true") return true;
      if (raw === "false") return false;
      return undefined;
    // An object set is a *definition*, not a value, and a single object is the
    // object a viewer picked. Neither survives a round trip through a query
    // string, and Foundry says so for the set case: object set variables in the
    // URL are "limited to a single object by RID" (p.199). Until there is a
    // by-RID lookup to do that properly, this refuses rather than half-works.
    default:
      return undefined;
  }
}

// ---- the action form (decision 0007) ---------------------------------------

/** A parameter, as the form needs it. Structural rather than imported so this
 * module keeps importing nothing. */
type FormParameter = {
  api_name: string;
  data_type: string;
  hidden: boolean;
  default_value?: unknown;
};

/** What the form starts with, for one object.
 *
 * Three sources in a deliberate order:
 *
 *   1. **the object's current value**, because this is an edit form and showing
 *      a blank box beside the thing being edited is how somebody blanks a
 *      property they only meant to look at;
 *   2. **the parameter's default** (p.27) when the object has nothing to say -
 *      which is every parameter that is not named after a property;
 *   3. **empty**.
 *
 * **Hidden parameters are seeded too, and that is the point of them.** p.25's
 * example passes a *previous* value into a hidden parameter so that a rule can
 * compare against it; a form that skipped them would leave the caller unable
 * to supply what the action was built to receive. They are absent from the
 * fields, not from the submission.
 */
export function seedActionForm(
  parameters: FormParameter[],
  properties: Record<string, unknown>,
): Record<string, string> {
  const seeded: Record<string, string> = {};
  for (const parameter of parameters) {
    const current = properties[parameter.api_name];
    const fallback = parameter.default_value;
    const value =
      current !== undefined && current !== null
        ? current
        : fallback !== undefined && fallback !== null
          ? fallback
          : "";
    seeded[parameter.api_name] =
      typeof value === "object" ? JSON.stringify(value) : String(value);
  }
  return seeded;
}

/** The `<input type>` for a parameter.
 *
 * Modest on purpose. A number field stops "twelve" reaching a rule that writes
 * an integer property, and a date field gives a picker; everything else is
 * text, because the *server* coerces (`ontology.coerce_property_value`, shared
 * with the sync path) and a browser-side type that disagreed with it would
 * refuse values the platform accepts.
 */
export function inputTypeFor(dataType: string): string {
  if (dataType === "integer" || dataType === "float") return "number";
  if (dataType === "date") return "date";
  return "text";
}
