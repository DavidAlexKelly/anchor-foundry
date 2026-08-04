"use client";

/**
 * The Object Explorer (ROADMAP item 4.1) as a destination.
 *
 * Workspace-scoped, like the ontology it searches. Object types are
 * workspace-wide (db 0003), so an explorer reached through a project was
 * always searching past that project's boundary — you just had to pick one
 * first to get here. Same argument as the apps gallery next door: making
 * somebody guess a filing decision that has no bearing on the answer.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { ObjectExplorer } from "@/components/object-explorer";
import { useWorkspaceBySlug } from "@/components/use-workspace";

export default function ExplorePage() {
  const params = useParams<{ workspace: string }>();
  const { workspace, isPending, notFound } = useWorkspaceBySlug(params.workspace);

  if (isPending) return <main className="page"><div className="state">Loading…</div></main>;
  if (notFound || !workspace) {
    return (
      <main className="page">
        <div className="state error">
          This workspace doesn&apos;t exist or you don&apos;t have access to it.
        </div>
      </main>
    );
  }

  return (
    <main className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link href="/home">Workspaces</Link>
        <span className="link-mark" />
        <Link href={`/${params.workspace}`}>{workspace.name}</Link>
        <span className="link-mark" />
        <span className="current">Explore</span>
      </nav>
      <div className="page-head">
        <div>
          <p className="eyebrow">workspace</p>
          <h1>Explore</h1>
          <p className="sub">
            Every object in this workspace, across every type and every project.
          </p>
        </div>
      </div>

      <ObjectExplorer
        workspaceId={workspace.id}
        canEdit={workspace.effective_role !== "viewer"}
      />
    </main>
  );
}
