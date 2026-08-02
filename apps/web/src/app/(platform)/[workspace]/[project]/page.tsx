"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api, objects as objectsApi } from "@/lib/api";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import { FirstRunChecklist } from "@/components/first-run";
import { ResourceBrowser } from "@/components/resource-browser";

export default function ProjectOverview() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const detail = useQuery({
    queryKey: ["project", workspace?.id, project?.id],
    queryFn: () => api.project(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  // Project-scoped, unlike `resource_counts.objects` - see the note in
  // first-run.tsx about why the checklist cannot use the workspace-wide count.
  const sources = useQuery({
    queryKey: ["object-type-sources", workspace?.id, project?.id],
    queryFn: () => objectsApi.listSources(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  const counts = detail.data?.resource_counts;

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">overview</p>
          <h1>{project?.name}</h1>
          {project?.description && <p className="sub">{project.description}</p>}
        </div>
        {detail.data && (
          <span className={`chip${detail.data.effective_role === "owner" ? " brass" : ""}`}>
            {detail.data.effective_role}
          </span>
        )}
      </div>

      {/* Derived from what exists, so it is right for whoever opens the
          project next - including somebody who did not set it up. */}
      {counts && sources.data && (
        <FirstRunChecklist
          counts={counts}
          objectSources={sources.data.length}
          workspaceSlug={params.workspace}
          projectSlug={params.project}
        />
      )}

      {/* The pillar cards this replaced were a menu of six *types*; Foundry's
          project page is a browser of the resources themselves, and the type
          is a column rather than a destination. The pillar pages still exist
          in the sidebar for anyone who navigates that way. */}
      {workspace && project && (
        <ResourceBrowser workspaceId={workspace.id} projectId={project.id} />
      )}
      {detail.isPending && <div className="state">Loading…</div>}
    </main>
  );
}
