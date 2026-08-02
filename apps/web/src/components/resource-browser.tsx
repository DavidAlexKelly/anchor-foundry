"use client";

/** The project resource browser (ROADMAP.md phase 2, section 0 item 2).
 *
 * Foundry's project page is a file browser: name, type, when it changed. It is
 * deliberately dull, because it is a *directory* rather than a dashboard - the
 * interesting part is the application each row opens.
 *
 * Rows are real anchors with target="_blank". That is not decoration: an
 * onClick calling window.open breaks cmd-click, middle-click, "open in new
 * window" and the browser's own back-forward behaviour, all of which people
 * use on a list of things without thinking about it.
 */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { resources as resourcesApi } from "@/lib/api";
import type { Resource, ResourceKind } from "@/lib/types";

const PAGE = 25;

/** Order matters: this is the order the filter chips appear in, and it runs
 * roughly source → derived → published, which is the order somebody reads a
 * project in. */
export const KIND_LABELS: { kind: ResourceKind; label: string; plural: string }[] = [
  { kind: "connection", label: "Connection", plural: "Connections" },
  { kind: "dataset", label: "Dataset", plural: "Datasets" },
  { kind: "model", label: "Model", plural: "Models" },
  { kind: "object_type", label: "Object type", plural: "Object types" },
  { kind: "canvas_app", label: "Canvas app", plural: "Canvas apps" },
  { kind: "code_repo", label: "Repository", plural: "Repositories" },
];

const LABEL: Record<ResourceKind, string> = Object.fromEntries(
  KIND_LABELS.map((k) => [k.kind, k.label]),
) as Record<ResourceKind, string>;

export function kindLabel(kind: ResourceKind): string {
  return LABEL[kind] ?? kind;
}

/** Relative for anything recent, absolute once "3 weeks ago" stops being more
 * useful than a date. */
export function whenText(iso: string): string {
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  if (mins < 60 * 24 * 14) return `${Math.round(mins / (60 * 24))}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function ResourceBrowser({
  workspaceId,
  projectId,
}: {
  workspaceId: string;
  projectId: string;
}) {
  const [kinds, setKinds] = useState<ResourceKind[]>([]);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"updated_at" | "name" | "kind">("updated_at");
  const [page, setPage] = useState(0);
  const [includeWorkspace, setIncludeWorkspace] = useState(false);

  const counts = useQuery({
    queryKey: ["resource-counts", workspaceId, projectId],
    queryFn: () => resourcesApi.counts(workspaceId, projectId),
  });

  const listing = useQuery({
    queryKey: [
      "resources", workspaceId, projectId, kinds, search, sort, page, includeWorkspace,
    ],
    queryFn: () =>
      resourcesApi.list(workspaceId, projectId, {
        kind: kinds,
        search: search.trim() || undefined,
        sort,
        // Names read best A→Z; everything else reads best newest-first.
        direction: sort === "name" ? "asc" : "desc",
        limit: PAGE,
        offset: page * PAGE,
        includeWorkspaceLevel: includeWorkspace,
      }),
    // Keeps the table on screen while a filter change is in flight, rather
    // than flashing an empty state between two populated ones.
    placeholderData: (prev) => prev,
  });

  function toggleKind(kind: ResourceKind) {
    setPage(0);
    setKinds((cur) => (cur.includes(kind) ? cur.filter((k) => k !== kind) : [...cur, kind]));
  }

  const rows = listing.data?.resources ?? [];
  const total = listing.data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PAGE) - 1);

  return (
    <section className="resource-browser">
      <div className="rb-controls">
        <input
          className="rb-search"
          type="search"
          placeholder="Search resources"
          value={search}
          onChange={(e) => {
            setPage(0);
            setSearch(e.target.value);
          }}
          aria-label="Search resources"
        />
        <label className="rb-sort">
          Sort
          <select
            value={sort}
            onChange={(e) => {
              setPage(0);
              setSort(e.target.value as typeof sort);
            }}
          >
            <option value="updated_at">Last changed</option>
            <option value="name">Name</option>
            <option value="kind">Type</option>
          </select>
        </label>
      </div>

      <div className="rb-chips" role="group" aria-label="Filter by type">
        {KIND_LABELS.map(({ kind, plural }) => {
          const n = counts.data?.counts[kind] ?? 0;
          const on = kinds.includes(kind);
          return (
            <button
              key={kind}
              type="button"
              className={`rb-chip${on ? " on" : ""}`}
              aria-pressed={on}
              onClick={() => toggleKind(kind)}
            >
              {plural}
              <span className="rb-chip-count">{n}</span>
            </button>
          );
        })}
        {/* Object types and workspace-scoped connections belong to the
            workspace, not to this project. They are off by default so the
            browser does not quietly claim they live here (STATUS.md §44). */}
        <label className="rb-ws-toggle">
          <input
            type="checkbox"
            checked={includeWorkspace}
            onChange={(e) => {
              setPage(0);
              setIncludeWorkspace(e.target.checked);
            }}
          />
          Include workspace-level
        </label>
      </div>

      {listing.isError && (
        <p className="state error">{(listing.error as Error).message}</p>
      )}

      {rows.length === 0 && !listing.isPending ? (
        <p className="state">
          {search || kinds.length
            ? "Nothing here matches those filters."
            : "This project is empty. Create a connection or upload a dataset to begin."}
        </p>
      ) : (
        <table className="rb-table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Type</th>
              <th scope="col">Last changed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <ResourceRow key={r.id} resource={r} />
            ))}
          </tbody>
        </table>
      )}

      {total > PAGE && (
        <div className="rb-pager">
          <button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <span>
            {page * PAGE + 1}–{Math.min((page + 1) * PAGE, total)} of {total}
          </span>
          <button
            type="button"
            disabled={page >= lastPage}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      )}
    </section>
  );
}

function ResourceRow({ resource }: { resource: Resource }) {
  return (
    <tr>
      <td>
        {/* Deliberately no rel="noopener". The session token lives in
            sessionStorage, which a new tab inherits only when it is opened as
            a child browsing context - and noopener severs exactly that, so
            every row opened a tab that was immediately bounced to /login.
            noopener guards against an *untrusted* page reaching window.opener;
            this is our own origin, so the guard buys nothing and costs the
            feature. */}
        <a
          className="rb-link"
          href={`/r/${resource.id}`}
          target="_blank"
          title={resource.description || undefined}
        >
          {resource.name}
        </a>
        {resource.project_id === null && (
          <span className="rb-scope" title="Belongs to the workspace, not this project">
            workspace
          </span>
        )}
      </td>
      <td>{kindLabel(resource.kind)}</td>
      <td>
        <time dateTime={resource.updated_at}>{whenText(resource.updated_at)}</time>
      </td>
    </tr>
  );
}
