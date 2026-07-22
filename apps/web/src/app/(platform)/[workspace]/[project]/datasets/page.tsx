"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ApiError, datasets as dsApi, downloadFile } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { Dataset, TabularResult } from "@/lib/types";

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
          <Field label="File" hint="CSV, TSV, Parquet, JSON, or JSONL — up to 50 MB">
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

function ExploreDialog({
  workspaceId,
  projectId,
  dataset,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  dataset: Dataset;
  onClose: () => void;
}) {
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
            Everything is stored in open formats in your own account — exportable at
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
