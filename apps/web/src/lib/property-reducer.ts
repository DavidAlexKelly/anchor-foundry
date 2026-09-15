/**
 * Declaring a property reducer in the editor (§349; Foundry
 * `object-link-types` p.131–133 **[Beta]**; db 0088).
 *
 * > "Reducers work with array properties containing numeric, temporal, string,
 * > and boolean base types. You can reduce struct arrays based on any struct
 * > field that uses a supported base type." (p.131)
 *
 * **The server owns every refusal here** — `services/property_reducers.py` is
 * what decides whether a declaration may be stored, and this file does not get
 * a vote. What it does is answer the questions *early*, where the answer can
 * still be changed: `struct-fields.ts` makes the same split two types over,
 * and `STATUS.md` keeps writing the same sentence about panels — the server
 * owns what is *legal*, the panel owns what to *offer*.
 *
 * **The vocabulary is per category, and that is the thing to get right here
 * rather than clever about.** p.132 gives numbers highest/lowest, dates
 * latest/earliest, strings first/last and booleans true-first/false-first, and
 * a dialog offering one max/min pair over everything would let somebody ask a
 * string array for its "latest" — which is a different question from its last,
 * and the server refuses it with a sentence saying so. So the operations a row
 * offers are read off the base type being reduced, which for a struct array is
 * the *field's* rather than the element's (p.133).
 *
 * Pure, and in `lib/` rather than beside the component, because vitest cannot
 * parse `.tsx`: a rule that lives in a component is a rule with no unit test.
 */

import type {
  ObjectTypeProperty, PropertyDataType, PropertyReducer, StructField,
} from "@/lib/types";

/**
 * p.132's supported table: which operations each base type takes, in p.132's
 * order.
 *
 * **A mirror of `property_reducers.OPERATIONS` on the server, and mirrors go
 * stale** (§191) — so `test_property_reducers.py` scans this file and compares
 * the two against the *server's* table, which is the direction that catches an
 * addition rather than only a disagreement.
 *
 * Nothing is left out here, unlike `array-property.ts`'s `ELEMENT_TYPES`: an
 * operation is a word in a dropdown, so there is no version of one this dialog
 * cannot complete.
 */
export const OPERATIONS: Record<string, string[]> = {
  integer: ["highest", "lowest"],
  float: ["highest", "lowest"],
  date: ["latest", "earliest"],
  timestamp: ["latest", "earliest"],
  string: ["first", "last"],
  boolean: ["true_first", "false_first"],
};

/**
 * What each operation reads as, in p.132's own words rather than the API's.
 *
 * p.132 writes "Most recent (latest), Least recent (earliest)" and "First,
 * last (lexicographically)" — so the parenthetical belongs on the string pair,
 * where it says *which* order, and the API name is what carries "latest".
 * Somebody choosing between two options in a dropdown is choosing between
 * these words, not between the stored ones.
 */
export const OPERATION_LABELS: Record<string, string> = {
  highest: "Highest",
  lowest: "Lowest",
  latest: "Most recent",
  earliest: "Least recent",
  first: "First (lexicographically)",
  last: "Last (lexicographically)",
  true_first: "True first",
  false_first: "False first",
};

type Row = Pick<ObjectTypeProperty, "data_type"> & {
  array_of?: PropertyDataType | null;
  struct_fields?: StructField[] | null;
  reducers?: PropertyReducer[] | null;
};

/** Whether this base type can be reduced at all (p.132's two tables). */
export function reducible(base: string | null | undefined): boolean {
  return !!base && base in OPERATIONS;
}

/**
 * The struct fields this property can be reduced by — p.133's "you can only
 * reduce by struct fields that use one of the supported base types".
 *
 * Empty for anything that is not an array of structs, which is what makes the
 * one call site read as a question about *this* row rather than about its
 * type: a field list with nothing in it is a property with nothing to reduce
 * by, whichever of the two reasons it has.
 */
export function reducibleFields(property: Row): StructField[] {
  if (property.data_type !== "array" || property.array_of !== "struct") return [];
  return (property.struct_fields ?? []).filter((f) => reducible(f.data_type));
}

/**
 * Whether to offer this property a reducer at all.
 *
 * **§214's rule, and the same gate `needsFields` applies one button over.** An
 * array of geopoints has no operation p.132 gives it, and an array of structs
 * whose every field is a geopoint has nothing to reduce *by* — in both cases a
 * Reduce button would open a dialog whose only outcome is a refusal, which is
 * worse than no button. The property dropdown makes the same judgement about
 * `attachment`, and §245 made it about `struct` before there was a dialog to
 * finish one.
 */
export function canReduce(property: Row): boolean {
  if (property.data_type !== "array") return false;
  if (property.array_of === "struct") return reducibleFields(property).length > 0;
  return reducible(property.array_of);
}

/** The base type one reducer's operations come from: the struct field's for an
 * array of structs (p.133), and the element's for everything else. */
export function basisOf(property: Row, reducer: PropertyReducer): string | null {
  if (property.array_of !== "struct") return property.array_of ?? null;
  if (!reducer.field) return null;
  const field = (property.struct_fields ?? []).find(
    (f) => f.api_name === reducer.field,
  );
  return field ? field.data_type : null;
}

/** What this row may be set to, or `[]` when its basis has no operations —
 * which is a stored declaration naming a field that has since been retyped,
 * not something `canReduce` lets somebody reach. */
export function operationsFor(property: Row, reducer: PropertyReducer): string[] {
  return OPERATIONS[basisOf(property, reducer) ?? ""] ?? [];
}

/**
 * A new row, already answered.
 *
 * **Seeded rather than empty**, which is `DEFAULT_ELEMENT`'s argument one
 * dialog over: an unanswered select is a declaration the server refuses, and
 * the reader has to notice a second control to fix it. For a struct array that
 * means the first field nothing has claimed yet — p.133's whole reason for a
 * list is reducing by *different* fields, so the row that would immediately be
 * refused as a duplicate is not the one to open on.
 *
 * When every reducible field is already claimed it falls back to the first
 * one, and `problem` then says the row is a duplicate. That is deliberate: a
 * named row with a complaint about it is something to change, and a row with
 * no field is a control somebody has to discover.
 */
export function blankReducer(property: Row, existing: PropertyReducer[]): PropertyReducer {
  if (property.array_of === "struct") {
    const taken = new Set(existing.map((r) => r.field));
    const field = reducibleFields(property).find((f) => !taken.has(f.api_name));
    const named = field ?? reducibleFields(property)[0];
    // `named` is only ever missing on a property `canReduce` refuses, which is
    // a property with no button — so this is the total-function branch rather
    // than a state the dialog can be in.
    const ops = named ? OPERATIONS[named.data_type] ?? [] : [];
    return {
      operation: ops[0] ?? "",
      field: named ? named.api_name : null,
    };
  }
  const ops = OPERATIONS[property.array_of ?? ""] ?? [];
  return { operation: ops[0] ?? "", field: null };
}

/** One row with its field changed, and its operation made to agree.
 *
 * **Both halves, because the operations are the field's** (p.133): moving a
 * reducer from a date field to an integer one leaves `latest` naming something
 * an integer cannot do, and the server refuses that with a message about an
 * operation the dropdown is no longer showing. `withDataType` in
 * `array-property.ts` is the same shape one declaration up. */
export function withField(
  property: Row, reducer: PropertyReducer, field: string,
): PropertyReducer {
  const next = { ...reducer, field };
  const ops = operationsFor(property, next);
  return ops.includes(next.operation)
    ? next
    : { ...next, operation: ops[0] ?? "" };
}

/**
 * Why this declaration cannot be saved yet, or `null`.
 *
 * One sentence at a time and the first one only — `struct-fields.problem`'s
 * rule, for its reason: a list of every complaint about a half-filled form is
 * a list somebody has to read to find the one they have already fixed.
 *
 * An empty list is **not** a problem: p.131 makes reduction optional, and a
 * property that declares none is an ordinary array. That is the dialog's way
 * of removing them.
 */
export function problem(
  property: Row, reducers: PropertyReducer[],
): string | null {
  const seen = new Set<string>();
  for (const [index, reducer] of reducers.entries()) {
    const where = `Reducer ${index + 1}`;
    if (property.array_of === "struct" && !reducer.field) {
      return `${where} needs a struct field to reduce by — a struct array reduces by a field, not by the struct.`;
    }
    const basis = basisOf(property, reducer);
    const allowed = basis ? OPERATIONS[basis] : undefined;
    if (!allowed) {
      return reducer.field
        ? `${where} reduces by ${reducer.field}, which cannot be ordered.`
        : `${where} has nothing to reduce: an array of ${property.array_of} has no reducer operations.`;
    }
    if (!allowed.includes(reducer.operation)) {
      return `${where} is not something you can do to ${basis} values.`;
    }
    // p.133 gives a second reducer exactly one job — breaking the tie the one
    // before it left — and two values tied on a basis are tied on it whichever
    // operation asks. So a repeated basis is refused here as it is on the
    // server, rather than saved and handed back as a 422.
    const basisKey = reducer.field ?? "";
    if (seen.has(basisKey)) {
      return reducer.field
        ? `Two reducers both reduce by ${reducer.field}, so the second cannot break a tie the first one left.`
        : `An array of ${property.array_of} has one thing to reduce by, so a second reducer cannot break a tie.`;
    }
    seen.add(basisKey);
  }
  return null;
}

/**
 * The base type this property presents to an interface (§350; p.131–132).
 *
 * > "A property reducer enables you to transform an array property into a
 * > single value in the array for display and **interface implementation
 * > purposes**." (p.131)
 *
 * **The element type, because reduction answers with an element** — p.131's
 * words are "a single value *in* the array", so a reduced list of dates is a
 * date. An array with no reducer presents as `array`, which satisfies no
 * interface property and is p.132's sentence rather than a fallback.
 *
 * A mirror of `property_reducers.implements_as` on the server, which is the
 * one that refuses; this is what lets the mapping dialog *offer* the property
 * before anybody waits for the refusal. Every non-array answers with its own
 * base type, so callers can put it in front of every property rather than
 * branching first.
 */
export function implementsAs(property: Row): string {
  if (property.data_type !== "array" || !property.reducers?.length) {
    return property.data_type;
  }
  // No fallback, for the reason the server's has none: db 0087's pairing means
  // an array always says what of, so `?? property.data_type` was a branch
  // nothing could make fail — an adversarial sweep is what found it (§213).
  return property.array_of ?? "";
}

/** What a row's button says: the count, because a property with reducers and
 * one without are different declarations and the difference should be legible
 * without opening anything. */
export function reducerSummary(property: Row): string {
  const held = property.reducers ?? [];
  return held.length ? ` (${held.length})` : "";
}
