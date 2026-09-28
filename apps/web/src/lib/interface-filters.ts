/**
 * Filtering an interface set from its dialog (§535; `ontology` p.61, §254).
 *
 * `POST /interfaces/{id}/evaluate` has taken filters in the interface's own
 * vocabulary since §254; the dialog did not offer them. This is what it
 * offers: a property the interface declares, an operator that property's type
 * can be asked, and a value, read in that type.
 *
 * **The server owns what is legal.** These are the offered subset of
 * `object_sets.OPERATORS` and `ORDERED_OPERATORS`, with the orderable types
 * restated from `ORDERABLE_TYPES` (a test holds the copy to the original): an
 * ordered comparison on a string is refused there for decision 0006's reason,
 * so it is not offered here.
 */

export const ORDERABLE_TYPES = ["integer", "float", "date", "timestamp"] as const;
const NUMERIC_TYPES = ["integer", "float"];

export const OP_LABELS: Record<string, string> = {
  eq: "is", neq: "is not", starts_with: "starts with",
  gt: "is more than", gte: "is at least", lt: "is less than", lte: "is at most",
};

/** The operators a property of this type is offered. */
export function opsFor(dataType: string | undefined): string[] {
  const ops = ["eq", "neq"];
  if (dataType === "string") ops.push("starts_with");
  if (dataType && (ORDERABLE_TYPES as readonly string[]).includes(dataType)) {
    ops.push("gt", "gte", "lt", "lte");
  }
  return ops;
}

export interface FilterDraft {
  property: string;
  op: string;
  value: string;
}

export function blankFilter(property = ""): FilterDraft {
  return { property, op: "eq", value: "" };
}

/** A draft whose property changed keeps its operator only if the new type
 * can be asked it. */
export function withProperty(draft: FilterDraft, property: string, dataType: string | undefined): FilterDraft {
  return { property, op: opsFor(dataType).includes(draft.op) ? draft.op : "eq", value: draft.value };
}

/** What is wrong with a finished row, or null. An unfinished one (no
 * property or no value yet) is not wrong; it is not sent. */
export function filterProblem(draft: FilterDraft, dataType: string | undefined): string | null {
  if (draft.property === "" || draft.value.trim() === "") return null;
  if (dataType && NUMERIC_TYPES.includes(dataType) && !Number.isFinite(Number(draft.value))) {
    return `${draft.property} is a number, and ${draft.value.trim()} is not one.`;
  }
  if (dataType === "integer" && !Number.isInteger(Number(draft.value))) {
    return `${draft.property} is a whole number, and ${draft.value.trim()} is not one.`;
  }
  if (dataType === "boolean" && !["true", "false"].includes(draft.value)) {
    return `${draft.property} is true or false.`;
  }
  return null;
}

/** The finished, sound rows as the API takes them, each value in its
 * property's type. */
export function filtersPayload(
  drafts: readonly FilterDraft[], types: Readonly<Record<string, string>>,
): { property: string; op: string; value: unknown }[] {
  const out: { property: string; op: string; value: unknown }[] = [];
  for (const draft of drafts) {
    if (draft.property === "" || draft.value.trim() === "") continue;
    const dataType = types[draft.property];
    if (filterProblem(draft, dataType) !== null) continue;
    const text = draft.value.trim();
    const value = dataType && NUMERIC_TYPES.includes(dataType)
      ? Number(text)
      : dataType === "boolean" ? text === "true" : text;
    out.push({ property: draft.property, op: draft.op, value });
  }
  return out;
}
