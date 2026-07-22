"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ApiError, connections as connApi, sync as syncApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { Connection, DiscoveredTable, SourceTypeInfo } from "@/lib/types";

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
        typedConfig[key] = prop?.type === "integer" ? Number(value) : value;
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
                  Fix the details from the connection list and test again — nothing is lost.
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
                  <p style={{ margin: 0 }}>Connect and query in place — no data copied.</p>
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
                <input
                  type={prop.type === "integer" ? "number" : "text"}
                  value={config[key] ?? ""}
                  onChange={(e) => setConfig({ ...config, [key]: e.target.value })}
                  required={selected.config_schema.required?.includes(key) ?? false}
                />
              </Field>
            ))}
            {selected.secret_fields.map((key) => (
              <Field
                key={key}
                label={key}
                hint="Stored in your AWS Secrets Manager — never shown again"
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
              <div className="schema-name">{schema}</div>
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
      if (!table) throw new Error("pick a table");
      const dot = table.indexOf(".");
      const schema = dot === -1 ? "public" : table.slice(0, dot);
      const name = dot === -1 ? table : table.slice(dot + 1);
      return syncApi.trigger(workspaceId, projectId, connection.id, {
        source_schema: schema,
        source_table: name,
        dataset_name: datasetName || undefined,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["connections", projectId] });
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
                  const dot = e.target.value.indexOf(".");
                  const name = dot === -1 ? e.target.value : e.target.value.slice(dot + 1);
                  if (name && !datasetName) setDatasetName(name);
                }}
                required
              >
                <option value="">Choose a table…</option>
                {discover.data
                  .filter((t) => t.kind === "table")
                  .map((t) => (
                    <option key={`${t.schema_name}.${t.name}`} value={`${t.schema_name}.${t.name}`}>
                      {t.schema_name}.{t.name} ({t.columns.length} columns)
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

function ConnectionRow({
  workspaceId,
  projectId,
  connection,
  canEdit,
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const [showSchema, setShowSchema] = useState(false);
  const [showSync, setShowSync] = useState(false);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["connections", projectId] });

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
            your own AWS Secrets Manager — the platform never stores them anywhere else.
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
              />
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
