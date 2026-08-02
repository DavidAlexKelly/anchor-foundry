"use client";

/**
 * The apps gallery (ROADMAP Canvas item 6) - every published app in the
 * workspace, whatever project it was built in.
 *
 * This is the *consumer* view, and that is why it is workspace-scoped rather
 * than a tab inside a project. Somebody who opens a dashboard every Monday
 * does not know or care which project its author kept it in; making them
 * find the project first would be asking them to learn the builder's filing
 * system. The endpoint behind it (`published-canvas-apps`) has been there
 * since §15 with nothing calling it.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { canvas as canvasApi } from "@/lib/api";
import { useWorkspaceBySlug } from "@/components/use-workspace";

function when(value: string | null): string {
  if (!value) return "not published";
  return `published ${new Date(value).toLocaleDateString()}`;
}

export default function PublishedAppsPage() {
  const params = useParams<{ workspace: string }>();
  const { workspace, isPending: wsPending, notFound } = useWorkspaceBySlug(params.workspace);

  const apps = useQuery({
    queryKey: ["published-canvas-apps", workspace?.id],
    queryFn: () => canvasApi.listPublished(workspace!.id),
    enabled: !!workspace,
  });

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
        <Link href={`/${params.workspace}`}>{workspace?.name}</Link>
        <span className="link-mark" />
        <span className="current">Apps</span>
      </nav>
      <div className="page-head">
        <div>
          <p className="eyebrow">workspace</p>
          <h1>Apps</h1>
          <p className="sub">Published canvas apps from every project in this workspace.</p>
        </div>
      </div>

      {apps.isPending && <div className="state">Loading apps…</div>}
      {apps.isError && (
        <div className="state error">Couldn&apos;t load published apps. Refresh to try again.</div>
      )}
      {apps.data && apps.data.length === 0 && (
        <div className="empty">
          <h2>Nothing published yet</h2>
          <p>
            An app appears here once someone publishes it to the workspace, or to a group
            you belong to. Until then it stays inside the project it was built in.
          </p>
        </div>
      )}
      {apps.data && apps.data.length > 0 && (
        <div className="grid">
          {apps.data.map((app) => (
            <Link key={app.id} className="card" href={`/${params.workspace}/apps/${app.id}`}>
              <h3>{app.name}</h3>
              <span className="slug">{app.slug}</span>
              <p>{app.description || "No description."}</p>
              <div className="meta">
                <span className={`chip${app.publish_scope === "workspace" ? "" : " brass"}`}>
                  {app.publish_scope === "workspace" ? "whole workspace" : "specific groups"}
                </span>
                <span className="count">v{app.current_version}</span>
                <span className="count">{when(app.published_at)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
