"use client";

/**
 * Webhooks, on the source they belong to (`data-connection` p.216-242; §261).
 *
 * p.220: "Once the source has been created, select the Webhooks tab and select
 * New webhook." So this sits on the connections screen rather than on one of
 * its own — a webhook without a source is not a thing p.216 has a word for.
 *
 * §259 built the resource and §260 the action rule, and left both reachable
 * only by posting JSON. That is the shape §258 closed for the notify rule and
 * §252 before it: **a feature the product cannot express does not exist for
 * the person who would use it.**
 *
 * Its own file rather than a section inside `connections/page.tsx`, which is
 * already 1,164 lines: p.221's wizard is seven steps and p.222 adds a test
 * call with a response to read, which is more than the sync configuration it
 * would sit beside. The rules that decide what this offers are in
 * `lib/webhook-form`, where a wrong answer is a line.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import { ApiError, webhooks as api } from "@/lib/api";
import {
  INPUT_TYPES, METHODS, OUTPUT_TYPES, WebhookDraft, blankWebhook, bodyProblem,
  outcomeLabel, parsedBody, problem, suggestedApiName,
} from "@/lib/webhook-form";
import type { Connection, Webhook, WebhookRun } from "@/lib/types";

/** A webhook as the API takes it. The body is parsed here rather than in the
 * form, because the form has to hold half-finished JSON and the wire cannot. */
function payload(draft: WebhookDraft): Record<string, unknown> {
  return {
    connection_id: draft.connection_id,
    api_name: draft.api_name,
    display_name: draft.display_name,
    description: draft.description,
    method: draft.method,
    path: draft.path,
    query: draft.query,
    headers: draft.headers,
    body: parsedBody(draft.bodyText) ?? null,
    inputs: draft.inputs,
    outputs: draft.outputs,
    store_responses: draft.store_responses,
    retry_statuses: draft.retry_statuses,
    timeout_seconds: draft.timeout_seconds,
  };
}

function toDraft(webhook: Webhook): WebhookDraft {
  return {
    connection_id: webhook.connection_id,
    api_name: webhook.api_name,
    display_name: webhook.display_name,
    description: webhook.description,
    method: webhook.method,
    path: webhook.path,
    query: webhook.query ?? {},
    headers: webhook.headers ?? {},
    // Two spaces, so a body somebody typed comes back readable rather than on
    // one line. `null` is no body and renders as an empty box, which is the
    // same thing this form means by empty.
    bodyText: webhook.body === null || webhook.body === undefined
      ? ""
      : JSON.stringify(webhook.body, null, 2),
    inputs: webhook.inputs ?? [],
    outputs: webhook.outputs ?? [],
    store_responses: webhook.store_responses,
    retry_statuses: webhook.retry_statuses ?? [],
    timeout_seconds: webhook.timeout_seconds,
  };
}

/** p.233's key/value sections, as one control.
 *
 * Rows rather than a JSON box, because a header is two strings and asking
 * somebody to type `{"X-Trace": "abc"}` is asking them to get a quote wrong.
 * A row with an empty name is dropped on the way out, which is what makes
 * "add a row, change your mind" work without a delete button per row.
 */
function PairRows({
  label, hint, testId, pairs, onChange,
}: {
  label: string;
  hint?: string;
  testId: string;
  pairs: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  const rows = Object.entries(pairs);
  const set = (index: number, key: string, value: string) => {
    const next = rows.map((row, i) => (i === index ? [key, value] : row));
    onChange(Object.fromEntries(next.filter(([k]) => k)) as Record<string, string>);
  };
  return (
    <Field label={label} hint={hint}>
      <div data-testid={testId}>
        {rows.map(([key, value], index) => (
          <div key={index} className="row-actions" style={{ gap: 6, marginBottom: 4 }}>
            <input
              type="text"
              aria-label={`${label} ${index + 1} name`}
              value={key}
              onChange={(e) => set(index, e.target.value, value)}
            />
            <input
              type="text"
              aria-label={`${label} ${index + 1} value`}
              value={value}
              onChange={(e) => set(index, key, e.target.value)}
            />
          </div>
        ))}
        <button
          type="button"
          className="btn quiet"
          data-testid={`${testId}-add`}
          onClick={() => onChange({ ...pairs, "": "" })}
        >
          Add
        </button>
      </div>
    </Field>
  );
}

function WebhookDialog({
  open, onClose, connections, existing, workspaceId, projectId,
}: {
  open: boolean;
  onClose: () => void;
  connections: Connection[];
  existing: Webhook | null;
  workspaceId: string;
  projectId: string;
}) {
  const client = useQueryClient();
  // p.220: "Some other source types also support webhooks." Ours support one,
  // so the picker offers one — offering a Postgres source would be offering a
  // save that fails (§214), and the server says the same thing on the way in.
  const usable = connections.filter((c) => c.source_type === "rest");
  const [draft, setDraft] = useState<WebhookDraft>(() =>
    existing ? toDraft(existing) : blankWebhook(usable[0]?.id ?? ""),
  );
  const [error, setError] = useState<string | null>(null);
  const patch = (next: Partial<WebhookDraft>) => setDraft({ ...draft, ...next });

  const save = useMutation({
    mutationFn: () =>
      existing
        ? api.update(workspaceId, projectId, existing.id, payload(draft))
        : api.create(workspaceId, projectId, payload(draft)),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["webhooks", workspaceId, projectId] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  });

  const said = problem(draft);

  return (
    <Dialog
      open={open}
      title={existing ? `Edit ${existing.display_name}` : "New webhook"}
      onClose={onClose}
      wide
    >
      <Field label="Name">
        <input
          type="text"
          data-testid="webhook-display-name"
          value={draft.display_name}
          onChange={(e) =>
            patch({
              display_name: e.target.value,
              // Suggested only while the api_name has not been created yet:
              // it is the handle a rule holds, so overwriting it after a save
              // would be renaming something behind somebody's back.
              api_name: existing ? draft.api_name : suggestedApiName(e.target.value),
            })
          }
        />
      </Field>
      <Field label="API name" hint="How a rule names this webhook. It cannot be changed later.">
        <input
          type="text"
          data-testid="webhook-api-name"
          value={draft.api_name}
          disabled={!!existing}
          onChange={(e) => patch({ api_name: e.target.value })}
        />
      </Field>
      <Field
        label="Source"
        hint="Where the base URL and the credentials come from (p.220). Only REST sources can carry a webhook."
      >
        <select
          data-testid="webhook-connection"
          value={draft.connection_id}
          onChange={(e) => patch({ connection_id: e.target.value })}
        >
          <option value="">Choose…</option>
          {usable.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </Field>

      <div className="row" style={{ gap: 8, alignItems: "flex-end" }}>
        <Field label="Method">
          <select
            data-testid="webhook-method"
            value={draft.method}
            onChange={(e) => patch({ method: e.target.value })}
          >
            {METHODS.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </Field>
        <Field label="Path" hint="Relative to the source's base URL (p.220).">
          <input
            type="text"
            data-testid="webhook-path"
            placeholder="api/v1/createItem"
            value={draft.path}
            onChange={(e) => patch({ path: e.target.value })}
          />
        </Field>
      </div>

      <PairRows
        label="Query parameters" testId="webhook-query"
        pairs={draft.query} onChange={(query) => patch({ query })}
      />
      <PairRows
        label="Headers" testId="webhook-headers"
        hint="The source sets Authorization; this cannot override it (p.233)."
        pairs={draft.headers} onChange={(headers) => patch({ headers })}
      />

      <Field
        label="Body"
        hint="Raw JSON (p.233). A value that is exactly {{{input}}} keeps the input's type; one with text around it becomes text."
      >
        <textarea
          data-testid="webhook-body"
          rows={6}
          style={{ fontFamily: "var(--mono, monospace)" }}
          value={draft.bodyText}
          onChange={(e) => patch({ bodyText: e.target.value })}
        />
      </Field>
      {/* Said under the box while somebody is typing, and separately from the
          form's other refusals: a JSON error names a *position*, and that is
          only useful next to the text it is a position in. */}
      {bodyProblem(draft.bodyText) && (
        <p className="field-hint" data-testid="webhook-body-problem"
           style={{ color: "var(--danger)" }}>
          {bodyProblem(draft.bodyText)}
        </p>
      )}

      <ListEditor
        label="Inputs"
        hint="p.228 — what a rule supplies when it fires this webhook."
        testId="webhook-inputs"
        rows={draft.inputs}
        types={INPUT_TYPES}
        blank={() => ({ api_name: "", data_type: "string", required: true })}
        cell={(row, set, index) => (
          <label className="row-actions" style={{ gap: 4 }}>
            <input
              type="checkbox"
              aria-label={`Inputs ${index + 1} required`}
              checked={row.required}
              onChange={(e) => set({ required: e.target.checked })}
            />
            <span className="slug">Required</span>
          </label>
        )}
        onChange={(inputs) => patch({ inputs })}
      />
      <ListEditor
        label="Outputs"
        hint="p.229 — what to keep from the response. The path is where it lives in the JSON."
        testId="webhook-outputs"
        rows={draft.outputs}
        types={OUTPUT_TYPES}
        blank={() => ({ api_name: "", data_type: "string", path: "" })}
        cell={(row, set, index) => (
          <input
            type="text"
            aria-label={`Outputs ${index + 1} path`}
            placeholder="results.id"
            value={row.path}
            onChange={(e) => set({ path: e.target.value })}
          />
        )}
        onChange={(outputs) => patch({ outputs })}
      />

      <div className="row" style={{ gap: 8, alignItems: "flex-end" }}>
        <Field label="Timeout (seconds)">
          <input
            type="number" min={1} max={60}
            data-testid="webhook-timeout"
            value={draft.timeout_seconds}
            onChange={(e) => patch({ timeout_seconds: Number(e.target.value) })}
          />
        </Field>
        <Field
          label="Keep responses"
          hint="p.242 — turn this off for a webhook known to return sensitive information. The status and timing are kept either way."
        >
          <input
            type="checkbox"
            aria-label="Keep responses"
            checked={draft.store_responses}
            onChange={(e) => patch({ store_responses: e.target.checked })}
          />
        </Field>
      </div>

      {said && (
        <p className="field-hint" data-testid="webhook-problem"
           style={{ color: "var(--danger)" }}>
          {said}
        </p>
      )}
      {error && (
        <p className="field-hint" data-testid="webhook-error"
           style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      <div className="row-actions">
        <button
          className="btn"
          data-testid="webhook-save"
          disabled={!!said || save.isPending}
          onClick={() => { setError(null); save.mutate(); }}
        >
          Save
        </button>
        <button className="btn quiet" onClick={onClose}>Cancel</button>
      </div>
    </Dialog>
  );
}

/** The inputs and outputs lists, which differ in one column.
 *
 * One component rather than two, because p.228 and p.229 describe the same
 * shape — a name, a type, and one thing that is not the same — and two copies
 * would drift on the parts that *are* the same, which is most of them.
 */
function ListEditor<T extends { api_name: string; data_type: string }>({
  label, hint, testId, rows, types, blank, cell, onChange,
}: {
  label: string;
  hint?: string;
  testId: string;
  rows: T[];
  types: readonly (readonly [string, string])[];
  blank: () => T;
  /** The one column the two lists do not share, rendered by the caller.
   *
   * **A render prop rather than a `"required" | "path"` flag**, and the reason
   * is types rather than taste: a flag makes this function patch a field its
   * own type parameter does not have, which needs a cast per branch — and a
   * cast in a shared component is a cast on *both* callers. The caller knows
   * its row type exactly, so the cell it draws needs no cast at all (§189:
   * a mutation harness will happily argue for deleting the line that makes a
   * type check out, and the answer is to not need the line).
   */
  cell: (row: T, set: (patch: Partial<T>) => void, index: number) => React.ReactNode;
  onChange: (rows: T[]) => void;
}) {
  const set = (index: number, patch: Partial<T>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  return (
    <Field label={label} hint={hint}>
      <div data-testid={testId}>
        {rows.map((row, index) => (
          <div key={index} className="row-actions" style={{ gap: 6, marginBottom: 4 }}>
            <input
              type="text"
              aria-label={`${label} ${index + 1} name`}
              value={row.api_name ?? ""}
              onChange={(e) =>
                set(index, { api_name: e.target.value } as Partial<T>)
              }
            />
            <select
              aria-label={`${label} ${index + 1} type`}
              value={row.data_type ?? "string"}
              onChange={(e) => set(index, { data_type: e.target.value } as Partial<T>)}
            >
              {types.map(([value, text]) => (
                <option key={value} value={value}>{text}</option>
              ))}
            </select>
            {cell(row, (patch) => set(index, patch), index)}
            <button
              type="button"
              className="btn quiet"
              aria-label={`Remove ${label} ${index + 1}`}
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn quiet"
          data-testid={`${testId}-add`}
          onClick={() => onChange([...rows, blank()])}
        >
          Add
        </button>
      </div>
    </Field>
  );
}

/** p.222's test request, and the response it produces.
 *
 * > "After saving, you will be able to run a test request to see if your
 * > configuration is correct… After a test request is made, you may use the
 * > response to parse output parameters." (p.222)
 *
 * The second sentence is why the response is shown in full rather than as a
 * tick: somebody is reading it to find out what path an output should have.
 */
function TestPanel({
  webhook, workspaceId, projectId,
}: {
  webhook: Webhook;
  workspaceId: string;
  projectId: string;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [run, setRun] = useState<WebhookRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const call = useMutation({
    mutationFn: () => api.test(workspaceId, projectId, webhook.id, values),
    onSuccess: (result) => { setError(null); setRun(result); },
    onError: (e) => {
      setRun(null);
      setError(e instanceof ApiError ? e.message : String(e));
    },
  });

  return (
    <div className="card" data-testid="webhook-test">
      {webhook.inputs.map((input) => (
        <Field key={input.api_name} label={input.api_name}>
          <input
            type="text"
            aria-label={`Test ${input.api_name}`}
            value={values[input.api_name] ?? ""}
            onChange={(e) =>
              setValues({ ...values, [input.api_name]: e.target.value })
            }
          />
        </Field>
      ))}
      <button
        className="btn"
        data-testid="webhook-test-run"
        disabled={call.isPending}
        onClick={() => call.mutate()}
      >
        Send a test request
      </button>
      {/* A request that could not be *built* — a required input left empty —
          never reaches the network and leaves no run, so it is an error rather
          than an outcome. */}
      {error && (
        <p className="field-hint" data-testid="webhook-test-error"
           style={{ color: "var(--danger)" }}>{error}</p>
      )}
      {run && (
        <div data-testid="webhook-test-result">
          <p className="field-hint">{outcomeLabel(run)}</p>
          {run.error && <p className="field-hint">{run.error}</p>}
          <pre style={{ overflowX: "auto", maxHeight: 240 }}>
            {/* `undefined` rather than null when the webhook keeps no
                responses, so the box says "not kept" instead of "null" — the
                two mean different things and p.242 is about the difference. */}
            {run.response_body === null
              ? "(responses are not kept for this webhook)"
              : JSON.stringify(run.response_body, null, 2)}
          </pre>
          {Object.keys(run.outputs ?? {}).length > 0 && (
            <pre data-testid="webhook-test-outputs" style={{ overflowX: "auto" }}>
              {JSON.stringify(run.outputs, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export function WebhooksPanel({
  workspaceId, projectId, connections,
}: {
  workspaceId: string;
  projectId: string;
  connections: Connection[];
}) {
  const client = useQueryClient();
  const [dialog, setDialog] = useState<{ open: boolean; editing: Webhook | null }>(
    { open: false, editing: null },
  );
  const [testing, setTesting] = useState<string | null>(null);

  const listed = useQuery({
    queryKey: ["webhooks", workspaceId, projectId],
    queryFn: () => api.list(workspaceId, projectId),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.remove(workspaceId, projectId, id),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["webhooks", workspaceId, projectId] }),
  });

  const usable = connections.filter((c) => c.source_type === "rest");

  return (
    <section data-testid="webhooks-panel">
      <div className="row-actions" style={{ justifyContent: "space-between" }}>
        <h2>Webhooks</h2>
        <button
          className="btn"
          data-testid="new-webhook"
          disabled={usable.length === 0}
          onClick={() => setDialog({ open: true, editing: null })}
        >
          New webhook
        </button>
      </div>
      <p className="field-hint">
        A request this project can make to an external system, from an action
        (`action-types` p.105) or as a test from here.
      </p>
      {/* **Said rather than left as a disabled button with no reason.** p.216
          ties a webhook to a source, so with no REST source there is nothing
          to attach one to — and a button that does nothing with no explanation
          is §214's control that cannot work. */}
      {usable.length === 0 && (
        <p className="field-hint" data-testid="webhooks-need-a-source">
          A webhook is attached to a REST source (p.216). Add one above first.
        </p>
      )}

      <table>
        <thead>
          <tr>
            <th>Webhook</th>
            <th>Request</th>
            <th>Source</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(listed.data ?? []).map((webhook) => (
            <tr key={webhook.id}>
              <td>
                <div>{webhook.display_name}</div>
                <div className="slug">{webhook.api_name}</div>
              </td>
              <td className="slug">
                {webhook.method} /{webhook.path}
              </td>
              <td>{webhook.connection_name}</td>
              <td className="row-actions">
                <button
                  className="btn quiet"
                  onClick={() => setDialog({ open: true, editing: webhook })}
                >
                  Edit
                </button>
                <button
                  className="btn quiet"
                  onClick={() =>
                    setTesting(testing === webhook.id ? null : webhook.id)
                  }
                >
                  Test
                </button>
                <button
                  className="btn quiet"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(webhook.id)}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {listed.isSuccess && listed.data.length === 0 && usable.length > 0 && (
        <p className="field-hint" data-testid="webhooks-empty">
          No webhooks yet.
        </p>
      )}

      {testing && listed.data?.some((w) => w.id === testing) && (
        <TestPanel
          webhook={listed.data.find((w) => w.id === testing)!}
          workspaceId={workspaceId}
          projectId={projectId}
        />
      )}

      {dialog.open && (
        <WebhookDialog
          // **Keyed by what it is editing**, so opening the dialog on a second
          // webhook rebuilds the draft rather than showing the first one's
          // fields. `useState`'s initialiser runs once per mount, and without
          // a key the mount is the same one.
          key={dialog.editing?.id ?? "new"}
          open
          onClose={() => setDialog({ open: false, editing: null })}
          connections={connections}
          existing={dialog.editing}
          workspaceId={workspaceId}
          projectId={projectId}
        />
      )}
    </section>
  );
}
