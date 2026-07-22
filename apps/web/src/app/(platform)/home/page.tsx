"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { CreateWorkspaceButton } from "@/components/create-workspace";

export default function HomePage() {
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  // Mirror of the API's floor (org admin) — the server is authoritative.
  const canCreate = me.data?.org_role === "owner" || me.data?.org_role === "admin";

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">workspaces</p>
          <h1>Choose a workspace</h1>
          <p className="sub">Each workspace keeps its own data, storage, and search — fully isolated.</p>
        </div>
        {canCreate && <CreateWorkspaceButton />}
      </div>

      {workspaces.isPending && <div className="state">Loading workspaces…</div>}
      {workspaces.isError && (
        <div className="state error">Couldn&apos;t load workspaces. Refresh to try again.</div>
      )}
      {workspaces.data && workspaces.data.length === 0 && (
        <div className="empty">
          <h2>No workspaces yet</h2>
          <p>
            You don&apos;t have access to any workspaces. An organisation admin can create
            one and add you to it.
          </p>
        </div>
      )}
      {workspaces.data && workspaces.data.length > 0 && (
        <div className="grid">
          {workspaces.data.map((w) => (
            <Link key={w.id} className="card" href={`/${w.slug}`}>
              <h3>{w.name}</h3>
              <span className="slug">{w.slug}</span>
              <p>{w.description || "No description."}</p>
              <div className="meta">
                <span className={`chip${w.effective_role === "admin" ? " brass" : ""}`}>
                  {w.effective_role}
                </span>
                <span className="count">
                  {w.project_count} {w.project_count === 1 ? "project" : "projects"}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
