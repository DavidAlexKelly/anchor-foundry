"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ApiError, datasets as dsApi, downloadFile } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { Dataset, DatasetHealth, TabularResult } from "@/lib/types";

function ResultGrid({ result }: { result: TabularResult }) {
  return (
    <>
      <div className="data-grid">
        <table>
          <thead>
            <tr>
              {result.columns.map((c) => (
                <th key={c.name} title={c.data_type}>
                  {c.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row, i) => (
              <tr key={i}>
                {row.map((v, j) => (
                  <td key={j}>{v === null ? "∅" : String(v)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="login-note">
        {result.truncated
          ? `Showing the first ${result.rows.length} rows.`
          : `${result.total_rows} ${result.total_rows === 1 ? "row" : "rows"}.`}
      </p>
    </>
  );
}

function UploadDialog({ workspaceId, projectId }: { workspaceId: string; projectId: string }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const queryClient = useQueryClient();

  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("choose a file");
      return dsApi.upload(workspaceId, projectId, { name, file });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
      setOpen(false);
      setName("");
      setFile(null);
    },
  });

  function close() {
    if (!upload.isPending) {
      setOpen(false);
      upload.reset();
    }
  }

  return (
    <>
      <button className="btn" onClick={() => setOpen(true)}>
        Upload file
      </button>
      <Dialog open={open} title="Upload a dataset" onClose={close}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            upload.mutate();
          }}
        >
          <Field label="File" hint="CSV, TSV, Parquet, JSON, or JSONL - up to 50 MB">
            <input
              type="file"
              accept=".csv,.tsv,.parquet,.json,.jsonl"
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                setFile(f);
                if (f && !name) setName(f.name.replace(/\.[^.]+$/, ""));
              }}
              required
            />
          </Field>
          <Field label="Dataset name">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={200}
            />
          </Field>
          {upload.isError && (
            <div className="form-error">
              {upload.error instanceof ApiError
                ? upload.error.message
                : "Couldn't upload the file. Check it and try again."}
            </div>
          )}
          <div className="form-actions">
            <button type="button" className="btn quiet" onClick={close}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn"
              disabled={upload.isPending || !file || !name.trim()}
            >
              {upload.isPending ? "Uploading…" : "Upload"}
            </button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

const RULE_TYPES: { value: string; label: string; needs: "range" | "pattern" | null }[] = [
  { value: "not_null", label: "Not null", needs: null },
  { value: "unique", label: "Unique", needs: null },
  { value: "value_in_range", label: "In range", needs: "range" },
  { value: "regex_match", label: "Matches pattern", needs: "pattern" },
  { value: "column_exists", label: "Column exists", needs: null },
];

/** The dataset's overall health. "none" is deliberately not a pass - nothing
 * was checked, which is a different fact and reads differently. */
function HealthBadge({ status }: { status: DatasetHealth["status"] | undefined }) {
  if (!status || status === "none") return <span className="count">no checks</span>;
  const tone = status === "pass" ? "ok" : status === "warn" ? "testing" : "error";
  return (
    <span className={`status-${tone}`}>
      <span className="status-dot" />
      <span className="status-label">{status}</span>
    </span>
  );
}

/** Define what "good" means for this dataset, and see whether the current
 * version lives up to it. */
function ChecksPanel({
  workspaceId,
  projectId,
  dataset,
  canEdit,
}: {
  workspaceId: string;
  projectId: string;
  dataset: Dataset;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const [ruleType, setRuleType] = useState("not_null");
  const [column, setColumn] = useState(dataset.table_schema[0]?.name ?? "");
  const [severity, setSeverity] = useState("error");
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");
  const [pattern, setPattern] = useState("");

  const health = useQuery({
    queryKey: ["health", dataset.id],
    queryFn: () => dsApi.health(workspaceId, projectId, dataset.id),
    retry: false,
  });
  const rules = useQuery({
    queryKey: ["expectations", dataset.id],
    queryFn: () => dsApi.expectations(workspaceId, projectId, dataset.id),
    retry: false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["expectations", dataset.id] });
    await queryClient.invalidateQueries({ queryKey: ["health", dataset.id] });
    await queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
  };

  const add = useMutation({
    mutationFn: () => {
      const needs = RULE_TYPES.find((r) => r.value === ruleType)?.needs;
      const config: Record<string, unknown> = {};
      if (needs === "range") {
        if (min !== "") config.min = Number(min);
        if (max !== "") config.max = Number(max);
      } else if (needs === "pattern") {
        config.pattern = pattern;
      }
      return dsApi.addExpectation(workspaceId, projectId, dataset.id, {
        rule_type: ruleType,
        column_name: column,
        config,
        severity,
      });
    },
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      dsApi.removeExpectation(workspaceId, projectId, dataset.id, id),
    onSuccess: refresh,
  });

  const needs = RULE_TYPES.find((r) => r.value === ruleType)?.needs;
  const resultsById = new Map(
    (health.data?.results ?? []).map((r) => [r.expectation_id, r]),
  );

  return (
    <div>
      <p className="login-note" style={{ marginTop: 0 }}>
        Health of version {health.data?.version_number ?? dataset.current_version}:{" "}
        <HealthBadge status={health.data?.status} />
      </p>

      {rules.data && rules.data.length > 0 && (
        <table className="table" style={{ marginBottom: 12 }}>
          <thead>
            <tr>
              <th>Column</th>
              <th>Check</th>
              <th>Severity</th>
              <th>Result</th>
              {canEdit && <th aria-label="Actions" />}
            </tr>
          </thead>
          <tbody>
            {rules.data.map((rule) => {
              const result = resultsById.get(rule.id);
              return (
                <tr key={rule.id}>
                  <td>
                    <strong>{rule.column_name}</strong>
                  </td>
                  <td>
                    {RULE_TYPES.find((r) => r.value === rule.rule_type)?.label ??
                      rule.rule_type}
                    {Object.keys(rule.config).length > 0 && (
                      <div className="count">{JSON.stringify(rule.config)}</div>
                    )}
                  </td>
                  <td className="count">{rule.severity}</td>
                  <td>
                    {result ? (
                      <>
                        <span
                          className={`status-${
                            result.status === "pass"
                              ? "ok"
                              : result.status === "error"
                                ? "testing"
                                : "error"
                          }`}
                        >
                          <span className="status-dot" />
                          <span className="status-label">{result.status}</span>
                        </span>
                        {result.message && (
                          <div className="count">{result.message}</div>
                        )}
                      </>
                    ) : (
                      <span className="count">—</span>
                    )}
                  </td>
                  {canEdit && (
                    <td>
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        onClick={() => remove.mutate(rule.id)}
                        disabled={remove.isPending}
                      >
                        Remove
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {rules.data && rules.data.length === 0 && (
        <div className="state">
          No checks yet. Add one below to start tracking this dataset&apos;s health.
        </div>
      )}

      {canEdit && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <Field label="Column">
            <select value={column} onChange={(e) => setColumn(e.target.value)} required>
              {dataset.table_schema.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Check">
            <select value={ruleType} onChange={(e) => setRuleType(e.target.value)}>
              {RULE_TYPES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
          {needs === "range" && (
            <>
              <Field label="Min" hint="Leave blank for no lower bound">
                <input type="number" value={min} onChange={(e) => setMin(e.target.value)} />
              </Field>
              <Field label="Max" hint="Leave blank for no upper bound">
                <input type="number" value={max} onChange={(e) => setMax(e.target.value)} />
              </Field>
            </>
          )}
          {needs === "pattern" && (
            <Field label="Pattern" hint="A regular expression every value must match">
              <input
                type="text"
                value={pattern}
                onChange={(e) => setPattern(e.target.value)}
                required
              />
            </Field>
          )}
          <Field label="Severity" hint="A warning surfaces without failing the dataset">
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="error">error</option>
              <option value="warn">warn</option>
            </select>
          </Field>
          {add.isError && (
            <div className="form-error">
              {add.error instanceof ApiError ? add.error.message : "Couldn't add the check."}
            </div>
          )}
          <div className="form-actions">
            <button className="btn" type="submit" disabled={add.isPending || !column}>
              {add.isPending ? "Adding…" : "Add check"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/** Column statistics for the current version - the "what am I actually
 * looking at" half of exploring a dataset, next to the row grid's "what does
 * a row look like". Fetched separately from preview so the grid is not held
 * up by an aggregate pass over the file. */
function ProfilePanel({
  workspaceId,
  projectId,
  dataset,
}: {
  workspaceId: string;
  projectId: string;
  dataset: Dataset;
}) {
  const profile = useQuery({
    queryKey: ["profile", dataset.id, dataset.current_version],
    queryFn: () => dsApi.profile(workspaceId, projectId, dataset.id),
    retry: false,
  });

  if (profile.isPending) return <div className="state">Profiling columns…</div>;
  if (profile.isError) {
    return (
      <div className="form-error">
        {profile.error instanceof ApiError
          ? profile.error.message
          : "Couldn't profile this dataset."}
      </div>
    );
  }
  if (!profile.data) return null;

  const rows = profile.data.row_count;
  return (
    <div style={{ maxHeight: 340, overflowY: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            <th>Column</th>
            <th>Type</th>
            <th>Nulls</th>
            <th>Distinct</th>
            <th>Min</th>
            <th>Max</th>
          </tr>
        </thead>
        <tbody>
          {profile.data.columns.map((column) => {
            const percent = Math.round(column.null_rate * 1000) / 10;
            return (
              <tr key={column.name}>
                <td>
                  <strong>{column.name}</strong>
                </td>
                <td className="count">{column.data_type}</td>
                <td>
                  {column.null_count === 0 ? (
                    <span className="count">none</span>
                  ) : (
                    // An entirely empty column is the thing worth noticing.
                    <span className={percent === 100 ? "status-error" : undefined}>
                      {percent}%{" "}
                      <span className="count">({column.null_count.toLocaleString()})</span>
                    </span>
                  )}
                </td>
                <td>
                  {column.distinct_count.toLocaleString()}
                  {rows > 0 && column.distinct_count === rows && (
                    <span className="chip" style={{ marginLeft: 6 }}>
                      unique
                    </span>
                  )}
                </td>
                <td className="count">{column.min ?? "—"}</td>
                <td className="count">{column.max ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SchemaPolicyControl({
  workspaceId,
  projectId,
  dataset,
  canEdit,
}: {
  workspaceId: string;
  projectId: string;
  dataset: Dataset;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (policy: "permissive" | "strict") =>
      dsApi.update(workspaceId, projectId, dataset.id, { schema_policy: policy }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["datasets", projectId] }),
  });
  const policy = save.data?.schema_policy ?? dataset.schema_policy;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        flexWrap: "wrap",
        padding: "8px 0 12px",
        borderBottom: "1px solid var(--line)",
        marginBottom: 12,
      }}
    >
      <strong style={{ fontSize: 12.5 }}>Schema changes</strong>
      {canEdit ? (
        <select
          value={policy}
          disabled={save.isPending}
          onChange={(e) => save.mutate(e.target.value as "permissive" | "strict")}
        >
          <option value="permissive">Allow any change</option>
          <option value="strict">Refuse removing or retyping a column</option>
        </select>
      ) : (
        <span className="chip">{policy}</span>
      )}
      <span className="slug">
        New columns are always allowed; strict blocks the changes that break
        anything reading this dataset.
      </span>
      {save.isError && (
        <div className="form-error" style={{ width: "100%" }}>
          {save.error instanceof ApiError ? save.error.message : "Couldn't save."}
        </div>
      )}
    </div>
  );
}

function ExploreDialog({
  workspaceId,
  projectId,
  dataset,
  canEdit,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  dataset: Dataset;
  canEdit: boolean;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"rows" | "columns" | "checks">("rows");
  const [sql, setSql] = useState(`SELECT * FROM dataset LIMIT 20`);
  const preview = useQuery({
    queryKey: ["preview", dataset.id],
    queryFn: () => dsApi.preview(workspaceId, projectId, dataset.id),
    retry: false,
  });
  const run = useMutation({
    mutationFn: () => dsApi.query(workspaceId, projectId, dataset.id, sql),
  });

  const shown = run.data ?? preview.data;

  return (
    <Dialog open wide title={dataset.name} onClose={onClose}>
      <p className="login-note" style={{ marginTop: 0 }}>
        {dataset.row_count.toLocaleString()} rows · query it as the table{" "}
        <code style={{ fontFamily: "var(--font-mono)" }}>dataset</code>
      </p>
      <div className="form-actions" style={{ marginBottom: 10, justifyContent: "flex-start" }}>
        <button
          className={tab === "rows" ? "btn" : "btn quiet"}
          onClick={() => setTab("rows")}
        >
          Rows
        </button>
        <button
          className={tab === "columns" ? "btn" : "btn quiet"}
          onClick={() => setTab("columns")}
        >
          Columns
        </button>
        <button
          className={tab === "checks" ? "btn" : "btn quiet"}
          onClick={() => setTab("checks")}
        >
          Checks
        </button>
      </div>
      {tab === "rows" ? (
        <>
          <textarea
            className="sql-box"
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            spellCheck={false}
            aria-label="SQL query"
          />
          <div className="form-actions" style={{ marginTop: 8, marginBottom: 12 }}>
            <button className="btn" onClick={() => run.mutate()} disabled={run.isPending}>
              {run.isPending ? "Running…" : "Run query"}
            </button>
          </div>
          {run.isError && (
            <div className="form-error" style={{ marginBottom: 10 }}>
              {run.error instanceof ApiError ? run.error.message : "Query failed."}
            </div>
          )}
          {preview.isPending && !shown && <div className="state">Loading preview…</div>}
          {shown && <ResultGrid result={shown} />}
        </>
      ) : tab === "columns" ? (
        <>
          {/* Shape lives with the columns, the same way the Checks tab owns
              values. */}
          <SchemaPolicyControl
            workspaceId={workspaceId}
            projectId={projectId}
            dataset={dataset}
            canEdit={canEdit}
          />
          <ProfilePanel
            workspaceId={workspaceId}
            projectId={projectId}
            dataset={dataset}
          />
        </>
      ) : (
        <ChecksPanel
          workspaceId={workspaceId}
          projectId={projectId}
          dataset={dataset}
          canEdit={canEdit}
        />
      )}
      <div className="form-actions">
        <button
          className="btn quiet"
          onClick={() =>
            downloadFile(
              dsApi.exportUrl(workspaceId, projectId, dataset.id, "csv"),
              `${dataset.slug}.csv`,
            )
          }
        >
          Export CSV
        </button>
        <button
          className="btn quiet"
          onClick={() =>
            downloadFile(
              dsApi.exportUrl(workspaceId, projectId, dataset.id, "parquet"),
              `${dataset.slug}.parquet`,
            )
          }
        >
          Export Parquet
        </button>
        <button className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}

function DatasetRow({
  workspaceId,
  projectId,
  dataset,
  canEdit,
}: {
  workspaceId: string;
  projectId: string;
  dataset: Dataset;
  canEdit: boolean;
}) {
  const [exploring, setExploring] = useState(false);
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => dsApi.remove(workspaceId, projectId, dataset.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
    },
  });

  return (
    <tr>
      <td>
        <strong>{dataset.name}</strong>
        <div className="slug">
          {dataset.table_schema.length} columns · v{dataset.current_version}
        </div>
      </td>
      <td className="count">{dataset.row_count.toLocaleString()}</td>
      <td>
        <span className="count">{dataset.origin}</span>
      </td>
      <td>
        <div className="row-actions">
          <button
            className="btn quiet"
            style={{ padding: "3px 9px", fontSize: 12 }}
            onClick={() => setExploring(true)}
          >
            Explore
          </button>
          {canEdit && (
            <button
              className="btn danger"
              style={{ padding: "3px 9px", fontSize: 12 }}
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Delete ${dataset.name}? Its stored files are removed too.`)) {
                  remove.mutate();
                }
              }}
            >
              Delete
            </button>
          )}
        </div>
        {exploring && (
          <ExploreDialog
            workspaceId={workspaceId}
            projectId={projectId}
            dataset={dataset}
            canEdit={canEdit}
            onClose={() => setExploring(false)}
          />
        )}
      </td>
    </tr>
  );
}

export default function DatasetsPage() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);

  const list = useQuery({
    queryKey: ["datasets", project?.id],
    queryFn: () => dsApi.list(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  const canEdit = project ? project.effective_role !== "viewer" : false;

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · datasets</p>
          <h1>Datasets</h1>
        </div>
        {canEdit && workspace && project && (
          <UploadDialog workspaceId={workspace.id} projectId={project.id} />
        )}
      </div>

      {list.isPending && <div className="state">Loading datasets…</div>}
      {list.isError && (
        <div className="state error">Couldn&apos;t load datasets. Refresh to try again.</div>
      )}
      {list.data && list.data.length === 0 && (
        <div className="empty">
          <h2>No datasets yet</h2>
          <p>
            Upload a file to explore it right here, or sync one in from a connection.
            Everything is stored in open formats in your own account - exportable at
            any time.
          </p>
          {canEdit && workspace && project && (
            <UploadDialog workspaceId={workspace.id} projectId={project.id} />
          )}
        </div>
      )}
      {list.data && list.data.length > 0 && workspace && project && (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Rows</th>
              <th>Origin</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {list.data.map((d) => (
              <DatasetRow
                key={d.id}
                workspaceId={workspace.id}
                projectId={project.id}
                dataset={d}
                canEdit={canEdit}
              />
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
