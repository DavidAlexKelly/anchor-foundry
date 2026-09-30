"use client";

/**
 * One derived property's cell in a table (§604; `object-link-types` p.143):
 * pending while the page is answered, a dash when the column could not be (the
 * table says why once, above it), and otherwise the value, drawn the way any
 * property's value is. `lib/derived-values.ts` decides which.
 */
import { PropertyValue } from "@/components/property-value";
import { plainValue, type DerivedCell } from "@/lib/derived-values";
import type { ObjectTypeProperty } from "@/lib/types";

export function DerivedValue({
  workspaceId,
  property,
  cell,
  emptyText,
  testId,
}: {
  workspaceId: string;
  /** Absent for a module's linked column, which has no property row to be
   * formatted by and is shown plainly (§605). */
  property?: ObjectTypeProperty;
  cell: DerivedCell;
  emptyText?: string;
  testId: string;
}) {
  if (cell.state === "pending") {
    return <span className="count" data-testid={testId} data-state="pending">…</span>;
  }
  if (cell.state === "error") {
    return (
      <span className="count" data-testid={testId} data-state="error" title={cell.reason}>
        —
      </span>
    );
  }
  if (!property) {
    const text = plainValue(cell.value);
    return (
      <span data-testid={testId} data-state="value" className={text === null ? "soft" : undefined}>
        {text ?? emptyText}
      </span>
    );
  }
  return (
    <span data-testid={testId} data-state="value">
      <PropertyValue
        workspaceId={workspaceId}
        dataType={property.data_type}
        valueFormat={property.value_format}
        structFields={property.struct_fields}
        value={cell.value as never}
        emptyText={emptyText}
      />
    </span>
  );
}
