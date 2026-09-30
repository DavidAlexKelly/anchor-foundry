"use client";

/**
 * One derived property's cell in a table (§604; `object-link-types` p.143):
 * pending while the page is answered, a dash when the column could not be (the
 * table says why once, above it), and otherwise the value, drawn the way any
 * property's value is. `lib/derived-values.ts` decides which.
 */
import { PropertyValue } from "@/components/property-value";
import type { DerivedCell } from "@/lib/derived-values";
import type { ObjectTypeProperty } from "@/lib/types";

export function DerivedValue({
  workspaceId,
  property,
  cell,
  emptyText,
  testId,
}: {
  workspaceId: string;
  property: ObjectTypeProperty;
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
