"use client";

/**
 * Exports on the source they write to (Foundry `data-connection` p.192-206;
 * decision 0014; §267).
 *
 * §265 built the rule, the store, the runner and the routes, and left every one
 * of them reachable only by posting JSON. p.203 says where this belongs:
 * "navigate to the Overview page of the source to which you want to export" —
 * the same place p.220 puts webhooks, and for the same reason.
 *
 * **The panel's real work is p.192.** Since June 2025 an export with nothing to
 * send is a *success*, which is right and leaves a history of green ticks that
 * says nothing about whether the destination is current. So every row carries
 * `freshness`: up to date at a version, or how many versions behind. That is
 * the question somebody opens this screen to ask.
 *
 * **A source that could be a destination but has not been enabled is shown,
 * not hidden.** p.202's switch is somebody's decision and "this kind of source
 * cannot be a destination" is a fact about the connector; a picker that merged
 * them would send a person looking for the wrong fix.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Dialog, Field } from "@/components/dialog";
import { ApiError, exports_ as api, datasets as datasetApi } from "@/lib/api";
import {
  MODES, MODE_LABELS, blankExport, destinations, freshness, kindOf, problem,
  runLabel, summarise, toPayload, type ExportDraft, type ExportMode,
} from "@/lib/export-form";
import type { Connection, Export } from "@/lib/types";

export function ExportsPanel({
  workspaceId,
  projectId,
  connections,
  canAdmin,
}: {
  workspaceId: string;
  projectId: string;
  connections: Connection[];
  /** Whether this person may work p.202's switch. Passed in rather than read
   * here, because the page already knows the workspace role and a second
   * source for it is a second thing to get wrong. */
  canAdmin: boolean;
}) {
  const client = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [historyFor, setHistoryFor] = useState<Export | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const listed = useQuery({
    queryKey: ["exports", projectId],
    queryFn: () => api.list(workspaceId, projectId),
  });
  const rows = listed.data ?? [];

  const refresh = () => client.invalidateQueries({ queryKey: ["exports", projectId] });

  const run = useMutation({
    mutationFn: (id: string) => api.run(workspaceId, projectId, id),
    onSuccess: async (result) => {
      setFailed(result.status === "failed" ? result.error : null);
      await refresh();
    },
    onError: (error) =>
      setFailed(error instanceof ApiError ? error.message : "Could not run that export."),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.remove(workspaceId, projectId, id),
    onSuccess: refresh,
  });
  const enable = useMutation({
    mutationFn: (cid: string) => api.setEnabled(workspaceId, projectId, cid, true),
    onSuccess: () => client.invalidateQueries({ queryKey: ["connections", projectId] }),
    onError: (error) =>
      setFailed(error instanceof ApiError ? error.message : "Could not enable exports."),
  });

  const { usable, disabled } = destinations(connections);

  return (
    <section data-testid="exports-panel" style={{ marginTop: 28 }}>
      <div className="row-actions" style={{ justifyContent: "space-between" }}>
        <h2>Exports</h2>
        <button
          className="btn"
          data-testid="new-export"
          disabled={usable.length === 0}
          onClick={() => { setFailed(null); setCreating(true); }}
        >
          New export
        </button>
      </div>
      <p className="field-hint">
        Writing a dataset out to one of this project&apos;s sources, on demand
        (p.192). Foundry schedules these too; here they are run by hand.
      </p>

      {/* **Said rather than left as a disabled button with no reason** — §214.
          And the two reasons are different sentences: nothing that could be a
          destination, versus one that could and has not been turned on. */}
      {usable.length === 0 && disabled.length === 0 && (
        <p className="field-hint" data-testid="exports-need-a-source">
          An export writes to a database or object-storage source. This project
          has none — a REST source is written to with a webhook instead.
        </p>
      )}
      {usable.length === 0 && disabled.length > 0 && (
        <div className="card" data-testid="exports-not-enabled">
          <p className="field-hint" style={{ marginTop: 0 }}>
            Exports are switched off for {disabled.map((c) => c.name).join(", ")}.
            p.202 makes that a deliberate act: until somebody turns it on, no
            data leaves the platform through this source.
          </p>
          {canAdmin ? (
            <div className="row-actions">
              {disabled.map((c) => (
                <button
                  key={c.id}
                  className="btn"
                  data-testid={`enable-exports-${c.id}`}
                  disabled={enable.isPending}
                  onClick={() => { setFailed(null); enable.mutate(c.id); }}
                >
                  Enable exports to {c.name}
                </button>
              ))}
            </div>
          ) : (
            <p className="field-hint" data-testid="exports-need-an-admin">
              A workspace admin can turn it on.
            </p>
          )}
        </div>
      )}

      {failed && (
        <p className="field-hint" data-testid="export-failed">{failed}</p>
      )}

      {rows.length > 0 && (
        <table className="table" data-testid="exports-table">
          <thead>
            <tr>
              <th>Export</th>
              <th>Dataset</th>
              <th>Destination</th>
              <th>State</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const state = freshness(row);
              return (
                <tr key={row.id}>
                  <td>
                    <strong>{row.name}</strong>
                    <div className="slug">{row.connection_name}</div>
                  </td>
                  <td>
                    {row.dataset_name}
                    <div className="slug">v{row.dataset_version}</div>
                  </td>
                  <td className="slug">{summarise(row)}</td>
                  <td>
                    <span
                      className={state.behind ? "chip" : "count"}
                      data-testid={`export-state-${row.name}`}
                    >
                      {state.label}
                    </span>
                  </td>
                  <td className="row-actions">
                    <button
                      className="btn quiet"
                      style={{ padding: "3px 9px", fontSize: 12 }}
                      data-testid={`run-export-${row.name}`}
                      disabled={run.isPending}
                      onClick={() => { setFailed(null); run.mutate(row.id); }}
                    >
                      {run.isPending ? "Running…" : "Run"}
                    </button>
                    <button
                      className="btn quiet"
                      style={{ padding: "3px 9px", fontSize: 12 }}
                      onClick={() => setHistoryFor(row)}
                    >
                      History
                    </button>
                    <button
                      className="btn danger"
                      style={{ padding: "3px 9px", fontSize: 12 }}
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(row.id)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {creating && (
        <ExportDialog
          workspaceId={workspaceId}
          projectId={projectId}
          destinations={usable}
          existingNames={rows.map((r) => r.name)}
          onClose={() => setCreating(false)}
        />
      )}
      {historyFor && (
        <HistoryDialog
          workspaceId={workspaceId}
          projectId={projectId}
          row={historyFor}
          onClose={() => setHistoryFor(null)}
        />
      )}
    </section>
  );
}

function ExportDialog({
  workspaceId,
  projectId,
  destinations: usable,
  existingNames,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  destinations: Connection[];
  existingNames: string[];
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<ExportDraft>({
    ...blankExport(),
    connection_id: usable[0]?.id ?? "",
  });
  const [failed, setFailed] = useState<string | null>(null);

  const datasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => datasetApi.list(workspaceId, projectId),
  });

  const source = usable.find((c) => c.id === draft.connection_id) ?? null;
  const kind = source ? kindOf(source.source_type) : null;
  const dataset = (datasets.data ?? []).find((d) => d.id === draft.dataset_id);

  const said = problem(draft, {
    sourceType: source?.source_type ?? null,
    datasetSchema: dataset?.table_schema ?? [],
    existingNames,
  });

  const create = useMutation({
    mutationFn: () =>
      api.create(workspaceId, projectId, toPayload(draft, source!.source_type)),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["exports", projectId] });
      onClose();
    },
    onError: (error) =>
      setFailed(error instanceof ApiError ? error.message : "Could not create that export."),
  });

  const set = (next: Partial<ExportDraft>) => {
    setFailed(null);
    setDraft({ ...draft, ...next });
  };

  return (
    <Dialog open wide title="New export" onClose={onClose}>
      <Field label="To this source">
        <select
          data-testid="export-connection"
          value={draft.connection_id}
          onChange={(e) => set({ connection_id: e.target.value })}
        >
          {usable.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </Field>

      <Field label="Dataset">
        <select
          data-testid="export-dataset"
          value={draft.dataset_id}
          onChange={(e) => set({ dataset_id: e.target.value })}
        >
          <option value="">Choose a dataset…</option>
          {(datasets.data ?? []).map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
      </Field>

      <Field label="Name">
        <input
          type="text"
          data-testid="export-name"
          value={draft.name}
          onChange={(e) => set({ name: e.target.value })}
        />
      </Field>

      {kind === "table" ? (
        <>
          <Field
            label="Schema"
            hint="p.197 — fill this in if your source needs it, and leave it empty if it does not."
          >
            <input
              type="text"
              data-testid="export-schema"
              value={draft.schema}
              onChange={(e) => set({ schema: e.target.value })}
            />
          </Field>
          <Field
            label="Table"
            hint="p.197 — it must already exist, with the dataset's exact column names."
          >
            <input
              type="text"
              data-testid="export-table"
              value={draft.table}
              onChange={(e) => set({ table: e.target.value })}
            />
          </Field>
          <Field label="How it writes">
            <select
              data-testid="export-mode"
              value={draft.mode}
              onChange={(e) => set({ mode: e.target.value as ExportMode })}
            >
              {MODES.map((mode) => (
                <option key={mode} value={mode}>{MODE_LABELS[mode]}</option>
              ))}
            </select>
          </Field>
        </>
      ) : (
        <Field
          label="Path"
          hint="p.193 recommends a folder of its own, so an export cannot overwrite anything else."
        >
          <input
            type="text"
            data-testid="export-prefix"
            value={draft.prefix}
            onChange={(e) => set({ prefix: e.target.value })}
          />
        </Field>
      )}

      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        {/* The form's own refusal, once somebody has started: `problem`
            refuses an untouched draft, and a message under a blank form is an
            error about not having begun. */}
        {draft.dataset_id !== "" && said && (
          <span className="field-hint" data-testid="export-problem">{said}</span>
        )}
        {failed && <span className="field-hint" data-testid="export-error">{failed}</span>}
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="export-save"
          disabled={said !== null || create.isPending}
          onClick={() => create.mutate()}
        >
          Create
        </button>
      </div>
    </Dialog>
  );
}

function HistoryDialog({
  workspaceId,
  projectId,
  row,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  row: Export;
  onClose: () => void;
}) {
  const runs = useQuery({
    queryKey: ["export-runs", row.id],
    queryFn: () => api.runs(workspaceId, projectId, row.id),
  });

  return (
    <Dialog open title={`History — ${row.name}`} onClose={onClose}>
      {runs.isPending && <div className="state">Loading history…</div>}
      {runs.data && runs.data.runs.length === 0 && (
        <div className="state">This export has not run yet.</div>
      )}
      {runs.data && runs.data.runs.length > 0 && (
        <table className="table" data-testid="export-runs">
          <thead>
            <tr>
              <th>When</th>
              <th>Result</th>
              <th>Version</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.runs.map((entry) => (
              <tr key={entry.id}>
                <td title={entry.started_at}>
                  {new Date(entry.started_at).toLocaleString()}
                </td>
                <td>
                  <span className={entry.status === "failed" ? "chip" : "count"}>
                    {runLabel(entry)}
                  </span>
                  {entry.error && <div className="form-error">{entry.error}</div>}
                </td>
                <td className="slug">
                  {entry.dataset_version === null ? "—" : `v${entry.dataset_version}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="form-actions">
        <button className="btn" onClick={onClose}>Close</button>
      </div>
    </Dialog>
  );
}
