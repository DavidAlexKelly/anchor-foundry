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
 *
 * **The kind filter lives in the URL** (`?kind=dataset&kind=model`), which is
 * what lets a pillar page *be* this browser with a filter applied rather than
 * a second implementation of the same list beside it - parity stage 1, and the
 * reason `KIND_LABELS` is exported. It follows §99's rule: the URL is the
 * state, not a copy of it, so a filtered link survives a reload and the back
 * button steps through filters the way a reader expects. The other controls
 * stay in component state deliberately - a half-typed search box is not
 * something anybody wants to send someone.
 */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { resources as resourcesApi } from "@/lib/api";
import type { Resource, ResourceKind } from "@/lib/types";
import { useUrlState } from "@/components/use-url-state";
import {
  KIND_LABELS,
  isKind,
  kindLabel,
  selectedKinds,
  toggleKind as nextKinds,
} from "@/components/resource-filter";

// Re-exported because callers already import them from here, and the filter
// module is an implementation detail of where the logic is testable from.
export { KIND_LABELS, isKind, kindLabel };

const PAGE = 25;

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
  const url = useUrlState();
  // Unknown kinds are dropped rather than passed through: a hand-typed
  // `?kind=nonsense` would otherwise reach the API as a filter matching
  // nothing, and the reader would see an empty project rather than a
  // disregarded filter.
  const kinds = selectedKinds(url.all("kind"));
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"updated_at" | "name" | "kind">("updated_at");
  const [page, setPage] = useState(0);
  const [includeWorkspace, setIncludeWorkspace] = useState(false);

  /** Page number resets whenever the kind filter changes - including via the
   * back button, which is why this is not simply a `setPage(0)` inside the
   * chip handler. Filters live in the URL and the page number does not, so
   * stepping back to a narrower filter while on page 3 would otherwise ask the
   * API for rows 75-100 of a list with eight rows in it and render "no
   * resources" over a project that has plenty. Adjusting state during render
   * is the documented React pattern for deriving state from a changing input;
   * it re-renders before committing, so no flash of the wrong page. */
  const kindKey = kinds.join(",");
  const [lastKindKey, setLastKindKey] = useState(kindKey);
  if (kindKey !== lastKindKey) {
    setLastKindKey(kindKey);
    setPage(0);
  }

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
    // Computed from what is *currently* in the URL rather than from `kinds`,
    // which is a render-time snapshot: ticking two chips faster than the
    // router settles would otherwise drop the first. `useUrlState` documents
    // this as the reason its setter takes a function.
    url.set((current) => ({ kind: nextKinds(current.getAll("kind"), kind) }));
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
