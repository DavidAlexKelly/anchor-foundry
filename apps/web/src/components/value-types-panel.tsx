"use client";

/**
 * The Value Types page (Foundry `object-link-types` p.222–234).
 *
 * Foundry puts these in a **Value Types Manager** application of their own,
 * scoped to a platform *space* (p.222, p.224 step 1). There is one ontology
 * per workspace here and no space-level sharing to import across, so this is a
 * section of the ontology page beside Shared properties — the same decision,
 * for the same reason, as §165 made for that panel.
 *
 * **Editing a name and editing a rule are two different buttons**, and that is
 * p.229 rather than a layout choice: "the metadata values for name,
 * description, and apiName can be changed whenever necessary. The base type
 * metadata and the constraints … are immutable." One dialog for both would put
 * a versioned change and an unversioned one behind the same Save, and nobody
 * would know which they had made.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Dialog, Field } from "@/components/dialog";
import { PROPERTY_TYPES } from "@/components/object-type-editor";
import { ValueConstraintEditor } from "@/components/value-constraint-editor";
import { ApiError, objects as objApi } from "@/lib/api";
import { constraintProblem } from "@/lib/value-type";
import type { PropertyDataType, ValueConstraint, ValueType } from "@/lib/types";

function toApiName(display: string): string {
  const words = display.match(/[A-Za-z0-9]+/g) ?? [];
  return words.map((w) => w.toLowerCase()).join("_").slice(0, 100);
}

/** p.224's creation modal: name, description, api name, base type, constraint,
 * example value. All six in one form, because a value type with no constraint
 * and no example is legal but nearly useless, and asking twice would make the
 * useful version the harder one to reach. */
function CreateValueTypeDialog({
  workspaceId,
  onClose,
}: {
  workspaceId: string;
  onClose: () => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [exampleValue, setExampleValue] = useState("");
  const [baseType, setBaseType] = useState<PropertyDataType>("string");
  const [constraint, setConstraint] = useState<ValueConstraint | null>(null);
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: () =>
      objApi.createValueType(workspaceId, {
        api_name: toApiName(displayName),
        display_name: displayName,
        description,
        example_value: exampleValue,
        base_type: baseType,
        constraint,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["value-types", workspaceId] });
      onClose();
    },
  });

  const problem = constraintProblem(constraint, baseType);

  return (
    <Dialog open title="New value type" onClose={onClose}>
      <p className="field-hint">
        A value type says what a value <em>means</em> and, optionally, what it is
        allowed to be. Properties across the ontology can use it, and changing
        its rule changes theirs.
      </p>
      <Field label="Name">
        <input
          type="text"
          data-testid="vt-name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </Field>
      <p className="field-hint" data-testid="vt-api-name">
        API name: <code>{toApiName(displayName) || "…"}</code>
      </p>
      <Field label="Description">
        <input
          type="text"
          data-testid="vt-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      <Field
        label="Base type"
        hint="Fixed once saved (p.229) — a value type whose base type changed would be attached to properties it can no longer describe."
      >
        <select
          data-testid="vt-base-type"
          value={baseType}
          onChange={(e) => {
            setBaseType(e.target.value as PropertyDataType);
            // A constraint belongs to a base type (p.233), so keeping one
            // across a retype would keep a rule the save then refuses.
            setConstraint(null);
          }}
        >
          {PROPERTY_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </Field>
      <ValueConstraintEditor
        baseType={baseType}
        value={constraint}
        onChange={setConstraint}
      />
      <Field
        label="Example value"
        hint="p.225 step 7 — what a conforming value looks like, so nobody has to read the rule to find out."
      >
        <input
          type="text"
          data-testid="vt-example"
          value={exampleValue}
          onChange={(e) => setExampleValue(e.target.value)}
        />
      </Field>
      {save.isError && (
        <p className="field-hint" data-testid="vt-error">
          {save.error instanceof ApiError ? save.error.message : "Could not save."}
        </p>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="vt-save"
          disabled={!displayName.trim() || problem !== null || save.isPending}
          onClick={() => save.mutate()}
        >
          Save
        </button>
      </div>
    </Dialog>
  );
}

/** p.229's other half: a constraint change appends a version. Its own dialog,
 * and its own button, because the consequence is different — every property
 * using this value type starts being judged by the new rule (p.230). */
function NewVersionDialog({
  workspaceId,
  valueType,
  onClose,
}: {
  workspaceId: string;
  valueType: ValueType;
  onClose: () => void;
}) {
  const [constraint, setConstraint] = useState<ValueConstraint | null>(
    valueType.constraint,
  );
  const queryClient = useQueryClient();

  const versions = useQuery({
    queryKey: ["value-type-versions", workspaceId, valueType.id],
    queryFn: () => objApi.valueTypeVersions(workspaceId, valueType.id),
  });

  const save = useMutation({
    mutationFn: () =>
      objApi.addValueTypeVersion(workspaceId, valueType.id, constraint),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["value-types", workspaceId] });
      // Every property using it resolves the rule on read (p.230), so every
      // object type detail in the cache is now stale by exactly this change.
      await queryClient.invalidateQueries({ queryKey: ["object-type"] });
      onClose();
    },
  });

  const problem = constraintProblem(constraint, valueType.base_type);

  return (
    <Dialog open title={`New version of ${valueType.api_name}`} onClose={onClose}>
      <p className="field-hint">
        The rule is immutable once saved, so changing it adds a version (p.229).
        Every property using this value type is judged by the newest one
        {valueType.usage_count > 0 ? ` — ${valueType.usage_count} of them.` : "."}
      </p>
      <ValueConstraintEditor
        baseType={valueType.base_type}
        value={constraint}
        onChange={setConstraint}
      />
      {save.isError && (
        <p className="field-hint" data-testid="vt-version-error">
          {save.error instanceof ApiError ? save.error.message : "Could not save."}
        </p>
      )}
      {versions.data && versions.data.length > 0 && (
        <>
          <p className="field-hint" style={{ marginTop: 14 }}>Previous versions</p>
          <table className="table" data-testid="vt-version-table">
            <thead><tr><th>Version</th><th>Rule</th></tr></thead>
            <tbody>
              {versions.data.map((v) => (
                <tr key={v.id}>
                  <td className="count">{v.version_number}</td>
                  <td>{v.constraint_summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="vt-version-save"
          disabled={problem !== null || save.isPending}
          onClick={() => save.mutate()}
        >
          Add version
        </button>
      </div>
    </Dialog>
  );
}

function UsageDialog({
  workspaceId,
  valueType,
  onClose,
}: {
  workspaceId: string;
  valueType: ValueType;
  onClose: () => void;
}) {
  const usage = useQuery({
    queryKey: ["value-type-usage", workspaceId, valueType.id],
    queryFn: () => objApi.valueTypeUsage(workspaceId, valueType.id),
  });
  return (
    <Dialog open title={`${valueType.api_name} is used by`} onClose={onClose}>
      {usage.data && usage.data.length === 0 && (
        <p className="field-hint">Nothing uses it yet.</p>
      )}
      {usage.data && usage.data.length > 0 && (
        <table className="table" data-testid="vt-usage-table">
          <thead><tr><th>Where</th><th>Property</th></tr></thead>
          <tbody>
            {usage.data.map((u, i) => (
              <tr key={i}>
                {/* p.227's two places, told apart - "email on Contact" and
                    "the contact_email shared property" are different things
                    to go and look at. */}
                <td>{u.kind === "shared_property" ? "Shared property" : u.owner_name}</td>
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

export function ValueTypesPanel({
  workspaceId,
  canEdit,
}: {
  workspaceId: string;
  canEdit: boolean;
}) {
  const [creating, setCreating] = useState(false);
  const [versioning, setVersioning] = useState<ValueType | null>(null);
  const [showingUsage, setShowingUsage] = useState<ValueType | null>(null);
  const queryClient = useQueryClient();

  const types = useQuery({
    queryKey: ["value-types", workspaceId],
    queryFn: () => objApi.listValueTypes(workspaceId),
  });

  const remove = useMutation({
    mutationFn: (id: string) => objApi.deleteValueType(workspaceId, id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["value-types", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["object-type"] });
    },
  });

  return (
    <>
      {creating && (
        <CreateValueTypeDialog
          workspaceId={workspaceId}
          onClose={() => setCreating(false)}
        />
      )}
      {versioning && (
        <NewVersionDialog
          workspaceId={workspaceId}
          valueType={versioning}
          onClose={() => setVersioning(null)}
        />
      )}
      {showingUsage && (
        <UsageDialog
          workspaceId={workspaceId}
          valueType={showingUsage}
          onClose={() => setShowingUsage(null)}
        />
      )}

      <div className="page-head" style={{ marginTop: 32 }}>
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Value types</h2>
          <p className="sub">
            What a value means, and what it is allowed to be
          </p>
        </div>
        {canEdit && (
          <button
            className="btn quiet"
            data-testid="new-value-type"
            onClick={() => setCreating(true)}
          >
            New value type
          </button>
        )}
      </div>
      {types.data && types.data.length === 0 && (
        <p className="login-note">
          None yet — a value type is worth creating when the same rule applies
          in more than one place, like an email address or a country code.
        </p>
      )}
      {types.data && types.data.length > 0 && (
        <table className="table" style={{ marginBottom: 28 }} data-testid="vt-table">
          <thead>
            <tr>
              <th>Value type</th><th>Base type</th><th>Rule</th><th>Version</th>
              <th>Used by</th><th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {types.data.map((t) => (
              <tr key={t.id}>
                <td>
                  <strong>{t.display_name}</strong>
                  <div className="slug">{t.api_name}</div>
                </td>
                <td className="count">{t.base_type}</td>
                {/* The server's own sentence, so the browser cannot disagree
                    with it about what a rule says. */}
                <td data-testid={`vt-rule-${t.api_name}`}>{t.constraint_summary}</td>
                <td className="count">v{t.version_number}</td>
                <td>
                  <button
                    className="btn quiet"
                    style={{ padding: "3px 9px", fontSize: 12 }}
                    aria-label={`Usage of ${t.api_name}`}
                    onClick={() => setShowingUsage(t)}
                  >
                    {t.usage_count}
                  </button>
                </td>
                <td>
                  <div className="row-actions">
                    {canEdit && (
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`New version of ${t.api_name}`}
                        onClick={() => setVersioning(t)}
                      >
                        Change rule
                      </button>
                    )}
                    {canEdit && (
                      <button
                        className="btn danger"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`Delete ${t.api_name}`}
                        disabled={remove.isPending}
                        title={
                          t.usage_count
                            ? `${t.usage_count} propert${
                                t.usage_count === 1 ? "y" : "ies"
                              } will stop being constrained`
                            : "Nothing uses it"
                        }
                        onClick={() => remove.mutate(t.id)}
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
