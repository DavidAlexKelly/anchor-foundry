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
 * on it; the standard view is one button away.
 *
 * **That used to say "and cannot be turned off", and §213 made it untrue.**
 * Workshop p.261 gives a module builder an Object View Mode and "an option to
 * toggle between them", so there is now a setting that expresses exactly what
 * this file once said nothing could. The guarantee is kept where it was
 * actually about the reader: every caller that is not a configured widget -
 * the Explorer, the traversal dialog - takes the defaults, and `allowToggle`
 * defaults to `true`, so withholding the standard view requires a builder to
 * have said so on purpose about one widget in one module.
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
  initialStandard = false,
  allowToggle = true,
  hideHeader = false,
}: {
  workspaceId: string;
  typeId: string;
  instance: ObjectInstance;
  /** Workshop p.261's Object View Mode, as the *starting* view. A preference,
   * not a guarantee: a type with no configured view opens on the standard one
   * whichever way this is set, which is what the query below decides. */
  initialStandard?: boolean;
  /** Workshop p.261's "with an option to toggle between them". The Explorer
   * and the traversal dialog never pass it, so `object-views` p.2's guarantee
   * holds everywhere except where a module builder has explicitly said
   * otherwise. */
  allowToggle?: boolean;
  /** Workshop p.262's Hide header. */
  hideHeader?: boolean;
}) {
  // Null while unresolved *and* when there is genuinely none, which is why the
  // switch is drawn from the query rather than from this: "no configured view"
  // and "not asked yet" must not look the same to a reader who then sees a
  // button appear under their cursor.
  const view = useQuery({
    queryKey: ["object-view", workspaceId, typeId],
    queryFn: () => objApi.getView(workspaceId, typeId),
  });
  // Seeded rather than derived, so a reader's click survives every refetch on
  // the page — and re-seeded when the builder changes the setting, which is the
  // only other thing that should move it (§212's rule, one widget along).
  const [standard, setStandard] = useState(initialStandard);
  const [seeded, setSeeded] = useState(initialStandard);
  if (seeded !== initialStandard) {
    setSeeded(initialStandard);
    setStandard(initialStandard);
  }

  // **Derived properties are only on the single-object read** (§162): a list
  // read returns the instance as it is *stored*, and a derived property is
  // stored nowhere. Every caller of this component hands over a row it already
  // had - the Explorer's table, a link group - so without this the one surface
  // the feature was built for would show `∅` on every derived property.
  //
  // Fetched only when the type actually has one, so the ordinary object view
  // still costs exactly what it did. `instance` is the placeholder, so the
  // view draws immediately and the derived values fill in.
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId),
  });
  const hasDerived = (type.data?.properties ?? []).some((p) => p.derivation);
  const full = useQuery({
    queryKey: ["instance", workspaceId, typeId, instance.id],
    queryFn: () => objApi.getInstance(workspaceId, typeId, instance.id),
    enabled: hasDerived,
  });
  const shown = hasDerived && full.data ? full.data : instance;

  const configured = view.data ?? null;
  return (
    <div className="object-view">
      {configured && allowToggle && (
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
          instance={shown}
        />
      ) : (
        <StandardObjectView
          workspaceId={workspaceId}
          typeId={typeId}
          instance={shown}
          hideHeader={hideHeader}
        />
      )}
    </div>
  );
}
