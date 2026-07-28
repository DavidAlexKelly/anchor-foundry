"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ApiError,
  connections as connApi,
  scheduledSync as scheduledSyncApi,
  sync as syncApi,
} from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type {
  Connection,
  DiscoveredTable,
  SchemaChanges,
  SourceTypeInfo,
  SyncHealth,
} from "@/lib/types";

function StatusBadge({ connection }: { connection: Connection }) {
  const label =
    connection.status === "ok"
      ? "Connected"
      : connection.status === "error"
        ? connection.last_error ?? "Connection failed"
        : "Not tested yet";
  return (
    <span className={`status-${connection.status}`} title={connection.last_error ?? undefined}>
      <span className="status-dot" />
      <span className="status-label">{label}</span>
    </span>
  );
}

// A discovered entry is identified by its (schema, name) pair, but a <select>
// value is a single string. Encoding it as "schema.name" and splitting on the
// first dot is ambiguous the moment a schema itself contains one - which
// object-storage sources make ordinary, since a "schema" there is a folder.
// Encode with a separator that cannot occur in either half, and resolve back
// through the discovered list rather than by parsing.
const TABLE_KEY_SEP = "\u0000";

function tableKey(t: { schema_name: string; name: string }): string {
  return `${t.schema_name}${TABLE_KEY_SEP}${t.name}`;
}

function tableLabel(t: { schema_name: string; name: string }): string {
  // A file at the root of an object-storage prefix has no folder; showing it
  // as ".orders.csv" would be noise.
  return t.schema_name ? `${t.schema_name}/${t.name}` : t.name;
}

// What a sync can actually read. Views stay excluded as they always have
// been; object-storage entries ("file") are syncable and were being silently
// dropped by an equality check against "table".
function isSyncable(t: { kind: string }): boolean {
  return t.kind !== "view";
}

function resolveTable(
  tables: DiscoveredTable[] | undefined,
  key: string | null,
): { schema: string; name: string } | null {
  if (!key) return null;
  const match = (tables ?? []).find((t) => tableKey(t) === key);
  return match ? { schema: match.schema_name, name: match.name } : null;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const delta = Date.now() - new Date(iso).getTime();
  const future = delta < 0;
  const seconds = Math.abs(delta) / 1000;
  const [value, unit] =
    seconds < 60
      ? [Math.round(seconds), "s"]
      : seconds < 3600
        ? [Math.round(seconds / 60), "m"]
        : seconds < 86400
          ? [Math.round(seconds / 3600), "h"]
          : [Math.round(seconds / 86400), "d"];
  return future ? `in ${value}${unit}` : `${value}${unit} ago`;
}

function duration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

/** One line describing a schema change, e.g. "+2 columns, -1, 1 retyped".
 * Returns null when nothing drifted, so callers can render conditionally. */
function driftSummary(changes: SchemaChanges | null | undefined): string | null {
  if (!changes) return null;
  const parts: string[] = [];
  if (changes.added?.length) parts.push(`+${changes.added.length}`);
  if (changes.removed?.length) parts.push(`-${changes.removed.length}`);
  if (changes.retyped?.length) parts.push(`${changes.retyped.length} retyped`);
  return parts.length ? parts.join(", ") : null;
}

function DriftDetail({ changes }: { changes: SchemaChanges }) {
  return (
    <div style={{ fontSize: 12 }}>
      {changes.added?.map((c) => (
        <div key={`a-${c.name}`}>
          <strong>+ {c.name}</strong> <span className="count">{c.data_type}</span>
        </div>
      ))}
      {changes.removed?.map((c) => (
        <div key={`r-${c.name}`}>
          <strong>− {c.name}</strong> <span className="count">{c.data_type}</span>
        </div>
      ))}
      {changes.retyped?.map((c) => (
        <div key={`t-${c.name}`}>
          <strong>~ {c.name}</strong>{" "}
          <span className="count">
            {c.from} → {c.to}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Run history for one connection: what ran, how long it took, how many rows,
 * and whether the source changed shape underneath it. */
function HistoryDialog({
  workspaceId,
  projectId,
  connection,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  onClose: () => void;
}) {
  const runs = useQuery({
    queryKey: ["sync-runs", connection.id],
    queryFn: () => syncApi.runs(workspaceId, projectId, connection.id),
  });

  return (
    <Dialog open title={`Sync history — ${connection.name}`} onClose={onClose}>
      {runs.isPending && <div className="state">Loading history…</div>}
      {runs.data && runs.data.length === 0 && (
        <div className="state">This connection hasn&apos;t been synced yet.</div>
      )}
      {runs.data && runs.data.length > 0 && (
        <div style={{ maxHeight: 380, overflowY: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Table</th>
                <th>Rows</th>
                <th>Took</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((run) => {
                const drift = driftSummary(run.schema_changes);
                const took =
                  run.finished_at && run.started_at
                    ? (new Date(run.finished_at).getTime() -
                        new Date(run.started_at).getTime()) /
                      1000
                    : null;
                return (
                  <tr key={run.id}>
                    <td title={run.started_at}>{relativeTime(run.started_at)}</td>
                    <td>
                      <span className="slug">{run.source_table}</span>
                      <div className="count">{run.mode}</div>
                    </td>
                    <td>{run.rows_synced.toLocaleString()}</td>
                    <td>{duration(took)}</td>
                    <td>
                      <span className={`status-${run.status === "succeeded" ? "ok" : "error"}`}>
                        <span className="status-dot" />
                        <span className="status-label">{run.status}</span>
                      </span>
                      {run.error && <div className="form-error">{run.error}</div>}
                      {drift && run.schema_changes && (
                        <details>
                          <summary className="chip">schema changed ({drift})</summary>
                          <DriftDetail changes={run.schema_changes} />
                        </details>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="form-actions">
        <button className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}

/** The health cell in the connections list: last result, how reliable it has
 * been lately, when it next runs, and a warning when the source changed shape.
 * Everything here is one shared request for the whole page. */
function HealthCell({ health }: { health: SyncHealth | undefined }) {
  if (!health || health.total_runs === 0) {
    return <span className="count">Never synced</span>;
  }
  const rate = health.success_rate === null ? null : Math.round(health.success_rate * 100);
  const drift = driftSummary(health.last_schema_changes);
  const settled = health.succeeded + health.failed;
  // "running" is neither good nor bad news, so it gets the neutral dot rather
  // than the red one - a sync in flight is not a failure.
  const tone =
    health.last_status === "succeeded"
      ? "ok"
      : health.last_status === "failed"
        ? "error"
        : "testing";
  return (
    <div style={{ fontSize: 12 }}>
      <span className={`status-${tone}`}>
        <span className="status-dot" />
        <span className="status-label">
          {health.last_status} {relativeTime(health.last_started_at)}
        </span>
      </span>
      <div className="count">
        {rate !== null ? (
          <>
            {rate}% of last {settled} · {duration(health.last_duration_seconds)} ·{" "}
            {(health.last_rows_synced ?? 0).toLocaleString()} rows
          </>
        ) : (
          <>no finished runs yet</>
        )}
      </div>
      {health.next_run_at && (
        <div className="count">next {relativeTime(health.next_run_at)}</div>
      )}
      {drift && (
        <div className="chip" title="The source changed shape on the most recent sync">
          schema changed ({drift})
        </div>
      )}
    </div>
  );
}

/** Spec §"Build Plan": pick type → configure → test → save. Save happens
 * first (credentials must reach Secrets Manager before any driver call),
 * then the wizard runs the test and reports on the saved connection. */
function AddConnectionWizard({
  workspaceId,
  projectId,
  canWorkspaceScope,
}: {
  workspaceId: string;
  projectId: string;
  canWorkspaceScope: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [typeName, setTypeName] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"project" | "workspace">("project");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [secret, setSecret] = useState<Record<string, string>>({});
  const queryClient = useQueryClient();

  const types = useQuery({
    queryKey: ["source-types", workspaceId, projectId],
    queryFn: () => connApi.sourceTypes(workspaceId, projectId),
    enabled: open,
  });
  const selected: SourceTypeInfo | undefined = types.data?.find((t) => t.type === typeName);

  const create = useMutation({
    mutationFn: async () => {
      if (!selected) throw new Error("pick a source type");
      const typedConfig: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(config)) {
        if (value === "") continue;
        const prop = selected.config_schema.properties[key];
        typedConfig[key] =
          prop?.type === "integer"
            ? Number(value)
            : prop?.type === "boolean"
              ? value === "true"
              : value;
      }
      const created = await connApi.create(workspaceId, projectId, {
        name,
        source_type: selected.type,
        scope,
        config: typedConfig,
        secret,
      });
      // Test immediately so the list shows a truthful status.
      return connApi.test(workspaceId, projectId, created.id);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["connections", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["sync-health", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
    },
  });

  function reset() {
    setTypeName(null);
    setName("");
    setScope("project");
    setConfig({});
    setSecret({});
    create.reset();
  }

  function close() {
    if (!create.isPending) {
      setOpen(false);
      reset();
    }
  }

  const result = create.data;

  return (
    <>
      <button className="btn" onClick={() => setOpen(true)}>
        Add connection
      </button>
      <Dialog open={open} title="Add connection" onClose={close}>
        {result ? (
          <div>
            {result.ok ? (
              <p>
                <span className="status-ok">
                  <span className="status-dot" />
                </span>
                <strong>{result.connection.name}</strong> is connected and ready to use.
              </p>
            ) : (
              <>
                <p>
                  <strong>{result.connection.name}</strong> was saved, but the test failed:
                </p>
                <div className="form-error">{result.error}</div>
                <p className="login-note">
                  Fix the details from the connection list and test again - nothing is lost.
                </p>
              </>
            )}
            <div className="form-actions">
              <button className="btn" onClick={close}>
                Done
              </button>
            </div>
          </div>
        ) : !selected ? (
          <div>
            <p className="login-note" style={{ marginTop: 0 }}>
              Where does this data live?
            </p>
            {types.isPending && <div className="state">Loading source types…</div>}
            <div className="grid" style={{ gridTemplateColumns: "1fr" }}>
              {types.data?.map((t) => (
                <button
                  key={t.type}
                  className="card"
                  style={{ textAlign: "left", border: "none", cursor: "pointer" }}
                  onClick={() => {
                    setTypeName(t.type);
                    const defaults: Record<string, string> = {};
                    for (const [key, prop] of Object.entries(t.config_schema.properties)) {
                      if (prop.default !== undefined) defaults[key] = String(prop.default);
                    }
                    setConfig(defaults);
                  }}
                >
                  <h3>{t.display_name}</h3>
                  <p style={{ margin: 0 }}>Connect and query in place - no data copied.</p>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Field label="Connection name" hint="How this source appears across the project">
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={200}
                autoFocus
              />
            </Field>
            {Object.entries(selected.config_schema.properties).map(([key, prop]) => (
              <Field key={key} label={prop.title ?? key}>
                {prop.enum ? (
                  // A constrained choice is a picker: typing one of a fixed set
                  // of values by hand only ever produces a 422 on a typo.
                  <select
                    value={config[key] ?? ""}
                    onChange={(e) => setConfig({ ...config, [key]: e.target.value })}
                    required={selected.config_schema.required?.includes(key) ?? false}
                  >
                    {prop.enum.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                ) : prop.type === "boolean" ? (
                  // A boolean typed into a text box ("true"/"false") is a
                  // wrong answer waiting to happen.
                  <input
                    type="checkbox"
                    checked={config[key] === "true"}
                    onChange={(e) =>
                      setConfig({ ...config, [key]: e.target.checked ? "true" : "false" })
                    }
                  />
                ) : (
                  <input
                    type={prop.type === "integer" ? "number" : "text"}
                    value={config[key] ?? ""}
                    onChange={(e) => setConfig({ ...config, [key]: e.target.value })}
                    required={selected.config_schema.required?.includes(key) ?? false}
                  />
                )}
              </Field>
            ))}
            {selected.secret_fields.map((key) => (
              <Field
                key={key}
                label={key}
                hint="Stored in your AWS Secrets Manager - never shown again"
              >
                <input
                  type="password"
                  value={secret[key] ?? ""}
                  onChange={(e) => setSecret({ ...secret, [key]: e.target.value })}
                  autoComplete="new-password"
                />
              </Field>
            ))}
            {canWorkspaceScope && (
              <Field label="Sharing" hint="Workspace-shared connections appear in every project">
                <select
                  value={scope}
                  onChange={(e) => setScope(e.target.value as "project" | "workspace")}
                >
                  <option value="project">This project only</option>
                  <option value="workspace">Whole workspace</option>
                </select>
              </Field>
            )}
            {create.isError && (
              <div className="form-error">
                {create.error instanceof ApiError
                  ? create.error.message
                  : "Couldn't save the connection. Check the details and try again."}
              </div>
            )}
            <div className="form-actions">
              <button type="button" className="btn quiet" onClick={reset}>
                Back
              </button>
              <button type="submit" className="btn" disabled={create.isPending || !name.trim()}>
                {create.isPending ? "Saving & testing…" : "Save & test"}
              </button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}

function DiscoverDialog({
  workspaceId,
  projectId,
  connection,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  onClose: () => void;
}) {
  const discover = useQuery({
    queryKey: ["discover", connection.id],
    queryFn: () => connApi.discover(workspaceId, projectId, connection.id),
    retry: false,
  });

  const bySchema = new Map<string, DiscoveredTable[]>();
  for (const t of discover.data ?? []) {
    const list = bySchema.get(t.schema_name) ?? [];
    list.push(t);
    bySchema.set(t.schema_name, list);
  }

  return (
    <Dialog open title={`Schema of ${connection.name}`} onClose={onClose}>
      {discover.isPending && <div className="state">Reading the source schema…</div>}
      {discover.isError && (
        <div className="form-error">
          {discover.error instanceof ApiError
            ? discover.error.message
            : "Couldn't read the schema."}
        </div>
      )}
      {discover.data && (
        <div className="discover-tree" style={{ maxHeight: 380, overflowY: "auto" }}>
          {[...bySchema.entries()].map(([schema, tables]) => (
            <div key={schema}>
              <div className="schema-name">{schema || "/"}</div>
              {tables.map((t) => (
                <table key={t.name}>
                  <tbody>
                    <tr className="tbl-head">
                      <td colSpan={3}>
                        {t.name} <span className="count">({t.kind})</span>
                      </td>
                    </tr>
                    {t.columns.map((c) => (
                      <tr key={c.name}>
                        <td>
                          {c.name} {c.is_primary_key && <span className="pk-mark">pk</span>}
                        </td>
                        <td>{c.data_type}</td>
                        <td>{c.nullable ? "null ok" : "not null"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ))}
            </div>
          ))}
        </div>
      )}
      <div className="form-actions">
        <button className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}


function SyncDialog({
  workspaceId,
  projectId,
  connection,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  onClose: () => void;
}) {
  const [table, setTable] = useState<string | null>(null);
  const [datasetName, setDatasetName] = useState("");
  const queryClient = useQueryClient();

  const discover = useQuery({
    queryKey: ["discover", connection.id],
    queryFn: () => connApi.discover(workspaceId, projectId, connection.id),
    retry: false,
  });

  const run = useMutation({
    mutationFn: () => {
      const picked = resolveTable(discover.data, table);
      if (!picked) throw new Error("pick a table");
      return syncApi.trigger(workspaceId, projectId, connection.id, {
        source_schema: picked.schema,
        source_table: picked.name,
        dataset_name: datasetName || undefined,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["connections", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["sync-health", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["sync-runs", connection.id] });
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
    },
  });

  const result = run.data;

  return (
    <Dialog open title={`Sync from ${connection.name}`} onClose={onClose}>
      {result ? (
        <div>
          {result.ok && result.dataset ? (
            <p>
              Synced <strong>{result.rows_synced.toLocaleString()}</strong> rows into the
              dataset <strong>{result.dataset.name}</strong>
              {result.created_dataset
                ? "."
                : ` (now at version ${result.dataset.current_version}).`}{" "}
              Find it under Datasets.
            </p>
          ) : (
            <div className="form-error">{result.error}</div>
          )}
          <div className="form-actions">
            <button className="btn" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run.mutate();
          }}
        >
          <p className="login-note" style={{ marginTop: 0 }}>
            A full snapshot of one table, stored as Parquet in your own account.
          </p>
          {discover.isPending && <div className="state">Reading the source schema…</div>}
          {discover.isError && (
            <div className="form-error">
              {discover.error instanceof ApiError
                ? discover.error.message
                : "Couldn't read the source schema."}
            </div>
          )}
          {discover.data && (
            <Field label="Table">
              <select
                value={table ?? ""}
                onChange={(e) => {
                  setTable(e.target.value || null);
                  const picked = resolveTable(discover.data, e.target.value);
                  if (picked && !datasetName) setDatasetName(picked.name);
                }}
                required
              >
                <option value="">Choose a table…</option>
                {discover.data
                  .filter(isSyncable)
                  .map((t) => (
                    <option key={tableKey(t)} value={tableKey(t)}>
                      {tableLabel(t)} ({t.columns.length} columns)
                    </option>
                  ))}
              </select>
            </Field>
          )}
          <Field label="Dataset name" hint="Re-syncing to the same name adds a new version">
            <input
              type="text"
              value={datasetName}
              onChange={(e) => setDatasetName(e.target.value)}
              maxLength={200}
            />
          </Field>
          {run.isError && (
            <div className="form-error">
              {run.error instanceof ApiError ? run.error.message : "Sync failed."}
            </div>
          )}
          <div className="form-actions">
            <button type="button" className="btn quiet" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn" disabled={run.isPending || !table}>
              {run.isPending ? "Syncing…" : "Sync now"}
            </button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

/** A connection carries at most one managed scheduled/incremental sync
 * target (migration 0014) - this dialog is both the "set it up" form and
 * the status view, since there's only ever one to show. */
function ScheduledSyncDialog({
  workspaceId,
  projectId,
  connection,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const schedule = useQuery({
    queryKey: ["scheduled-sync", connection.id],
    queryFn: () => scheduledSyncApi.get(workspaceId, projectId, connection.id),
  });
  const discover = useQuery({
    queryKey: ["discover", connection.id],
    queryFn: () => connApi.discover(workspaceId, projectId, connection.id),
    retry: false,
  });

  const [mode, setMode] = useState<"full" | "incremental">("full");
  const [table, setTable] = useState<string | null>(null);
  const [datasetName, setDatasetName] = useState("");
  const [pkColumn, setPkColumn] = useState("");
  const [cursorColumn, setCursorColumn] = useState("");
  const [cronSchedule, setCronSchedule] = useState("*/15 * * * *");

  useEffect(() => {
    if (!schedule.data) return;
    setMode(schedule.data.sync_mode === "incremental" ? "incremental" : "full");
    if (schedule.data.sync_source_table) {
      setTable(
        tableKey({
          schema_name: schedule.data.sync_source_schema ?? "",
          name: schedule.data.sync_source_table,
        }),
      );
    }
    setDatasetName(schedule.data.sync_dataset_name ?? "");
    setPkColumn(schedule.data.sync_primary_key_column ?? "");
    setCursorColumn(schedule.data.sync_cursor_column ?? "");
    if (schedule.data.sync_schedule) setCronSchedule(schedule.data.sync_schedule);
  }, [schedule.data]);

  const columns = discover.data?.find((t) => tableKey(t) === table)?.columns ?? [];

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["scheduled-sync", connection.id] });
    await queryClient.invalidateQueries({ queryKey: ["connections", projectId] });
    await queryClient.invalidateQueries({ queryKey: ["sync-health", projectId] });
  };

  const save = useMutation({
    mutationFn: () => {
      const picked = resolveTable(discover.data, table);
      if (!picked) throw new Error("pick a table");
      return scheduledSyncApi.set(workspaceId, projectId, connection.id, {
        mode,
        source_schema: picked.schema,
        source_table: picked.name,
        dataset_name: datasetName || undefined,
        primary_key_column: mode === "incremental" ? pkColumn : undefined,
        cursor_column: mode === "incremental" ? cursorColumn : undefined,
        cron_schedule: cronSchedule || undefined,
      });
    },
    onSuccess: invalidate,
  });
  const clear = useMutation({
    mutationFn: () => scheduledSyncApi.clear(workspaceId, projectId, connection.id),
    onSuccess: invalidate,
  });
  const runNow = useMutation({
    mutationFn: () => scheduledSyncApi.run(workspaceId, projectId, connection.id),
    onSuccess: async () => {
      await invalidate();
      await queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
    },
  });

  const configured = !!schedule.data?.sync_source_table;
  const result = runNow.data;

  return (
    <Dialog open wide title={`Scheduled sync - ${connection.name}`} onClose={onClose}>
      {schedule.isPending && <div className="state">Loading schedule…</div>}
      {schedule.data && (
        <>
          {configured && (
            <div className="card" style={{ marginBottom: 14 }}>
              <p className="login-note" style={{ marginTop: 0 }}>
                {schedule.data.sync_mode} sync of{" "}
                {tableLabel({
                  schema_name: schedule.data.sync_source_schema ?? "",
                  name: schedule.data.sync_source_table ?? "",
                })}
                {schedule.data.sync_schedule
                  ? ` on ${schedule.data.sync_schedule}`
                  : " - no cron, run manually with the button below"}
              </p>
              {schedule.data.sync_next_run_at && (
                <p className="slug">
                  next run: {new Date(schedule.data.sync_next_run_at).toLocaleString()}
                </p>
              )}
              {schedule.data.sync_last_cursor_value && (
                <p className="slug">last cursor: {schedule.data.sync_last_cursor_value}</p>
              )}
              {result && (
                <div style={{ marginTop: 8 }}>
                  {result.ok ? (
                    <p className="login-note" style={{ margin: 0 }}>
                      Synced {result.rows_synced.toLocaleString()} rows
                      {result.dataset ? ` → ${result.dataset.name} v${result.dataset.current_version}` : ""}.
                    </p>
                  ) : (
                    <div className="form-error">{result.error}</div>
                  )}
                </div>
              )}
              <div className="form-actions" style={{ marginTop: 10 }}>
                <button
                  type="button"
                  className="btn quiet"
                  disabled={runNow.isPending}
                  onClick={() => runNow.mutate()}
                >
                  {runNow.isPending ? "Running…" : "Run now"}
                </button>
                <button
                  type="button"
                  className="btn danger"
                  disabled={clear.isPending}
                  onClick={() => clear.mutate()}
                >
                  Stop scheduling
                </button>
              </div>
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <Field label="Mode">
              <select value={mode} onChange={(e) => setMode(e.target.value as "full" | "incremental")}>
                <option value="full">Full - replace the dataset each run</option>
                <option value="incremental">Incremental - merge only new/changed rows</option>
              </select>
            </Field>
            {discover.isPending && <div className="state">Reading the source schema…</div>}
            {discover.data && (
              <Field label="Table">
                <select value={table ?? ""} onChange={(e) => setTable(e.target.value || null)} required>
                  <option value="">Choose a table…</option>
                  {discover.data
                    .filter(isSyncable)
                    .map((t) => (
                      <option key={tableKey(t)} value={tableKey(t)}>
                        {tableLabel(t)}
                      </option>
                    ))}
                </select>
              </Field>
            )}
            <Field label="Dataset name" hint="Defaults to the table name">
              <input
                type="text"
                value={datasetName}
                onChange={(e) => setDatasetName(e.target.value)}
                maxLength={200}
              />
            </Field>
            {mode === "incremental" && (
              <>
                <Field label="Primary key column">
                  <select value={pkColumn} onChange={(e) => setPkColumn(e.target.value)} required>
                    <option value="">Choose a column…</option>
                    {columns.map((c) => (
                      <option key={c.name} value={c.name}>{c.name}</option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="Cursor column"
                  hint="A column that only increases over time (id, updated_at, ...)"
                >
                  <select value={cursorColumn} onChange={(e) => setCursorColumn(e.target.value)} required>
                    <option value="">Choose a column…</option>
                    {columns.map((c) => (
                      <option key={c.name} value={c.name}>{c.name}</option>
                    ))}
                  </select>
                </Field>
              </>
            )}
            <Field label="Cron schedule" hint="Leave a schedule to run automatically; clear it to sync manually only">
              <input
                type="text"
                style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, width: 160 }}
                value={cronSchedule}
                onChange={(e) => setCronSchedule(e.target.value)}
                placeholder="*/15 * * * *"
              />
            </Field>
            {save.isError && (
              <div className="form-error">
                {save.error instanceof ApiError ? save.error.message : "Couldn't save the schedule."}
              </div>
            )}
            <div className="form-actions">
              <button type="button" className="btn quiet" onClick={onClose}>
                Close
              </button>
              <button type="submit" className="btn" disabled={save.isPending || !table}>
                {save.isPending ? "Saving…" : "Save schedule"}
              </button>
            </div>
          </form>
        </>
      )}
    </Dialog>
  );
}

function ConnectionRow({
  workspaceId,
  projectId,
  connection,
  canEdit,
  health,
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  canEdit: boolean;
  health: SyncHealth | undefined;
}) {
  const queryClient = useQueryClient();
  const [showSchema, setShowSchema] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showSync, setShowSync] = useState(false);
  const [showScheduledSync, setShowScheduledSync] = useState(false);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["connections", projectId] });
    queryClient.invalidateQueries({ queryKey: ["sync-health", projectId] });

  const test = useMutation({
    mutationFn: () => connApi.test(workspaceId, projectId, connection.id),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => connApi.remove(workspaceId, projectId, connection.id),
    onSuccess: async () => {
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
    },
  });

  return (
    <tr>
      <td>
        <strong>{connection.name}</strong>
        <div className="slug">{connection.source_type}</div>
      </td>
      <td>
        {connection.scope === "workspace" ? (
          <span className="chip">workspace</span>
        ) : (
          <span className="count">project</span>
        )}
      </td>
      <td>
        <StatusBadge connection={connection} />
      </td>
      <td>
        <HealthCell health={health} />
      </td>
      <td>
        {canEdit && (
          <div className="row-actions">
            <button
              className="btn quiet"
              style={{ padding: "3px 9px", fontSize: 12 }}
              disabled={test.isPending}
              onClick={() => test.mutate()}
            >
              {test.isPending ? "Testing…" : "Test"}
            </button>
            <button
              className="btn quiet"
              style={{ padding: "3px 9px", fontSize: 12 }}
              onClick={() => setShowSchema(true)}
            >
              Schema
            </button>
            <button
              className="btn quiet"
              style={{ padding: "3px 9px", fontSize: 12 }}
              onClick={() => setShowSync(true)}
            >
              Sync
            </button>
            <button
              className="btn quiet"
              style={{ padding: "3px 9px", fontSize: 12 }}
              onClick={() => setShowHistory(true)}
            >
              History
            </button>
            <button
              className="btn quiet"
              style={{ padding: "3px 9px", fontSize: 12 }}
              onClick={() => setShowScheduledSync(true)}
            >
              Scheduled sync
            </button>
            <button
              className="btn danger"
              style={{ padding: "3px 9px", fontSize: 12 }}
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Remove ${connection.name}? Its stored credentials are deleted too.`)) {
                  remove.mutate();
                }
              }}
            >
              Remove
            </button>
          </div>
        )}
        {showHistory && (
          <HistoryDialog
            workspaceId={workspaceId}
            projectId={projectId}
            connection={connection}
            onClose={() => setShowHistory(false)}
          />
        )}
        {showSync && (
          <SyncDialog
            workspaceId={workspaceId}
            projectId={projectId}
            connection={connection}
            onClose={() => setShowSync(false)}
          />
        )}
        {showSchema && (
          <DiscoverDialog
            workspaceId={workspaceId}
            projectId={projectId}
            connection={connection}
            onClose={() => setShowSchema(false)}
          />
        )}
        {showScheduledSync && (
          <ScheduledSyncDialog
            workspaceId={workspaceId}
            projectId={projectId}
            connection={connection}
            onClose={() => setShowScheduledSync(false)}
          />
        )}
      </td>
    </tr>
  );
}

export default function ConnectionsPage() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);

  const list = useQuery({
    queryKey: ["connections", project?.id],
    queryFn: () => connApi.list(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  // One request covering every connection on the page, rather than a runs
  // request per row. Health is informational, so a failure here must not take
  // the list down with it - the cell just renders empty.
  const health = useQuery({
    queryKey: ["sync-health", project?.id],
    queryFn: () => syncApi.health(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
    retry: false,
  });
  const healthById = new Map((health.data ?? []).map((h) => [h.connection_id, h]));

  const canEdit = project ? project.effective_role !== "viewer" : false;
  const canWorkspaceScope = workspace?.effective_role === "admin";

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · connections</p>
          <h1>Connections</h1>
        </div>
        {canEdit && workspace && project && (
          <AddConnectionWizard
            workspaceId={workspace.id}
            projectId={project.id}
            canWorkspaceScope={canWorkspaceScope}
          />
        )}
      </div>

      {list.isPending && <div className="state">Loading connections…</div>}
      {list.isError && (
        <div className="state error">Couldn&apos;t load connections. Refresh to try again.</div>
      )}
      {list.data && list.data.length === 0 && (
        <div className="empty">
          <h2>Connect your first source</h2>
          <p>
            Point Anchor at a database and query it in place. Credentials go straight to
            your own AWS Secrets Manager - the platform never stores them anywhere else.
          </p>
          {canEdit && workspace && project && (
            <AddConnectionWizard
              workspaceId={workspace.id}
              projectId={project.id}
              canWorkspaceScope={canWorkspaceScope}
            />
          )}
        </div>
      )}
      {list.data && list.data.length > 0 && workspace && project && (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Sharing</th>
              <th>Status</th>
              <th>Sync health</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {list.data.map((c) => (
              <ConnectionRow
                key={c.id}
                workspaceId={workspace.id}
                projectId={project.id}
                connection={c}
                canEdit={canEdit}
                health={healthById.get(c.id)}
              />
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
