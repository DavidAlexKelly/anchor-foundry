"use client";

/** The builder used to live here. It is now an application at `/r/{id}`
 * (parity stage 1a, `docs/parity/workshop.md`).
 *
 * **A redirect, not a deletion.** This URL is in the browser suite, in
 * `STATUS.md`, and in whatever bookmarks and chat messages exist outside this
 * repository. Removing the route would turn all of them into a 404 to save one
 * file, and a resource that demonstrably existed answering "no such thing" is
 * the worst of the available outcomes.
 *
 * The redirect costs one fetch, because the old URL names the app by its own
 * id and the new one names it by its resource id. `canvasApi.get` is the same
 * call the builder made on its first render, so this is a request that was
 * going to happen anyway - it just happens here and its answer is read for one
 * field.
 */

import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import { canvas as canvasApi } from "@/lib/api";

export default function CanvasAppRedirectPage() {
  const params = useParams<{ workspace: string; project: string; appId: string }>();
  const router = useRouter();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);

  const appQuery = useQuery({
    queryKey: ["canvas-app", params.appId],
    queryFn: () => canvasApi.get(workspace!.id, project!.id, params.appId),
    enabled: !!workspace && !!project,
  });

  const resourceId = appQuery.data?.resource_id;
  useEffect(() => {
    // `replace`, not `push`: this URL is a forwarding address, and leaving it
    // in history means Back from the builder lands here and forwards again.
    if (resourceId) router.replace(`/r/${resourceId}`);
  }, [resourceId, router]);

  if (appQuery.isError) {
    return (
      <main>
        <div className="state error">Couldn&apos;t load this app. It may have been deleted.</div>
      </main>
    );
  }
  return (
    <main>
      <div className="state">Opening…</div>
    </main>
  );
}
