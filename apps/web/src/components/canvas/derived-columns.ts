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

export interface DerivedColumn {
  /** The name a column list uses, and what an expression elsewhere would
   * reference. Same shape as a property api name, because it stands in one. */
  api_name: string;
  display_name?: string;
  /** p.170's kind. Only one is built; the field is here because p.169's is the
   * other, and a document that has to be migrated to gain a discriminator is
   * a document that was written without one. */
  kind: "column_math";
  expression: string;
}

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
    const expression = typeof it.expression === "string" ? it.expression : "";
    if (!name || !expression || it.kind !== "column_math") continue;
    // **A repeat is dropped rather than shadowing.** Two columns with one name
    // is a table where which one you get depends on order, and the second is
    // the one nobody meant.
    if (seen.has(name)) continue;
    seen.add(name);
    out.push({
      api_name: name,
      ...(typeof it.display_name === "string" && it.display_name
        ? { display_name: it.display_name } : {}),
      kind: "column_math",
      expression,
    });
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
  const names = new Set(known.map((p) => p.api_name));
  const columnMath = new Set(others.map((c) => c.api_name));
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
  column: DerivedColumn,
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
