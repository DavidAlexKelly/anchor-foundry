"use client";

/**
 * Declaring a struct property's fields (Foundry `object-link-types`
 * p.152–158; db 0064).
 *
 * > "In the Property editor panel, add a name and description, and select
 * > **Struct** from the Base type dropdown." … "In the **Struct fields**
 * > section, select **Add field**, then **New field**." … "Name the new struct
 * > field and optionally add a description." (p.152–155)
 *
 * **This is what makes the type declarable by a person.** §245 built the
 * `struct` type and deliberately kept it off the property-type dropdown, on
 * §214's rule: choosing it there would have produced a property the server
 * refuses, because the dropdown is not the whole declaration. This dialog is
 * the rest of the declaration, and the type joins the list in the same commit.
 *
 * **Two of p.152–160's steps are deliberately absent, and they are the same
 * one twice.** p.153's *Backing column* and p.155's step 7 — "map a column
 * from a datasource to the new struct field" — with p.160's *Automap all* on
 * top, are a **mapping** feature: they say where a field's value comes from.
 * This platform maps a struct the way p.149's own first sentence describes,
 * from one "struct type dataset column", which `column_mappings` already
 * expresses. Per-field mapping is a second way for the same value to arrive,
 * and building it before anybody has asked would be inventing the harder half
 * of a feature to avoid stating that the simpler half is what exists.
 *
 * Every refusal here is the server's, answered early — see `lib/struct-fields`
 * for why that split rather than a browser-side copy of the rules.
 */

import { useState } from "react";
import { Dialog } from "@/components/dialog";
import {
  FIELD_TYPES,
  blankField,
  problem,
  renamedFields,
  toFieldApiName,
} from "@/lib/struct-fields";
import type { PropertyDataType, StructField } from "@/lib/types";

export function StructFieldsEditor({
  open,
  onClose,
  propertyName,
  value,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  propertyName: string;
  value: StructField[] | null | undefined;
  onSave: (next: StructField[]) => void;
}) {
  // **Seeded once, from what was open when the dialog mounted.** `value` is
  // also what `renamed` compares against, and re-reading it on every render
  // would compare the draft with itself — the warning would never appear.
  const [saved] = useState<StructField[]>(value ?? []);
  const [fields, setFields] = useState<StructField[]>(
    // p.149 requires at least one field, so a struct being declared for the
    // first time opens on a row rather than on an empty list and a button. The
    // first thing to do is name a field; making somebody click Add to find
    // that out is a step that teaches nothing.
    value && value.length > 0 ? value.map((f) => ({ ...f })) : [blankField()],
  );

  // **Functional, every one of them, and the removal is why.** A handler that
  // closes over `fields` is reading the render it was created in, and React
  // re-renders asynchronously — so three ✕ clicks faster than three renders
  // apply the first twice and lose one row's worth of the edit. A browser test
  // that removed three rows and found one left is what turned this up; typing
  // quickly into two boxes is the same fault with a less visible symptom.
  const patch = (index: number, next: Partial<StructField>) =>
    setFields((current) =>
      current.map((f, i) => (i === index ? { ...f, ...next } : f)),
    );

  const missing = problem(fields);
  const renamed = renamedFields(saved, fields);

  return (
    <Dialog open={open} wide title={`Struct fields · ${propertyName}`} onClose={onClose}>
      <p className="field-hint">
        What this property holds. A struct has a depth of one — a field cannot
        itself be a struct (p.149) — and the order below is the order the value
        is stored and shown in.
      </p>

      {/* **Above the list, not below it, and that is a fix rather than a
          preference.** Removing a field shrinks the table, so a button under
          it slides upward — by exactly one row, into the position the ✕ that
          did the removing just occupied. A click at that position then lands
          here and puts a blank field back. A browser test emptying a
          three-field struct found three removals and *one add* from three
          clicks; `dispatch_event` on the same buttons emptied it cleanly,
          which is what identified the cause as the pointer rather than the
          state. Nothing above a shrinking list moves. */}
      <button
        type="button"
        className="btn"
        style={{ marginBottom: 8 }}
        data-testid="struct-add-field"
        onClick={() => setFields((current) => [...current, blankField()])}
      >
        Add field
      </button>

      <table className="table" data-testid="struct-field-rows">
        <thead>
          <tr>
            <th>Name</th><th>Label</th><th>Type</th><th>Description</th>
            <th aria-label="Remove" />
          </tr>
        </thead>
        <tbody>
          {fields.map((field, index) => (
            <tr key={index} data-struct-field={field.api_name}>
              <td>
                <input
                  type="text"
                  placeholder="field_name"
                  aria-label={`Field ${index + 1} name`}
                  style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, width: 150 }}
                  value={field.api_name}
                  onChange={(e) =>
                    patch(index, { api_name: toFieldApiName(e.target.value) })
                  }
                />
              </td>
              <td>
                <input
                  type="text"
                  placeholder={field.api_name || "Optional"}
                  aria-label={`Field ${index + 1} label`}
                  value={field.display_name}
                  onChange={(e) => patch(index, { display_name: e.target.value })}
                />
              </td>
              <td>
                <select
                  aria-label={`Field ${index + 1} type`}
                  value={field.data_type}
                  onChange={(e) =>
                    patch(index, { data_type: e.target.value as PropertyDataType })
                  }
                >
                  {FIELD_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </td>
              <td>
                <input
                  type="text"
                  placeholder="Optional"
                  aria-label={`Field ${index + 1} description`}
                  value={field.description}
                  onChange={(e) => patch(index, { description: e.target.value })}
                />
              </td>
              <td>
                <button
                  type="button"
                  className="btn"
                  style={{ padding: "3px 9px", fontSize: 12 }}
                  aria-label={`Remove field ${index + 1}`}
                  onClick={() =>
                    setFields((current) => current.filter((_, i) => i !== index))
                  }
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
          {fields.length === 0 && (
            <tr data-testid="struct-no-fields">
              <td colSpan={5} className="field-hint">
                No fields yet. A struct needs at least one (p.149).
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* p.158's warning, in this platform's terms. Foundry's is about a RID
          being regenerated; here a stored value is a mapping keyed by field
          name, so a rename leaves every instance holding the old key until the
          next sync. Naming the *fix* is what makes it a warning rather than a
          scolding. */}
      {renamed.length > 0 && (
        <p className="state warn" data-testid="struct-rename-warning">
          Renaming {renamed.map((n) => `"${n}"`).join(", ")} leaves existing
          objects holding the old field name until this type&rsquo;s source is
          synced again, and anything referencing the old name has to be updated
          (p.158).
        </p>
      )}

      {missing && (
        <p className="field-hint" data-testid="struct-problem">{missing}</p>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          disabled={missing !== null}
          data-testid="struct-save"
          onClick={() => {
            // Trimmed on the way out rather than on the way in, so a name can
            // still be typed with a stray space and fixed without the box
            // fighting the cursor. `problem` has already read it the same way.
            onSave(
              fields.map((f) => ({
                ...f,
                api_name: f.api_name.trim(),
                display_name: f.display_name.trim(),
                description: f.description.trim(),
              })),
            );
            onClose();
          }}
        >
          Apply
        </button>
      </div>
    </Dialog>
  );
}
