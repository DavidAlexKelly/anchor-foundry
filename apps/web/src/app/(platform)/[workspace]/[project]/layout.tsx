"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { ResourceCounts } from "@/lib/types";

const SECTIONS: { path: string; label: string; countKey: keyof ResourceCounts }[] = [
  { path: "connections", label: "Connections", countKey: "connections" },
  { path: "datasets", label: "Datasets", countKey: "datasets" },
  { path: "models", label: "Models", countKey: "models" },
  { path: "objects", label: "Objects", countKey: "objects" },
  { path: "canvas", label: "Canvas", countKey: "canvas" },
  { path: "code", label: "Code", countKey: "code" },
];

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ workspace: string; project: string }>();
  const pathname = usePathname();
  const { workspace, isPending: wsPending, notFound: wsMissing } = useWorkspaceBySlug(
    params.workspace,
  );
  const { project, isPending: projPending, notFound: projMissing } = useProjectBySlug(
    workspace?.id,
    params.project,
  );

  const detail = useQuery({
    queryKey: ["project", workspace?.id, project?.id],
    queryFn: () => api.project(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  if (wsPending || projPending) {
    return <div className="state">Loading project…</div>;
  }
  if (wsMissing || projMissing) {
    return (
      <div className="state error">
        This project doesn&apos;t exist or you don&apos;t have access to it.
      </div>
    );
  }

  const base = `/${params.workspace}/${params.project}`;
  const counts = detail.data?.resource_counts;

  return (
    <div className="project-shell">
      <aside className="side">
        <nav className="crumbs" aria-label="Breadcrumb" style={{ paddingTop: 0, marginBottom: 14 }}>
          <Link href="/home">Workspaces</Link>
          <span className="link-mark" />
          <Link href={`/${params.workspace}`}>{workspace?.name}</Link>
        </nav>
        <h2 className="project-name">{project?.name}</h2>
        <span className="project-slug">{project?.slug}</span>
        <nav className="side-nav" aria-label="Project sections">
          <Link href={base} aria-current={pathname === base}>
            <span>Overview</span>
          </Link>
          <div className="divider" />
          {SECTIONS.map((s) => (
            <Link
              key={s.path}
              href={`${base}/${s.path}`}
              aria-current={pathname === `${base}/${s.path}` || pathname.startsWith(`${base}/${s.path}/`)}
            >
              <span>{s.label}</span>
              <span className="count">{counts ? counts[s.countKey] : "–"}</span>
            </Link>
          ))}
        </nav>
      </aside>
      <section className="content">{children}</section>
    </div>
  );
}
