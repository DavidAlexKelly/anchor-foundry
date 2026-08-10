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
import { SettingsPanel } from "@/components/canvas/SettingsPanel";
import { VariablesPanel } from "@/components/canvas/VariablesPanel";
import { CANVAS_RESOLVER, CanvasContainer, PALETTE, PaletteItem } from "@/components/canvas/widgets";
import { useProjectById, useWorkspaceById } from "@/components/use-workspace";
import { ApiError, actions as actionApi, api, canvas as canvasApi } from "@/lib/api";
import { eventsOf, hasLayout, layoutOf, moduleFrom, variablesOf } from "@/lib/workshop-module";
import type {
  CanvasAppDetail,
  CanvasPublishScope,
  Group,
  ResolvedResource,
  WorkshopEvent,
  WorkshopVariable,
} from "@/lib/types";

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
}: {
  app: CanvasAppDetail;
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

  return (
    <Editor resolver={CANVAS_RESOLVER} enabled={canEdit}>
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
