"use client";

/**
 * Which view of an object a reader gets (parity `docs/parity/ontology.md`
 * §4.2; Foundry `object-views` p.2–4).
 *
 * > "Configured Object Views are fully customizable representations of an
 * > object built using Workshop… Standard Object Views remain accessible even
 * > after a configured Object View is built." (p.2)
 *
 * Both halves of that sentence are here. A type with a configured view opens
 * on it; the standard view is one button away and cannot be turned off,
 * because the rule is about the reader rather than about configuration - there
 * is no setting that could express "hide it".
 *
 * **A configured view is a published module rendered read-only**, on the same
 * workspace-wide path a published app uses (`published-canvas-apps`). Nothing
 * new was added to reach it: an object view is read by whoever can read the
 * object, which is exactly the audience publishing already describes, and a
 * second access path to the same document would be a second thing to get
 * wrong.
 *
 * **The object arrives as one variable.** `subject_variable` names the
 * module's `single_object` variable and this seeds it with the instance -
 * whole, the same shape a row click writes (`canvas/events.ts`), so
 * `object_property` derivations and every object-reading widget work without
 * knowing they are inside an object view.
 */

import { Editor, Frame, useEditor } from "@craftjs/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { canvas as canvasApi, objects as objApi } from "@/lib/api";
import { CanvasEnvProvider, CanvasParameterProvider } from "@/components/canvas/context";
import { VariableBridge } from "@/components/canvas/VariableBridge";
import { CANVAS_RESOLVER } from "@/components/canvas/widgets";
import { CanvasNode } from "@/components/canvas/SettingsPanel";
import { StandardObjectView } from "@/components/standard-object-view";
import { eventsOf, layoutOf, variablesOf } from "@/lib/workshop-module";
import type { ObjectInstance } from "@/lib/types";

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

function ConfiguredObjectView({
  workspaceId,
  appId,
  subjectVariable,
  typeId,
  instance,
}: {
  workspaceId: string;
  appId: string;
  subjectVariable: string;
  typeId: string;
  instance: ObjectInstance;
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
        <p className="state error" data-testid="configured-object-view-failed">
          This object type&apos;s configured view couldn&apos;t be loaded, so here is the
          standard one.
        </p>
        <StandardObjectView workspaceId={workspaceId} typeId={typeId} instance={instance} />
      </>
    );
  }

  const definition = layoutOf(app.data.definition);
  const declared = variablesOf(app.data.definition);
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
              bound={[subjectVariable]}
            >
              <ReadOnlyFrame definition={definition} />
            </VariableBridge>
          </CanvasParameterProvider>
        </CanvasEnvProvider>
      </Editor>
    </div>
  );
}

export function ObjectView({
  workspaceId,
  typeId,
  instance,
}: {
  workspaceId: string;
  typeId: string;
  instance: ObjectInstance;
}) {
  // Null while unresolved *and* when there is genuinely none, which is why the
  // switch is drawn from the query rather than from this: "no configured view"
  // and "not asked yet" must not look the same to a reader who then sees a
  // button appear under their cursor.
  const view = useQuery({
    queryKey: ["object-view", workspaceId, typeId],
    queryFn: () => objApi.getView(workspaceId, typeId),
  });
  const [standard, setStandard] = useState(false);

  const configured = view.data ?? null;
  return (
    <div className="object-view">
      {configured && (
        <div className="row-actions" style={{ justifyContent: "flex-end", marginBottom: 8 }}>
          {/* p.2's guarantee, as a control. Two buttons rather than a toggle so
              the current state is readable without inferring it from a label
              that says what would happen next. */}
          <button
            type="button"
            className={standard ? "btn quiet" : "btn"}
            aria-pressed={!standard}
            onClick={() => setStandard(false)}
          >
            {configured.canvas_app_name}
          </button>
          <button
            type="button"
            className={standard ? "btn" : "btn quiet"}
            aria-pressed={standard}
            onClick={() => setStandard(true)}
          >
            Standard view
          </button>
        </div>
      )}
      {configured && !standard ? (
        <ConfiguredObjectView
          workspaceId={workspaceId}
          appId={configured.canvas_app_id}
          subjectVariable={configured.subject_variable}
          typeId={typeId}
          instance={instance}
        />
      ) : (
        <StandardObjectView workspaceId={workspaceId} typeId={typeId} instance={instance} />
      )}
    </div>
  );
}
