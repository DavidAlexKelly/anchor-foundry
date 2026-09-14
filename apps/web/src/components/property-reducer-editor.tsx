"use client";

/**
 * Declaring a property reducer (Foundry `object-link-types` p.131–133
 * **[Beta]**; db 0088).
 *
 * > "1. Navigate to Ontology Manager. … 3. Select the array property to
 * > configure from your object type's Properties tab. 4. Choose the
 * > **Interaction** tab in the property editor panel that opens on the right.
 * > 5. Scroll to the **Reduce array** section." (p.133)
 *
 * **This is what makes §348's column declarable by a person.** That unit built
 * the whole read path — the declaration, the refusals, the reduction, the
 * value beside the array on two reads — and deliberately left it reachable
 * only through the API, on §346's precedent: a control that cannot complete a
 * declaration is worse than no control (§214). This dialog is the control.
 *
 * **A dialog rather than a third select on the row, unlike the element type.**
 * §347 put `array_of` beside the base type because it is *one more choice* and
 * the two read as one sentence ("a list of dates"). A reducer is not one
 * choice: p.133 makes it an ordered list whose rows have two controls each,
 * and Foundry gives it a *section* of its own rather than a field. So this
 * follows `StructFieldsEditor`, which is the same shape for the same reason —
 * and its layout decisions are inherited deliberately, including the one about
 * where the Add button goes.
 *
 * **p.133's placement is not reproducible here and the difference is
 * structural.** Foundry edits a property in a panel with tabs (Overview,
 * Interaction, …); this platform edits a property as a *row*, which is why
 * every other per-property declaration — fields, formatting, value type — is
 * already a button on that row rather than a tab. A "Reduce array" section
 * inside an Interaction tab would mean building the panel first, and that is a
 * change to how every property is edited rather than to this one.
 *
 * Every refusal here is the server's, answered early — see `lib/property-
 * reducer` for why that split rather than a browser-side copy of the rules.
 */

import { useState } from "react";
import { Dialog } from "@/components/dialog";
import {
  OPERATION_LABELS, blankReducer, operationsFor, problem, reducibleFields,
  withField,
} from "@/lib/property-reducer";
import type { ObjectTypeProperty, PropertyReducer } from "@/lib/types";

export function PropertyReducerEditor({
  open,
  onClose,
  propertyName,
  property,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  propertyName: string;
  /** The row being edited — the *whole* property, because every question this
   * dialog asks is about `array_of` and `struct_fields` as well as about the
   * reducers themselves (p.133). */
  property: ObjectTypeProperty;
  /** The list as it stands, empty included — see the Apply button for why
   * there is no `null` here to mean "none". */
  onSave: (next: PropertyReducer[]) => void;
}) {
  // Copied on mount for `StructFieldsEditor`'s reason: this is a draft, and
  // Cancel has to leave the row as it was.
  const [reducers, setReducers] = useState<PropertyReducer[]>(
    // **Opens empty when there are none**, unlike the struct dialog, because
    // the two defaults answer different questions. A struct with no fields is
    // a declaration p.149 refuses, so that dialog opens on a row; reduction is
    // optional (p.131), so opening on a row would mean arriving having already
    // declared something nobody asked for — and Cancel would be the only way
    // out that did not change the property.
    (property.reducers ?? []).map((r) => ({ ...r })),
  );

  const fields = reducibleFields(property);
  const byStruct = property.array_of === "struct";
  // Functional updates throughout — `StructFieldsEditor` learned why the hard
  // way: a handler closing over `reducers` reads the render it was made in, so
  // two removals faster than two renders apply the first one twice.
  const patch = (index: number, next: PropertyReducer) =>
    setReducers((current) => current.map((r, i) => (i === index ? next : r)));

  const missing = problem(property, reducers);

  return (
    <Dialog open={open} wide title={`Reduce array · ${propertyName}`} onClose={onClose}>
      <p className="field-hint">
        Which one value of this list to show in a table (p.131). Reduction is
        read-time only — the whole list is still stored, still queried and still
        what an action writes.
        {byStruct && " A struct array reduces by a field, not by the struct (p.133)."}
      </p>

      {/* Above the list for `StructFieldsEditor`'s reason, which was a real
          bug rather than a preference: a button under a shrinking list slides
          into the position the ✕ that shrank it just occupied. */}
      <button
        type="button"
        className="btn"
        style={{ marginBottom: 8 }}
        data-testid="reducer-add"
        onClick={() =>
          setReducers((current) => [...current, blankReducer(property, current)])
        }
      >
        Add reducer
      </button>

      <table className="table" data-testid="reducer-rows">
        <thead>
          <tr>
            <th aria-label="Order" />
            {byStruct && <th>Field</th>}
            <th>Take the</th>
            <th aria-label="Remove" />
          </tr>
        </thead>
        <tbody>
          {reducers.map((reducer, index) => (
            <tr key={index} data-reducer={reducer.field ?? ""}>
              {/* p.133's tie-breaking made legible: the first row picks and
                  the ones after it break the ties it leaves, which is a fact
                  about *order* that a list of identical rows does not say. */}
              <td className="field-hint" style={{ whiteSpace: "nowrap" }}>
                {index === 0 ? "First" : `then ${index + 1}`}
              </td>
              {byStruct && (
                <td>
                  <select
                    aria-label={`Reducer ${index + 1} field`}
                    value={reducer.field ?? ""}
                    onChange={(e) =>
                      patch(index, withField(property, reducer, e.target.value))
                    }
                  >
                    {fields.map((f) => (
                      <option key={f.api_name} value={f.api_name}>
                        {f.display_name || f.api_name}
                      </option>
                    ))}
                  </select>
                </td>
              )}
              <td>
                <select
                  aria-label={`Reducer ${index + 1} operation`}
                  value={reducer.operation}
                  onChange={(e) =>
                    patch(index, { ...reducer, operation: e.target.value })
                  }
                >
                  {operationsFor(property, reducer).map((op) => (
                    <option key={op} value={op}>{OPERATION_LABELS[op] ?? op}</option>
                  ))}
                </select>
              </td>
              <td>
                <button
                  type="button"
                  className="btn"
                  style={{ padding: "3px 9px", fontSize: 12 }}
                  aria-label={`Remove reducer ${index + 1}`}
                  onClick={() =>
                    setReducers((current) => current.filter((_, i) => i !== index))
                  }
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
          {reducers.length === 0 && (
            <tr data-testid="reducer-none">
              <td colSpan={byStruct ? 4 : 3} className="field-hint">
                No reducer. This property reads as the whole list.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {missing && (
        <p className="field-hint" data-testid="reducer-problem">{missing}</p>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          disabled={missing !== null}
          data-testid="reducer-save"
          onClick={() => {
            // **This used to send `null` for an empty list, and that was a
            // guard nothing could make fail** (§213). The reasoning written
            // beside it claimed `[]` would "make every later comparison read a
            // change that is not one" — and the same sentence said the server
            // normalises `[]` to NULL, which is exactly why it cannot: db
            // 0088's column holds one value for both, `property_reducers.parse`
            // turns `[]` into `None` before anything is written, and no
            // comparison in the platform ever sees the difference. A sweep
            // replacing the conditional with this line survived, which is the
            // shape of a claim that was written down rather than measured.
            //
            // So the conditional is gone and the reason stands in its place.
            // Removing every row still stops a property reducing; the server
            // is what makes that true, and one answer to the question is
            // better than two that agree.
            onSave(reducers);
            onClose();
          }}
        >
          Apply
        </button>
      </div>
    </Dialog>
  );
}
