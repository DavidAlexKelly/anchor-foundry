"use client";

/**
 * An array property drawn as its reducer says (Foundry `object-link-types`
 * p.131 **[Beta]**; db 0088).
 *
 * > "For example, applying a reducer to an array with multiple inspection
 * > dates allows you to **display only the most recent date when viewing the
 * > property in a table or application** but ensures the full array remains
 * > accessible for queries and other operations. Applications that support
 * > reducers, such as Workshop, also enable you to **view the complete array
 * > on hover** or in expanded views." (p.131)
 *
 * **Both halves of that sentence, because one without the other is a lie.** A
 * cell showing one date and nothing else reads as a property that holds one
 * date — which is the opposite of what p.131 says reduction does to the stored
 * value. So the count says how many there are and the hover says what they
 * are, and the reduced value is the only part that is large.
 *
 * **Its own component rather than a fourth prop on `PropertyValue`.** That
 * file's docstring names the threshold: it already threads three per-property
 * declarations through, and says the next one should collapse the three into a
 * single `property` prop instead of joining them. This is not that refactor,
 * and it does not need to be — a reduced value is a *value*, not a
 * declaration, so what goes to `PropertyValue` is the element and the element
 * type, which is an argument it already takes.
 *
 * That last point is worth saying plainly: the element renders **typed**. A
 * reduced date is drawn as a date, where the same date inside the array is
 * drawn as its ISO string — because an array's elements have nowhere to get a
 * type from and a reduced one does (`array_of`, db 0087). The limitation is
 * still there on the un-reduced list, and it is still lifted by the same
 * refactor rather than by a special case here.
 */

import { PropertyValue } from "@/components/property-value";
import type {
  ObjectInstance, ObjectTypeProperty, PropertyStyle,
} from "@/lib/types";

export function ReducedValue({
  workspaceId,
  property,
  instance,
  style,
}: {
  workspaceId: string;
  property: ObjectTypeProperty;
  instance: ObjectInstance;
  style?: PropertyStyle | null;
}) {
  const whole = instance.properties[property.api_name];
  const reduced = instance.reduced?.[property.api_name];

  // **Absent, not null, is the question** — `reduce_all` leaves out a property
  // it has no answer for, so `undefined` covers both "no reducer declared" and
  // "an array of structs where nobody filled the field in". Either way the
  // honest thing to draw is the list itself.
  if (reduced === undefined) {
    return (
      <PropertyValue
        workspaceId={workspaceId}
        dataType={property.data_type}
        valueFormat={property.value_format}
        structFields={property.struct_fields}
        style={style}
        value={whole}
      />
    );
  }

  const held = Array.isArray(whole) ? whole.length : 0;
  return (
    <span
      className="reduced-value"
      data-testid="reduced-value"
      style={style ?? undefined}
    >
      <PropertyValue
        workspaceId={workspaceId}
        // The **element's** type, which is the whole reason this reads better
        // than the list does: `array_of` is what an array's own elements have
        // no way to reach (db 0087).
        dataType={property.array_of ?? undefined}
        valueFormat={property.value_format}
        structFields={property.struct_fields}
        value={reduced}
      />
      {held > 1 && (
        // p.131's "view the complete array on hover", and the count that makes
        // somebody hover. `title` rather than a popover: the whole list is
        // already one request away in `properties`, and a cell in a table is
        // not where a second interactive surface belongs.
        <span
          className="slug"
          style={{ marginLeft: 6 }}
          title={JSON.stringify(whole)}
          data-testid="reduced-count"
        >
          of {held}
        </span>
      )}
    </span>
  );
}
