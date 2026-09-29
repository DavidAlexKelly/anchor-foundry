"use client";

/**
 * A published module, running: the frame the viewer route draws, shared with
 * the kiosk route (§684) so a kiosk shows exactly what view mode shows.
 *
 * **Two differences in a kiosk, both p.610's "read-only"**: no view is
 * recorded (a screen left on a wall is not somebody opening the module, and
 * recording one is a write the session is refused), and no state saving
 * (saving a state is a write too).
 */

import { Editor, Frame, useEditor } from "@craftjs/core";
import { CanvasEnvProvider, CanvasParameterProvider } from "@/components/canvas/context";
import { VariableBridge } from "@/components/canvas/VariableBridge";
import { CANVAS_RESOLVER } from "@/components/canvas/widgets";
import { CanvasNode } from "@/components/canvas/SettingsPanel";
import { seedFromQuery } from "@/components/canvas/pure";
import {
  eventsOf, pageSelectionOf, routingOf, savedColoursOf, stateSavingOf, variablesOf,
} from "@/lib/workshop-module";
import type { CanvasAppDetail } from "@/lib/types";

/** Craft.js's `enabled` option is what makes a node draggable, selectable and
 * editable. `<Editor enabled={false}>` is the documented way to render a
 * definition read-only, and this route never offers a way back - a viewer
 * here has no save endpoint to call even if they found the toggle. */
function ReadOnlyFrame({ definition }: { definition: Record<string, unknown> }) {
  const { enabled } = useEditor((state) => ({ enabled: state.options.enabled }));
  if (enabled) return null;
  return (
    <div className="canvas-frame-area">
      <Frame data={JSON.stringify(definition)} />
    </div>
  );
}

export function PublishedModule({
  workspaceId,
  app,
  definition,
  search,
  kiosk = false,
}: {
  workspaceId: string;
  app: CanvasAppDetail;
  /** The node tree to draw, already translated for this reader. */
  definition: Record<string, unknown>;
  search: URLSearchParams;
  kiosk?: boolean;
}) {
  return (
    <Editor resolver={CANVAS_RESOLVER} enabled={false} onRender={CanvasNode}>
      <CanvasEnvProvider
        value={{
          workspaceId, projectId: app.project_id, mode: "run",
          // p.214's Saved colors. A viewer resolves `saved:c1` the same way
          // the builder does or every referencing widget renders nothing —
          // which is the one failure a palette must not have, because it
          // only appears on the route nobody is looking at while building.
          savedColours: savedColoursOf(app.definition),
        }}
      >
        {/* Interface variables seeded from the URL (Foundry p.165) - the
            same external IDs an embedding module maps. */}
        <CanvasParameterProvider seed={seedFromQuery(variablesOf(app.definition), search)}>
          <VariableBridge
            workspaceId={workspaceId}
            projectId={app.project_id}
            appId={app.id}
            declared={variablesOf(app.definition)}
            events={eventsOf(app.definition)}
            published
            routing={routingOf(app.definition)}
            layout={definition}
            // p.188: layout views are recorded in View mode only. This
            // route is a running module; the builder's Preview is not,
            // because an author looking at their own work is not a view.
            countViews={!kiosk}
            // p.75's lazy rule (§392). Always on here: this route is a
            // running module, where exactly one page is on screen.
            lazy
            pageSelection={pageSelectionOf(app.definition) || undefined}
            stateSaving={kiosk ? undefined : stateSavingOf(app.definition)}
          >
            <ReadOnlyFrame definition={definition} />
          </VariableBridge>
        </CanvasParameterProvider>
      </CanvasEnvProvider>
    </Editor>
  );
}
