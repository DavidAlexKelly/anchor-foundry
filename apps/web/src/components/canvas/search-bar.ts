/**
 * p.472-473's Exploration Search Bar (§577).
 *
 * > "Use the Exploration Search Bar widget to visualize and apply filters to
 * > an object set. The widget supports both filtering on properties on the
 * > object type and filtering with linked object types and their properties."
 * > (p.472)
 *
 * > "Property types available: Define which property types to display in the
 * > dropdown menu. Options include All (Including hidden), Prominent,
 * > Visible, or Custom. … Disable property value autocomplete: Toggle to
 * > display/hide suggested filters. Disable keyword filtering: Toggle to
 * > enable/disable keyword filtering for string properties." (p.473)
 *
 * The bar is the Filter Pills (§233) with a field in front of them: what is
 * typed is matched against the properties the menu may offer, and against the
 * string properties as a keyword search. Choosing a property asks for its
 * value, with the values the set holds suggested as the reader types.
 *
 * **A keyword search is p.452's query** (`keyword_query`, §543) on one string
 * property, so `north OR south` means what it says, and one property holds
 * one search: a second replaces the first, as the Filter List's box does.
 *
 * Pure.
 */

import type { Property as Declared } from "./property-sort";

export interface Property extends Declared {
  /** `ontology` p.94's visibility; a property saved before it existed is
   * normal. */
  visibility?: "normal" | "prominent" | "hidden" | null;
}

export const PROPERTY_SCOPES = {
  all: "All (including hidden)",
  prominent: "Prominent",
  visible: "Visible",
  custom: "Custom",
} as const;
export type PropertyScope = keyof typeof PROPERTY_SCOPES;

/** p.473's Property types available, and Visible by default: a hidden
 * property is hidden from exactly this kind of list. */
export function propertyScopeOf(raw: unknown): PropertyScope {
  // Own keys only: `in` would take "toString" for a scope.
  return typeof raw === "string" && Object.hasOwn(PROPERTY_SCOPES, raw) ? raw as PropertyScope
    : "visible";
}

/** The properties the menu may offer, in the type's order. Custom is the
 * list the builder ticked, hidden ones included, since ticking one is asking
 * for it. */
export function availableProperties(
  properties: readonly Property[], scope: PropertyScope, custom: readonly string[] = [],
): Property[] {
  if (scope === "all") return [...properties];
  if (scope === "prominent") return properties.filter((p) => p.visibility === "prominent");
  if (scope === "custom") return properties.filter((p) => custom.includes(p.api_name));
  return properties.filter((p) => p.visibility !== "hidden");
}

export type MenuEntry =
  | { kind: "keyword"; property: string; label: string }
  | { kind: "property"; property: string; label: string };

/** The most entries the menu lists: a list longer than a screen is a list
 * nobody reads, and typing narrows it. */
export const MAX_MENU = 20;

const nameOf = (p: Property) => p.display_name || p.api_name;

/** What the menu offers for the text typed: a keyword search of it in each
 * string property first (the likeliest meaning of a word typed into a search
 * bar), then the properties whose names hold it, to filter on by value. */
export function searchMenu(
  text: string, properties: readonly Property[], options: { keyword: boolean },
): MenuEntry[] {
  const typed = text.trim();
  const lower = typed.toLowerCase();
  const out: MenuEntry[] = [];
  if (typed && options.keyword) {
    for (const p of properties) {
      if (p.data_type === "string") {
        out.push({ kind: "keyword", property: p.api_name, label: `Search "${typed}" in ${nameOf(p)}` });
      }
    }
  }
  for (const p of properties) {
    if (!lower || nameOf(p).toLowerCase().includes(lower) || p.api_name.toLowerCase().includes(lower)) {
      out.push({ kind: "property", property: p.api_name, label: nameOf(p) });
    }
  }
  return out.slice(0, MAX_MENU);
}

/** The groups asked for (`object_sets.MAX_GROUPS`, the most one read gives). */
export const MAX_SUGGESTED = 20;

/** The set the suggestions are read from: the bar's set, narrowed to the
 * values that start with what is typed, so a value outside the most common
 * twenty is still found by typing towards it. `starts_with` is an operator
 * every declared type accepts. */
export function suggestionDefinition(definition: unknown, property: string, typed: string): unknown {
  const text = typed.trim();
  if (!text || !definition || typeof definition !== "object") return definition;
  const d = definition as { filters?: unknown[] };
  return { ...d, filters: [...(d.filters ?? []), { property, op: "starts_with", value: text }] };
}

/** The values to suggest for a property as its value is typed: those the set
 * holds that contain the text, most common first as the counts come, without
 * the empty value, which is not a filter anybody types towards. */
export function suggestionsOf(
  groups: readonly { value: string; count: number }[], typed: string, limit = 8,
): { value: string; count: number }[] {
  const lower = typed.trim().toLowerCase();
  return groups
    .filter((g) => g.value !== "" && g.value.toLowerCase().includes(lower))
    .slice(0, limit);
}

/** p.473's Placeholder, or the bar's own words for what it does. */
export function placeholderOf(raw: unknown, keyword: boolean): string {
  if (typeof raw === "string" && raw.trim()) return raw;
  return keyword ? "Search, or filter by a property…" : "Filter by a property…";
}
