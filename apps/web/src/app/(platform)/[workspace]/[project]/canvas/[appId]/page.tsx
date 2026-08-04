"use client";

import { Editor, Element, Frame, useEditor } from "@craftjs/core";
import { VariablesPanel } from "@/components/canvas/VariablesPanel";
import { eventsOf, hasLayout, layoutOf, moduleFrom, variablesOf } from "@/lib/workshop-module";
import type { WorkshopEvent } from "@/lib/types";
import type { WorkshopVariable } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api, canvas as canvasApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { CanvasEnvProvider, CanvasParameterProvider } from "@/components/canvas/context";
import { VariableBridge } from "@/components/canvas/VariableBridge";
import type { WorkshopEventDef } from "@/components/canvas/events";
import {
  EventsPanel,
  TRIGGER_WIDGETS,
  type PageCandidate,
  type TriggerCandidate,
} from "@/components/canvas/EventsPanel";
import { LayoutPanel } from "@/components/canvas/LayoutPanel";
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
        Private apps are visible only to this project. Publishing lists the app under the
        workspace&apos;s Apps page, read-only, for everyone here or for specific groups.
        It shares the layout, not access to the data: every widget still reads as whoever
        is looking. Publishing is not a snapshot either - each save you make from here is
        immediately what they see.
      </p>
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

function TopBar({
  app,
  workspaceSlug,
  projectSlug,
  workspaceId,
  projectId,
  canEdit,
  canPublish,
  variables,
  events,
}: {
  app: CanvasAppDetail;
  workspaceSlug: string;
  projectSlug: string;
  workspaceId: string;
  projectId: string;
  canEdit: boolean;
  canPublish: boolean;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEvent>;
}) {
  const { enabled, actions, query } = useEditor((state) => ({ enabled: state.options.enabled }));
  const [showPublish, setShowPublish] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const save = useMutation({
    // All three parts in one save. The layout comes from Craft.js, the
    // variables and events from their panels, and a save carrying only some of
    // them would silently discard the rest.
    mutationFn: () =>
      canvasApi.saveDefinition(
        workspaceId,
        projectId,
        app.id,
        moduleFrom(app.definition, {
          layout: query.getSerializedNodes(),
          variables,
          events,
        }),
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
    <div className="page-head">
      <div>
        <p className="eyebrow">
          <Link href={`/${workspaceSlug}/${projectSlug}/canvas`}>project · canvas</Link>
        </p>
        <h1>{app.name}</h1>
        <p className="sub">
          v{app.current_version}
          {app.publish_scope !== "private" && ` · published (${app.publish_scope})`}
          {save.isSuccess && !failure && " · saved"}
        </p>
        {failure && <p className="state error">{failure}</p>}
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
  appId,
  variables,
  events,
  children,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEventDef>;
  children: React.ReactNode;
}) {
  const { enabled } = useEditor((state) => ({ enabled: state.options.enabled }));
  return (
    <CanvasEnvProvider value={{ workspaceId, projectId, mode: enabled ? "edit" : "run" }}>
      {/* Parameter state lives inside the env provider and outside the editor
          tree, so a filter set in Preview survives switching back to Edit -
          the alternative resets every filter each time the mode flips, which
          makes a filter impossible to actually try out. */}
      <CanvasParameterProvider>
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

  // The variables half of the document. Held here rather than in the panel
  // because the Save button is in the top bar and has to write both halves at
  // once - and reseeded only when a *new version* arrives, so a refetch cannot
  // discard edits somebody has made but not saved.
  const [variables, setVariables] = useState<Record<string, WorkshopVariable>>({});
  const [events, setEvents] = useState<Record<string, WorkshopEvent>>({});
  const savedVersion = appQuery.data?.current_version;
  useEffect(() => {
    if (!appQuery.data) return;
    setVariables(variablesOf(appQuery.data.definition));
    setEvents(eventsOf(appQuery.data.definition));
  }, [savedVersion, appQuery.data?.id]);

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
  const hasSavedLayout = hasLayout(app.definition);

  return (
    <main>
      <Editor resolver={CANVAS_RESOLVER} enabled={canEdit}>
        <CanvasEnvBridge
          workspaceId={workspace.id}
          projectId={project.id}
          appId={app.id}
          variables={variables}
          events={eventsOf(app.definition)}
        >
          <TopBar
            app={app}
            workspaceSlug={params.workspace}
            projectSlug={params.project}
            workspaceId={workspace.id}
            projectId={project.id}
            canEdit={canEdit}
            canPublish={canPublish}
            variables={variables}
            events={events}
          />
          <CanvasBody
            hasSavedLayout={hasSavedLayout}
            definition={app.definition}
            canEdit={canEdit}
            workspaceId={workspace.id}
            projectId={project.id}
            appId={app.id}
            variables={variables}
            onVariablesChange={setVariables}
            events={events}
            onEventsChange={setEvents}
          />
        </CanvasEnvBridge>
      </Editor>
    </main>
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
  //
  // Roadmap 1.6 puts Variables and Events in the *left* column beside the
  // layout tree. They are here instead, with the layout tree keeping the left
  // to itself: both of these are things you edit *because of* a widget you
  // just selected, and putting them a column away from the settings you
  // arrived from would make every wiring job a diagonal.
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
