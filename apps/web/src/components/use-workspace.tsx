"use client";

/** Routes use human slugs (spec §18) while the API is id-addressed; resolve
 * slug → workspace via the cached workspace list. A slug that isn't in the
 * user's list is indistinguishable from a workspace they can't access -
 * which is exactly the 404-shaped answer the API would give (§9). */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ProjectSummary, WorkspaceSummary } from "@/lib/types";

export function useWorkspaceBySlug(slug: string): {
  workspace: WorkspaceSummary | undefined;
  isPending: boolean;
  notFound: boolean;
} {
  const q = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const workspace = q.data?.find((w) => w.slug === slug);
  return { workspace, isPending: q.isPending, notFound: q.isSuccess && !workspace };
}

export function useProjectBySlug(
  workspaceId: string | undefined,
  slug: string,
): { project: ProjectSummary | undefined; isPending: boolean; notFound: boolean } {
  // One project, not the workspace's whole list (§822). Keyed under
  // ["projects", workspaceId] so whatever refreshes the list refreshes this.
  const q = useQuery({
    queryKey: ["projects", workspaceId, { slug }],
    queryFn: () => api.projectLookup(workspaceId!, { slug }),
    enabled: !!workspaceId,
  });
  const project = q.data?.find((p) => p.slug === slug);
  return {
    project,
    isPending: !workspaceId || q.isPending,
    notFound: q.isSuccess && !project,
  };
}

/** The same two lookups keyed by id, for `/r/{id}` applications.
 *
 * A resolved resource already carries `workspace_id` and `project_id`, so an
 * application opened by resource id has no slug to look up and no reason to
 * invent one. What it still needs is `effective_role` - whether this person may
 * edit or publish - and that lives on the summary rows these queries already
 * hold. The workspace lookup shares the by-slug one's cache entry; the
 * project lookup asks for its one project, as the by-slug one does (§822).
 */
export function useWorkspaceById(id: string | undefined): {
  workspace: WorkspaceSummary | undefined;
  isPending: boolean;
} {
  const q = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  return { workspace: q.data?.find((w) => w.id === id), isPending: q.isPending };
}

export function useProjectById(
  workspaceId: string | undefined,
  projectId: string | null,
): { project: ProjectSummary | undefined; isPending: boolean } {
  const q = useQuery({
    queryKey: ["projects", workspaceId, { id: projectId }],
    queryFn: () => api.projectLookup(workspaceId!, { id: projectId! }),
    enabled: !!workspaceId && !!projectId,
  });
  return {
    project: projectId ? q.data?.find((p) => p.id === projectId) : undefined,
    // A resource with no project (a workspace-level one) has nothing to wait
    // for; the query never runs, and a query that never runs stays pending.
    isPending: !workspaceId || (!!projectId && q.isPending),
  };
}
