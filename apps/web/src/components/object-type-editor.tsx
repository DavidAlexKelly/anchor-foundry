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
import { ValueFormatEditor, formattable } from "@/components/value-format-editor";
import { ConditionalFormatEditor } from "@/components/conditional-format-editor";
import { DerivedPropertyEditor } from "@/components/derived-property-editor";
import { SharedPropertyPicker } from "@/components/shared-property-picker";
import { StatusField } from "@/components/status-field";
import { ValueTypePicker } from "@/components/value-type-picker";
import { ApiError, objects as objApi, type PropertyInput } from "@/lib/api";
import { sameSelection, toggleSelection } from "@/lib/object-type-groups";
import type {
  ObjectTypeDetail,
  ObjectTypeImpact,
  PropertyDataType,
  PropertyVisibility,
} from "@/lib/types";

// Exported so the shared property dialog offers the same list. A second copy
// would be a base type this editor knows about and that one does not, which is
// exactly the drift `routes/objects.py` stopped making by building its pattern
// from `ontology.PROPERTY_TYPES` rather than typing it out again.
export const PROPERTY_TYPES: PropertyDataType[] = [
  "string", "integer", "float", "boolean", "date", "timestamp", "geopoint", "json",
];

export const PROPERTY_VISIBILITIES: PropertyVisibility[] = ["normal", "prominent", "hidden"];

export function toPropertyApiName(display: string): string {
  const words = display.match(/[A-Za-z0-9]+/g) ?? [];
  return words.map((w) => w.toLowerCase()).join("_").slice(0, 100);
}

export function PropertyRows({
  properties,
  onChange,
  workspaceId,
  objectTypeId,
  effectiveValueTypes,
}: {
  properties: PropertyInput[];
  onChange: (next: PropertyInput[]) => void;
  /** Both only for the derived-property chain, which needs the workspace's
   * link types and a type to start from. Absent on the *create* dialog, where
   * neither exists yet - which is also why the server refuses a derivation
   * there (§161). */
  workspaceId?: string;
  objectTypeId?: string;
  /** What each property is *actually* constrained by, which may have come from
   * its shared property (`object-link-types` p.227). Read-only context for the
   * picker: it is not something a save sends back, and echoing it would turn
   * an inherited value type into a local choice. */
  effectiveValueTypes?: Record<string, string | null>;
}) {
  // Which row's formatter is open, by index. One dialog rather than one per
  // row: only one can be open, and a dialog per property is a dialog per
  // property to keep in step.
  const [formatting, setFormatting] = useState<number | null>(null);
  const editing = formatting === null ? null : properties[formatting];
  // Separate state from the formatter's: they are two dialogs about two
  // different settings, and one index would make "which dialog is open" a
  // second thing to track beside "which row".
  const [colouring, setColouring] = useState<number | null>(null);
  const colouringRow = colouring === null ? null : properties[colouring];
  const [deriving, setDeriving] = useState<number | null>(null);
  const derivingRow = deriving === null ? null : properties[deriving];
  const [sharing, setSharing] = useState<number | null>(null);
  const sharingRow = sharing === null ? null : properties[sharing];
  const [constraining, setConstraining] = useState<number | null>(null);
  const constrainingRow =
    constraining === null ? null : properties[constraining];

  return (
    <div>
      {editing && (
        <ValueFormatEditor
          open
          onClose={() => setFormatting(null)}
          propertyName={editing.api_name || `property ${formatting! + 1}`}
          dataType={editing.data_type}
          value={editing.value_format}
          onSave={(next) => {
            const rows = [...properties];
            rows[formatting!] = { ...editing, value_format: next };
            onChange(rows);
          }}
        />
      )}
      {derivingRow && workspaceId && objectTypeId && (
        <DerivedPropertyEditor
          open
          onClose={() => setDeriving(null)}
          propertyName={derivingRow.api_name || `property ${deriving! + 1}`}
          workspaceId={workspaceId}
          objectTypeId={objectTypeId}
          value={derivingRow.derivation}
          onSave={(next) => {
            const rows = [...properties];
            rows[deriving!] = { ...derivingRow, derivation: next };
            onChange(rows);
          }}
        />
      )}
      {sharingRow && workspaceId && (
        <SharedPropertyPicker
          open
          onClose={() => setSharing(null)}
          propertyName={sharingRow.api_name || `property ${sharing! + 1}`}
          workspaceId={workspaceId}
          value={sharingRow}
          dataType={sharingRow.data_type}
          onSave={(next) => {
            const rows = [...properties];
            rows[sharing!] = next;
            onChange(rows);
          }}
        />
      )}
      {constrainingRow && workspaceId && (
        <ValueTypePicker
          open
          onClose={() => setConstraining(null)}
          propertyName={constrainingRow.api_name || `property ${constraining! + 1}`}
          workspaceId={workspaceId}
          value={constrainingRow}
          dataType={constrainingRow.data_type}
          effectiveId={effectiveValueTypes?.[constrainingRow.api_name]}
          onSave={(next) => {
            const rows = [...properties];
            rows[constraining!] = next;
            onChange(rows);
          }}
        />
      )}
      {colouringRow && (
        <ConditionalFormatEditor
          open
          onClose={() => setColouring(null)}
          propertyName={colouringRow.api_name || `property ${colouring! + 1}`}
          // Every property, because a rule may read one this row is not on
          // (`object-link-types` p.105 label B).
          properties={properties
            .filter((p) => p.api_name.trim())
            .map((p) => ({ api_name: p.api_name, data_type: p.data_type }))}
          value={colouringRow.conditional_format}
          onSave={(next) => {
            const rows = [...properties];
            rows[colouring!] = { ...colouringRow, conditional_format: next };
            onChange(rows);
          }}
        />
      )}
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
          {/* p.178: "Shared properties on objects are denoted with a globe
              icon next to their name." Before the controls it disables, so
              the reason they are disabled is read first. */}
          {prop.shared_property_id && (
            <span
              title="Inherited from a shared property"
              aria-label={`Property ${index + 1} is shared`}
              style={{ fontSize: 13 }}
            >
              🌐
            </span>
          )}
          <select
            value={prop.visibility ?? "normal"}
            aria-label={`Property ${index + 1} visibility`}
            // p.188: "direct edits to property metadata that is inherited from
            // the shared property will be disabled". Visibility and the
            // formatter are the two inherited fields this row can reach; the
            // API refuses them too, and this is what stops somebody meeting
            // that refusal by surprise.
            disabled={!!prop.shared_property_id}
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
          {/* Required (Foundry `object-link-types` p.116): "object type
              properties that must have a value". Unlike visibility above, this
              is not a hint - an action that would empty it is refused, and a
              sync reports the rows that do not comply. */}
          <label style={{ fontSize: 12.5, display: "flex", gap: 4, alignItems: "center" }}>
            <input
              type="checkbox"
              aria-label={`Property ${index + 1} required`}
              checked={!!prop.required}
              onChange={(e) => {
                const next = [...properties];
                next[index] = { ...prop, required: e.target.checked };
                onChange(next);
              }}
            />
            required
          </label>
          {/* Edit-only (Foundry `object-link-types` p.113): this property has
              no column in any backing dataset. Beside `required` rather than
              in a dialog because it is one bit, and because it changes what
              *every* other control on the row means - a mapped column, a sync,
              an action write-back. */}
          <label style={{ fontSize: 12.5, display: "flex", gap: 4, alignItems: "center" }}>
            <input
              type="checkbox"
              aria-label={`Property ${index + 1} edit-only`}
              checked={!!prop.edit_only}
              onChange={(e) => {
                const next = [...properties];
                next[index] = { ...prop, edit_only: e.target.checked };
                onChange(next);
              }}
            />
            edit-only
          </label>
          {/* Value formatting (Foundry `object-link-types` p.94-101). Offered
              only where it applies (p.95) - a Format button on a string
              property would open a dialog whose every answer the server
              refuses. The dot says one is set without opening anything. */}
          {formattable(prop.data_type) && (
            <button
              type="button"
              className="btn"
              style={{ padding: "3px 9px", fontSize: 12 }}
              aria-label={`Property ${index + 1} format`}
              disabled={!!prop.shared_property_id}
              onClick={() => setFormatting(index)}
            >
              Format{prop.value_format ? " •" : ""}
            </button>
          )}
          {/* Shared property (`object-link-types` p.187). Only on the edit
              dialog: the create dialog has no workspace context, and p.187's
              own flow starts from a property that already exists. */}
          {workspaceId && (
            <button
              type="button"
              className="btn"
              style={{ padding: "3px 9px", fontSize: 12 }}
              aria-label={`Property ${index + 1} shared`}
              onClick={() => setSharing(index)}
            >
              Shared{prop.shared_property_id ? " •" : ""}
            </button>
          )}
          {/* Value type (`object-link-types` p.227). Beside Shared because
              they are siblings - one shares this property's metadata, the
              other its rule - and a property may carry both. */}
          {workspaceId && (
            <button
              type="button"
              className="btn"
              style={{ padding: "3px 9px", fontSize: 12 }}
              aria-label={`Property ${index + 1} value type`}
              onClick={() => setConstraining(index)}
            >
              Rule
              {prop.value_type_id
                ? " •"
                : effectiveValueTypes?.[prop.api_name]
                  ? " ↑"
                  : ""}
            </button>
          )}
          {/* Conditional formatting (`object-link-types` p.102-109). Unlike
              the formatter above there is no base-type gate: `Is null` applies
              to every type, so every property has at least one rule it could
              legitimately carry. */}
          <button
            type="button"
            className="btn"
            style={{ padding: "3px 9px", fontSize: 12 }}
            aria-label={`Property ${index + 1} rules`}
            onClick={() => setColouring(index)}
          >
            Rules{prop.conditional_format?.length ? ` (${prop.conditional_format.length})` : ""}
          </button>
          {/* Derived (`object-link-types` p.143). Offered only where a chain
              could exist: the create dialog has no type to start from, and no
              link type can touch a type that does not exist yet. */}
          {workspaceId && objectTypeId && (
            <button
              type="button"
              className="btn"
              style={{ padding: "3px 9px", fontSize: 12 }}
              aria-label={`Property ${index + 1} derive`}
              onClick={() => setDeriving(index)}
            >
              Derive{prop.derivation ? " •" : ""}
            </button>
          )}
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
  canPromote = true,
}: {
  workspaceId: string;
  type: ObjectTypeDetail;
  onClose: () => void;
  /** p.255: only the ontology level may apply `promoted`. The page knows the
   * caller's workspace role; this dialog only needs the answer. */
  canPromote?: boolean;
}) {
  const [displayName, setDisplayName] = useState(type.display_name);
  const [description, setDescription] = useState(type.description);
  const [status, setStatus] = useState(type.status);
  const [deprecation, setDeprecation] = useState(type.deprecation);
  const [properties, setProperties] = useState<PropertyInput[]>(
    type.properties.map((p) => ({
      api_name: p.api_name,
      display_name: p.display_name,
      data_type: p.data_type,
      required: p.required,
      // Carried through, or opening this dialog and saving would silently
      // reset every property to `normal` - a setting lost by editing something
      // else, which is the worst way to lose one. Value formatting joined this
      // list for exactly the same reason, and that is why the list is worth a
      // comment: every new property setting has to be added here, and nothing
      // fails if it is not.
      visibility: p.visibility,
      value_format: p.value_format,
      conditional_format: p.conditional_format,
      edit_only: p.edit_only,
      derivation: p.derivation,
      shared_property_id: p.shared_property_id,
      value_type_id: p.value_type_id,
      status: p.status,
      deprecation: p.deprecation,
    })),
  );
  const [titleProperty, setTitleProperty] = useState(
    type.properties.find((p) => p.id === type.title_property_id)?.api_name ?? "",
  );
  const [acknowledged, setAcknowledged] = useState(false);
  const queryClient = useQueryClient();

  // p.261's "Edit groups in the object type overview page". Its own query and
  // its own write, because a group is not one of this type's fields — see
  // `api.setGroupsForObjectType`.
  const currentGroups = useQuery({
    queryKey: ["object-type-groups-for", workspaceId, type.id],
    queryFn: () => objApi.groupsForObjectType(workspaceId, type.id),
  });
  const [groupIds, setGroupIds] = useState<string[] | null>(null);
  const originalGroupIds = (currentGroups.data ?? []).map((g) => g.id);
  const selectedGroupIds = groupIds ?? originalGroupIds;
  const allGroups = useQuery({
    queryKey: ["object-type-groups", workspaceId],
    queryFn: () => objApi.listObjectTypeGroups(workspaceId),
  });

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
    mutationFn: async () => {
      const updated = await objApi.updateType(workspaceId, type.id, {
        ...body,
        status,
        deprecation,
        acknowledge_breaking: blocking.length > 0,
      });
      // **Only when it actually changed**, and that condition is the whole
      // defence. The groups are their own resource with their own verb, so
      // this dialog holds two writes - and a dialog that PUT the membership on
      // every save would reintroduce the carry-through failure one layer up:
      // open the dialog, somebody else files the type under a group, change a
      // description, save, and their grouping is gone. Sending nothing when
      // nothing changed is what makes that impossible rather than unlikely.
      if (!sameSelection(selectedGroupIds, originalGroupIds)) {
        await objApi.setGroupsForObjectType(workspaceId, type.id, selectedGroupIds);
      }
      return updated;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["object-type-groups-for", workspaceId, type.id],
      });
      // The group's own member count and p.262's column both moved.
      await queryClient.invalidateQueries({
        queryKey: ["object-type-groups", workspaceId],
      });
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
        {/* p.253's developmental state, above the properties because
            p.256's propagation reaches them - the warning has to be readable
            next to what it is about to change. */}
        <StatusField
          kind="object_type"
          value={status}
          deprecation={deprecation}
          onChange={setStatus}
          onDeprecationChange={setDeprecation}
          properties={properties.map((p) => ({
            api_name: p.api_name,
            status: p.status ?? "experimental",
          }))}
          canPromote={canPromote}
        />
        {/* p.261: "Groups can also be added directly to object types by
            selecting Edit groups in the object type overview page." Drawn only
            when there is a group to pick - a checklist of nothing is a control
            that cannot do anything. */}
        {(currentGroups.data ?? []).length + (allGroups.data ?? []).length > 0 && (
          <Field
            label="Groups"
            hint="A classification for finding this type. Being in one does not change it."
          >
            <div data-testid="type-group-picker">
              {(allGroups.data ?? []).map((g) => (
                <label key={g.id} style={{ display: "block", padding: "3px 0" }}>
                  <input
                    type="checkbox"
                    data-testid={`type-group-${g.api_name}`}
                    checked={selectedGroupIds.includes(g.id)}
                    onChange={() =>
                      setGroupIds(toggleSelection(selectedGroupIds, g.id))
                    }
                  />{" "}
                  {g.display_name} <span className="slug">{g.api_name}</span>
                </label>
              ))}
            </div>
          </Field>
        )}
        <Field label="Properties" hint="Renaming a property removes it and adds a new one">
          <PropertyRows
            properties={properties}
            workspaceId={workspaceId}
            objectTypeId={type.id}
            effectiveValueTypes={Object.fromEntries(
              type.properties.map((p) => [p.api_name, p.effective_value_type_id]),
            )}
            onChange={(next) => {
              setProperties(next);
              setAcknowledged(false);  // a changed proposal is not the one that was accepted
            }}
          />
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
