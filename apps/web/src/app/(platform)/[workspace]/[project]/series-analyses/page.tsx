"use client";

/** The project's saved time series analyses (§668; `workshop` p.397): the
 * reader's own and the project's public ones, each opened in its resource
 * view. */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ApiError, seriesAnalyses } from "@/lib/api";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";

export default function SeriesAnalysesPage() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const list = useQuery({
    queryKey: ["series-analyses", workspace?.id, project?.id],
    queryFn: () => seriesAnalyses.list(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });
  return (
    <div>
      <h1>Time series analyses</h1>
      <p className="login-note">Analyses saved from a Time series analysis widget: your own, and those shared with the project.</p>
      {list.isError && (
        <p className="form-error">{list.error instanceof ApiError ? list.error.message : "Couldn't list the analyses."}</p>
      )}
      {list.data && list.data.length === 0 && <p className="login-note">No analyses have been saved here.</p>}
      {list.data && list.data.length > 0 && (
        <table className="data-grid" data-testid="series-analyses">
          <thead><tr><th>Analysis</th><th>By</th><th>Shared</th><th>Saved</th></tr></thead>
          <tbody>
            {list.data.map((a) => (
              <tr key={a.id} data-label={a.name}>
                <td>
                  <Link href={`/${params.workspace}/${params.project}/series-analyses/${a.id}`}>{a.name}</Link>
                </td>
                <td>{a.mine ? "You" : a.created_by_name ?? "Another reader"}</td>
                <td>{a.visibility}</td>
                <td>{new Date(a.updated_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
