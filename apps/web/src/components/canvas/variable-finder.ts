/** p.72's three ways of finding a variable in a module that has a lot of them.
 *
 * > "The Variables panel… displays a list with the current variables that exist
 * > within a module, a plus + option to add a new variable, **an input to search
 * > variables by their name or unique ID**, an option to open the variable
 * > lineage graph, and **a filter to display variables based on their definition
 * > type or what settings are enabled**. The variable list includes
 * > **partitions** to help you quickly find relevant variables: when a widget is
 * > selected, a partition displays variables used by that widget; when no widget
 * > is selected, a partition displays variables used in the active page."
 * > (p.72)
 *
 * Three separate controls with one purpose, which is why they are one module:
 * a module with forty variables has a Variables panel nobody can read, and each
 * of these narrows it a different way. They compose — a search inside a filter
 * inside a partition is the normal case, not an edge one.
 *
 * **The lineage graph is not here.** p.72 lists it in the same sentence, and it
 * is a different kind of thing: a view of how variables feed each other rather
 * than a way of shortening a list. Naming it here so its absence reads as a
 * boundary rather than an oversight.
 */
import type { WorkshopVariable } from "../../lib/types";

/** p.73's definition types, as the panel groups them.
 *
 * Derived from the variable rather than stored on it: this repo has one
 * `derivation` with a `transform`, and Foundry's list is a *presentation* of
 * that. Storing a second field saying which one it is would be a fact that can
 * disagree with the derivation beside it — the shape §1.2a's usage scanning
 * already refuses.
 */
export type DefinitionType =
  | "static"
  | "object_set_definition"
  | "object_property"
  | "object_set_aggregation"
  | "variable_transformation"
  | "function";

/** What the filter offers, in the order it offers it. Static first because it
 * is the commonest and the one an author scanning for "the thing I typed in"
 * is looking for. */
export const DEFINITION_TYPES: readonly DefinitionType[] = [
  "static",
  "object_set_definition",
  "object_property",
  "object_set_aggregation",
  "variable_transformation",
  "function",
];

/** The transforms that are their own definition type on p.73. Anything else
 * derived is a "variable transformation", which is p.73's own catch-all: "a
 * series of common operations, possibly referencing other variables". */
const OWN_TYPE: Record<string, DefinitionType> = {
  object_property: "object_property",
  object_set_aggregation: "object_set_aggregation",
};

export function definitionTypeOf(variable: WorkshopVariable): DefinitionType {
  if (variable.object_set) return "object_set_definition";
  const transform = variable.derivation?.transform;
  if (!transform) return "static";
  return OWN_TYPE[transform] ?? "variable_transformation";
}

/** p.73's three variable settings, which the filter also offers.
 *
 * Keyed by the prop that turns each on, so the filter is checked against the
 * document rather than against a list of labels that can drift from it.
 */
export const SETTINGS = {
  interface: (v: WorkshopVariable) => v.interface != null,
  routing: (v: WorkshopVariable) => (v.url_behavior ?? "never") !== "never",
  state_saving: (v: WorkshopVariable) => v.save_state === true,
} as const;

export type SettingName = keyof typeof SETTINGS;

/** p.72's search: "by their name or unique ID".
 *
 * Matches the label, the **external ID** and the internal id. p.72 says "unique
 * ID" and this system has two things that could be called one — the opaque
 * generated `id` and the author-chosen `external_id` — so a search box that
 * picked one would be right half the time and silently wrong the other half.
 * Both are cheap to match, and neither produces a surprising hit: an author who
 * pastes an id from a URL or from an error message expects to find it.
 *
 * Case-insensitive and a substring, because a search that needs the whole name
 * is a search that needs you to already know the answer.
 */
export function matches(variable: WorkshopVariable, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [variable.label, variable.external_id, variable.id].some(
    (field) => typeof field === "string" && field.toLowerCase().includes(needle),
  );
}

export interface Filters {
  query?: string;
  /** Empty means "every type", not "no types" — a filter nobody has touched
   * must not hide everything. */
  types?: readonly DefinitionType[];
  settings?: readonly SettingName[];
}

/** Everything the filters leave in, in the order given.
 *
 * The three conditions are **and**-ed and the values within each are **or**-ed,
 * which is the reading that makes a filter usable: "an object set OR a function"
 * is a question somebody asks, "an object set AND a function" is a question with
 * no answers.
 */
export function apply(
  variables: readonly WorkshopVariable[],
  filters: Filters,
): WorkshopVariable[] {
  const types = filters.types ?? [];
  const settings = filters.settings ?? [];
  return variables.filter((variable) => {
    if (!matches(variable, filters.query ?? "")) return false;
    if (types.length > 0 && !types.includes(definitionTypeOf(variable))) return false;
    if (settings.length > 0 && !settings.some((name) => SETTINGS[name](variable))) return false;
    return true;
  });
}

export interface Partitioned {
  /** p.72's partition: the variables the selection uses. */
  relevant: WorkshopVariable[];
  /** Everything else, still listed — a partition orders a list, it does not
   * hide half of it. */
  rest: WorkshopVariable[];
  /** What the partition is *of*, for the heading. `null` when there is nothing
   * to partition by, in which case `relevant` is empty and the panel draws one
   * plain list. */
  by: "widget" | "page" | null;
}

/** p.72's partitions: "when a widget is selected, a partition displays variables
 * used by that widget; when no widget is selected, a partition displays
 * variables used in the active page".
 *
 * `usedBy` maps a variable id to the **node ids** that reference it — which is
 * what `usagesOf` already produces, so the panel does not grow a second notion
 * of what "used" means.
 *
 * **A partition is an ordering, not a filter.** Everything stays in the list;
 * the relevant ones come first under a heading. Hiding the rest would make the
 * panel lie about what the module contains, and p.72's own word for this is
 * "to help you quickly find relevant variables" — find, not restrict.
 */
export function partition(
  variables: readonly WorkshopVariable[],
  usedBy: (variableId: string) => readonly string[],
  scope: { widget?: string | null; pageNodes?: readonly string[] | null },
): Partitioned {
  const widget = scope.widget ?? null;
  const pageNodes = scope.pageNodes ?? null;
  const by: Partitioned["by"] = widget ? "widget" : pageNodes ? "page" : null;
  if (by === null) return { relevant: [], rest: [...variables], by: null };

  // A widget's own node for the widget partition; every node on the page for
  // the page one. A `Set` because a page can hold a lot of nodes and this runs
  // once per variable.
  const wanted = new Set<string>(widget ? [widget] : (pageNodes ?? []));
  const relevant: WorkshopVariable[] = [];
  const rest: WorkshopVariable[] = [];
  for (const variable of variables) {
    const nodes = usedBy(variable.id);
    (nodes.some((node) => wanted.has(node)) ? relevant : rest).push(variable);
  }
  return { relevant, rest, by };
}
