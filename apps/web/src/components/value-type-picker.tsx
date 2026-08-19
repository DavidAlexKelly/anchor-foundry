"use client";

/**
 * Putting a value type on a property (Foundry `object-link-types` p.227).
 *
 * > "To assign a value type to a property, select the value type from the
 * > dropdown menu during property configuration." (p.227)
 *
 * **Only the value types whose base type matches are offered**, the rule
 * `shared-property-picker` follows for the same reason: a value type *is* the
 * type (p.222), so attaching an `email` to an integer property would be a rule
 * that rejects every row — p.227's "will fail to index", arriving on a screen
 * rather than on the save.
 *
 * **A property can be constrained without having chosen anything.** p.227
 * allows a value type on a shared property too, so a property attached to one
 * inherits its rule. That is shown rather than hidden, and the dropdown stays
 * usable: the property's own choice wins, which is the more specific
 * statement, and somebody has to be able to see which of the two they are
 * looking at.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Dialog, Field } from "@/components/dialog";
import { objects as objApi } from "@/lib/api";
import type { PropertyInput } from "@/lib/api";
import { offerableTo, optionLabel } from "@/lib/value-type";
import type { PropertyDataType } from "@/lib/types";

export function ValueTypePicker({
  open,
  onClose,
  propertyName,
  workspaceId,
  value,
  dataType,
  /** What is in force now, which may have come from the shared property. */
  effectiveId,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  propertyName: string;
  workspaceId: string;
  value: PropertyInput;
  dataType: PropertyDataType;
  effectiveId?: string | null;
  onSave: (next: PropertyInput) => void;
}) {
  const types = useQuery({
    queryKey: ["value-types", workspaceId],
    queryFn: () => objApi.listValueTypes(workspaceId),
  });
  const all = types.data ?? [];
  const fits = offerableTo(all, dataType);
  const [chosen, setChosen] = useState(value.value_type_id ?? "");

  const inherited =
    !value.value_type_id && effectiveId
      ? all.find((t) => t.id === effectiveId) ?? null
      : null;

  return (
    <Dialog open={open} title={`Value type for ${propertyName}`} onClose={onClose}>
      <p className="field-hint">
        A value type says what this property&apos;s values mean and what they are
        allowed to be. The rule is enforced when data is synced and when an
        action writes — the sync reports what does not comply, and the action is
        refused.
      </p>

      {inherited && (
        <p className="field-hint" data-testid="vt-inherited">
          Currently inheriting <strong>{inherited.api_name}</strong> from this
          property&apos;s shared property ({inherited.constraint_summary}).
          Choosing one here replaces it for this property only.
        </p>
      )}

      <Field
        label="Value type"
        hint={
          fits.length
            ? "Only the ones whose base type matches this property."
            : `None of this workspace's ${all.length} value types is a ${dataType}.`
        }
      >
        <select
          data-testid="vt-choice"
          value={chosen}
          onChange={(e) => setChosen(e.target.value)}
        >
          <option value="">Not constrained</option>
          {fits.map((t) => (
            <option key={t.id} value={t.id}>{optionLabel(t)}</option>
          ))}
        </select>
      </Field>

      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="vt-apply"
          disabled={(chosen || null) === (value.value_type_id ?? null)}
          onClick={() => {
            onSave({ ...value, value_type_id: chosen || null });
            onClose();
          }}
        >
          Apply
        </button>
      </div>
    </Dialog>
  );
}
