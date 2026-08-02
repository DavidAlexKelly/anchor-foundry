"use client";

/** `/r/{id}` - resolve a resource id to the application that handles its kind
 * (ROADMAP.md phase 2, section 0 item 3).
 *
 * The URL carries the id and nothing else. That is the whole point of the
 * registry's stable ids: a link built from a workspace and project slug stops
 * working the moment somebody renames either, which is exactly when a shared
 * link is most likely to be clicked.
 *
 * The per-kind applications are later roadmap items (the dataset one is 3.1,
 * Workshop is section 1, Code Repositories is section 2). Until each lands,
 * its entry here renders the resource's own summary and points at the pillar
 * page that handles it today - so the link resolves to something true rather
 * than to an apology.
 */

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { ApplicationShell, ResourceSummary } from "@/components/application-shell";
import { DatasetApplication } from "@/components/applications/dataset-app";
import { RepositoryApplication } from "@/components/applications/repository-app";
import { resources as resourcesApi } from "@/lib/api";
import { ApiError } from "@/lib/api";
import type { ResolvedResource, ResourceKind } from "@/lib/types";

/** Where each kind is handled today, and which roadmap item replaces that with
 * a real application. `href` is null for kinds whose current home cannot be
 * linked to for one resource. */
const APPLICATIONS: Record<
  Exclude<ResourceKind, "dataset" | "code_repo">,
  { buildingIn: string; label: string; href: (r: ResolvedResource) => string | null }
> = {
  model: {
    buildingIn: "roadmap section 2 (Code Repositories)",
    label: "Open in Models",
    href: (r) => (r.project_slug ? `/${r.workspace_slug}/${r.project_slug}/models` : null),
  },
  canvas_app: {
    buildingIn: "roadmap section 1 (Workshop)",
    label: "Open in Canvas",
    href: (r) => (r.project_slug ? `/${r.workspace_slug}/${r.project_slug}/canvas` : null),
  },
  object_type: {
    buildingIn: "roadmap item 4.2 (Ontology Manager)",
    label: "Open in Objects",
    href: (r) => `/${r.workspace_slug}`,
  },
  connection: {
    buildingIn: "not yet scheduled",
    label: "Open in Connections",
    href: (r) => (r.project_slug ? `/${r.workspace_slug}/${r.project_slug}/connections` : null),
  },
};

export default function ResourcePage() {
  const params = useParams<{ resourceId: string }>();
  const resource = useQuery({
    queryKey: ["resource", params.resourceId],
    queryFn: () => resourcesApi.resolve(params.resourceId),
    retry: false,
  });

  if (resource.isPending) {
    return <div className="state">Loading…</div>;
  }

  if (resource.isError) {
    const notFound = resource.error instanceof ApiError && resource.error.status === 404;
    return (
      <div className="state error app-gone">
        <h1>{notFound ? "This resource is not here" : "Something went wrong"}</h1>
        <p>
          {notFound
            ? "It may have been deleted, or you may not have access to it. Links to resources stay valid across renames and moves, so a broken one usually means the resource itself is gone."
            : (resource.error as Error).message}
        </p>
      </div>
    );
  }

  // Kinds with a real application of their own. The rest resolve to their
  // summary until theirs is built.
  if (resource.data.kind === "dataset") {
    return (
      <ApplicationShell resource={resource.data}>
        <DatasetApplication resource={resource.data} />
      </ApplicationShell>
    );
  }
  if (resource.data.kind === "code_repo") {
    return (
      <ApplicationShell resource={resource.data}>
        <RepositoryApplication resource={resource.data} />
      </ApplicationShell>
    );
  }

  const app = APPLICATIONS[resource.data.kind];
  return (
    <ApplicationShell resource={resource.data}>
      <ResourceSummary
        resource={resource.data}
        buildingIn={app.buildingIn}
        existingHref={app.href(resource.data)}
        existingLabel={app.label}
      />
    </ApplicationShell>
  );
}
