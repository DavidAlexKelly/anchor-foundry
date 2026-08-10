/** The resource browser's kind filter, as it is expressed in the URL.
 *
 * **Why this is a module and not four lines inside the component.** The filter
 * moved into the URL so a pillar page can *be* the browser with a filter
 * applied rather than a second implementation of the same list (parity stage
 * 1). That makes the query string a small public interface — links get shared,
 * bookmarked and typed by hand — and the two rules below are the whole of it:
 * an unknown kind is dropped, and a toggle is computed from what the URL
 * currently says. Both are cheap to get wrong and invisible when wrong, which
 * is exactly the shape of thing worth testing without a browser.
 *
 * Nothing here imports React or touches the DOM, for the reason
 * `canvas/pure.ts` sets out: the interaction check belongs in `e2e/`, driving
 * real servers, and this file is arranged so a weaker imitation of that cannot
 * be written in it.
 */

import type { ResourceKind } from "@/lib/types";

/** Every kind the browser can filter by, in the order its chips appear:
 * roughly source → derived → published, which is the order somebody reads a
 * project in. Exported as the single source of truth so that adding a kind
 * cannot leave the URL filter unable to express it. */
export const KIND_LABELS: { kind: ResourceKind; label: string; plural: string }[] = [
  { kind: "connection", label: "Connection", plural: "Connections" },
  { kind: "dataset", label: "Dataset", plural: "Datasets" },
  { kind: "model", label: "Model", plural: "Models" },
  { kind: "object_type", label: "Object type", plural: "Object types" },
  { kind: "canvas_app", label: "Canvas app", plural: "Canvas apps" },
  { kind: "code_repo", label: "Repository", plural: "Repositories" },
];

/** A Map, not an object literal, and the difference is load-bearing: `in` and
 * `[]` on a plain object walk the prototype chain, so `?kind=toString` read as
 * a real kind and `kindLabel("toString")` returned `Object.prototype.toString`
 * — a function where the table wanted a name. A Map has no such chain. Caught
 * by the test below rather than in production, but only because the test was
 * written to ask. */
const LABEL = new Map<string, string>(KIND_LABELS.map((k) => [k.kind, k.label]));

export function kindLabel(kind: ResourceKind): string {
  return LABEL.get(kind) ?? kind;
}

/** Narrows a raw query-string value to a kind we actually have.
 *
 * **An unknown kind is dropped, not forwarded.** `?kind=nonsense` reaching the
 * API is a filter that matches nothing, and the reader sees an empty project
 * rather than a disregarded filter — indistinguishable, at a glance, from a
 * project that really is empty or a listing that really is broken. */
export function isKind(value: string): value is ResourceKind {
  return LABEL.has(value);
}

/** The kinds currently selected, given the raw repeated `kind` parameters.
 * Order follows the URL, and duplicates collapse: `?kind=dataset&kind=dataset`
 * is one filter, not a filter applied twice. */
export function selectedKinds(raw: string[]): ResourceKind[] {
  const out: ResourceKind[] = [];
  for (const value of raw) {
    if (isKind(value) && !out.includes(value)) out.push(value);
  }
  return out;
}

/** What the `kind` parameters become when a chip is toggled.
 *
 * Takes the *current* raw parameters rather than a render-time snapshot: two
 * chips ticked faster than the router settles would otherwise both build on
 * the same stale value and the second would drop the first. `useUrlState`
 * documents this as the reason its setter accepts a function. */
export function toggleKind(raw: string[], kind: ResourceKind): ResourceKind[] {
  const on = selectedKinds(raw);
  return on.includes(kind) ? on.filter((k) => k !== kind) : [...on, kind];
}
