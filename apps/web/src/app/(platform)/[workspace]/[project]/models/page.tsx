"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ApiError, datasets as dsApi, models as modelApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { Model } from "@/lib/types";

const DEFAULT_SQL = "SELECT *\n  FROM orders\n LIMIT 100";
const DEFAULT_PYTHON = "output = orders.copy()\n";

function RunBadge({ model }: { model: Model }) {
  if (!model.last_run_status) {
    return <span className="status-unconfigured"><span className="status-dot" /><span className="status-label">Never run</span></span>;
  }
  const cls = model.last_run_status === "succeeded" ? "status-ok"
    : model.last_run_status === "failed" ? "status-error" : "status-testing";
  return (
    <span className={cls}>
      <span className="status-dot" />
      <span className="status-label">{model.last_run_status}</span>
    </span>
  );
}

function ScheduleSummary({ model }: { model: Model }) {
  if (model.trigger_mode !== "cron") return <span className="count">manual</span>;
  const next = model.next_run_at ? new Date(model.next_run_at).toLocaleString() : "due now";
  return (
    <span title={model.cron_schedule ?? undefined}>
      <span className="chip">{model.cron_schedule}</span>
      <div className="slug">next: {next}</div>
    </span>
  );
}

function ModelDialog({
  workspaceId,
  projectId,
  existing,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  existing: Model | null;
  onClose: () => void;
}) {
  const [name, setName] = useState(existing?.name ?? "");
  const [language, setLanguage] = useState<"sql" | "python">(existing?.language ?? "sql");
  const [code, setCode] = useState(existing?.code ?? DEFAULT_SQL);
  const [inputs, setInputs] = useState<{ dataset_id: string; input_alias: string }[]>(
    existing?.inputs.map((i) => ({ dataset_id: i.dataset_id, input_alias: i.input_alias })) ?? [],
  );
  const [triggerMode, setTriggerMode] = useState<"manual" | "cron">(
    existing?.trigger_mode === "cron" ? "cron" : "manual",
  );
  const [cronSchedule, setCronSchedule] = useState(existing?.cron_schedule ?? "0 * * * *");
  const queryClient = useQueryClient();

  const availableDatasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });

  const save = useMutation({
    mutationFn: () =>
      existing
        ? modelApi.update(workspaceId, projectId, existing.id, {
            name,
            code,
            inputs,
            trigger_mode: triggerMode,
            cron_schedule: triggerMode === "cron" ? cronSchedule : null,
          })
        : modelApi.create(workspaceId, projectId, { name, language, code, inputs }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["models", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
      onClose();
    },
  });

  function aliasFor(datasetId: string): string {
    const ds = availableDatasets.data?.find((d) => d.id === datasetId);
    const base = (ds?.slug ?? "input").replace(/[^a-z0-9_]/g, "_").replace(/^[0-9]+/, "");
    return base || "input";
  }

  return (
    <Dialog open wide title={existing ? `Edit ${existing.name}` : "New model"} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Name">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={200}
          />
        </Field>
        {existing ? (
          <Field label="Language">
            <span className="chip">{existing.language === "python" ? "Python" : "SQL"}</span>
          </Field>
        ) : (
          <Field label="Language" hint="Can't be changed once the model is created">
            <select
              value={language}
              onChange={(e) => {
                const next = e.target.value as "sql" | "python";
                setLanguage(next);
                if (code === DEFAULT_SQL || code === DEFAULT_PYTHON) {
                  setCode(next === "python" ? DEFAULT_PYTHON : DEFAULT_SQL);
                }
              }}
            >
              <option value="sql">SQL</option>
              <option value="python">Python</option>
            </select>
          </Field>
        )}
        <Field
          label="Input datasets"
          hint="Each input is a table (SQL) or a pandas DataFrame (Python), named by its alias"
        >
          <div>
            {inputs.map((input, index) => (
              <div key={index} className="row-actions" style={{ marginBottom: 6 }}>
                <select
                  value={input.dataset_id}
                  onChange={(e) => {
                    const next = [...inputs];
                    next[index] = {
                      dataset_id: e.target.value,
                      input_alias: input.input_alias || aliasFor(e.target.value),
                    };
                    setInputs(next);
                  }}
                  required
                >
                  <option value="">Choose a dataset…</option>
                  {availableDatasets.data?.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 12.5,
                    padding: "4px 8px",
                    border: "1px solid var(--line-strong)",
                    borderRadius: "var(--radius)",
                    width: 140,
                  }}
                  value={input.input_alias}
                  onChange={(e) => {
                    const next = [...inputs];
                    next[index] = { ...input, input_alias: e.target.value };
                    setInputs(next);
                  }}
                  placeholder="alias"
                  required
                />
                <button
                  type="button"
                  className="btn danger"
                  style={{ padding: "3px 9px", fontSize: 12 }}
                  onClick={() => setInputs(inputs.filter((_, i) => i !== index))}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn quiet"
              style={{ padding: "4px 10px", fontSize: 12.5 }}
              onClick={() => setInputs([...inputs, { dataset_id: "", input_alias: "" }])}
            >
              Add input
            </button>
          </div>
        </Field>
        <Field
          label={(existing?.language ?? language) === "python" ? "Python" : "SQL"}
          hint={
            (existing?.language ?? language) === "python"
              ? "Each input alias is a pandas DataFrame; set an `output` DataFrame with the result"
              : "Query the inputs by their aliases; the result becomes the output dataset"
          }
        >
          <textarea
            className="sql-box"
            style={{ minHeight: 140 }}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            spellCheck={false}
          />
        </Field>
        {existing && (
          <Field label="Schedule" hint="Cron runs are queued for the background worker, same as Python">
            <div className="row-actions">
              <select
                value={triggerMode}
                onChange={(e) => setTriggerMode(e.target.value as "manual" | "cron")}
              >
                <option value="manual">Manual only</option>
                <option value="cron">On a schedule</option>
              </select>
              {triggerMode === "cron" && (
                <input
                  type="text"
                  style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, width: 140 }}
                  value={cronSchedule}
                  onChange={(e) => setCronSchedule(e.target.value)}
                  placeholder="0 * * * *"
                  required
                />
              )}
            </div>
          </Field>
        )}
        {save.isError && (
          <div className="form-error">
            {save.error instanceof ApiError ? save.error.message : "Couldn't save the model."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn"
            disabled={save.isPending || !name.trim() || !code.trim()}
          >
            {save.isPending ? "Saving…" : existing ? "Save changes" : "Create model"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ModelRow({
  workspaceId,
  projectId,
  model,
  canEdit,
}: {
  workspaceId: string;
  projectId: string;
  model: Model;
  canEdit: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const queryClient = useQueryClient();
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["models", projectId] });
    await queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
    await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
  };

  const run = useMutation({
    mutationFn: () => modelApi.run(workspaceId, projectId, model.id),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => modelApi.remove(workspaceId, projectId, model.id),
    onSuccess: refresh,
  });

  const result = run.data;

  return (
    <tr>
      <td>
        <strong>{model.name}</strong>
        <div className="slug">
          {model.inputs.map((i) => i.input_alias).join(", ") || "no inputs"} →{" "}
          {model.output_dataset_id ? "output dataset" : "not yet run"}
        </div>
        {result && result.status === "queued" && (
          <p className="login-note" style={{ margin: "6px 0 0" }}>
            Queued — Python models run on the background worker. Check back for the result.
          </p>
        )}
        {result && result.status !== "queued" && !result.ok && (
          <div className="form-error" style={{ marginTop: 6 }}>{result.error}</div>
        )}
        {result && result.status !== "queued" && result.ok && result.output_dataset && (
          <p className="login-note" style={{ margin: "6px 0 0" }}>
            Produced {result.rows_produced.toLocaleString()} rows → {result.output_dataset.name}{" "}
            v{result.output_dataset.current_version} (see Datasets)
          </p>
        )}
      </td>
      <td>
        <RunBadge model={model} />
      </td>
      <td>
        <ScheduleSummary model={model} />
      </td>
      <td>
        {canEdit && (
          <div className="row-actions">
            <button
              className="btn"
              style={{ padding: "3px 11px", fontSize: 12 }}
              disabled={run.isPending}
              onClick={() => run.mutate()}
            >
              {run.isPending ? "Running…" : "Run"}
            </button>
            <button
              className="btn quiet"
              style={{ padding: "3px 9px", fontSize: 12 }}
              onClick={() => setEditing(true)}
            >
              Edit
            </button>
            <button
              className="btn danger"
              style={{ padding: "3px 9px", fontSize: 12 }}
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Delete ${model.name}? Its output dataset is kept.`)) {
                  remove.mutate();
                }
              }}
            >
              Delete
            </button>
          </div>
        )}
        {editing && (
          <ModelDialog
            workspaceId={workspaceId}
            projectId={projectId}
            existing={model}
            onClose={() => setEditing(false)}
          />
        )}
      </td>
    </tr>
  );
}

export default function ModelsPage() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const [creating, setCreating] = useState(false);

  const list = useQuery({
    queryKey: ["models", project?.id],
    queryFn: () => modelApi.list(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  const canEdit = project ? project.effective_role !== "viewer" : false;

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · models</p>
          <h1>Models</h1>
        </div>
        {canEdit && (
          <button className="btn" onClick={() => setCreating(true)}>
            New model
          </button>
        )}
      </div>

      {list.isPending && <div className="state">Loading models…</div>}
      {list.isError && (
        <div className="state error">Couldn&apos;t load models. Refresh to try again.</div>
      )}
      {list.data && list.data.length === 0 && (
        <div className="empty">
          <h2>No models yet</h2>
          <p>
            Models transform datasets into new datasets with SQL — joins, filters,
            aggregations. Every run is versioned and lineage is tracked automatically.
          </p>
          {canEdit && (
            <button className="btn" onClick={() => setCreating(true)}>
              Create model
            </button>
          )}
        </div>
      )}
      {list.data && list.data.length > 0 && workspace && project && (
        <table className="table">
          <thead>
            <tr>
              <th>Model</th>
              <th>Last run</th>
              <th>Schedule</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {list.data.map((m) => (
              <ModelRow
                key={m.id}
                workspaceId={workspace.id}
                projectId={project.id}
                model={m}
                canEdit={canEdit}
              />
            ))}
          </tbody>
        </table>
      )}
      {creating && workspace && project && (
        <ModelDialog
          workspaceId={workspace.id}
          projectId={project.id}
          existing={null}
          onClose={() => setCreating(false)}
        />
      )}
    </main>
  );
}
