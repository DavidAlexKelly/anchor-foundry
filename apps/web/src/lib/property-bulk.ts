/**
 * p.91's bulk edit of an object type's properties (§672; `object-link-types`
 * p.91).
 *
 * > "You can select multiple properties in the property editor by holding the
 * > Cmd/Ctrl key while selecting properties. Once multiple properties are
 * > selected, the following bulk editing actions become available: Changing
 * > base type. Adding/removing of type classes. Changing render hints.
 * > Changing visibility. Adding/removing value formatting." (p.91)
 *
 * Each is the edit one row's control makes, made on every selected row, so a
 * bulk edit can say nothing a row could not. **A shared property's inherited
 * metadata is left alone** - its base type, visibility and formatting are its
 * shared property's (p.188), and the row's own controls are disabled for the
 * same reason - and how many were left is said.
 */

import type { PropertyDataType, PropertyVisibility, ValueFormat } from "./types";
import { withDataType } from "./array-property";

export type BulkChange =
  | { kind: "data_type"; value: PropertyDataType }
  | { kind: "visibility"; value: PropertyVisibility }
  | { kind: "add_class"; value: string }
  | { kind: "remove_class"; value: string }
  | { kind: "value_format"; value: ValueFormat | null };

type Row = {
  data_type: PropertyDataType;
  array_of?: PropertyDataType | null;
  visibility?: PropertyVisibility;
  value_format?: ValueFormat | null;
  type_classes?: string[];
  shared_property_id?: string | null;
};

/** What a shared property holds for its users, and a bulk edit leaves. */
const INHERITED: BulkChange["kind"][] = ["data_type", "visibility", "value_format"];

/** The rows with the change made on each selected one, and how many selected
 * rows were left because a shared property holds that setting. */
export function bulkApply<T extends Row>(
  rows: readonly T[], selected: ReadonlySet<number>, change: BulkChange,
): { rows: T[]; skipped: number } {
  let skipped = 0;
  const out = rows.map((row, index) => {
    if (!selected.has(index)) return row;
    if (row.shared_property_id && INHERITED.includes(change.kind)) {
      skipped += 1;
      return row;
    }
    switch (change.kind) {
      case "data_type":
        return withDataType(row, change.value);
      case "visibility":
        return { ...row, visibility: change.value };
      case "add_class": {
        const classes = row.type_classes ?? [];
        return classes.includes(change.value) ? row : { ...row, type_classes: [...classes, change.value] };
      }
      case "remove_class":
        return { ...row, type_classes: (row.type_classes ?? []).filter((c) => c !== change.value) };
      case "value_format":
        return { ...row, value_format: change.value };
    }
  });
  return { rows: out, skipped };
}

/** The type classes any selected row has, for Remove to offer. */
export function classesIn(rows: readonly Row[], selected: ReadonlySet<number>): string[] {
  return [...new Set(rows.flatMap((row, index) => (selected.has(index) ? row.type_classes ?? [] : [])))].sort();
}

/** The one base type every selected row shares, which a formatter is written
 * for; null when they differ. */
export function sharedDataType(rows: readonly Row[], selected: ReadonlySet<number>): PropertyDataType | null {
  const types = new Set(rows.filter((_, index) => selected.has(index)).map((row) => row.data_type));
  return types.size === 1 ? [...types][0]! : null;
}

/** The selection with one row's membership flipped. */
export function toggled(selected: ReadonlySet<number>, index: number): Set<number> {
  const next = new Set(selected);
  if (next.has(index)) next.delete(index);
  else next.add(index);
  return next;
}
