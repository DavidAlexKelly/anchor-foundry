"use client";

/**
 * The Functions section of the ontology page (decision 0018 option B; §769;
 * Foundry `ontology-manager` p.29 lists Functions among the home page's
 * sections, and `functions` p.49-50 sets out how they are versioned).
 *
 * **Publish and run, and nothing between.** A function here is SQL over the
 * ontology, so writing one is a query and its parameters. The dialog says what
 * would be refused while the fields are on screen (`lib/functions`); the server
 * then runs the query against empty inputs before it keeps a version, and
 * says what is wrong with it if it fails.
 *
 * **A published version never changes** (p.49), so there is no Edit: the
 * button is "New version", which starts from the newest one with the next
 * patch number, for the author to change.
 */

import { useEffect, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Dialog, Field } from "@/components/dialog";
import { TypePicker } from "@/components/type-picker";
import { ApiError, objects as objApi } from "@/lib/api";
import {
  BATCH_FIELD_TYPES, OUTPUT_KINDS, PARAMETER_TYPES, SCALAR_TYPES, blankDraft, blankField,
  blankParameter, bodyOf, draftOf,
  draftProblem, editedTypes, editsOver, refersToObjects, resultLine, valuesFor,
  type DraftVersion,
} from "@/lib/functions";
import type {
  FunctionBatchField, FunctionDetail, FunctionParameter, FunctionSummary,
} from "@/lib/types";

function toApiName(display: string): string {
  const words = display.match(/[A-Za-z0-9]+/g) ?? [];
  return words.map((w) => w.toLowerCase()).join("_").slice(0, 100);
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Could not save.";
}

/** The tables the query may read: each input, by api_name, with its columns,
 * so nobody has to leave the dialog to look them up. */
function InputTables({ workspaceId, inputs, onRemove }: {
  workspaceId: string;
  inputs: string[];
  onRemove: (id: string) => void;
}) {
  const types = useQueries({
    queries: inputs.map((id) => ({
      queryKey: ["object-type", id],
      queryFn: () => objApi.getType(workspaceId, id),
    })),
  });
  if (inputs.length === 0) {
    return <p className="field-hint" data-testid="fn-no-inputs">Reads no object types.</p>;
  }
  return (
    <ul data-testid="fn-inputs" style={{ margin: "4px 0 8px", paddingLeft: 18 }}>
      {inputs.map((id, i) => {
        const t = types[i]?.data;
        return (
          <li key={id} className="field-hint">
            <code>{t?.api_name ?? "…"}</code>
            {t && ` (__id, __primary_key, ${t.properties.map((p) => p.api_name).join(", ")})`}
            <button
              type="button"
              className="btn quiet"
              style={{ marginLeft: 6, padding: "1px 6px", fontSize: 11 }}
              aria-label={`Stop reading ${t?.api_name ?? id}`}
              onClick={() => onRemove(id)}
            >
              ×
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function ParameterRow({ workspaceId, index, value, onChange, onRemove }: {
  workspaceId: string;
  index: number;
  value: FunctionParameter;
  onChange: (next: FunctionParameter) => void;
  onRemove: () => void;
}) {
  const n = index + 1;
  return (
    <div className="row-actions" style={{ gap: 6, marginBottom: 6, flexWrap: "wrap" }}>
      <input
        type="text"
        aria-label={`Parameter ${n} name`}
        placeholder="name"
        value={value.api_name}
        onChange={(e) => onChange({ ...value, api_name: e.target.value })}
      />
      <select
        aria-label={`Parameter ${n} type`}
        value={value.data_type}
        onChange={(e) => onChange({
          ...value, data_type: e.target.value as FunctionParameter["data_type"],
          object_type_id: null,
        })}
      >
        {PARAMETER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      {refersToObjects(value.data_type) && (
        <TypePicker
          workspaceId={workspaceId}
          testId={`fn-param-${n}-type`}
          placeholder="Choose an object type…"
          value={value.object_type_id}
          onChange={(id) => onChange({ ...value, object_type_id: id || null })}
        />
      )}
      {value.data_type === "batch" && (
        // action-types p.85's struct (§779): the fields each entry carries,
        // read in the query with `unnest($name)`.
        <div data-testid={`fn-param-${n}-fields`} style={{ flexBasis: "100%", paddingLeft: 16 }}>
          {(value.fields ?? []).map((f, i) => {
            const setField = (next: FunctionBatchField) => onChange({
              ...value, fields: (value.fields ?? []).map((g, j) => (j === i ? next : g)) });
            return (
              <div key={i} className="row-actions" style={{ gap: 6, marginBottom: 4 }}>
                <input type="text" aria-label={`Parameter ${n} field ${i + 1} name`}
                  placeholder="field" value={f.api_name}
                  onChange={(e) => setField({ ...f, api_name: e.target.value })} />
                <select aria-label={`Parameter ${n} field ${i + 1} type`} value={f.data_type}
                  onChange={(e) => setField({ ...f,
                    data_type: e.target.value as FunctionBatchField["data_type"],
                    object_type_id: null })}>
                  {BATCH_FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                {f.data_type === "object" && (
                  <TypePicker workspaceId={workspaceId} testId={`fn-param-${n}-field-${i + 1}-type`}
                    placeholder="Choose an object type…" value={f.object_type_id ?? null}
                    onChange={(id) => setField({ ...f, object_type_id: id || null })} />
                )}
                <button type="button" className="btn quiet"
                  aria-label={`Remove parameter ${n} field ${i + 1}`}
                  onClick={() => onChange({ ...value,
                    fields: (value.fields ?? []).filter((_, j) => j !== i) })}>Remove</button>
              </div>
            );
          })}
          <button type="button" className="btn quiet" data-testid={`fn-param-${n}-add-field`}
            onClick={() => onChange({ ...value, fields: [...(value.fields ?? []), blankField()] })}>
            Add field
          </button>
        </div>
      )}
      <label style={{ fontSize: 12 }}>
        <input
          type="checkbox"
          aria-label={`Parameter ${n} required`}
          checked={value.required}
          onChange={(e) => onChange({ ...value, required: e.target.checked })}
        />{" "}
        required
      </label>
      <button type="button" className="btn quiet" aria-label={`Remove parameter ${n}`}
        onClick={onRemove}>Remove</button>
    </div>
  );
}

function VersionDialog({ workspaceId, existing, onClose }: {
  workspaceId: string;
  /** Absent for a new function. */
  existing?: FunctionDetail;
  onClose: () => void;
}) {
  const latest = existing?.versions[0];
  const [draft, setDraft] = useState<DraftVersion>(() => latest ? draftOf(latest) : blankDraft());
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [adding, setAdding] = useState("");
  const queryClient = useQueryClient();
  const set = (next: Partial<DraftVersion>) => setDraft({ ...draft, ...next });

  const save = useMutation({
    mutationFn: () => existing
      ? objApi.addFunctionVersion(workspaceId, existing.id, bodyOf(draft))
      : objApi.createFunction(workspaceId, {
          api_name: toApiName(displayName), display_name: displayName, description,
          version: bodyOf(draft),
        }),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: ["functions", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["function", saved.id] });
      onClose();
    },
  });

  const problem = (!existing && !toApiName(displayName))
    ? "Give the function a name."
    : draftProblem(draft, latest?.version ?? null);

  return (
    <Dialog
      open
      wide
      title={existing ? `New version of ${existing.api_name}` : "New function"}
      onClose={onClose}
    >
      <p className="field-hint">
        A function is a query over the ontology that widgets and actions can call.
        A published version never changes; a change is a new version (p.49).
      </p>
      {!existing && (
        <>
          <Field label="Name">
            <input type="text" data-testid="fn-name" value={displayName}
              onChange={(e) => setDisplayName(e.target.value)} />
          </Field>
          <p className="field-hint" data-testid="fn-api-name">
            API name: <code>{toApiName(displayName) || "…"}</code>
          </p>
          <Field label="Description">
            <input type="text" data-testid="fn-description" value={description}
              onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </>
      )}
      <Field label="Version" hint="A semantic version, such as 1.0.0 (p.50).">
        <input type="text" data-testid="fn-version" value={draft.version}
          onChange={(e) => set({ version: e.target.value })} />
      </Field>

      <Field label="Reads" hint="Each object type is a table the query can name.">
        <div>
          <InputTables
            workspaceId={workspaceId}
            inputs={draft.inputs}
            onRemove={(id) => set({ inputs: draft.inputs.filter((i) => i !== id) })}
          />
          <div className="row-actions" style={{ gap: 6 }}>
            <TypePicker
              workspaceId={workspaceId}
              testId="fn-input-picker"
              placeholder="Choose an object type…"
              value={adding || null}
              onChange={setAdding}
            />
            <button
              type="button"
              className="btn quiet"
              data-testid="fn-add-input"
              disabled={!adding || draft.inputs.includes(adding)}
              onClick={() => {
                set({ inputs: [...draft.inputs, adding] });
                setAdding("");
              }}
            >
              Add
            </button>
          </div>
        </div>
      </Field>

      <Field label="Parameters" hint="Named in the query as $name.">
        <div data-testid="fn-parameters">
          {draft.parameters.map((p, i) => (
            <ParameterRow
              key={i}
              workspaceId={workspaceId}
              index={i}
              value={p}
              onChange={(next) => set({
                parameters: draft.parameters.map((q, j) => (j === i ? next : q)),
              })}
              onRemove={() => set({ parameters: draft.parameters.filter((_, j) => j !== i) })}
            />
          ))}
          <button type="button" className="btn quiet" data-testid="fn-add-parameter"
            onClick={() => set({ parameters: [...draft.parameters, blankParameter()] })}>
            Add parameter
          </button>
        </div>
      </Field>

      <Field label="Returns">
        <div className="row-actions" style={{ gap: 6 }}>
          <select
            data-testid="fn-output-kind"
            value={draft.output.kind}
            onChange={(e) => set({ output: {
              kind: e.target.value as DraftVersion["output"]["kind"], data_type: "integer",
            } })}
          >
            {OUTPUT_KINDS.map((o) => <option key={o.kind} value={o.kind}>{o.label}</option>)}
          </select>
          {(draft.output.kind === "value" || draft.output.kind === "array") && (
            <select
              data-testid="fn-output-type"
              aria-label="Returns a"
              value={draft.output.data_type ?? ""}
              onChange={(e) => set({ output: { ...draft.output, data_type: e.target.value } })}
            >
              {SCALAR_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          )}
          {(draft.output.kind === "object_set" || draft.output.kind === "map") && (
            <TypePicker
              workspaceId={workspaceId}
              testId="fn-output-object"
              placeholder="Choose an object type…"
              value={draft.output.object_type_id ?? null}
              onChange={(id) => set({ output: { kind: draft.output.kind, object_type_id: id } })}
            />
          )}
        </div>
      </Field>
      {draft.output.kind === "object_set" && (
        <p className="field-hint">The query's first column is the objects' primary keys.</p>
      )}
      {draft.output.kind === "aggregation" && (
        <p className="field-hint">
          A bucket and a value, or a bucket, a segment and a value, as a Chart XY
          layer draws them (Workshop p.284).
        </p>
      )}
      {draft.output.kind === "edits" && (
        <EditedTypes
          workspaceId={workspaceId}
          types={editedTypes(draft.output)}
          onChange={(types) => set({ output: editsOver(types) })}
        />
      )}
      {draft.output.kind === "map" && (
        <p className="field-hint">
          The query's first column is each object&apos;s primary key, and every other
          column a value for it — what an Object Table&apos;s function-backed column shows
          (Workshop p.221).
        </p>
      )}

      <Field label="Query" hint="One SELECT. It runs over the tables above, and nothing else.">
        <textarea
          data-testid="fn-sql"
          rows={6}
          spellCheck={false}
          style={{ fontFamily: "var(--font-mono, monospace)" }}
          value={draft.sql}
          onChange={(e) => set({ sql: e.target.value })}
        />
      </Field>

      {problem && <p className="field-hint" data-testid="fn-problem">{problem}</p>}
      {save.isError && <p className="form-error" data-testid="fn-error">{errorText(save.error)}</p>}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="fn-save"
          disabled={problem !== null || save.isPending}
          onClick={() => save.mutate()}
        >
          Publish {draft.version}
        </button>
      </div>
    </Dialog>
  );
}

function RunDialog({ workspaceId, fn, onClose }: {
  workspaceId: string;
  fn: FunctionDetail;
  onClose: () => void;
}) {
  const [version, setVersion] = useState(fn.versions[0]?.version ?? "");
  const [typed, setTyped] = useState<Record<string, string>>({});
  const chosen = fn.versions.find((v) => v.version === version) ?? fn.versions[0];
  const run = useMutation({
    mutationFn: () => objApi.executeFunction(
      workspaceId, fn.id, valuesFor(chosen?.parameters ?? [], typed), version),
  });
  const result = run.data;
  return (
    <Dialog open wide title={`Run ${fn.api_name}`} onClose={onClose}>
      <Field label="Version">
        <select data-testid="fn-run-version" value={version}
          onChange={(e) => { setVersion(e.target.value); run.reset(); }}>
          {fn.versions.map((v) => <option key={v.id} value={v.version}>{v.version}</option>)}
        </select>
      </Field>
      {(chosen?.parameters ?? []).map((p) => (
        <Field
          key={p.api_name}
          label={p.api_name}
          hint={`${p.data_type === "object" ? "an object's id"
            : p.data_type === "object_set" ? "primary keys, separated by commas"
            : p.data_type}${p.required ? "" : ", optional"}`}
        >
          <input
            type="text"
            aria-label={`Value of ${p.api_name}`}
            value={typed[p.api_name] ?? ""}
            onChange={(e) => setTyped({ ...typed, [p.api_name]: e.target.value })}
          />
        </Field>
      ))}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Close</button>
        <button type="button" className="btn primary" data-testid="fn-run"
          disabled={run.isPending} onClick={() => run.mutate()}>
          Run
        </button>
      </div>
      {run.isError && <p className="form-error" data-testid="fn-run-error">{errorText(run.error)}</p>}
      {result && (
        <div data-testid="fn-result" style={{ marginTop: 12 }}>
          <p className="field-hint" data-testid="fn-result-line">{resultLine(result)}</p>
          {(result.kind === "array" || result.kind === "object_set") && (
            <ul data-testid="fn-result-values">
              {(result.values ?? []).map((v, i) => <li key={i}>{String(v)}</li>)}
            </ul>
          )}
          {result.kind === "aggregation" && (
            <table className="table" data-testid="fn-result-buckets">
              <tbody>
                {(result.buckets ?? []).map((b, i) => (
                  <tr key={i}>
                    <td>{b.key}</td>
                    {result.dimensions === 3 && <td>{b.segment}</td>}
                    <td>{b.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result.kind === "map" && (
            <table className="table" data-testid="fn-result-map">
              <thead>
                <tr>
                  <th>Object</th>
                  {(result.columns ?? []).map((c) => <th key={c.name}>{c.name}</th>)}
                </tr>
              </thead>
              <tbody>
                {Object.entries(result.entries ?? {}).map(([key, fields]) => (
                  <tr key={key}>
                    <td>{key}</td>
                    {(result.columns ?? []).map((c) => (
                      <td key={c.name}>{String(fields[c.name] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result.kind === "edits" && (result.edits ?? []).some((e) => e.edit) && (
            <table className="table" data-testid="fn-result-edits">
              <thead>
                <tr><th>Type</th><th>Object</th><th>Edit</th><th>Properties</th></tr>
              </thead>
              <tbody>
                {(result.edits ?? []).map((e) => (
                  <tr key={`${e.object_type}-${e.primary_key}`}>
                    <td>{e.object_type}</td>
                    <td>{e.primary_key}</td>
                    <td>{e.edit}</td>
                    <td>{Object.keys(e.properties).length ? JSON.stringify(e.properties) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result.kind === "edits" && !(result.edits ?? []).some((e) => e.edit) && (
            <table className="table" data-testid="fn-result-edits">
              <thead>
                <tr>
                  <th>Object</th>
                  {(result.columns ?? []).map((c) => <th key={c.name}>{c.name}</th>)}
                </tr>
              </thead>
              <tbody>
                {(result.edits ?? []).map((e) => (
                  <tr key={e.primary_key}>
                    <td>{e.primary_key}</td>
                    {(result.columns ?? []).map((c) => (
                      <td key={c.name}>{String(e.properties[c.name] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result.kind === "table" && (
            <table className="table" data-testid="fn-result-table">
              <thead>
                <tr>{(result.columns ?? []).map((c) => <th key={c.name}>{c.name}</th>)}</tr>
              </thead>
              <tbody>
                {(result.rows ?? []).map((row, i) => (
                  <tr key={i}>{row.map((cell, j) => <td key={j}>{String(cell ?? "")}</td>)}</tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Dialog>
  );
}

export function FunctionsPanel({ workspaceId, canEdit, openId: asked = null, onOpened }: {
  workspaceId: string;
  canEdit: boolean;
  /** A function the header search found (§777), opened to run: the dialog
   * that shows what it takes and returns. */
  openId?: string | null;
  onOpened?: () => void;
}) {
  const [creating, setCreating] = useState(false);
  const [versioning, setVersioning] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  useEffect(() => {
    if (!asked) return;
    setRunning(asked);
    onOpened?.();
  }, [asked, onOpened]);
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["functions", workspaceId],
    queryFn: () => objApi.listFunctions(workspaceId),
  });
  const openId = versioning ?? running;
  const detail = useQuery({
    queryKey: ["function", openId],
    queryFn: () => objApi.getFunction(workspaceId, openId!),
    enabled: !!openId,
  });
  const remove = useMutation({
    mutationFn: (id: string) => objApi.deleteFunction(workspaceId, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["functions", workspaceId] }),
  });

  return (
    <>
      {creating && <VersionDialog workspaceId={workspaceId} onClose={() => setCreating(false)} />}
      {versioning && detail.data && (
        <VersionDialog workspaceId={workspaceId} existing={detail.data}
          onClose={() => setVersioning(null)} />
      )}
      {running && detail.data && (
        <RunDialog workspaceId={workspaceId} fn={detail.data} onClose={() => setRunning(null)} />
      )}
      <div className="page-head" style={{ marginTop: 32 }}>
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Functions</h2>
          <p className="sub">Queries over the ontology that widgets and actions can call</p>
        </div>
        {canEdit && (
          <button className="btn quiet" data-testid="new-function" onClick={() => setCreating(true)}>
            New function
          </button>
        )}
      </div>
      {list.data && list.data.length === 0 && (
        <p className="login-note">
          None yet — a function is worth writing when a widget or an action needs an
          answer the ontology does not store, such as a total across objects.
        </p>
      )}
      {list.data && list.data.length > 0 && (
        <table className="table" style={{ marginBottom: 28 }} data-testid="functions-table">
          <thead>
            <tr><th>Function</th><th>Version</th><th aria-label="Actions" /></tr>
          </thead>
          <tbody>
            {list.data.map((f: FunctionSummary) => (
              <tr key={f.id}>
                <td>
                  <strong>{f.display_name}</strong>
                  <div className="slug">{f.api_name}</div>
                  {f.description && <div className="field-hint">{f.description}</div>}
                </td>
                <td className="count" data-testid={`fn-version-${f.api_name}`}>
                  {f.latest_version}
                </td>
                <td>
                  <div className="row-actions">
                    <button className="btn quiet" style={{ padding: "3px 9px", fontSize: 12 }}
                      aria-label={`Run ${f.api_name}`} onClick={() => setRunning(f.id)}>
                      Run
                    </button>
                    {canEdit && (
                      <button className="btn quiet" style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`New version of ${f.api_name}`}
                        onClick={() => setVersioning(f.id)}>
                        New version
                      </button>
                    )}
                    {canEdit && (
                      <button className="btn danger" style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`Delete ${f.api_name}`} disabled={remove.isPending}
                        onClick={() => remove.mutate(f.id)}>
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

/** The object types an edit function edits (§773, §783). p.75: "Create several
 * different types of objects and set up links between them" - so a function
 * may edit several, and then each row of its query says whose it is. */
function EditedTypes({ workspaceId, types, onChange }: {
  workspaceId: string;
  types: string[];
  onChange: (types: string[]) => void;
}) {
  return (
    <div data-testid="fn-output-objects">
      {types.map((t, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 4 }}>
          <TypePicker
            workspaceId={workspaceId}
            testId={i === 0 ? "fn-output-object" : `fn-output-object-${i + 1}`}
            placeholder="Choose an object type…"
            value={t || null}
            onChange={(id) => onChange(types.map((u, j) => (j === i ? id ?? "" : u)))}
          />
          {types.length > 1 && (
            <button type="button" className="link-button" aria-label={`Remove edited type ${i + 1}`}
                    onClick={() => onChange(types.filter((_u, j) => j !== i))}>
              Remove
            </button>
          )}
        </div>
      ))}
      <button type="button" className="link-button" onClick={() => onChange([...types, ""])}>
        Add an object type
      </button>
      <p className="field-hint">
        {types.length === 1
          ? <>The query&apos;s first column is the primary key of each object to change, and
              every other column a property to set on it. An object that does not exist is
              created — what an action&apos;s Function rule applies (action-types p.75).
              To edit several object types, or to delete, give the four columns below.</>
          : <>Each row says what becomes of one object (action-types p.75).</>}
        {" "}<code>__object_type</code> (its type&apos;s API name), <code>__primary_key</code>,
        {" "}<code>__edit</code> (create, modify or delete) and <code>__properties</code>, a JSON
        object of the properties to set, such as <code>json_object(&apos;status&apos;,
        &apos;closed&apos;)</code>. A <code>link</code> or <code>unlink</code> names a link type
        and the key at its other end instead, such as <code>json_object(&apos;flown_by&apos;,
        &apos;3&apos;)</code>.
      </p>
    </div>
  );
}
