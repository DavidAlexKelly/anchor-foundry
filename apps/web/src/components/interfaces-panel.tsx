"use client";

/**
 * The Interfaces section of the Ontology Manager (Foundry `object-link-types`
 * p.4, p.53; `ontology` p.60–62).
 *
 * §251 built the resource and §252 put it in two places that already answer
 * "what shapes exist here" — search, and the object type listing's new
 * *Implements* column. Neither of those could be non-empty, because nothing in
 * the browser could declare an interface or claim one. This is that, and it is
 * the same shape §165 gave shared properties and §183 gave value types: a
 * section of the ontology page rather than an application of its own, because
 * there is one ontology per workspace here and nothing to import across.
 *
 * **Two dialogs, and the split is p.60's.** What a shape *is* belongs to
 * whoever wrote `Inspectable`; what a type *claims* belongs to whoever owns
 * Vehicle. Folding them together would put "add a property to the interface"
 * and "point this type's column at it" behind one Save, and the first is a
 * change to every implementation while the second is a change to one type.
 *
 * The implement dialog is where p.66's mapping earns its keep: an interface
 * property's select offers only the object type's properties **of that base
 * type**, so three of the server's four refusals cannot be produced from here
 * at all — see `lib/interfaces.ts` for the table.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Dialog, Field } from "@/components/dialog";
import { PROPERTY_TYPES } from "@/components/object-type-editor";
import { StatusBadge, StatusField } from "@/components/status-field";
import { ApiError, objects as objApi } from "@/lib/api";
import {
  DraftProperty, blankProperty, candidates, draftProblem, extendable,
  implementationLabel, interfacePropertyTypes, suggestMapping,
  toInterfaceApiName, toPropertyApiName, unmappedRequired,
} from "@/lib/interfaces";
import { canDelete, deleteBlockedReason } from "@/lib/ontology-status";
import type {
  Deprecation, InterfaceSummary, ObjectTypeSummary, OntologyStatus,
  PropertyDataType,
} from "@/lib/types";

const TYPE_OPTIONS = interfacePropertyTypes(PROPERTY_TYPES);

/** Declaring or editing a shape.
 *
 * One dialog for both, unlike §183's value types — and the difference is the
 * reason that one is split. p.229 makes a value type's constraint *immutable*,
 * so editing a name and changing a rule are different acts with different
 * consequences. Nothing here is immutable except the API name, which is simply
 * absent from the edit form. Everything else is one document, saved together,
 * because the properties and the extension list constrain each other: adding
 * `status` here while a parent already declares it as a different base type is
 * a refusal only the pair can see.
 */
function InterfaceDialog({
  workspaceId,
  interfaceId,
  all,
  onClose,
}: {
  workspaceId: string;
  /** Absent for a new one. */
  interfaceId?: string;
  all: InterfaceSummary[];
  onClose: () => void;
}) {
  const editing = interfaceId !== undefined;
  const [displayName, setDisplayName] = useState("");
  const [apiName, setApiName] = useState("");
  // Whether somebody has typed an API name themselves. Until they do it
  // follows the display name, which is what makes the common case one field.
  const [apiNameTouched, setApiNameTouched] = useState(false);
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<OntologyStatus>("experimental");
  const [deprecation, setDeprecation] = useState<Deprecation | null>(null);
  const [properties, setProperties] = useState<DraftProperty[]>([]);
  const [extendsIds, setExtendsIds] = useState<string[]>([]);
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: ["interface", workspaceId, interfaceId],
    queryFn: () => objApi.getInterface(workspaceId, interfaceId!),
    enabled: editing,
  });

  // Loading an existing shape into the form. Keyed on the fetched object so a
  // refetch does not overwrite edits in progress with the same values.
  const loaded = detail.data;
  useEffect(() => {
    if (!loaded) return;
    setDisplayName(loaded.display_name);
    setApiName(loaded.api_name);
    setApiNameTouched(true);
    setDescription(loaded.description);
    setStatus(loaded.status);
    setDeprecation(loaded.deprecation);
    setProperties(loaded.properties.map((p) => ({ ...p })));
    setExtendsIds(loaded.extends);
  }, [loaded]);

  const effectiveApiName = apiNameTouched ? apiName : toInterfaceApiName(displayName);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        display_name: displayName,
        description,
        properties: properties.map((p) => ({
          api_name: p.api_name,
          display_name: p.display_name || null,
          description: p.description,
          data_type: p.data_type,
          required: p.required,
        })),
        extends: extendsIds,
        status,
        deprecation: status === "deprecated" ? (deprecation as Record<string, unknown> | null) : null,
      };
      return editing
        ? objApi.updateInterface(workspaceId, interfaceId!, body)
        : objApi.createInterface(workspaceId, { ...body, api_name: effectiveApiName });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["interfaces", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["interface", workspaceId] });
      // An interface's shape decides which implementations are still valid,
      // and the object type listing draws what each type claims (§252).
      await queryClient.invalidateQueries({ queryKey: ["object-types"] });
      onClose();
    },
  });

  const problem = draftProblem({
    display_name: displayName,
    api_name: effectiveApiName,
    properties,
  });

  function patch(i: number, next: Partial<DraftProperty>) {
    setProperties(properties.map((p, j) => (j === i ? { ...p, ...next } : p)));
  }

  return (
    <Dialog
      open
      title={editing ? `Edit ${apiName}` : "New interface"}
      onClose={onClose}
    >
      <p className="field-hint">
        A shape several object types can claim to have. It stores nothing of its
        own — an implementing type keeps its own properties and its own data,
        and the interface is the statement that all of them have this shape.
      </p>

      <Field label="Name">
        <input
          type="text"
          data-testid="iface-name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </Field>
      {editing ? (
        <p className="field-hint">
          API name: <code>{apiName}</code> — fixed, because it is the name
          anything pointing at this interface holds.
        </p>
      ) : (
        <Field
          label="API name"
          hint="Named like an object type (Inspectable, SchedulableResource), because an interface is one."
        >
          <input
            type="text"
            data-testid="iface-api-name"
            value={effectiveApiName}
            onChange={(e) => { setApiNameTouched(true); setApiName(e.target.value); }}
          />
        </Field>
      )}
      <Field label="Description">
        <input
          type="text"
          data-testid="iface-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>

      {/* p.53: "interfaces may extend any number of other interfaces", and
          p.62's `SchedulableResource extends Trackable` for multi-level
          abstraction. Checkboxes rather than a multi-select because the number
          is small and a multi-select hides what is already ticked. */}
      {extendable(all, interfaceId).length > 0 && (
        <Field
          label="Extends"
          hint="p.62 — everything a parent declares is part of this shape too."
        >
          <div data-testid="iface-extends">
            {extendable(all, interfaceId).map((i) => (
              <label key={i.id} className="row-actions" style={{ gap: 6 }}>
                <input
                  type="checkbox"
                  aria-label={`Extend ${i.api_name}`}
                  checked={extendsIds.includes(i.id)}
                  onChange={(e) =>
                    setExtendsIds(
                      e.target.checked
                        ? [...extendsIds, i.id]
                        : extendsIds.filter((x) => x !== i.id),
                    )
                  }
                />
                <span>{i.display_name}</span>
                <span className="slug">{i.api_name}</span>
              </label>
            ))}
          </div>
        </Field>
      )}

      <StatusField
        kind="interface"
        value={status}
        deprecation={deprecation}
        onChange={setStatus}
        onDeprecationChange={setDeprecation}
      />

      <div className="page-head" style={{ marginTop: 16 }}>
        <div><h2 style={{ fontSize: 14, margin: 0 }}>Properties</h2></div>
        {/* Above the list, for §246's reason: a control below a list that can
            shrink moves under the pointer when a row is removed. */}
        <button
          type="button"
          className="btn quiet"
          data-testid="iface-add-property"
          onClick={() => setProperties([...properties, blankProperty()])}
        >
          Add property
        </button>
      </div>
      {properties.length === 0 && (
        <p className="field-hint" data-testid="iface-no-properties">
          No properties yet. An interface with none is legal and says nothing —
          p.61&apos;s Inspectable is a last inspection date and a status.
        </p>
      )}
      {properties.length > 0 && (
        <table className="table" data-testid="iface-property-rows">
          <thead>
            <tr>
              <th>Name</th><th>API name</th><th>Type</th><th>Required</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {properties.map((p, i) => (
              <tr key={i}>
                <td>
                  <input
                    type="text"
                    aria-label={`Property ${i + 1} name`}
                    value={p.display_name}
                    onChange={(e) => {
                      const display = e.target.value;
                      // The API name follows until it has been typed, same as
                      // the interface's own — and only while it still matches
                      // what the old display name produced, so an edited one
                      // is never overwritten.
                      patch(i, {
                        display_name: display,
                        ...(p.api_name === toPropertyApiName(p.display_name)
                          ? { api_name: toPropertyApiName(display) }
                          : {}),
                      });
                    }}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    className="slug"
                    aria-label={`Property ${i + 1} API name`}
                    value={p.api_name}
                    onChange={(e) => patch(i, { api_name: e.target.value })}
                  />
                </td>
                <td>
                  <select
                    aria-label={`Property ${i + 1} type`}
                    value={p.data_type}
                    onChange={(e) =>
                      patch(i, { data_type: e.target.value as PropertyDataType })
                    }
                  >
                    {TYPE_OPTIONS.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Property ${i + 1} required`}
                    checked={p.required}
                    onChange={(e) => patch(i, { required: e.target.checked })}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn quiet"
                    style={{ padding: "3px 9px", fontSize: 12 }}
                    aria-label={`Remove property ${i + 1}`}
                    onClick={() =>
                      setProperties(properties.filter((_, j) => j !== i))
                    }
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* What this shape actually amounts to once the parents are counted.
          Only when it differs from what was declared here, because otherwise
          it is the same table twice. */}
      {editing && detail.data &&
        detail.data.effective_properties.length > detail.data.properties.length && (
        <p className="field-hint" data-testid="iface-effective">
          With everything inherited, this shape has{" "}
          {detail.data.effective_properties.length} properties:{" "}
          {detail.data.effective_properties.map((p) => p.api_name).join(", ")}.
        </p>
      )}

      {problem && <p className="field-hint" data-testid="iface-problem">{problem}</p>}
      {save.isError && (
        <p className="field-hint" data-testid="iface-error">
          {save.error instanceof ApiError ? save.error.message : "Could not save."}
        </p>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="iface-save"
          disabled={problem !== null || save.isPending}
          onClick={() => save.mutate()}
        >
          Save
        </button>
      </div>
    </Dialog>
  );
}

/** One object type's claim to one shape (p.66's mapping).
 *
 * Reached from the interface rather than from the object type, and that is
 * where p.61's argument points: you decide that Vehicle, Equipment and
 * Facility are all Inspectable while looking at Inspectable. The object type
 * listing shows the result (§252) and this is where it is set.
 */
function ImplementDialog({
  workspaceId,
  iface,
  types,
  onClose,
}: {
  workspaceId: string;
  iface: InterfaceSummary;
  types: ObjectTypeSummary[];
  onClose: () => void;
}) {
  const [typeId, setTypeId] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: ["interface", workspaceId, iface.id],
    queryFn: () => objApi.getInterface(workspaceId, iface.id),
  });
  const objectType = useQuery({
    queryKey: ["object-type", workspaceId, typeId],
    queryFn: () => objApi.getType(workspaceId, typeId),
    enabled: !!typeId,
  });
  const existing = useQuery({
    queryKey: ["implementations", workspaceId, typeId],
    queryFn: () => objApi.listImplementations(workspaceId, typeId),
    enabled: !!typeId,
  });

  const effective = detail.data?.effective_properties ?? [];
  const propertyTypes: Record<string, string> = Object.fromEntries(
    (objectType.data?.properties ?? []).map((p) => [p.api_name, p.data_type]),
  );

  // Opening mapping: whatever this type already claimed, else the suggestion.
  // Both depend on two fetches, so this waits for them rather than seeding
  // from the type alone and then correcting itself on screen.
  const already = existing.data?.find((e) => e.interface_id === iface.id);
  const ready = !!objectType.data && !!existing.data && !!detail.data;
  useEffect(() => {
    if (!ready) return;
    setMapping(already ? { ...already.property_mapping } : suggestMapping(effective, propertyTypes));
    // `effective` and `propertyTypes` are rebuilt every render; the fetched
    // objects they come from are what actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, typeId, detail.data, objectType.data, existing.data]);

  const save = useMutation({
    mutationFn: () => {
      const others = (existing.data ?? [])
        .filter((e) => e.interface_id !== iface.id)
        .map((e) => ({ interface_id: e.interface_id, property_mapping: e.property_mapping }));
      // The whole list, replacing what was there — so this type's other
      // claims have to be sent back or they are withdrawn.
      return objApi.setImplementations(workspaceId, typeId, [
        ...others,
        { interface_id: iface.id, property_mapping: mapping },
      ]);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["interfaces", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["implementations", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["object-types"] });
      onClose();
    },
  });

  const missing = unmappedRequired(effective, mapping);

  return (
    <Dialog open title={`Implement ${iface.api_name}`} onClose={onClose}>
      <p className="field-hint">
        An object type implements this shape by saying which of its own
        properties answers each of the interface&apos;s. The names need not
        match — that is the point (p.66).
      </p>
      <Field label="Object type">
        <select
          data-testid="impl-type"
          value={typeId}
          onChange={(e) => setTypeId(e.target.value)}
        >
          <option value="">Choose one…</option>
          {types.map((t) => (
            <option key={t.id} value={t.id}>{t.display_name}</option>
          ))}
        </select>
      </Field>

      {typeId && effective.length === 0 && (
        <p className="field-hint" data-testid="impl-empty-shape">
          {iface.api_name} declares no properties, so implementing it promises
          nothing. Give it some first.
        </p>
      )}

      {typeId && objectType.data && effective.length > 0 && (
        <table className="table" data-testid="impl-rows">
          <thead>
            <tr><th>Interface property</th><th>Type</th><th>Answered by</th></tr>
          </thead>
          <tbody>
            {effective.map((p) => {
              const options = candidates(p, propertyTypes);
              return (
                <tr key={p.api_name}>
                  <td>
                    <strong>{p.display_name}</strong>
                    <div className="slug">
                      {p.api_name}
                      {p.required ? "" : " · optional"}
                    </div>
                  </td>
                  <td className="count">{p.data_type}</td>
                  <td>
                    {options.length === 0 ? (
                      <span
                        className="field-hint"
                        data-testid={`impl-none-${p.api_name}`}
                      >
                        no {p.data_type} property on this type
                      </span>
                    ) : (
                      <select
                        aria-label={`Answered by for ${p.api_name}`}
                        value={mapping[p.api_name] ?? ""}
                        onChange={(e) => {
                          const next = { ...mapping };
                          if (e.target.value) next[p.api_name] = e.target.value;
                          else delete next[p.api_name];
                          setMapping(next);
                        }}
                      >
                        <option value="">—</option>
                        {options.map((name) => (
                          <option key={name} value={name}>{name}</option>
                        ))}
                      </select>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {typeId && missing.length > 0 && (
        <p className="field-hint" data-testid="impl-missing">
          {iface.api_name} requires {missing.join(", ")}, and this type answers
          nothing to {missing.length === 1 ? "it" : "them"}.
        </p>
      )}
      {save.isError && (
        <p className="field-hint" data-testid="impl-error">
          {save.error instanceof ApiError ? save.error.message : "Could not save."}
        </p>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="impl-save"
          disabled={
            !typeId || effective.length === 0 || missing.length > 0 || save.isPending
          }
          onClick={() => save.mutate()}
        >
          Save
        </button>
      </div>
    </Dialog>
  );
}

export function InterfacesPanel({
  workspaceId,
  canEdit,
  types,
}: {
  workspaceId: string;
  canEdit: boolean;
  /** The workspace's object types, for the implement dialog. Passed in rather
   * than fetched again: the page above already has them, and a second copy
   * would be a second answer to "which types exist" on one screen. */
  types: ObjectTypeSummary[];
}) {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [implementing, setImplementing] = useState<InterfaceSummary | null>(null);
  const queryClient = useQueryClient();

  const interfaces = useQuery({
    queryKey: ["interfaces", workspaceId],
    queryFn: () => objApi.listInterfaces(workspaceId),
  });

  const remove = useMutation({
    mutationFn: (id: string) => objApi.deleteInterface(workspaceId, id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["interfaces", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["object-types"] });
    },
  });

  const all = interfaces.data ?? [];

  return (
    <>
      {creating && (
        <InterfaceDialog
          workspaceId={workspaceId}
          all={all}
          onClose={() => setCreating(false)}
        />
      )}
      {editingId && (
        <InterfaceDialog
          workspaceId={workspaceId}
          interfaceId={editingId}
          all={all}
          onClose={() => setEditingId(null)}
        />
      )}
      {implementing && (
        <ImplementDialog
          workspaceId={workspaceId}
          iface={implementing}
          types={types}
          onClose={() => setImplementing(null)}
        />
      )}

      <div className="page-head" style={{ marginTop: 32 }}>
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Interfaces</h2>
          <p className="sub">A shape several object types can claim to have</p>
        </div>
        {canEdit && (
          <button
            className="btn quiet"
            data-testid="new-interface"
            onClick={() => setCreating(true)}
          >
            New interface
          </button>
        )}
      </div>
      {interfaces.data && interfaces.data.length === 0 && (
        <p className="login-note">
          None yet — an interface is worth declaring when several object types
          share a shape you want to act on together, like every type that can be
          inspected having a last inspection date and a status.
        </p>
      )}
      {interfaces.data && interfaces.data.length > 0 && (
        <table className="table" style={{ marginBottom: 28 }} data-testid="iface-table">
          <thead>
            <tr>
              <th>Interface</th><th>Properties</th><th>Implemented by</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {all.map((i) => (
              <tr key={i.id}>
                <td>
                  <strong>{i.display_name}</strong>
                  <StatusBadge status={i.status} />
                  <div className="slug">{i.api_name}</div>
                </td>
                {/* Its own declarations. The resolved count is in the edit
                    dialog, where the parents that explain the difference are
                    also on screen. */}
                <td className="count" data-testid={`iface-props-${i.api_name}`}>
                  {i.property_count}
                </td>
                <td data-testid={`iface-impls-${i.api_name}`}>
                  {implementationLabel(i.implementation_count)}
                </td>
                <td>
                  <div className="row-actions">
                    {canEdit && (
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`Implement ${i.api_name}`}
                        onClick={() => setImplementing(i)}
                      >
                        Implement
                      </button>
                    )}
                    {canEdit && (
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`Edit ${i.api_name}`}
                        onClick={() => setEditingId(i.id)}
                      >
                        Edit
                      </button>
                    )}
                    {canEdit && (
                      <button
                        className="btn danger"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`Delete ${i.api_name}`}
                        // **Disabled only for the refusal this row can see in
                        // full.** p.256's status gate is decided by one value
                        // that is right here. The other refusal — anything
                        // implementing *or extending* it — is half visible:
                        // the summary carries the implementation count and not
                        // the extension count, so disabling on it would leave
                        // an interface two others extend looking deletable
                        // anyway. That one arrives as the server's sentence
                        // with the names in it, which is the better answer.
                        disabled={remove.isPending || !canDelete(i.status)}
                        title={
                          deleteBlockedReason(i.status)
                            ?? (i.implementation_count > 0
                              ? `${implementationLabel(i.implementation_count)} implement${
                                  i.implementation_count === 1 ? "s" : ""
                                } it — change those first`
                              : "Nothing implements it")
                        }
                        onClick={() => remove.mutate(i.id)}
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
      {remove.isError && (
        <p className="field-hint" data-testid="iface-delete-error">
          {remove.error instanceof ApiError
            ? remove.error.message
            : "Could not delete."}
        </p>
      )}
    </>
  );
}
