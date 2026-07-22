"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";

const SUMMARY: { key: "connections" | "datasets" | "models" | "objects" | "canvas" | "code"; label: string; blurb: string }[] = [
  { key: "connections", label: "Connections", blurb: "Links to your source systems" },
  { key: "datasets", label: "Datasets", blurb: "Tables landed and transformed" },
  { key: "models", label: "Models", blurb: "Transforms that build datasets" },
  { key: "objects", label: "Objects", blurb: "The workspace ontology" },
  { key: "canvas", label: "Canvas", blurb: "Apps built on your objects" },
  { key: "code", label: "Code", blurb: "Repositories for power mode" },
];

export default function ProjectOverview() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const detail = useQuery({
    queryKey: ["project", workspace?.id, project?.id],
    queryFn: () => api.project(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  const counts = detail.data?.resource_counts;
  const total = counts ? Object.values(counts).reduce((a, b) => a + b, 0) : null;

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

      {total === 0 && (
        <div className="empty">
          <h2>An empty project is a starting line</h2>
          <p>
            There&apos;s no forced flow here. Connect a source, upload a file into
            Datasets, or sketch your first object type — start wherever your work starts.
          </p>
        </div>
      )}

      {counts && total !== 0 && (
        <div className="grid">
          {SUMMARY.map((s) => (
            <a key={s.key} className="card" href={`/${params.workspace}/${params.project}/${s.key}`}>
              <h3>{s.label}</h3>
              <p>{s.blurb}</p>
              <div className="meta">
                <span className="count">{counts[s.key]}</span>
              </div>
            </a>
          ))}
        </div>
      )}
      {detail.isPending && <div className="state">Loading…</div>}
    </main>
  );
}
