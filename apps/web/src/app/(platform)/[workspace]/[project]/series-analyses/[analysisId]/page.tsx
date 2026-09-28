"use client";

/** One saved time series analysis in its resource view (§668; `workshop`
 * p.397): "Saved analyses can be opened in a standalone resource view or
 * loaded into the Workshop widget using its RID." */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ApiError, seriesAnalyses } from "@/lib/api";
import { SeriesAnalysisView } from "@/components/series-analysis-view";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";

export default function SeriesAnalysisPage() {
  const params = useParams<{ workspace: string; project: string; analysisId: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const analysis = useQuery({
    queryKey: ["series-analysis", workspace?.id, project?.id, params.analysisId],
    queryFn: () => seriesAnalyses.get(workspace!.id, project!.id, params.analysisId),
    enabled: !!workspace && !!project,
    retry: false,
  });
  const a = analysis.data;
  return (
    <div>
      <p className="login-note">
        <Link href={`/${params.workspace}/${params.project}/series-analyses`}>Time series analyses</Link>
      </p>
      {analysis.isError && (
        <p className="form-error">
          {analysis.error instanceof ApiError ? analysis.error.message : "Couldn't open this analysis."}
        </p>
      )}
      {a && (
        <>
          <h1>{a.name}</h1>
          <p className="login-note" data-testid="series-analysis-about">
            {`${a.visibility === "public" ? "Shared with the project" : "Private"} · by ${a.mine ? "you" : a.created_by_name ?? "another reader"} · saved ${new Date(a.updated_at).toLocaleString()}`}
          </p>
          {/* p.397's RID: what a widget's Autoload analyses names (§663). */}
          <p className="login-note">RID <code data-testid="series-analysis-rid">{a.id}</code></p>
          {workspace && <SeriesAnalysisView workspaceId={workspace.id} analysis={a} />}
        </>
      )}
    </div>
  );
}
