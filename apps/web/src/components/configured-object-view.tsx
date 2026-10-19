"use client";

/** The configured views of an object and of a set of objects (§992: out of
 * `object-view.tsx`). Each is a published Workshop module rendered read-only,
 * so each needs the whole widget table - `CANVAS_RESOLVER` is most of the
 * platform's JavaScript - and a reader of a type with no configured view never
 * renders one. Here, behind a dynamic import, the Explorer, a dataset and an
 * object's standard view load without it. What the views are and why is
 * `object-view.tsx`'s header. */
import { Editor, Frame, useEditor } from "@craftjs/core";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { canvas as canvasApi } from "@/lib/api";
import { tabBindings } from "@/lib/object-view-tabs";
import { CanvasEnvProvider, CanvasParameterProvider } from "@/components/canvas/context";
import { VariableBridge } from "@/components/canvas/VariableBridge";
import { CANVAS_RESOLVER } from "@/components/canvas/widgets";
import { CanvasNode } from "@/components/canvas/SettingsPanel";
import { StandardObjectView } from "@/components/standard-object-view";
import { eventsOf, variablesOf } from "@/lib/workshop-module";
import type { ObjectInstance } from "@/lib/types";
import { readerLayout } from "@/components/canvas/reader-layout";

/** Craft.js's `enabled` is what makes a node draggable and selectable, so
 * `enabled={false}` is the documented way to render a definition read-only.
 * Nothing here offers a way back: a reader of an object view has no save
 * endpoint to call even if they found a toggle. */
function ReadOnlyFrame({ definition }: { definition: Record<string, unknown> }) {
  const { enabled } = useEditor((state) => ({ enabled: state.options.enabled }));
  if (enabled) return null;
  return (
    <div className="canvas-frame-area">
      <Frame data={JSON.stringify(definition)} />
    </div>
  );
}

/** A host module's variables passed into a configured view's tabs - workshop
 * p.263's Interface configuration (§710). `mapping` is the widget's flat
 * `{"<tab id>:<external id>": host variable}`; `values` and `set` are the
 * host's, so a mapped variable is one value seen from both modules (p.127). */
export interface ViewInterfaceLink {
  mapping: Record<string, unknown>;
  values: Record<string, unknown>;
  set: (name: string, value: unknown) => void;
}

export function ConfiguredObjectView({
  workspaceId,
  appId,
  tabId,
  subjectVariable,
  typeId,
  instance,
  link,
}: {
  workspaceId: string;
  appId: string;
  tabId: string;
  subjectVariable: string;
  typeId: string;
  instance: ObjectInstance;
  link?: ViewInterfaceLink;
}) {
  const app = useQuery({
    queryKey: ["published-canvas-app", appId],
    queryFn: () => canvasApi.getPublished(workspaceId, appId),
  });

  if (app.isPending) {
    return <div className="state" data-testid="configured-object-view">Loading this view…</div>;
  }
  // **Falling back is the right failure.** A configured view that will not load
  // - unpublished since, deleted, shared to groups this reader is not in -
  // leaves the object itself perfectly viewable, and p.2 says the standard view
  // is always reachable anyway. Showing an error where an object should be
  // would be worse than showing the object.
  if (app.isError || !app.data) {
    return (
      <>
        <p className="state error" role="alert" data-testid="configured-object-view-failed">
          This object type&apos;s configured view couldn&apos;t be loaded, so here is the
          standard one.
        </p>
        <StandardObjectView workspaceId={workspaceId} typeId={typeId} instance={instance} />
      </>
    );
  }

  const definition = readerLayout(app.data.definition);
  const declared = variablesOf(app.data.definition);
  const bindings = link ? tabBindings(link.mapping, tabId, declared, subjectVariable) : {};
  return (
    <div data-testid="configured-object-view" data-app={appId}>
      <Editor resolver={CANVAS_RESOLVER} enabled={false} onRender={CanvasNode}>
        <CanvasEnvProvider
          value={{ workspaceId, projectId: app.data.project_id, mode: "run" }}
        >
          {/* The object, whole - id, type, key and properties - because that is
              what `object_property` reads from and what an action's subject
              needs. A primary key alone would be a reference nobody could
              write through. */}
          <CanvasParameterProvider
            link={link ? { bindings, values: link.values, set: link.set } : undefined}
            seed={{
              [subjectVariable]: {
                id: instance.id,
                object_type_id: typeId,
                primary_key: instance.primary_key,
                properties: instance.properties,
              },
            }}
          >
            <VariableBridge
              workspaceId={workspaceId}
              projectId={app.data.project_id}
              appId={app.data.id}
              declared={declared}
              events={eventsOf(app.data.definition)}
              published
              // The subject is supplied from outside, so the module's own
              // definition for it must stand aside - Foundry's precedence rule
              // for a mapped variable (p.122, p.127), which is the same
              // situation an embed is in.
              bound={[subjectVariable, ...Object.keys(bindings)]}
            >
              <ReadOnlyFrame definition={definition} />
            </VariableBridge>
          </CanvasParameterProvider>
        </CanvasEnvProvider>
      </Editor>
    </div>
  );
}

/** p.41's configured object set panel (§744): "object set panels display
 * multiple objects as an object set". The type's `panel_set` module, with the
 * set arriving in its `object_set` subject variable as a seed - the instance
 * view's arrangement, with a set where that has an object. When the module
 * cannot be loaded, p.41's default set panel stands in, for the instance
 * view's reason: the objects are still worth showing. */
export function ConfiguredSetPanel({
  workspaceId,
  appId,
  subjectVariable,
  definition,
  fallback,
}: {
  workspaceId: string;
  appId: string;
  subjectVariable: string;
  definition: unknown;
  fallback: ReactNode;
}) {
  const app = useQuery({
    queryKey: ["published-canvas-app", appId],
    queryFn: () => canvasApi.getPublished(workspaceId, appId),
  });
  if (app.isPending) {
    return <div className="state" data-testid="configured-set-panel">Loading this panel…</div>;
  }
  if (app.isError || !app.data) {
    return (
      <>
        <p className="state error" role="alert" data-testid="configured-set-panel-failed">
          This object type&apos;s object set panel couldn&apos;t be loaded, so here is the
          standard one.
        </p>
        {fallback}
      </>
    );
  }
  const declared = variablesOf(app.data.definition);
  return (
    <div data-testid="configured-set-panel" data-app={appId}>
      <Editor resolver={CANVAS_RESOLVER} enabled={false} onRender={CanvasNode}>
        <CanvasEnvProvider value={{ workspaceId, projectId: app.data.project_id, mode: "run" }}>
          <CanvasParameterProvider seed={{ [subjectVariable]: definition }}>
            <VariableBridge
              workspaceId={workspaceId}
              projectId={app.data.project_id}
              appId={app.data.id}
              declared={declared}
              events={eventsOf(app.data.definition)}
              published
              // The set is supplied from outside, so the module's own
              // definition of the variable stands aside (p.122, p.127).
              bound={[subjectVariable]}
            >
              <ReadOnlyFrame definition={readerLayout(app.data.definition)} />
            </VariableBridge>
          </CanvasParameterProvider>
        </CanvasEnvProvider>
      </Editor>
    </div>
  );
}
