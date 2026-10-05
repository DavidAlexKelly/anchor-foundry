"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useWorkspaceBySlug } from "@/components/use-workspace";
import { CreateProjectButton } from "@/components/create-project";

export default function WorkspacePage() {
  const params = useParams<{ workspace: string }>();
  const { workspace, isPending: wsPending, notFound } = useWorkspaceBySlug(params.workspace);

  // A page at a time, searched (§823): the grid drew every project in the
  // workspace, and a workspace can hold thousands. Keyed under
  // ["projects", id] so creating a project refreshes it.
  const [search, setSearch] = useState("");
  const projects = useInfiniteQuery({
    queryKey: ["projects", workspace?.id, { page: search }],
    queryFn: ({ pageParam }) => api.projectPage(workspace!.id, search, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const shown = pages.reduce((n, p) => n + p.items.length, 0);
      return shown < last.total && last.items.length > 0 ? shown : undefined;
    },
    enabled: !!workspace,
    placeholderData: (previous) => previous,
  });
  const shown = projects.data?.pages.flatMap((p) => p.items) ?? [];
  const total = projects.data?.pages[0]?.total ?? 0;

  if (wsPending) return <main className="page"><div className="state">Loading…</div></main>;
  if (notFound) {
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
        <span className="current">{workspace?.name}</span>
      </nav>
      <div className="page-head">
        <div>
          <p className="eyebrow">workspace</p>
          <h1>{workspace?.name}</h1>
          {workspace?.description && <p className="sub">{workspace.description}</p>}
        </div>
        <div className="row-actions">
          {/* Apps are workspace-wide, not per-project: somebody who opens a
              dashboard every Monday should not have to know which project its
              author filed it in (ROADMAP Canvas item 6). */}
          <Link className="btn quiet" href={`/${params.workspace}/apps`}>
            Apps
          </Link>
          {/* The ontology is workspace-wide (db 0003), so searching it is too
              — roadmap item 4.1. */}
          <Link className="btn quiet" href={`/${params.workspace}/explore`}>
            Explore
          </Link>
          {/* p.68's cleanup tool, beside the explorer because both are about
              the workspace's ontology as a whole. Offered only to people who
              could act on it: p.71's three buttons are all writes, and a link
              to a page of controls somebody cannot press is §214's control
              that looks like it works. */}
          {workspace && workspace.effective_role !== "viewer" && (
            <Link className="btn quiet" href={`/${params.workspace}/cleanup`}>
              Cleanup
            </Link>
          )}
          {/* p.66 puts Export and Import on an Advanced settings page reached
              from the home page. Offered only to people who could use it, for
              the same reason as Cleanup beside it. */}
          {workspace && workspace.effective_role !== "viewer" && (
            <Link className="btn quiet" href={`/${params.workspace}/advanced`}>
              Advanced
            </Link>
          )}
          {/* p.35's "Tags section": everybody may read the tags, so the link
              is for everybody; only an admin is offered the form there. */}
          <Link className="btn quiet" href={`/${params.workspace}/tags`} data-testid="workspace-tags">
            Tags
          </Link>
          <span className={`chip${workspace?.effective_role === "admin" ? " brass" : ""}`}>
            {workspace?.effective_role}
          </span>
          {workspace && workspace.effective_role !== "viewer" && (
            <CreateProjectButton workspaceId={workspace.id} workspaceSlug={workspace.slug} />
          )}
        </div>
      </div>

      <div className="row-actions" style={{ marginBottom: 12 }}>
        <input
          type="search"
          aria-label="Search projects"
          placeholder="Search projects"
          data-testid="project-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {projects.data && (
          <span className="field-hint" data-testid="project-count">
            {shown.length < total ? `${shown.length} of ${total} projects` : `${total} ${total === 1 ? "project" : "projects"}`}
          </span>
        )}
      </div>
      {projects.isPending && <div className="state">Loading projects…</div>}
      {projects.isError && (
        <div className="state error">Couldn&apos;t load projects. Refresh to try again.</div>
      )}
      {projects.data && total === 0 && search.trim() !== "" && (
        <div className="state">No projects match.</div>
      )}
      {projects.data && total === 0 && search.trim() === "" && (
        <div className="empty">
          <h2>No projects yet</h2>
          <p>
            Projects hold your connections, datasets, models, and apps. Anyone with the
            editor role here can create one.
          </p>
        </div>
      )}
      {shown.length > 0 && (
        <div className="grid" data-testid="project-grid">
          {shown.map((p) => (
            <Link key={p.id} className="card" href={`/${params.workspace}/${p.slug}`}>
              <h3>{p.name}</h3>
              <span className="slug">{p.slug}</span>
              <p>{p.description || "No description."}</p>
              <div className="meta">
                <span className={`chip${p.effective_role === "owner" ? " brass" : ""}`}>
                  {p.effective_role}
                </span>
                {p.permission_mode === "custom" && <span className="count">custom access</span>}
              </div>
            </Link>
          ))}
        </div>
      )}
      {projects.hasNextPage && (
        <div className="row-actions" style={{ marginTop: 16 }}>
          <button
            type="button"
            className="btn quiet"
            data-testid="project-more"
            disabled={projects.isFetchingNextPage}
            onClick={() => projects.fetchNextPage()}
          >
            {projects.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        </div>
      )}
    </main>
  );
}
