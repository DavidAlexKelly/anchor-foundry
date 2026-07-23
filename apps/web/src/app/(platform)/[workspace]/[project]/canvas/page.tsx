"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, canvas as canvasApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { CanvasApp } from "@/lib/types";

function NewAppDialog({
  workspaceId,
  projectId,
  workspaceSlug,
  projectSlug,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  workspaceSlug: string;
  projectSlug: string;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const queryClient = useQueryClient();
  const router = useRouter();

  const create = useMutation({
    mutationFn: () => canvasApi.create(workspaceId, projectId, { name, description }),
    onSuccess: async (app) => {
      await queryClient.invalidateQueries({ queryKey: ["canvas-apps", projectId] });
      router.push(`/${workspaceSlug}/${projectSlug}/canvas/${app.id}`);
    },
  });

  return (
    <Dialog open title="New canvas app" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Name">
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus />
        </Field>
        <Field label="Description" hint="Optional — shown on the app card">
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
        </Field>
        {create.isError && (
          <div className="form-error">
            {create.error instanceof ApiError ? create.error.message : "Couldn't create the app."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn" disabled={create.isPending || !name.trim()}>
            {create.isPending ? "Creating…" : "Create app"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function AppCard({
  app,
  workspaceSlug,
  projectSlug,
  workspaceId,
  projectId,
  canEdit,
}: {
  app: CanvasApp;
  workspaceSlug: string;
  projectSlug: string;
  workspaceId: string;
  projectId: string;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => canvasApi.remove(workspaceId, projectId, app.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["canvas-apps", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
    },
  });

  return (
    <div className="card">
      <h3>{app.name}</h3>
      <div className="slug">{app.slug}</div>
      <p>{app.description || "No description yet."}</p>
      <div className="meta">
        <span className="count">v{app.current_version}</span>
        {app.publish_scope !== "private" && <span className="chip">{app.publish_scope}</span>}
      </div>
      <div className="row-actions" style={{ marginTop: 10 }}>
        <Link href={`/${workspaceSlug}/${projectSlug}/canvas/${app.id}`} className="btn quiet" style={{ padding: "3px 11px", fontSize: 12 }}>
          Open
        </Link>
        {canEdit && (
          <button
            className="btn danger"
            style={{ padding: "3px 9px", fontSize: 12 }}
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(`Delete ${app.name}? This can't be undone.`)) remove.mutate();
            }}
          >
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

export default function CanvasListPage() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const [creating, setCreating] = useState(false);

  const list = useQuery({
    queryKey: ["canvas-apps", project?.id],
    queryFn: () => canvasApi.list(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  const canEdit = project ? project.effective_role !== "viewer" : false;

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · canvas</p>
          <h1>Canvas</h1>
        </div>
        {canEdit && (
          <button className="btn" onClick={() => setCreating(true)}>
            New canvas app
          </button>
        )}
      </div>

      {list.isPending && <div className="state">Loading apps…</div>}
      {list.isError && <div className="state error">Couldn&apos;t load apps. Refresh to try again.</div>}
      {list.data && list.data.length === 0 && (
        <div className="empty">
          <h2>No apps yet</h2>
          <p>
            Canvas apps are built from widgets bound to your objects — tables, charts, forms with
            write-back. No code needed; drop into code when you want it.
          </p>
          {canEdit && (
            <button className="btn" onClick={() => setCreating(true)}>
              New canvas app
            </button>
          )}
        </div>
      )}
      {list.data && list.data.length > 0 && workspace && project && (
        <div className="grid">
          {list.data.map((app) => (
            <AppCard
              key={app.id}
              app={app}
              workspaceSlug={workspace.slug}
              projectSlug={project.slug}
              workspaceId={workspace.id}
              projectId={project.id}
              canEdit={canEdit}
            />
          ))}
        </div>
      )}
      {creating && workspace && project && (
        <NewAppDialog
          workspaceId={workspace.id}
          projectId={project.id}
          workspaceSlug={workspace.slug}
          projectSlug={project.slug}
          onClose={() => setCreating(false)}
        />
      )}
    </main>
  );
}
