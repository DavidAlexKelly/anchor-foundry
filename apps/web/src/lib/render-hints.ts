/**
 * A property's render hints (§724; `object-link-types` p.248-252; db 0140).
 *
 * > "Foundry uses render hints to communicate information about the use of
 * > Ontology properties to Object Storage v1 (Phonograph) and user
 * > applications in the platform." (p.248)
 *
 * The browser's copy of `services/render_hints.py` - the list, the default and
 * the one rule - so the checklist can keep a save legal as it is ticked rather
 * than letting the server refuse it afterwards. A drift between the two is a
 * box whose save fails, which `render-hints.test.ts` pins.
 */

export type RenderHint =
  | "disable_formatting" | "identifier" | "keywords" | "long_text" | "low_cardinality"
  | "selectable" | "sortable" | "searchable" | "leading_wildcards" | "regex";

/** p.249-252's table, in its order, each with what the table says it is for. */
export const RENDER_HINTS: readonly { key: RenderHint; label: string; hint: string }[] = [
  { key: "disable_formatting", label: "Disable formatting",
    hint: "Values are not formatted to the browser's local number format." },
  { key: "identifier", label: "Identifier",
    hint: "A numeric key: not formatted or filtered as a number." },
  { key: "keywords", label: "Keywords", hint: "Shown in its own section in object views." },
  { key: "long_text", label: "Long text", hint: "A large amount of text, shown to be read." },
  { key: "low_cardinality", label: "Low cardinality", hint: "Not many possible values." },
  { key: "selectable", label: "Selectable", hint: "Users may aggregate on it." },
  { key: "sortable", label: "Sortable", hint: "Users may sort on it." },
  { key: "searchable", label: "Searchable", hint: "Users may search on it." },
  { key: "leading_wildcards", label: "Enable leading wildcards",
    hint: "Text queries may start with a wildcard." },
  { key: "regex", label: "Enable regex queries", hint: "Text queries may be regular expressions." },
];

/** On unless deselected (p.182), and what a property that names none has. */
export const DEFAULT_HINTS: readonly RenderHint[] = ["selectable", "sortable", "searchable"];

/** p.250-251: "The Searchable render hint must also be selected along with"
 * each of these. */
export const NEEDS_SEARCHABLE: readonly RenderHint[] = [
  "low_cardinality", "selectable", "sortable", "leading_wildcards", "regex",
];

/** A property's hints as stored, in the table's order: absent is the default
 * rather than none, which is the server's reading of a client that sends
 * none. */
export function hintsOf(raw: readonly string[] | null | undefined): RenderHint[] {
  const chosen = raw ?? DEFAULT_HINTS;
  return RENDER_HINTS.map((h) => h.key).filter((key) => chosen.includes(key));
}

/** The hints with one ticked or unticked, kept legal as p.250-251 states
 * it: ticking one that needs Searchable ticks Searchable too, and unticking
 * Searchable unticks what needed it - rather than a box that cannot be
 * ticked until something else is, with nothing to say which. */
export function toggledHint(
  hints: readonly string[] | null | undefined, key: RenderHint, on: boolean,
): RenderHint[] {
  const current = new Set(hintsOf(hints));
  if (on) {
    current.add(key);
    if (NEEDS_SEARCHABLE.includes(key)) current.add("searchable");
  } else {
    current.delete(key);
    if (key === "searchable") for (const dependent of NEEDS_SEARCHABLE) current.delete(dependent);
  }
  return hintsOf([...current]);
}

/** Whether a property may be grouped by (§727; p.250's Selectable): one
 * bucket per exact value is an "aggregation on exact term values", on any
 * base type. The server refuses the rest; a picker offering them would be
 * offering a refusal. */
export function isSelectable(property: { render_hints?: readonly string[] | null }): boolean {
  return hintsOf(property.render_hints ?? null).includes("selectable");
}

/** The hints by their labels, for a button that says what is set. */
export function hintLabels(hints: readonly string[] | null | undefined): string[] {
  const chosen = hintsOf(hints);
  return RENDER_HINTS.filter((h) => chosen.includes(h.key)).map((h) => h.label);
}
