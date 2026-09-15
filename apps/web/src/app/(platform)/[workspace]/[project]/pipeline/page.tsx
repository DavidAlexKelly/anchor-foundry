"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { models as modelApi } from "@/lib/api";
import { PipelineGraphView } from "@/components/pipeline-graph";
import { nodePath } from "@/lib/pipeline-graph";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { PipelineGraph, PipelineNode } from "@/lib/types";

export default function PipelinePage() {
  const params = useParams<{ workspace: string; project: string }>();
  const router = useRouter();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);

  const graph = useQuery<PipelineGraph>({
    queryKey: ["pipeline", project?.id],
    queryFn: () => modelApi.pipeline(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  function open(node: PipelineNode) {
    // One rule for the three graphs that draw these nodes — see
    // `lib/pipeline-graph`, which is where an object type learned to open
    // into the Ontology Manager (§351; p.32).
    router.push(nodePath(node, params.workspace, params.project));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · pipeline</p>
          <h1>Pipeline</h1>
          <p className="sub">
            Every dataset and model in this project, flowing left to right.
          </p>
        </div>
      </div>

      {graph.isPending && <div className="state">Loading the pipeline…</div>}
      {graph.isError && <div className="state error">Couldn&apos;t load the pipeline.</div>}
      {graph.data && <PipelineGraphView graph={graph.data} onOpen={open} />}
    </>
  );
}
