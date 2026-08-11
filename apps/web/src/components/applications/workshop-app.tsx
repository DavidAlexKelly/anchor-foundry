"use client";

/** Workshop — the module builder as its own application (parity stage 1a,
 * `docs/parity/workshop.md`).
 *
 * This is a move, not a rewrite. The Craft.js `<Editor>`, the three panels, the
 * palette and the viewer are the same ones that ran at
 * `/[workspace]/[project]/canvas/[appId]`; what changed is where they render.
 * Foundry's rule is that "each resource type opens in a different platform
 * application" (`docs/pal/foundry_getting-started.pdf` p.37), and a builder
 * with three panels of its own competing with a project sidebar for the same
 * screen was the one place we had not applied it.
 *
 * Two things are deliberately different from the page it replaces:
 *
 *   1. **No breadcrumb, no title, no eyebrow.** `ApplicationShell` draws all
 *      three for every application. Keeping the builder's own copies would put
 *      the module's name on screen twice, one of them linking somewhere the
 *      breadcrumb already goes.
 *   2. **Ids come from the resolved resource, not from slugs.** The old page
 *      read `useParams` and resolved workspace and project slugs to ids on
 *      every load. A resolved resource already carries both ids and the app's
 *      own `kind_id`, so the only lookup left is the one that answers "may this
 *      person edit or publish" - which is a role on a cached summary row, not
 *      an identity.
 */

import { Editor, Element, Frame, useEditor } from "@craftjs/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import { CanvasEnvProvider, CanvasParameterProvider } from "@/components/canvas/context";
import { useSearchParams } from "next/navigation";
import { seedFromQuery } from "@/components/canvas/pure";
import { VariableBridge } from "@/components/canvas/VariableBridge";
import type { WorkshopEventDef } from "@/components/canvas/events";
import {
  EventsPanel,
  TRIGGER_WIDGETS,
  type ActionCandidate,
  type PageCandidate,
  type TriggerCandidate,
} from "@/components/canvas/EventsPanel";
import { LayoutPanel } from "@/components/canvas/LayoutPanel";
import { CanvasNode, SettingsPanel } from "@/components/canvas/SettingsPanel";
import { VariablesPanel } from "@/components/canvas/VariablesPanel";
import { CANVAS_RESOLVER, CanvasContainer, PALETTE, PaletteItem } from "@/components/canvas/widgets";
import { useProjectById, useWorkspaceById } from "@/components/use-workspace";
import { ApiError, actions as actionApi, api, canvas as canvasApi } from "@/lib/api";
import { eventsOf, hasLayout, layoutOf, moduleFrom, variablesOf } from "@/lib/workshop-module";
import { useModuleTitle } from "@/components/canvas/module-title";
import type {
  CanvasAppDetail,
  CanvasPublishScope,
  Group,
  ResolvedResource,
  WorkshopEvent,
  WorkshopVariable,
} from "@/lib/types";

/** The Versions dialog (Foundry p.191-192).
 *
 * > "The Versions dialog is where builders can view a history of the saved
 * > versions for a module. Each saved version displays a timestamp, editor, and
 * > description if available."
 *
 * §88 made publishing mean something — saving does not move viewers, publishing
 * does. This is the surface around that: which version viewers are on, moving
 * them to a *chosen* one rather than the newest, and getting back to a version
 * that worked.
 *
 * **Revert saves the old document as a new version rather than rewinding**
 * (p.192), so the history in between survives and reverting a revert is another
 * save rather than an archaeology problem.
 */
function VersionsDialog({
  workspaceId,
  projectId,
  app,
  canEdit,
  onView,
  onReverted,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  app: CanvasAppDetail;
  canEdit: boolean;
  onView: (version: number) => void;
  /** Called after a revert, so the canvas can be remounted against the new
   * document — see the comment on `reloadToken`. */
  onReverted: () => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [failure, setFailure] = useState<string | null>(null);

  const versions = useQuery({
    queryKey: ["canvas-versions", app.id],
    queryFn: () => canvasApi.listVersions(workspaceId, projectId, app.id),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["canvas-versions", app.id] });
    await queryClient.invalidateQueries({ queryKey: ["canvas-app", app.id] });
  };
  const fail = (e: Error) => setFailure(e.message);

  const publishVersion = useMutation({
    mutationFn: (n: number) => canvasApi.publishVersion(workspaceId, projectId, app.id, n),
    onSuccess: refresh, onError: fail,
  });
  const revert = useMutation({
    mutationFn: (n: number) => canvasApi.revertToVersion(workspaceId, projectId, app.id, n),
    // The refetch has to land *before* the remount, or the canvas reloads
    // against the definition it already had and the revert looks like it did
    // nothing - which is the bug this callback exists to fix.
    onSuccess: async () => { await refresh(); onReverted(); onClose(); }, onError: fail,
  });
  const describe = useMutation({
    mutationFn: (input: { n: number; description: string }) =>
      canvasApi.describeVersion(workspaceId, projectId, app.id, input.n, input.description),
    onSuccess: async () => { setEditing(null); await refresh(); }, onError: fail,
  });
  const settings = useMutation({
    mutationFn: (next: { auto_publish_on_save?: boolean; prompt_for_description?: boolean }) =>
      canvasApi.setVersionSettings(workspaceId, projectId, app.id, next),
    onSuccess: refresh, onError: fail,
  });

  return (
    <Dialog open title={`Versions of ${app.name}`} onClose={onClose}>
      {failure && <p className="state error">{failure}</p>}
      <table className="rb-table" data-testid="versions-table">
        <thead>
          <tr><th>Version</th><th>Saved</th><th>By</th><th>Description</th><th /></tr>
        </thead>
        <tbody>
          {(versions.data ?? []).map((v) => (
            <tr key={v.id} data-version={v.version_number}>
              <td>
                v{v.version_number}
                {v.version_number === app.published_version && (
                  <span className="pill" data-testid="published-pill"> published</span>
                )}
              </td>
              <td>{new Date(v.created_at).toLocaleString()}</td>
              {/* Null when the account that saved it has since been deleted -
                  the version outlives the account, so it says so rather than
                  showing an empty cell. */}
              <td>{v.created_by_name ?? "(deleted user)"}</td>
              <td>
                {editing === v.version_number ? (
                  <input
                    value={draft}
                    autoFocus
                    data-testid="description-input"
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={() => describe.mutate({ n: v.version_number, description: draft })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") describe.mutate({ n: v.version_number, description: draft });
                      if (e.key === "Escape") setEditing(null);
                    }}
                  />
                ) : (
                  <span
                    className={v.description ? "" : "soft"}
                    onClick={() => {
                      if (!canEdit) return;
                      setEditing(v.version_number);
                      setDraft(v.description);
                    }}
                  >
                    {v.description || (canEdit ? "Add a description" : "—")}
                  </span>
                )}
              </td>
              <td>
                <div className="row-actions">
                  <button
                    type="button" className="btn quiet"
                    onClick={() => { onView(v.version_number); onClose(); }}
                  >
                    View
                  </button>
                  {canEdit && v.version_number !== app.published_version && (
                    <button
                      type="button" className="btn quiet"
                      data-testid={`publish-v${v.version_number}`}
                      onClick={() => publishVersion.mutate(v.version_number)}
                    >
                      Publish
                    </button>
                  )}
                  {canEdit && v.version_number !== app.current_version && (
                    <button
                      type="button" className="btn quiet"
                      data-testid={`revert-v${v.version_number}`}
                      onClick={() => revert.mutate(v.version_number)}
                    >
                      Revert
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {canEdit && (
        <>
          <label className="vars-toggle field">
            <input
              type="checkbox"
              checked={app.auto_publish_on_save}
              data-testid="auto-publish"
              onChange={(e) => settings.mutate({ auto_publish_on_save: e.target.checked })}
            />
            Automatically publish when saving
          </label>
          {/* Said plainly, because this undoes the default that makes saving
              safe: with it on, every save is immediately what viewers see. */}
          <p className="login-note" style={{ marginTop: 0 }}>
            With this on, every save is what viewers see straight away.
          </p>
          <label className="vars-toggle field">
            <input
              type="checkbox"
              checked={app.prompt_for_description}
              data-testid="prompt-description"
              onChange={(e) => settings.mutate({ prompt_for_description: e.target.checked })}
            />
            Always prompt for a description when saving
          </label>
        </>
      )}
    </Dialog>
  );
}

/** One historic version, read-only, with the banner p.191 requires.
 *
 * > "View this version: View the module at that specific version. When viewing
 * > a non-published version, a warning banner will appear at the top of the
 * > module."
 *
 * The banner is conditional exactly as documented — viewing the *published*
 * version is viewing what everybody else sees, which needs no warning, and a
 * banner that appeared every time would be one people learn to ignore.
 */
function ViewingVersion({
  workspaceId,
  projectId,
  app,
  version,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  app: CanvasAppDetail;
  version: number;
  onClose: () => void;
}) {
  const detail = useQuery({
    queryKey: ["canvas-version", app.id, version],
    queryFn: () => canvasApi.getVersion(workspaceId, projectId, app.id, version),
  });

  const definition = detail.data?.definition;
  const isPublished = version === app.published_version;

  return (
    <div data-testid="version-view" data-version={version}>
      <div className="ws-actions">
        <p className="sub">Viewing v{version} of {app.name}</p>
        <div className="spacer" />
        <button type="button" className="btn quiet" onClick={onClose}>
          Back to editing
        </button>
      </div>
      {!isPublished && (
        <p className="state error" role="status" data-testid="unpublished-banner">
          This is v{version}, which is not the version your viewers see
          {app.published_version ? ` (they are on v${app.published_version})` : " (nothing is published)"}.
          Nothing here can be edited.
        </p>
      )}
      {detail.isPending && <div className="state">Loading that version…</div>}
      {detail.isError && (
        <div className="state error">Couldn&apos;t load v{version}.</div>
      )}
      {definition && (
        <Editor resolver={CANVAS_RESOLVER} enabled={false} onRender={CanvasNode}>
          <CanvasEnvBridge
            workspaceId={workspaceId}
            projectId={projectId}
            appId={app.id}
            variables={variablesOf(definition)}
            events={eventsOf(definition)}
          >
            <Frame data={JSON.stringify(layoutOf(definition))} />
          </CanvasEnvBridge>
        </Editor>
      )}
    </div>
  );
}

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
        Private apps are visible only to this project. Publishing lists the app under the
        workspace&apos;s Apps page, read-only, for everyone here or for specific groups.
        It shares the layout, not access to the data: every widget still reads as whoever
        is looking. Publishing pins the version they see: saving afterwards does not
        change their view until you publish again.
      </p>
      {app.publish_scope !== "private" && app.published_version !== app.current_version && (
        <p className="login-note">
          They are on v{app.published_version ?? 0}; you are editing v{app.current_version}.
          Publishing again moves them to it.
        </p>
      )}
      <Field label="Visibility">
        <select value={scope} onChange={(e) => setScope(e.target.value as CanvasPublishScope)}>
          <option value="private">Private - this project only</option>
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
              <p className="canvas-widget-empty">No groups yet - create one under Organisation settings.</p>
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

/** The builder's own controls, under the shell's header rather than instead of
 * it. What is left after the breadcrumb and title moved up: the version state,
 * which is Workshop's alone and is the one thing an author of a published
 * module has to be able to see, and the three buttons. */
function ActionBar({
  app,
  workspaceId,
  projectId,
  canEdit,
  canPublish,
  variables,
  events,
  onView,
  onReverted,
}: {
  app: CanvasAppDetail;
  workspaceId: string;
  projectId: string;
  canEdit: boolean;
  canPublish: boolean;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEvent>;
  onView: (version: number) => void;
  onReverted: () => void;
}) {
  const { enabled, actions, query } = useEditor((state) => ({ enabled: state.options.enabled }));
  const [showPublish, setShowPublish] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const save = useMutation({
    // All three parts in one save. The layout comes from Craft.js, the
    // variables and events from their panels, and a save carrying only some of
    // them would silently discard the rest.
    mutationFn: (description: string) =>
      canvasApi.saveDefinition(
        workspaceId,
        projectId,
        app.id,
        moduleFrom(app.definition, {
          layout: query.getSerializedNodes(),
          variables,
          events,
        }),
        description,
      ),
    onSuccess: async () => {
      setFailure(null);
      await queryClient.invalidateQueries({ queryKey: ["canvas-app", app.id] });
    },
    // The server refuses a cycle or a binding to a variable that is not
    // declared. Surfaced here rather than swallowed: the save did not happen,
    // and a Save button that goes quiet is a Save button people trust wrongly.
    onError: (e: Error) => setFailure(e.message),
  });

  return (
    <div className="ws-actions">
      <p className="sub">
        v{app.current_version}
        {app.publish_scope !== "private" && ` · published (${app.publish_scope})`}
        {/* The one thing an author of a published app has to be able to see:
            whether what they are looking at is what everyone else is. Saving
            no longer moves viewers (§88), which is only an improvement if the
            difference is visible. */}
        {app.publish_scope !== "private" &&
          app.published_version !== app.current_version &&
          ` · viewers see v${app.published_version ?? 0}`}
        {save.isSuccess && !failure && " · saved"}
      </p>
      {failure && <p className="state error">{failure}</p>}
      <div className="spacer" />
      <div className="row-actions">
        <button
          type="button"
          className="btn quiet"
          onClick={() => actions.setOptions((o) => (o.enabled = !enabled))}
        >
          {enabled ? "Preview" : "Back to editing"}
        </button>
        {canEdit && enabled && (
          <button
            type="button"
            className="btn"
            disabled={save.isPending}
            onClick={() => {
              // p.192's "Always prompt to add a version description when
              // saving". A prompt, never a requirement - the server accepts an
              // empty description whatever this setting says, because a save
              // refused for want of a sentence is a save somebody loses.
              if (app.prompt_for_description) {
                const said = window.prompt("What changed in this version?", "");
                if (said === null) return;  // cancelled the prompt, not the save
                save.mutate(said);
                return;
              }
              save.mutate("");
            }}
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        )}
        <button type="button" className="btn quiet" onClick={() => setShowVersions(true)}>
          Versions
        </button>
        {canPublish && (
          <button type="button" className="btn quiet" onClick={() => setShowPublish(true)}>
            Publish
          </button>
        )}
      </div>
      {showVersions && (
        <VersionsDialog
          workspaceId={workspaceId}
          projectId={projectId}
          app={app}
          canEdit={canEdit}
          onView={onView}
          onReverted={onReverted}
          onClose={() => setShowVersions(false)}
        />
      )}
      {showPublish && (
        <PublishDialog workspaceId={workspaceId} projectId={projectId} app={app} onClose={() => setShowPublish(false)} />
      )}
    </div>
  );
}

function CanvasEnvBridge({
  workspaceId,
  projectId,
  appId,
  variables,
  events,
  seed,
  children,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEventDef>;
  seed?: Record<string, unknown>;
  children: React.ReactNode;
}) {
  const { enabled } = useEditor((state) => ({ enabled: state.options.enabled }));
  return (
    <CanvasEnvProvider value={{ workspaceId, projectId, mode: enabled ? "edit" : "run" }}>
      {/* Parameter state lives inside the env provider and outside the editor
          tree, so a filter set in Preview survives switching back to Edit -
          the alternative resets every filter each time the mode flips, which
          makes a filter impossible to actually try out. */}
      <CanvasParameterProvider seed={seed}>
        {/* Resolves what the viewer has selected into what each variable is
            worth. The builder passes its *working* variables, not the saved
            ones, so a set configured a moment ago drives the table without a
            save first - which is the difference between building an app and
            guessing at one. */}
        <VariableBridge
          workspaceId={workspaceId}
          projectId={projectId}
          appId={appId}
          declared={variables}
          events={events}
        >
          {children}
        </VariableBridge>
      </CanvasParameterProvider>
    </CanvasEnvProvider>
  );
}

/** The left column: what the module is made of, then what can be added to it.
 *
 * Stacked rather than tabbed, unlike the right-hand column. The two panels on
 * the right answer different questions about different things (this widget /
 * this module) and one is usually irrelevant; these two are both about the
 * document in front of you, and an author dropping a widget wants to see
 * where it landed. Hiding either behind a tab would trade a scroll for a
 * click on every single edit. */
function Toolbox() {
  return (
    <div className="canvas-toolbox">
      <LayoutPanel />
      <p className="field-label canvas-toolbox-heading">Widgets</p>
      {PALETTE.map((p) => (
        <PaletteItem key={p.key} componentKey={p.key} label={p.label} hint={p.hint} />
      ))}
    </div>
  );
}

export function WorkshopApplication({ resource }: { resource: ResolvedResource }) {
  // Interface variables initialised from the URL (Foundry p.165). The same
  // external IDs an embedding module maps - one mechanism, three consumers.
  const search = useSearchParams();
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  // **Craft's `<Frame data>` is read once, at mount.** Changing it afterwards
  // does nothing, which is fine for a save (the tree already *is* what was
  // saved) and wrong for a revert: the document changed underneath the editor,
  // and without a remount the canvas keeps drawing the old one. The symptom is
  // a Revert button that appears to do nothing until the page is reloaded.
  //
  // Bumped only by revert rather than keyed on `current_version`, so an
  // ordinary save does not throw away the selection and scroll position of
  // somebody who is still working.
  const [reloadToken, setReloadToken] = useState(0);
  const workspaceId = resource.workspace_id;
  const projectId = resource.project_id;
  const appId = resource.kind_id;

  // Roles, not identities. Both come from summary lists the app already holds.
  const { workspace } = useWorkspaceById(workspaceId);
  const { project } = useProjectById(workspaceId, projectId);

  const appQuery = useQuery({
    queryKey: ["canvas-app", appId],
    queryFn: () => canvasApi.get(workspaceId, projectId!, appId),
    enabled: !!projectId,
  });

  // The tab name (p.47). Above the early returns because it is a hook, and
  // fed the *saved* document rather than the editor's live node map: retyping
  // a header title should not rewrite the tab on every keystroke.
  useModuleTitle(layoutOf(appQuery.data?.definition), resource.name);

  const canEdit = project ? project.effective_role !== "viewer" : false;
  const canPublish = workspace?.effective_role === "admin";

  // What a `run_action` effect may run (§60). Fetched here rather than inside
  // the panel because the panel is given what the layout and the workspace
  // contain and does not reach out for either - the same reason `triggerNodes`
  // and `pages` arrive as props.
  const actionTypes = useQuery({
    queryKey: ["action-types", workspaceId],
    queryFn: () => actionApi.listTypes(workspaceId),
  });
  const actionCandidates: ActionCandidate[] = (actionTypes.data ?? []).map((a) => ({
    id: a.id,
    label: `${a.display_name} · ${a.object_type_name}`,
    editable: a.editable_properties,
  }));

  // The variables half of the document. Held here rather than in the panel
  // because the Save button has to write both halves at once - and reseeded
  // only when a *new version* arrives, so a refetch cannot discard edits
  // somebody has made but not saved.
  const [variables, setVariables] = useState<Record<string, WorkshopVariable>>({});
  const [events, setEvents] = useState<Record<string, WorkshopEvent>>({});
  const savedVersion = appQuery.data?.current_version;
  useEffect(() => {
    if (!appQuery.data) return;
    setVariables(variablesOf(appQuery.data.definition));
    setEvents(eventsOf(appQuery.data.definition));
  }, [savedVersion, appQuery.data?.id]);

  // A module always lives in a project. A resolved `canvas_app` without one is
  // a registry row that disagrees with its own table, and saying so beats
  // rendering a builder whose every write would 404.
  if (!projectId) {
    return <div className="state error">This module is not in a project, so it cannot be opened.</div>;
  }
  if (appQuery.isPending) {
    return <div className="state">Loading app…</div>;
  }
  if (appQuery.isError) {
    return <div className="state error">Couldn&apos;t load this app. It may have been deleted.</div>;
  }

  const app = appQuery.data;

  // "View this version" (p.191). Rendered instead of the builder rather than
  // inside it: a historic document in an *editable* canvas is one Save away
  // from silently becoming the current one, and the person who did it would
  // have thought they were only looking.
  if (viewingVersion !== null) {
    return (
      <ViewingVersion
        workspaceId={workspaceId}
        projectId={projectId}
        app={app}
        version={viewingVersion}
        onClose={() => setViewingVersion(null)}
      />
    );
  }

  return (
    <Editor
      key={reloadToken}
      resolver={CANVAS_RESOLVER}
      enabled={canEdit}
      onRender={CanvasNode}
    >
      <CanvasEnvBridge
        workspaceId={workspaceId}
        projectId={projectId}
        appId={app.id}
        variables={variables}
        events={eventsOf(app.definition)}
        seed={seedFromQuery(variables, search)}
      >
        <ActionBar
          app={app}
          workspaceId={workspaceId}
          projectId={projectId}
          canEdit={canEdit}
          canPublish={canPublish}
          variables={variables}
          events={events}
          onView={setViewingVersion}
          onReverted={() => setReloadToken((n) => n + 1)}
        />
        <CanvasBody
          hasSavedLayout={hasLayout(app.definition)}
          definition={app.definition}
          canEdit={canEdit}
          workspaceId={workspaceId}
          projectId={projectId}
          appId={app.id}
          variables={variables}
          onVariablesChange={setVariables}
          events={events}
          onEventsChange={setEvents}
          actions={actionCandidates}
        />
      </CanvasEnvBridge>
    </Editor>
  );
}

function CanvasBody({
  hasSavedLayout,
  definition,
  canEdit,
  workspaceId,
  projectId,
  appId,
  variables,
  onVariablesChange,
  events,
  onEventsChange,
  actions,
}: {
  hasSavedLayout: boolean;
  definition: Record<string, unknown>;
  canEdit: boolean;
  workspaceId: string;
  projectId: string;
  appId: string;
  variables: Record<string, WorkshopVariable>;
  onVariablesChange: (next: Record<string, WorkshopVariable>) => void;
  events: Record<string, WorkshopEvent>;
  onEventsChange: (next: Record<string, WorkshopEvent>) => void;
  actions: ActionCandidate[];
}) {
  const { enabled, triggerNodes, pageNodes } = useEditor((state) => {
    // Read from the editor's own node map rather than from the saved
    // definition: a widget dropped a moment ago is wireable, and a widget
    // deleted a moment ago is not - which is what somebody wiring an event
    // has just done and expects to see.
    const triggers: TriggerCandidate[] = [];
    const pages: PageCandidate[] = [];
    for (const [id, node] of Object.entries(state.nodes)) {
      const name = node?.data?.name;
      if (!name) continue;
      const props = (node.data.props ?? {}) as Record<string, unknown>;
      const label = String(
        props.label || props.title || props.text || node.data.displayName || name,
      ).slice(0, 40);
      if (TRIGGER_WIDGETS.includes(name)) {
        triggers.push({ id, label: `${node.data.displayName ?? name} · ${label}`, widget: name });
      }
      if (name === "CanvasPage" || name === "CanvasOverlay") {
        pages.push({ id, label: `${node.data.displayName ?? name} · ${label}` });
      }
    }
    return { enabled: state.options.enabled, triggerNodes: triggers, pageNodes: pages };
  });
  const showChrome = enabled && canEdit;
  // Three things want the right-hand column: the selected widget's settings,
  // the module's variables, and its events. Tabbed rather than stacked - a
  // variable list that pushed the settings below the fold would make
  // configuring a widget worse in service of a panel most edits do not touch.
  const [tab, setTab] = useState<"widget" | "variables" | "events">("widget");
  return (
    <div className={showChrome ? "canvas-shell" : "canvas-shell canvas-shell--full"}>
      {showChrome && <Toolbox />}
      <div className="canvas-frame-area">
        {hasSavedLayout ? (
          <Frame data={JSON.stringify(layoutOf(definition))} />
        ) : (
          <Frame>
            <Element is={CanvasContainer} canvas />
          </Frame>
        )}
      </div>
      {showChrome && (
        <div className="canvas-settings">
          <nav className="ds-tabs canvas-panel-tabs">
            {(["widget", "variables", "events"] as const).map((t) => (
              <button
                key={t}
                type="button"
                className={`ds-tab${t === tab ? " on" : ""}`}
                aria-current={t === tab}
                onClick={() => setTab(t)}
              >
                {t === "widget"
                  ? "Widget"
                  : t === "variables"
                    ? `Variables (${Object.keys(variables).length})`
                    : `Events (${Object.keys(events).length})`}
              </button>
            ))}
          </nav>
          {tab === "events" && (
            <EventsPanel
              events={events}
              variables={variables}
              triggerNodes={triggerNodes}
              pages={pageNodes}
              actions={actions}
              onChange={onEventsChange}
              readOnly={!canEdit}
            />
          )}
          {tab === "widget" ? (
            <SettingsPanel />
          ) : tab === "variables" ? (
            <VariablesPanel
              workspaceId={workspaceId}
              projectId={projectId}
              appId={appId}
              variables={variables}
              layout={layoutOf(definition)}
              onChange={onVariablesChange}
              readOnly={!canEdit}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}
