"use client";

/**
 * Editing an object type, with the change history and impact warning that
 * make editing one safe (ROADMAP Objects item 5).
 *
 * The property rows live here rather than in the Objects page because the
 * create dialog and the edit dialog need exactly the same editor, and two
 * copies of a form that has to agree on api_name normalisation and property
 * ordering is the mirror problem this codebase already tracks four instances
 * of. One renderer, two dialogs.
 *
 * The warning is *live*, not a confirmation step. Impact is recomputed as the
 * properties change, so "removing this breaks the People mapping" is on
 * screen while there is still a decision to make, rather than arriving after
 * the user has committed to saving. Save then requires an explicit
 * acknowledgement, because every consumer of a removed property degrades
 * silently — nothing downstream will ever raise to tell them.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import { ApiError, objects as objApi, type PropertyInput } from "@/lib/api";
import type {
  ObjectTypeDetail,
  ObjectTypeImpact,
  PropertyDataType,
  PropertyVisibility,
} from "@/lib/types";

const PROPERTY_TYPES: PropertyDataType[] = [
  "string", "integer", "float", "boolean", "date", "timestamp", "geopoint", "json",
];

const PROPERTY_VISIBILITIES: PropertyVisibility[] = ["normal", "prominent", "hidden"];

export function toPropertyApiName(display: string): string {
  const words = display.match(/[A-Za-z0-9]+/g) ?? [];
  return words.map((w) => w.toLowerCase()).join("_").slice(0, 100);
}

export function PropertyRows({
  properties,
  onChange,
}: {
  properties: PropertyInput[];
  onChange: (next: PropertyInput[]) => void;
}) {
  return (
    <div>
      {properties.map((prop, index) => (
        <div key={index} className="row-actions" style={{ marginBottom: 6 }}>
          <input
            type="text"
            placeholder="property_name"
            aria-label={`Property ${index + 1} name`}
            style={{
              fontFamily: "var(--font-mono)", fontSize: 12.5,
              padding: "4px 8px", border: "1px solid var(--line-strong)",
              borderRadius: "var(--radius)", width: 160,
            }}
            value={prop.api_name}
            onChange={(e) => {
              const next = [...properties];
              next[index] = { ...prop, api_name: toPropertyApiName(e.target.value) };
              onChange(next);
            }}
          />
          <select
            value={prop.data_type}
            aria-label={`Property ${index + 1} type`}
            onChange={(e) => {
              const next = [...properties];
              next[index] = { ...prop, data_type: e.target.value as PropertyDataType };
              onChange(next);
            }}
          >
            {PROPERTY_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          {/* Visibility (Foundry `object-link-types` p.111): "an indication to
              user applications for how prominently to display the property".
              A display hint, never a permission — a hidden property is still
              stored and still returned by the API. */}
          <select
            value={prop.visibility ?? "normal"}
            aria-label={`Property ${index + 1} visibility`}
            onChange={(e) => {
              const next = [...properties];
              next[index] = { ...prop, visibility: e.target.value as PropertyVisibility };
              onChange(next);
            }}
          >
            {PROPERTY_VISIBILITIES.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
          <label style={{ fontSize: 12.5, display: "flex", gap: 4, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={!!prop.required}
              onChange={(e) => {
                const next = [...properties];
                next[index] = { ...prop, required: e.target.checked };
                onChange(next);
              }}
            />
            required
          </label>
          <button
            type="button"
            className="btn danger"
            style={{ padding: "3px 9px", fontSize: 12 }}
            onClick={() => onChange(properties.filter((_, i) => i !== index))}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn quiet"
        style={{ padding: "4px 10px", fontSize: 12.5 }}
        onClick={() =>
          onChange([...properties, { api_name: "", data_type: "string", required: false }])
        }
      >
        Add property
      </button>
    </div>
  );
}

export function TitlePropertyField({
  properties,
  value,
  onChange,
}: {
  properties: PropertyInput[];
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <Field label="Title property" hint="Shown as the object's name - optional">
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Title property">
        <option value="">None</option>
        {properties.filter((p) => p.api_name).map((p) => (
          <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
        ))}
      </select>
    </Field>
  );
}

function ImpactList({ impacts }: { impacts: ObjectTypeImpact[] }) {
  const blocking = impacts.filter((i) => i.blocking);
  const advisory = impacts.filter((i) => !i.blocking);
  return (
    <>
      {blocking.length > 0 && (
        <div className="form-error" style={{ textAlign: "left" }}>
          <strong>This change breaks {blocking.length} existing consumer{blocking.length === 1 ? "" : "s"}.</strong>
          <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
            {blocking.map((i, n) => (
              <li key={n}>
                <code>{i.property}</code> {i.change} — {i.consumer_kind.replace("_", " ")}{" "}
                <strong>{i.consumer_name}</strong> ({i.detail})
              </li>
            ))}
          </ul>
          <p style={{ margin: "6px 0 0" }}>
            Nothing will report an error afterwards: a mapping keeps writing a property nothing
            displays, an action stops type-checking it, and a link traverses to nothing.
          </p>
        </div>
      )}
      {advisory.length > 0 && (
        <p className="login-note" style={{ marginTop: 8 }}>
          Also affected, but still working:{" "}
          {advisory.map((i) => `${i.consumer_name} (${i.property} ${i.change})`).join(", ")}.
        </p>
      )}
    </>
  );
}

/** What the impact analysis actually depends on — the api_name and type of
 * every named property. Keying the query on this rather than the whole form
 * means editing a display name or a description asks the server nothing. */
function impactSignature(properties: PropertyInput[]): string {
  return properties
    .filter((p) => p.api_name.trim())
    .map((p) => `${p.api_name}:${p.data_type}`)
    .join(",");
}

function VersionHistory({
  workspaceId,
  type,
  onRestored,
}: {
  workspaceId: string;
  type: ObjectTypeDetail;
  onRestored: () => void;
}) {
  const [confirming, setConfirming] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const versions = useQuery({
    queryKey: ["object-type-versions", workspaceId, type.id],
    queryFn: () => objApi.listTypeVersions(workspaceId, type.id),
  });

  const restore = useMutation({
    mutationFn: ({ version, acknowledge }: { version: number; acknowledge: boolean }) =>
      objApi.restoreTypeVersion(workspaceId, type.id, version, acknowledge),
    onSuccess: async () => {
      setConfirming(null);
      await queryClient.invalidateQueries({ queryKey: ["object-type", type.id] });
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      await queryClient.invalidateQueries({
        queryKey: ["object-type-versions", workspaceId, type.id],
      });
      onRestored();
    },
  });

  const blocked =
    restore.isError && restore.error instanceof ApiError && restore.error.status === 409;

  return (
    <>
      <h3 style={{ fontSize: 13.5, margin: "18px 0 6px" }}>Definition history</h3>
      {versions.isPending && <div className="state">Loading history…</div>}
      {versions.data && (
        <table className="table">
          <thead>
            <tr><th>Version</th><th>Properties</th><th>Changed</th><th aria-label="Actions" /></tr>
          </thead>
          <tbody>
            {versions.data.map((v, index) => (
              <tr key={v.id}>
                <td>
                  <strong>v{v.version_number}</strong>
                  {v.restored_from !== null && (
                    <div className="slug">reverted to v{v.restored_from}</div>
                  )}
                </td>
                <td className="slug">
                  {v.properties.map((p) => `${p.api_name}:${p.data_type}`).join(", ")}
                </td>
                <td className="slug">
                  {new Date(v.created_at).toLocaleString()}
                  {v.created_by_email && <div>{v.created_by_email}</div>}
                </td>
                <td>
                  {index > 0 && (
                    <button
                      type="button"
                      className="btn quiet"
                      style={{ padding: "3px 9px", fontSize: 12 }}
                      disabled={restore.isPending}
                      onClick={() => {
                        setConfirming(v.version_number);
                        restore.mutate({ version: v.version_number, acknowledge: false });
                      }}
                    >
                      Restore
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {restore.isError && (
        <div className="form-error" style={{ textAlign: "left" }}>
          {restore.error instanceof ApiError ? restore.error.message : "Couldn't restore."}
          {blocked && confirming !== null && (
            <div className="row-actions" style={{ marginTop: 8 }}>
              <button
                type="button"
                className="btn danger"
                style={{ padding: "3px 9px", fontSize: 12 }}
                onClick={() => restore.mutate({ version: confirming, acknowledge: true })}
              >
                Restore v{confirming} anyway
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}

export function EditObjectTypeDialog({
  workspaceId,
  type,
  onClose,
}: {
  workspaceId: string;
  type: ObjectTypeDetail;
  onClose: () => void;
}) {
  const [displayName, setDisplayName] = useState(type.display_name);
  const [description, setDescription] = useState(type.description);
  const [properties, setProperties] = useState<PropertyInput[]>(
    type.properties.map((p) => ({
      api_name: p.api_name,
      display_name: p.display_name,
      data_type: p.data_type,
      required: p.required,
      // Carried through, or opening this dialog and saving would silently
      // reset every property to `normal` - a setting lost by editing something
      // else, which is the worst way to lose one.
      visibility: p.visibility,
    })),
  );
  const [titleProperty, setTitleProperty] = useState(
    type.properties.find((p) => p.id === type.title_property_id)?.api_name ?? "",
  );
  const [acknowledged, setAcknowledged] = useState(false);
  const queryClient = useQueryClient();

  const named = properties.filter((p) => p.api_name.trim());
  const body = {
    display_name: displayName,
    description,
    properties: named,
    title_property: titleProperty || null,
  };

  const originalSignature = impactSignature(
    type.properties.map((p) => ({ api_name: p.api_name, data_type: p.data_type })),
  );
  const signature = impactSignature(named);

  const impact = useQuery({
    queryKey: ["object-type-impact", workspaceId, type.id, signature],
    queryFn: () => objApi.typeImpact(workspaceId, type.id, body),
    // Nothing to ask when the properties are untouched — an unchanged
    // definition cannot break anything.
    enabled: signature !== originalSignature && named.length > 0,
  });
  const impacts = signature === originalSignature ? [] : impact.data ?? [];
  const blocking = impacts.filter((i) => i.blocking);

  const save = useMutation({
    mutationFn: () =>
      objApi.updateType(workspaceId, type.id, {
        ...body,
        acknowledge_breaking: blocking.length > 0,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["object-type", type.id] });
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["object-sources", workspaceId] });
      await queryClient.invalidateQueries({
        queryKey: ["object-type-versions", workspaceId, type.id],
      });
      onClose();
    },
  });

  return (
    <Dialog open wide title={`Edit ${type.display_name}`} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <Field label="Display name" hint={`API name: ${type.api_name} (not editable)`}>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            maxLength={200}
            autoFocus
          />
        </Field>
        <Field label="Description" hint="Optional">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={2000}
          />
        </Field>
        <Field label="Properties" hint="Renaming a property removes it and adds a new one">
          <PropertyRows properties={properties} onChange={(next) => {
            setProperties(next);
            setAcknowledged(false);  // a changed proposal is not the one that was accepted
          }} />
        </Field>
        <TitlePropertyField
          properties={properties}
          value={titleProperty}
          onChange={setTitleProperty}
        />

        {impact.isFetching && <p className="login-note">Checking what this would affect…</p>}
        <ImpactList impacts={impacts} />
        {blocking.length > 0 && (
          <label style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 8, fontSize: 12.5 }}>
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            I understand, save it anyway
          </label>
        )}
        {save.isError && (
          <div className="form-error">
            {save.error instanceof ApiError ? save.error.message : "Couldn't save the object type."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>Cancel</button>
          <button
            type="submit"
            className={blocking.length > 0 ? "btn danger" : "btn"}
            disabled={
              save.isPending ||
              !displayName.trim() ||
              named.length === 0 ||
              impact.isFetching ||
              (blocking.length > 0 && !acknowledged)
            }
          >
            {save.isPending ? "Saving…" : blocking.length > 0 ? "Save anyway" : "Save"}
          </button>
        </div>
      </form>

      <VersionHistory workspaceId={workspaceId} type={type} onRestored={onClose} />
    </Dialog>
  );
}
