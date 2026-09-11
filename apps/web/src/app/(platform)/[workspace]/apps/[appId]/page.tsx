"use client";

/**
 * Opening a published app (ROADMAP Canvas item 6).
 *
 * The roadmap called item 6 "just needs a list page and a nav entry", and the
 * list page was indeed the easy half. The other half is that **publishing had
 * nowhere to lead**: the only route that rendered an app was the editor,
 * which resolves its project by slug and reads the project-scoped endpoint,
 * so anybody without project membership - the exact audience publishing
 * exists for - got a 404 on a link to an app published to them. This route is
 * the read path that was missing: workspace-scoped, no project slug in the
 * URL, and the editor is hard-disabled rather than merely hidden.
 *
 * **What publishing does and does not share.** It shares the layout, not
 * data access. Each widget still reads its dataset or object type as *this*
 * viewer, which is the right default - an app must not become a way to
 * launder access to data somebody was not given. For a project on inherited
 * permissions (the default) every workspace member already has viewer access,
 * so the app simply works; in a `permission_mode='custom'` project the
 * widgets say what they could not read rather than rendering empty.
 */

import { Editor, Frame, useEditor } from "@craftjs/core";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { canvas as canvasApi } from "@/lib/api";
import { CanvasEnvProvider, CanvasParameterProvider } from "@/components/canvas/context";
import { VariableBridge } from "@/components/canvas/VariableBridge";
import { CANVAS_RESOLVER } from "@/components/canvas/widgets";
import { CanvasNode } from "@/components/canvas/SettingsPanel";
import { seedFromQuery } from "@/components/canvas/pure";
import { useModuleTitle } from "@/components/canvas/module-title";
import {
  VERSION_PARAM,
  aheadNote,
  aheadOfPublished,
  versionFrom,
  versionNote,
} from "@/lib/app-version";
import { useWorkspaceBySlug } from "@/components/use-workspace";
import {
  eventsOf, layoutOf, pageSelectionOf, routingOf, stateSavingOf, variablesOf,
} from "@/lib/workshop-module";

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

export default function PublishedAppPage() {
  const params = useParams<{ workspace: string; appId: string }>();
  const search = useSearchParams();
  const { workspace, isPending: wsPending, notFound } = useWorkspaceBySlug(params.workspace);

  // **p.166's `/dev/`** (§314): "you can change the `/latest/` to `/dev/` in
  // the URL, and the link will now redirect to the last saved version of the
  // Workshop application instead of the last published version."
  //
  // A query parameter rather than a path segment, because every other piece of
  // linkable state in this platform lives in the query string — see
  // `app-version.ts` for why a second convention would be worse than a
  // divergence.
  const version = versionFrom(search.get(VERSION_PARAM));

  const app = useQuery({
    // Keyed on the version, so the two are separate cached answers rather than
    // one that depends on which link you followed first.
    queryKey: ["canvas-app-at", params.appId, version],
    queryFn: () =>
      version === "saved"
        ? canvasApi.getSaved(workspace!.id, params.appId)
        : canvasApi.getPublished(workspace!.id, params.appId),
    enabled: !!workspace,
  });

  // The tab name (p.47). A viewer of a published module gets the same title a
  // builder sees, falling back to the app's name - `useModuleTitle` waits for
  // the fetch rather than blanking the tab while it is in flight.
  useModuleTitle(layoutOf(app.data?.definition), app.data?.name ?? "");

  if (wsPending || app.isPending) {
    return <main className="page"><div className="state">Loading app…</div></main>;
  }
  if (notFound) {
    return (
      <main className="page">
        <div className="state error">
          This workspace doesn&apos;t exist or you don&apos;t have access to it.
        </div>
      </main>
    );
  }
  if (app.isError || !app.data) {
    return (
      <main className="page">
        <div className="state error">
          {version === "saved"
            ? "There's no saved version here for you. Either this app doesn't exist, or you don't have permission to see work that hasn't been published — which is the same answer on purpose."
            : "This app isn't published to you. It may have been unpublished, or shared only with groups you're not in."}
        </div>
      </main>
    );
  }

  // After migration 0034 a stored definition wraps the node tree; the
  // renderer wants the tree.
  const definition = layoutOf(app.data.definition);
  return (
    <main className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link href="/home">Workspaces</Link>
        <span className="link-mark" />
        <Link href={`/${params.workspace}`}>{workspace?.name}</Link>
        <span className="link-mark" />
        <Link href={`/${params.workspace}/apps`}>Apps</Link>
        <span className="link-mark" />
        <span className="current">{app.data.name}</span>
      </nav>
      <div className="page-head">
        <div>
          <p className="eyebrow">{version === "saved" ? "saved version" : "published app"}</p>
          <h1>{app.data.name}</h1>
          <p className="sub">
            v{app.data.current_version}
            {app.data.description ? ` · ${app.data.description}` : ""}
          </p>
        </div>
      </div>
      {/* p.166 calls this "for testing purposes", so somebody who arrived on a
          hand-edited link has to be told that what they are looking at is not
          what their colleagues see. */}
      {versionNote(version) && (
        <p className="state" data-testid="version-note">
          {versionNote(version)}
          {aheadNote(
            aheadOfPublished(
              version,
              app.data.current_version,
              app.data.published_version ?? null,
            ),
          ) && (
            <>
              {" "}
              {aheadNote(
                aheadOfPublished(
                  version,
                  app.data.current_version,
                  app.data.published_version ?? null,
                ),
              )}
            </>
          )}
        </p>
      )}
      {Object.keys(definition).length === 0 ? (
        <div className="empty">
          <h2>This app is empty</h2>
          <p>It has been published, but nothing has been placed on it yet.</p>
        </div>
      ) : (
        <Editor resolver={CANVAS_RESOLVER} enabled={false} onRender={CanvasNode}>
          <CanvasEnvProvider
            value={{ workspaceId: workspace!.id, projectId: app.data.project_id, mode: "run" }}
          >
            {/* Interface variables seeded from the URL (Foundry p.165) - the
                same external IDs an embedding module maps. */}
            <CanvasParameterProvider
              seed={seedFromQuery(variablesOf(app.data.definition), search)}
            >
              <VariableBridge
                workspaceId={workspace!.id}
                projectId={app.data.project_id}
                appId={app.data.id}
                declared={variablesOf(app.data.definition)}
                events={eventsOf(app.data.definition)}
                published
                routing={routingOf(app.data.definition)}
                layout={definition}
                pageSelection={pageSelectionOf(app.data.definition) || undefined}
                stateSaving={stateSavingOf(app.data.definition)}
              >
                <ReadOnlyFrame definition={definition} />
              </VariableBridge>
            </CanvasParameterProvider>
          </CanvasEnvProvider>
        </Editor>
      )}
    </main>
  );
}
