/** What one filter clause is, and which operators a declared property type
 * accepts — the browser's single copy of `object_sets`' filter vocabulary.
 *
 * Written for p.470's Exploration Filter Pills, which is the first widget that
 * has to *render* a clause somebody else wrote and let a viewer change it. Every
 * widget before it wrote one shape of clause and knew which: a Filter List
 * writes `eq`/`in`, a Search writes `starts_with`, a Prominent Terms widget
 * writes `eq`. None of them had to answer "what could this clause be".
 *
 * ---
 *
 * **This is `property-sort.ts`'s argument at the other half of the language, and
 * it was already overdue.** §231 moved the orderable *types* into one place
 * after finding six copies of the constraint; the *operators* were in the same
 * state and the grep that found the six could not see it. `VariablesPanel.tsx`
 * offered four operators under a comment reading "`gt` and friends are refused
 * by the API because Postgres casts and OpenSearch compares text" — true when
 * written, untrue from §221, and **it never named decision 0006**, so searching
 * for the decision's number missed it. A stale claim that states its reason in
 * its own words is invisible to a search for the citation.
 *
 * So the rule §231 landed on gets one more clause: the durable fix is not one
 * module per constraint, it is that **nothing outside this file may write the
 * list**. `ORDERABLE_TYPES` is imported rather than restated, so the mirror test
 * that guards it guards this too.
 */

import { ORDERABLE_TYPES } from "./property-sort";
import type { Property } from "./property-sort";

export type { Property };

/** Operators every declared type accepts.
 *
 * Mirrors `object_sets.OPERATORS`. All four are text-or-exact questions that
 * mean the same thing on Postgres and OpenSearch without knowing a property's
 * type — which is why they need no ontology and the ordered four do.
 */
export const UNIVERSAL_OPERATORS: readonly string[] = ["eq", "neq", "in", "starts_with"];

/** Operators that need a declared type both stores order identically.
 *
 * Mirrors `object_sets.ORDERED_OPERATORS`. Built in §221; refused before that,
 * and refused still for a property whose declared type has no agreed order.
 */
export const ORDERED_OPERATORS: readonly string[] = ["gt", "gte", "lt", "lte"];

/** How each operator reads in a pill and in a picker. */
export const OPERATOR_LABELS: Record<string, string> = {
  eq: "is",
  neq: "is not",
  in: "is one of",
  starts_with: "starts with",
  gt: "is more than",
  gte: "is at least",
  lt: "is less than",
  lte: "is at most",
  within_box: "is inside the area",
};

/** `object_sets.GEO_OPERATORS`, named so a pill can *describe* one.
 *
 * **Deliberately not offered by the editor.** A bounding box is four numbers
 * that mean a rectangle somebody drew on a map (§230); typing them into a text
 * field is not the interaction, and a picker offering "is inside the area" with
 * nowhere to draw would be §214's control that looks like it works. A set that
 * already carries one renders as a pill and says so — read-only is the honest
 * state, not a gap.
 */
export const GEO_OPERATORS: readonly string[] = ["within_box"];

/** Which operators a property of this declared type may be filtered with.
 *
 * **An unknown or absent type gets the universal four**, which is narrower than
 * the server would allow and never wider. That is the safe direction: the
 * ordered four are exactly the ones `object_sets` refuses without a declared
 * type, so offering them on a property whose type the browser has not resolved
 * would produce a refusal in place of a filter.
 */
export function operatorsFor(dataType: string | null | undefined): string[] {
  const type = dataType ?? "";
  return ORDERABLE_TYPES.includes(type)
    ? [...UNIVERSAL_OPERATORS, ...ORDERED_OPERATORS]
    : [...UNIVERSAL_OPERATORS];
}

/** p.470's four Modes, in p.470's order — each one adds to the last. */
export const MODES: Record<string, string> = {
  read_only: "Read only",
  remove: "Remove only",
  update: "Update existing filters only",
  add: "Add, update, remove",
};

export const DEFAULT_MODE = "read_only";

export function modeOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(MODES, raw) ? raw : DEFAULT_MODE;
}

/** **Read only is the default, and the direction matters.** p.470 lists the
 * modes from least to most powerful, and a document that names a mode this
 * build does not have should lose the ability to edit rather than gain it —
 * §214's rule, pointed at the safe end. */
export function canRemove(mode: unknown): boolean {
  return modeOf(mode) !== "read_only";
}

export function canEdit(mode: unknown): boolean {
  return modeOf(mode) === "update" || modeOf(mode) === "add";
}

export function canAdd(mode: unknown): boolean {
  return modeOf(mode) === "add";
}

export interface Clause {
  property: string;
  op: string;
  value: unknown;
}

/** One clause, read from a resolved object-set definition.
 *
 * `null` for anything that is not a clause this language can express — a
 * definition can hold shapes written by an older build or by hand, and a pill
 * rendering `[object Object]` beside a remove button is worse than one absent.
 */
export function clauseOf(raw: unknown): Clause | null {
  if (!raw || typeof raw !== "object") return null;
  const c = raw as Record<string, unknown>;
  const property = typeof c.property === "string" ? c.property : "";
  const op = typeof c.op === "string" ? c.op : "eq";
  if (!property) return null;
  if (!Object.hasOwn(OPERATOR_LABELS, op)) return null;
  return { property, op, value: c.value };
}

export function clausesOf(raw: unknown): Clause[] {
  if (!Array.isArray(raw)) return [];
  const out: Clause[] = [];
  for (const item of raw) {
    const clause = clauseOf(item);
    if (clause) out.push(clause);
  }
  return out;
}

/** What a clause's value reads as in a pill.
 *
 * A list is joined rather than shown as an array, and a bounding box names its
 * edges — `[object Object]` is what a pill shows for a `within_box` otherwise,
 * which is the one clause shape a viewer is least able to guess at.
 */
export function valueLabel(clause: Clause): string {
  const { value } = clause;
  if (Array.isArray(value)) return value.map((v) => String(v)).join(", ");
  if (value && typeof value === "object") {
    const box = value as Record<string, unknown>;
    const edges = ["north", "south", "east", "west"];
    if (edges.every((e) => typeof box[e] === "number")) {
      return `N ${box.north}, S ${box.south}, E ${box.east}, W ${box.west}`;
    }
    return "…";
  }
  if (value === null || value === undefined) return "";
  return String(value);
}

/** What a pill says, given what the ontology calls the property.
 *
 * The display name when there is one, because a pill is read by a viewer rather
 * than by whoever wrote the ontology — and the api_name when there is not, since
 * a pill with no subject cannot be acted on.
 */
export function describe(clause: Clause, properties: readonly Property[]): string {
  const declared = properties.find((p) => p.api_name === clause.property);
  const name = declared?.display_name || clause.property;
  const op = OPERATOR_LABELS[clause.op] ?? clause.op;
  const value = valueLabel(clause);
  return value ? `${name} ${op} ${value}` : `${name} ${op}`;
}

/** Whether the widget could actually remove this clause if asked.
 *
 * **The rule this widget needs and no other widget has.** Pills come from the
 * *resolved* set, which is the base definition's filters plus whatever a
 * `narrow_set` added. Only the second kind is in the variable this widget
 * writes — the first is structural, part of what the set *is*, and no amount of
 * writing to an array will take it off.
 *
 * A remove button on a clause the widget cannot remove is §214's control that
 * looks like it works: the click would write a list that changes nothing, and
 * the pill would sit there. So a structural pill renders without one.
 *
 * Matched by shape rather than by identity because the two lists are different
 * objects: the written one came from a variable, the resolved one came back
 * from the server through `narrow_set`.
 */
export function isRemovable(clause: Clause, written: readonly Clause[]): boolean {
  return written.some((w) => sameClause(w, clause));
}

export function sameClause(a: Clause, b: Clause): boolean {
  return a.property === b.property && a.op === b.op
    && JSON.stringify(a.value ?? null) === JSON.stringify(b.value ?? null);
}

/** The written list with one clause taken out.
 *
 * Removes **one** match rather than every equal clause: a variable can hold the
 * same clause twice (two widgets, one variable), and a viewer clicking one pill
 * of two identical ones has asked to remove one of them.
 */
export function without(written: readonly Clause[], clause: Clause): Clause[] {
  const out: Clause[] = [];
  let dropped = false;
  for (const w of written) {
    if (!dropped && sameClause(w, clause)) {
      dropped = true;
      continue;
    }
    out.push(w);
  }
  return out;
}

/** The written list with one clause's value replaced.
 *
 * The same one-match rule as `without`, and for the same reason.
 */
export function withValue(
  written: readonly Clause[],
  clause: Clause,
  value: unknown,
): Clause[] {
  let replaced = false;
  return written.map((w) => {
    if (!replaced && sameClause(w, clause)) {
      replaced = true;
      return { ...w, value };
    }
    return w;
  });
}

/** What a viewer typed, as the clause's value.
 *
 * **`in` takes a list and everything else takes a scalar**, which is the one
 * shape decision here: an `in` whose value arrived as a bare string is refused
 * by `object_sets.parse` with a sentence about list operators, so a comma is
 * how a viewer says several. Blank entries are dropped — a trailing comma is a
 * typing artefact, not an empty value to match.
 *
 * Nothing is coerced to a number. The server reads the declared type and the
 * stores compare against it (§220); guessing here would mean a browser deciding
 * that "007" is 7 for a property the ontology calls a string.
 */
export function parseValue(op: string, text: string): unknown {
  if (op !== "in") return text;
  return text.split(",").map((v) => v.trim()).filter(Boolean);
}

/** A value, back in the box a viewer edits it in. The inverse of `parseValue`
 * for the shapes it produces, so an edit round-trips. */
export function editableValue(clause: Clause): string {
  return Array.isArray(clause.value)
    ? clause.value.map((v) => String(v)).join(", ")
    : clause.value === null || clause.value === undefined
      ? ""
      : String(clause.value);
}

/** Whether a clause can be edited in a text box at all.
 *
 * A bounding box cannot (see `GEO_OPERATORS`), so mode `update` shows it as a
 * pill without an editor rather than offering four numbers in one field.
 */
export function isEditable(clause: Clause): boolean {
  return !GEO_OPERATORS.includes(clause.op);
}
