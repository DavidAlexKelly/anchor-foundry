"use client";

import { Editor, Element, Frame, useEditor } from "@craftjs/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ApiError, api, canvas as canvasApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { CanvasEnvProvider } from "@/components/canvas/context";
import { SettingsPanel } from "@/components/canvas/SettingsPanel";
import { CANVAS_RESOLVER, CanvasContainer, PALETTE, PaletteItem } from "@/components/canvas/widgets";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { CanvasAppDetail, CanvasPublishScope, Group } from "@/lib/types";

function PublishDialog({
  workspaceId,
  projectId,
  app,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  app: CanvasAppDetail;
  onClose: () => void;
}) {
  const [scope, setScope] = useState<CanvasPublishScope>(app.publish_scope);
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const queryClient = useQueryClient();

  const groups = useQuery({ queryKey: ["org-groups"], queryFn: api.orgGroups, enabled: scope === "groups" });
  const shares = useQuery({
    queryKey: ["canvas-shares", app.id],
    queryFn: () => canvasApi.listShares(workspaceId, projectId, app.id),
    enabled: scope === "groups",
  });

  const publish = useMutation({
    mutationFn: () => canvasApi.publish(workspaceId, projectId, app.id, { scope, group_ids: groupIds }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["canvas-app", app.id] });
      onClose();
    },
  });

  const selectedGroupIds = groupIds.length > 0 ? groupIds : (shares.data?.map((s) => s.group_id) ?? []);

  return (
    <Dialog open title={`Publish ${app.name}`} onClose={onClose}>
      <p className="login-note" style={{ marginTop: 0 }}>
        Private apps are visible only to this project. Publishing shares the current saved version
        read-only with the rest of the workspace, or specific groups.
      </p>
      <Field label="Visibility">
        <select value={scope} onChange={(e) => setScope(e.target.value as CanvasPublishScope)}>
          <option value="private">Private — this project only</option>
          <option value="workspace">Whole workspace</option>
          <option value="groups">Specific groups</option>
        </select>
      </Field>
      {scope === "groups" && (
        <Field label="Groups" hint="Members of any checked group can open this app">
          <div>
            {groups.data?.map((g: Group) => (
              <label key={g.id} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <input
                  type="checkbox"
                  checked={selectedGroupIds.includes(g.id)}
                  onChange={(e) => {
                    const base = selectedGroupIds;
                    setGroupIds(e.target.checked ? [...base, g.id] : base.filter((id) => id !== g.id));
                  }}
                />
                {g.name}
              </label>
            ))}
            {groups.data && groups.data.length === 0 && (
              <p className="canvas-widget-empty">No groups yet — create one under Organisation settings.</p>
            )}
          </div>
        </Field>
      )}
      {publish.isError && (
        <div className="form-error">
          {publish.error instanceof ApiError ? publish.error.message : "Couldn't update publishing."}
        </div>
      )}
      <div className="form-actions">
        <button type="button" className="btn quiet" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          disabled={publish.isPending || (scope === "groups" && selectedGroupIds.length === 0)}
          onClick={() => publish.mutate()}
        >
          {publish.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </Dialog>
  );
}

function TopBar({
  app,
  workspaceSlug,
  projectSlug,
  workspaceId,
  projectId,
  canEdit,
  canPublish,
}: {
  app: CanvasAppDetail;
  workspaceSlug: string;
  projectSlug: string;
  workspaceId: string;
  projectId: string;
  canEdit: boolean;
  canPublish: boolean;
}) {
  const { enabled, actions, query } = useEditor((state) => ({ enabled: state.options.enabled }));
  const [showPublish, setShowPublish] = useState(false);
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: () => canvasApi.saveDefinition(workspaceId, projectId, app.id, query.getSerializedNodes()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["canvas-app", app.id] });
    },
  });

  return (
    <div className="page-head">
      <div>
        <p className="eyebrow">
          <Link href={`/${workspaceSlug}/${projectSlug}/canvas`}>project · canvas</Link>
        </p>
        <h1>{app.name}</h1>
        <p className="sub">
          v{app.current_version}
          {app.publish_scope !== "private" && ` · published (${app.publish_scope})`}
          {save.isSuccess && " · saved"}
        </p>
      </div>
      <div className="row-actions">
        <button
          type="button"
          className="btn quiet"
          onClick={() => actions.setOptions((o) => (o.enabled = !enabled))}
        >
          {enabled ? "Preview" : "Back to editing"}
        </button>
        {canEdit && enabled && (
          <button type="button" className="btn" disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
        )}
        {canPublish && (
          <button type="button" className="btn quiet" onClick={() => setShowPublish(true)}>
            Publish
          </button>
        )}
      </div>
      {showPublish && (
        <PublishDialog workspaceId={workspaceId} projectId={projectId} app={app} onClose={() => setShowPublish(false)} />
      )}
    </div>
  );
}

function CanvasEnvBridge({
  workspaceId,
  projectId,
  children,
}: {
  workspaceId: string;
  projectId: string;
  children: React.ReactNode;
}) {
  const { enabled } = useEditor((state) => ({ enabled: state.options.enabled }));
  return (
    <CanvasEnvProvider value={{ workspaceId, projectId, mode: enabled ? "edit" : "run" }}>
      {children}
    </CanvasEnvProvider>
  );
}

function Toolbox() {
  return (
    <div className="canvas-toolbox">
      <p className="field-label">Widgets</p>
      {PALETTE.map((p) => (
        <PaletteItem key={p.key} componentKey={p.key} label={p.label} hint={p.hint} />
      ))}
    </div>
  );
}

export default function CanvasAppEditorPage() {
  const params = useParams<{ workspace: string; project: string; appId: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);

  const appQuery = useQuery({
    queryKey: ["canvas-app", params.appId],
    queryFn: () => canvasApi.get(workspace!.id, project!.id, params.appId),
    enabled: !!workspace && !!project,
  });

  const canEdit = project ? project.effective_role !== "viewer" : false;
  const canPublish = workspace?.effective_role === "admin";

  if (appQuery.isPending || !workspace || !project) {
    return (
      <main>
        <div className="state">Loading app…</div>
      </main>
    );
  }
  if (appQuery.isError) {
    return (
      <main>
        <div className="state error">Couldn&apos;t load this app. It may have been deleted.</div>
      </main>
    );
  }

  const app = appQuery.data;
  const hasSavedLayout = Object.keys(app.definition).length > 0;

  return (
    <main>
      <Editor resolver={CANVAS_RESOLVER} enabled={canEdit}>
        <CanvasEnvBridge workspaceId={workspace.id} projectId={project.id}>
          <TopBar
            app={app}
            workspaceSlug={params.workspace}
            projectSlug={params.project}
            workspaceId={workspace.id}
            projectId={project.id}
            canEdit={canEdit}
            canPublish={canPublish}
          />
          <CanvasBody hasSavedLayout={hasSavedLayout} definition={app.definition} canEdit={canEdit} />
        </CanvasEnvBridge>
      </Editor>
    </main>
  );
}

function CanvasBody({
  hasSavedLayout,
  definition,
  canEdit,
}: {
  hasSavedLayout: boolean;
  definition: Record<string, unknown>;
  canEdit: boolean;
}) {
  const { enabled } = useEditor((state) => ({ enabled: state.options.enabled }));
  const showChrome = enabled && canEdit;
  return (
    <div className={showChrome ? "canvas-shell" : "canvas-shell canvas-shell--full"}>
      {showChrome && <Toolbox />}
      <div className="canvas-frame-area">
        {hasSavedLayout ? (
          <Frame data={JSON.stringify(definition)} />
        ) : (
          <Frame>
            <Element is={CanvasContainer} canvas />
          </Frame>
        )}
      </div>
      {showChrome && (
        <div className="canvas-settings">
          <SettingsPanel />
        </div>
      )}
    </div>
  );
}
