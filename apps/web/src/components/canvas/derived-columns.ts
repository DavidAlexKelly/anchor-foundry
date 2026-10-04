/**
 * A module's derived properties, per object type (`foundry_workshop` p.168-172).
 *
 * > "Derived properties are defined at the module level and per object type."
 * > (p.168)
 *
 * The arithmetic is `column-math.ts`; this is the declaration around it —
 * which type a property belongs to, what it is called, and p.170's rule about
 * what an expression may reference.
 */

import { MathError, evaluate, parse, references, type Expr } from "./column-math";
import type { Derivation } from "@/lib/types";

/** p.170's Column math: arithmetic over the row's own values. */
export interface ColumnMathColumn {
  /** The name a column list uses, and what an expression elsewhere would
   * reference. Same shape as a property api name, because it stands in one. */
  api_name: string;
  display_name?: string;
  kind: "column_math";
  expression: string;
}

/** p.169's Linked property/aggregation (§605): "Linked property: allows users
 * to derive a single property from a linked object type… Linked aggregation:
 * allows users to aggregate linked properties". The same chain an ontology
 * derived property holds (`object-link-types` p.145-147), held by the module
 * rather than by the type, and answered by the same server read (§604). */
export interface LinkedColumn {
  api_name: string;
  display_name?: string;
  kind: "linked";
  /** Null while being drawn: a column named and not yet built. */
  derivation: Derivation | null;
}

/** Workshop p.221's function-backed column (§770): "a function that takes in
 * the expected input (for example, an object set of Flight Alert objects) and
 * returns the expected map output". The table passes the objects it is showing
 * as `objects_parameter` (p.221's "Use a runtime input"), and the cell is the
 * row's `field` from the map. */
export interface FunctionColumn {
  api_name: string;
  display_name?: string;
  kind: "function";
  function_id: string;
  /** The version called (p.49: a consumer names one). Null calls the newest. */
  version: string | null;
  /** The `object_set` parameter the shown objects go to. */
  objects_parameter: string;
  /** Which of the map's fields this column shows; empty is the first. */
  field: string;
  /** Every other parameter, from a module variable or a fixed value. */
  inputs: Record<string, { variable: string } | { value: unknown }>;
}

/** p.168's two kinds, and p.221's function column. The field was written as a
 * discriminator with one value (§411) so that later kinds need no migration. */
export type DerivedColumn = ColumnMathColumn | LinkedColumn | FunctionColumn;

/** Only what the rules read, so a caller can pass an ontology property row. */
export interface KnownProperty {
  api_name: string;
  data_type?: string | null;
}

/**
 * The declarations for one object type, read defensively (§212).
 *
 * **Refused one at a time here, unlike a rule list.** §405 drops a whole
 * conditional-format list because first-match-wins makes it ordered; these are
 * independent columns, so a broken one is one missing column rather than a
 * different set of them.
 */
export function columnsFor(raw: unknown, objectTypeId: string): DerivedColumn[] {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  const forType = (raw as Record<string, unknown>)[objectTypeId];
  if (!Array.isArray(forType)) return [];
  const out: DerivedColumn[] = [];
  const seen = new Set<string>();
  for (const entry of forType) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    const it = entry as Record<string, unknown>;
    const name = typeof it.api_name === "string" ? it.api_name.trim() : "";
    if (!name) continue;
    const label = typeof it.display_name === "string" && it.display_name
      ? { display_name: it.display_name } : {};
    let column: DerivedColumn;
    if (it.kind === "column_math") {
      const expression = typeof it.expression === "string" ? it.expression : "";
      if (!expression) continue;
      column = { api_name: name, ...label, kind: "column_math", expression };
    } else if (it.kind === "linked") {
      // Only a chain that has at least one link to follow; anything else is a
      // column somebody named and never built, which draws nothing. One check
      // covers every malformed shape - an array, a string or a null has no
      // `links` list - which §605's sweep showed by finding the separate
      // object check could not change the answer.
      const d = it.derivation as { links?: unknown } | null | undefined;
      const links = d?.links;
      if (!Array.isArray(links) || links.length === 0) continue;
      column = { api_name: name, ...label, kind: "linked", derivation: d as Derivation };
    } else if (it.kind === "function") {
      if (typeof it.function_id !== "string" || !it.function_id) continue;
      column = {
        api_name: name,
        ...label,
        kind: "function",
        function_id: it.function_id,
        version: typeof it.version === "string" && it.version ? it.version : null,
        objects_parameter: typeof it.objects_parameter === "string" ? it.objects_parameter : "",
        field: typeof it.field === "string" ? it.field : "",
        inputs: inputsOf(it.inputs),
      };
    } else {
      continue;
    }
    // **A repeat is dropped rather than shadowing.** Two columns with one name
    // is a table where which one you get depends on order, and the second is
    // the one nobody meant.
    if (seen.has(name)) continue;
    seen.add(name);
    out.push(column);
  }
  return out;
}

/** A function column's other inputs, keeping only the two shapes it can use. */
function inputsOf(raw: unknown): FunctionColumn["inputs"] {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: FunctionColumn["inputs"] = {};
  for (const [name, source] of Object.entries(raw as Record<string, unknown>)) {
    if (!source || typeof source !== "object") continue;
    const it = source as Record<string, unknown>;
    if (typeof it.variable === "string" && it.variable) out[name] = { variable: it.variable };
    else if ("value" in it) out[name] = { value: it.value };
  }
  return out;
}

/**
 * Why this expression cannot be used, or `null`.
 *
 * `known` is the object type's own properties. **p.170's restriction is the
 * interesting half**: *"Both the object type's native properties and
 * aggregation type derived properties may be used and referenced. Note that
 * other column math type derived properties may not be used."*
 *
 * So a reference may name a property of the type — including an ontology-level
 * derived one, which is an aggregation and is a property of the type as far as
 * a reader is concerned — and may not name another column-math column. The
 * second half is what stops a chain of expressions, and with it the question
 * of what order to evaluate them in and what a cycle means.
 */
export function problem(
  expression: string,
  known: readonly KnownProperty[],
  others: readonly DerivedColumn[] = [],
): string | null {
  let tree: Expr;
  try {
    tree = parse(expression);
  } catch (error) {
    return error instanceof MathError ? error.message : "this expression cannot be read";
  }
  // p.170: "aggregation type derived properties may be used and referenced"
  // - which a module's linked column is (§605), as an ontology one is.
  const names = new Set([
    ...known.map((p) => p.api_name),
    ...others.filter((c) => c.kind === "linked").map((c) => c.api_name),
  ]);
  const columnMath = new Set(
    others.filter((c) => c.kind === "column_math").map((c) => c.api_name),
  );
  for (const ref of references(tree)) {
    if (columnMath.has(ref)) {
      return `${ref} is another calculated column, and p.170 allows only the `
        + "object type's own properties here";
    }
    if (!names.has(ref)) return `this object type has no property called ${ref}`;
  }
  if (!references(tree).length) {
    // p.170 is "combine values from multiple properties". An expression with
    // none is a constant, which is a column of the same number on every row -
    // legal arithmetic and not a derived property.
    return "this needs at least one property to calculate from";
  }
  return null;
}

/** One row's value for one column, or `null`. Parsed per call and not cached:
 * a table page is twenty-five rows and the expression is a dozen tokens, and a
 * cache keyed on a string is a second place for the answer to live. */
export function valueFor(
  column: ColumnMathColumn,
  properties: Record<string, unknown>,
): number | null {
  try {
    return evaluate(parse(column.expression), properties);
  } catch {
    // A document can hold an expression this build cannot read (§212). A
    // column of blanks is the honest answer; the panel is where the sentence
    // belongs, because that is where somebody can act on it.
    return null;
  }
}

/**
 * What a table has to ask the server for, to draw the columns it shows (§605).
 *
 * Two kinds of value are not on a list read's rows: an ontology derived
 * property (by name) and a module's linked column (by its derivation). A table
 * needs each one it **shows**, and each one a column-math column it shows
 * **references** - p.170 lets an expression use an aggregation, and an
 * expression over a value the table never fetched is a column of blanks that
 * looks like data.
 */
export function derivedInputs(
  shown: readonly string[],
  properties: readonly { api_name: string; derivation?: unknown }[],
  columns: readonly DerivedColumn[],
): { properties: string[]; derivations: Record<string, Derivation> } {
  const wanted = new Set(shown);
  for (const column of columns) {
    if (column.kind !== "column_math" || !wanted.has(column.api_name)) continue;
    try {
      for (const ref of references(parse(column.expression))) wanted.add(ref);
    } catch {
      // An expression this build cannot read references nothing it can use.
    }
  }
  const derivations: Record<string, Derivation> = {};
  for (const column of columns) {
    if (column.kind === "linked" && column.derivation && wanted.has(column.api_name)) {
      derivations[column.api_name] = column.derivation;
    }
  }
  return {
    properties: properties
      .filter((p) => !!p.derivation && wanted.has(p.api_name))
      .map((p) => p.api_name),
    derivations,
  };
}

/** A linked column's chain in a phrase, for the panel's row: what it
 * aggregates and how far it walks. */
export function linkedSummary(derivation: Derivation | null): string {
  if (!derivation) return "not built yet";
  const hops = derivation.links?.length ?? 0;
  const walk = `over ${hops} link${hops === 1 ? "" : "s"}`;
  const what = derivation.aggregate
    ? derivation.property
      ? `${derivation.aggregate} of ${derivation.property}`
      : derivation.aggregate
    : derivation.property ?? "a value";
  return `${what} ${walk}`;
}
