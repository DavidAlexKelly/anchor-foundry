"use client";

/**
 * Attaching a property to a shared property (Foundry `object-link-types`
 * p.187–188).
 *
 * > "Select the property on the panel that you want to update, then scroll
 * > down to the Shared Property section of the configuration. Use the dropdown
 * > menu to select an existing shared property to use, or convert the property
 * > to a new shared property." (p.187)
 *
 * **Only the shared properties whose base type matches are offered.** p.181
 * requires them to match, so listing the rest would be listing saves that
 * fail — the same rule the derived-property editor follows about links. The
 * ones that do not match are still *counted* in a hint, because "there are no
 * shared properties" and "there are four and none of them is a date" are
 * different situations and only one of them is somebody's mistake.
 *
 * **Attaching adopts the shared metadata here as well as on the server.** The
 * server would do it anyway on a fresh attach, but a form that showed the old
 * display name until the next reload would be showing something that is about
 * to stop being true. What the row must then not do is let anybody edit those
 * fields — p.188 disables them, and `object-type-editor` does.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Dialog, Field } from "@/components/dialog";
import { objects as objApi } from "@/lib/api";
import type { PropertyInput } from "@/lib/api";
import { attached, detached, offerableTo } from "@/lib/shared-property";
import type { PropertyDataType } from "@/lib/types";

export function SharedPropertyPicker({
  open,
  onClose,
  propertyName,
  workspaceId,
  value,
  dataType,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  propertyName: string;
  workspaceId: string;
  /** The property as it stands, so attaching can return the whole row. */
  value: PropertyInput;
  dataType: PropertyDataType;
  onSave: (next: PropertyInput) => void;
}) {
  const shared = useQuery({
    queryKey: ["shared-properties", workspaceId],
    queryFn: () => objApi.listSharedProperties(workspaceId),
  });
  const all = shared.data ?? [];
  const fits = offerableTo(all, dataType);
  const attachedTo = all.find((s) => s.id === value.shared_property_id) ?? null;
  const [chosen, setChosen] = useState(value.shared_property_id ?? "");

  const pick = fits.find((s) => s.id === chosen) ?? null;

  return (
    <Dialog open={open} title={`Shared property for ${propertyName}`} onClose={onClose}>
      <p className="field-hint">
        A shared property is one definition used by several object types. Its
        name, description, visibility and formatting come from the shared
        property and are edited in one place; this property keeps its own API
        name and its own data.
      </p>

      {attachedTo && (
        <p className="field-hint" data-testid="shared-current">
          Currently using <strong>{attachedTo.api_name}</strong>, which{" "}
          {attachedTo.usage_count === 1
            ? "only this property uses"
            : `${attachedTo.usage_count} properties use`}
          .
        </p>
      )}

      <Field
        label="Shared property"
        hint={
          fits.length
            ? "Only the ones whose base type matches this property."
            : `None of this workspace's ${all.length} shared properties is a ${dataType}.`
        }
      >
        <select
          data-testid="shared-choice"
          value={chosen}
          onChange={(e) => setChosen(e.target.value)}
        >
          <option value="">Not shared</option>
          {fits.map((s) => (
            <option key={s.id} value={s.id}>
              {s.display_name} ({s.api_name})
            </option>
          ))}
        </select>
      </Field>

      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        {/* p.188's Detach, offered only when there is something to detach.
            The property keeps everything it inherited - detaching is not a
            way to lose a display name. */}
        {value.shared_property_id && (
          <button
            type="button"
            className="btn danger"
            data-testid="shared-detach"
            onClick={() => {
              onSave(detached(value));
              onClose();
            }}
          >
            Detach
          </button>
        )}
        <button
          type="button"
          className="btn primary"
          data-testid="shared-apply"
          disabled={!pick || pick.id === value.shared_property_id}
          onClick={() => {
            if (!pick) return;
            onSave(attached(value, pick));
            onClose();
          }}
        >
          Use it
        </button>
      </div>
    </Dialog>
  );
}
