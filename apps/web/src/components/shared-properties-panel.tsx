"use client";

/**
 * The shared property page (Foundry `object-link-types` p.180–185, p.190–191).
 *
 * > "Select the Shared properties menu option in Ontology Manager. Once on the
 * > shared property page, select New shared property at the top right." (p.180)
 *
 * A section of the ontology page rather than a menu destination of its own,
 * for the reason Link types and Actions are: this application puts one
 * workspace's ontology on one page, and a shared property is a smaller thing
 * than either of those.
 *
 * **Usage is on the row, not behind a tab.** p.184 puts it on a Usage tab and
 * p.191 defines it as "the object types on which a shared property is used" —
 * but the moment somebody needs it is the moment before they press Delete, and
 * a count that is already on screen answers that without a click. The full
 * list is one click away, on the row, for when the count is surprising.
 *
 * **Delete says what it will do.** p.185: "all object types using this shared
 * property will revert to regular properties". That is unusually benign for a
 * delete and it is worth saying so, because somebody who expects a cascade
 * will not press the button at all.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Dialog, Field } from "@/components/dialog";
import { ValueFormatEditor, formattable } from "@/components/value-format-editor";
import { PROPERTY_TYPES, PROPERTY_VISIBILITIES } from "@/components/object-type-editor";
import { ApiError, objects as objApi, type SharedPropertyInput } from "@/lib/api";
import type {
  PropertyDataType,
  PropertyVisibility,
  SharedProperty,
} from "@/lib/types";

function toApiName(display: string): string {
  const words = display.match(/[A-Za-z0-9]+/g) ?? [];
  return words.map((w) => w.toLowerCase()).join("_").slice(0, 100);
}

/** p.181's creation modal and p.184's edit tabs, which hold the same fields.
 * One dialog rather than two: p.184's own list is p.181's list, and two forms
 * would be two places for a field to go missing. */
function SharedPropertyDialog({
  workspaceId,
  existing,
  onClose,
}: {
  workspaceId: string;
  /** Absent when creating. When present, `api_name` is not editable — it is
   * the stable machine name a consumer holds, and the API has no parameter
   * for it. */
  existing?: SharedProperty;
  onClose: () => void;
}) {
  const [displayName, setDisplayName] = useState(existing?.display_name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [dataType, setDataType] = useState<PropertyDataType>(
    existing?.data_type ?? "string",
  );
  const [visibility, setVisibility] = useState<PropertyVisibility>(
    existing?.visibility ?? "normal",
  );
  const [valueFormat, setValueFormat] = useState(existing?.value_format ?? null);
  const [formatting, setFormatting] = useState(false);
  const queryClient = useQueryClient();

  const body: SharedPropertyInput = {
    display_name: displayName,
    description,
    data_type: dataType,
    visibility,
    value_format: valueFormat,
    ...(existing ? {} : { api_name: toApiName(displayName) }),
  };

  const save = useMutation({
    mutationFn: () =>
      existing
        ? objApi.updateSharedProperty(workspaceId, existing.id, body)
        : objApi.createSharedProperty(workspaceId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["shared-properties", workspaceId],
      });
      // Every object type resolves its inherited metadata on read, so both
      // the summaries and every *detail* already fetched are stale by exactly
      // this edit. The detail is the one that matters and the one that is
      // easy to miss: it is keyed per type (`["object-type", typeId]`), so
      // invalidating the list alone leaves the property editor showing the
      // metadata as it was before the edit that was the whole point.
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["object-type"] });
      onClose();
    },
  });

  return (
    <Dialog
      open
      title={existing ? `Edit ${existing.api_name}` : "New shared property"}
      onClose={onClose}
    >
      {formatting && (
        <ValueFormatEditor
          open
          onClose={() => setFormatting(false)}
          propertyName={displayName || "this property"}
          dataType={dataType}
          value={valueFormat}
          onSave={setValueFormat}
        />
      )}
      <Field label="Name">
        <input
          type="text"
          data-testid="shared-name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </Field>
      {!existing && (
        <p className="field-hint" data-testid="shared-api-name">
          API name: <code>{toApiName(displayName) || "…"}</code>
        </p>
      )}
      <Field label="Description" hint="p.181: what this property means, once.">
        <input
          type="text"
          data-testid="shared-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      <Field
        label="Base type"
        hint={
          existing && existing.usage_count > 0
            ? `Fixed while ${existing.usage_count} propert${
                existing.usage_count === 1 ? "y uses" : "ies use"
              } it — detach them to change it.`
            : "Must match the column type of every property that uses it (p.181)."
        }
      >
        <select
          data-testid="shared-type"
          value={dataType}
          disabled={!!existing && existing.usage_count > 0}
          onChange={(e) => {
            setDataType(e.target.value as PropertyDataType);
            // A formatter belongs to a base type (p.95), so keeping one across
            // a retype would keep a formatter the save then refuses.
            setValueFormat(null);
          }}
        >
          {PROPERTY_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </Field>
      <Field label="Visibility">
        <select
          data-testid="shared-visibility"
          value={visibility}
          onChange={(e) => setVisibility(e.target.value as PropertyVisibility)}
        >
          {PROPERTY_VISIBILITIES.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </Field>
      {formattable(dataType) && (
        <Field label="Value formatting" hint="p.181, and the same formatter a local property gets.">
          <button
            type="button"
            className="btn"
            data-testid="shared-format"
            onClick={() => setFormatting(true)}
          >
            Format{valueFormat ? " •" : ""}
          </button>
        </Field>
      )}
      {save.isError && (
        <p className="field-hint" data-testid="shared-error">
          {save.error instanceof ApiError ? save.error.message : "Could not save."}
        </p>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="shared-save"
          disabled={!displayName.trim() || save.isPending}
          onClick={() => save.mutate()}
        >
          Save
        </button>
      </div>
    </Dialog>
  );
}

function UsageDialog({
  workspaceId,
  shared,
  onClose,
}: {
  workspaceId: string;
  shared: SharedProperty;
  onClose: () => void;
}) {
  const usage = useQuery({
    queryKey: ["shared-property-usage", workspaceId, shared.id],
    queryFn: () => objApi.sharedPropertyUsage(workspaceId, shared.id),
  });
  return (
    <Dialog open title={`${shared.api_name} is used by`} onClose={onClose}>
      {usage.data && usage.data.length === 0 && (
        <p className="field-hint">Nothing uses it yet.</p>
      )}
      {usage.data && usage.data.length > 0 && (
        <table className="table" data-testid="shared-usage-table">
          <thead><tr><th>Object type</th><th>As property</th></tr></thead>
          <tbody>
            {usage.data.map((u) => (
              <tr key={`${u.object_type_id}:${u.property_api_name}`}>
                <td>{u.object_type_display_name}</td>
                {/* p.188 lets the names differ, so the row says both. */}
                <td className="slug">{u.property_api_name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Close</button>
      </div>
    </Dialog>
  );
}

export function SharedPropertiesPanel({
  workspaceId,
  canEdit,
  openId,
  onOpened,
}: {
  workspaceId: string;
  canEdit: boolean;
  /** Open this one's editor as soon as it can be resolved. The ontology
   * search hands over an id, and only this component knows how to turn one
   * into an open dialog — the alternative is the page holding a duplicate of
   * the edit dialog so that the search has something of its own to open. */
  openId?: string | null;
  onOpened?: () => void;
}) {
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<SharedProperty | null>(null);
  const [showingUsage, setShowingUsage] = useState<SharedProperty | null>(null);
  const queryClient = useQueryClient();

  const shared = useQuery({
    queryKey: ["shared-properties", workspaceId],
    queryFn: () => objApi.listSharedProperties(workspaceId),
  });

  // Resolved during render rather than in an effect: the id may arrive before
  // the list does, and an effect keyed on `openId` alone would miss the case
  // where the list is what arrives second.
  const requested = openId
    ? (shared.data ?? []).find((s) => s.id === openId) ?? null
    : null;
  if (requested && editing?.id !== requested.id) {
    setEditing(requested);
    onOpened?.();
  }

  const remove = useMutation({
    mutationFn: (id: string) => objApi.deleteSharedProperty(workspaceId, id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["shared-properties", workspaceId],
      });
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      // p.185's revert happens in the database; this is what makes it visible
      // without a reload.
      await queryClient.invalidateQueries({ queryKey: ["object-type"] });
    },
  });

  return (
    <>
      {creating && (
        <SharedPropertyDialog workspaceId={workspaceId} onClose={() => setCreating(false)} />
      )}
      {editing && (
        <SharedPropertyDialog
          workspaceId={workspaceId}
          existing={editing}
          onClose={() => setEditing(null)}
        />
      )}
      {showingUsage && (
        <UsageDialog
          workspaceId={workspaceId}
          shared={showingUsage}
          onClose={() => setShowingUsage(null)}
        />
      )}

      <div className="page-head" style={{ marginTop: 32 }}>
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Shared properties</h2>
          <p className="sub">
            One definition several object types use, edited in one place
          </p>
        </div>
        {canEdit && (
          <button
            className="btn quiet"
            data-testid="new-shared-property"
            onClick={() => setCreating(true)}
          >
            New shared property
          </button>
        )}
      </div>
      {shared.data && shared.data.length === 0 && (
        <p className="login-note">
          None yet — a shared property is worth creating when two object types
          mean the same thing by a property, like a start date on an employee
          and on a contractor.
        </p>
      )}
      {shared.data && shared.data.length > 0 && (
        <table className="table" style={{ marginBottom: 28 }} data-testid="shared-table">
          <thead>
            <tr>
              <th>Property</th><th>Type</th><th>Visibility</th><th>Used by</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {shared.data.map((s) => (
              <tr key={s.id}>
                <td>
                  <strong>{s.display_name}</strong>
                  <div className="slug">{s.api_name}</div>
                </td>
                <td className="count">{s.data_type}</td>
                <td className="count">{s.visibility}</td>
                <td>
                  <button
                    className="btn quiet"
                    style={{ padding: "3px 9px", fontSize: 12 }}
                    aria-label={`Usage of ${s.api_name}`}
                    onClick={() => setShowingUsage(s)}
                  >
                    {s.usage_count}
                  </button>
                </td>
                <td>
                  <div className="row-actions">
                    {canEdit && (
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`Edit ${s.api_name}`}
                        onClick={() => setEditing(s)}
                      >
                        Edit
                      </button>
                    )}
                    {canEdit && (
                      <button
                        className="btn danger"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`Delete ${s.api_name}`}
                        disabled={remove.isPending}
                        // p.185's own words, because a delete that reverts
                        // rather than cascades is not what anybody expects.
                        title={
                          s.usage_count
                            ? `${s.usage_count} propert${
                                s.usage_count === 1 ? "y" : "ies"
                              } will revert to regular properties`
                            : "Nothing uses it"
                        }
                        onClick={() => remove.mutate(s.id)}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
