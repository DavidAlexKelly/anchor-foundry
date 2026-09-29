"use client";

/**
 * The Ontology's saved changes (§683; `ontology-manager` p.8).
 *
 * > "Select the History tab in the homepage sidebar to view a list of all
 * > saved Ontology changes with details on when the changes were made and the
 * > user who applied them. By default, the list of changes are collapsed. You
 * > can select the (down arrow) on any change to view details." (p.8)
 *
 * A section of the ontology page rather than p.8's sidebar tab, as the other
 * ontology-wide lists here are, and with p.8's option to merge one author's
 * run of changes into one entry. The words for each change are
 * `lib/ontology-history.ts`.
 */

import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { objects as objApi } from "@/lib/api";
import { describe, details, mergedByAuthor } from "@/lib/ontology-history";
import type { OntologyChange } from "@/lib/types";

const PAGE = 25;

function when(iso: string): string {
  return new Date(iso).toLocaleString();
}

function Change({ change }: { change: OntologyChange }) {
  const [open, setOpen] = useState(false);
  const lines = details(change.metadata);
  return (
    <li data-testid="history-entry" data-action={change.action}>
      <button
        type="button"
        className="btn quiet"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        style={{ textAlign: "left" }}
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span> {describe(change)}
      </button>
      <span className="field-hint" style={{ marginLeft: 8 }}>
        {change.user_name ?? "Someone"} · <time dateTime={change.created_at}>{when(change.created_at)}</time>
      </span>
      {open && (
        <ul className="field-hint" data-testid="history-details" style={{ margin: "4px 0 8px 24px" }}>
          {lines.length === 0 ? <li>No further details were recorded.</li>
            : lines.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
    </li>
  );
}

export function OntologyHistoryPanel({ workspaceId }: { workspaceId: string }) {
  const [merged, setMerged] = useState(false);
  const history = useInfiniteQuery({
    queryKey: ["ontology-history", workspaceId],
    queryFn: ({ pageParam }) =>
      objApi.ontologyHistory(workspaceId, { limit: PAGE, before: pageParam ?? undefined }),
    initialPageParam: null as number | null,
    // A short page is the last one.
    getNextPageParam: (last) => (last.length < PAGE ? null : last[last.length - 1]!.id),
  });
  const changes = history.data?.pages.flat() ?? [];

  return (
    <section data-testid="ontology-history" style={{ marginTop: 32 }}>
      <div className="page-head">
        <div><h2 style={{ fontSize: 15, margin: 0 }}>History</h2></div>
        <label className="vars-toggle" style={{ fontSize: 12.5 }}>
          <input
            type="checkbox"
            data-testid="history-merge"
            checked={merged}
            onChange={(e) => setMerged(e.target.checked)}
          />
          Merge changes by the same author
        </label>
      </div>
      {history.isSuccess && changes.length === 0 && (
        <p className="login-note">No saved changes yet.</p>
      )}
      {merged ? (
        <ol style={{ listStyle: "none", padding: 0 }}>
          {mergedByAuthor(changes).map((run) => (
            <li key={run.changes[0]!.id} data-testid="history-run">
              <strong>{run.user_name ?? "Someone"}</strong>
              <span className="field-hint"> · {run.changes.length} change{run.changes.length === 1 ? "" : "s"}</span>
              <ul style={{ listStyle: "none", paddingLeft: 16 }}>
                {run.changes.map((change) => <Change key={change.id} change={change} />)}
              </ul>
            </li>
          ))}
        </ol>
      ) : (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {changes.map((change) => <Change key={change.id} change={change} />)}
        </ul>
      )}
      {history.hasNextPage && (
        <button
          type="button"
          className="btn quiet"
          data-testid="history-more"
          disabled={history.isFetchingNextPage}
          onClick={() => history.fetchNextPage()}
        >
          Show older changes
        </button>
      )}
    </section>
  );
}

/** p.8: "At the bottom left of an Ontology resource view, a footer states when
 * the resource was last edited and by which user." The newest entry of the
 * resource's own history, so it counts every kind of save, not only the ones
 * that make a version. */
export function LastEdited({ workspaceId, resourceId }: { workspaceId: string; resourceId: string }) {
  const last = useQuery({
    queryKey: ["ontology-history", workspaceId, resourceId],
    queryFn: () => objApi.ontologyHistory(workspaceId, { resourceId, limit: 1 }),
  });
  const change = last.data?.[0];
  if (!change) return null;
  return (
    <p className="field-hint" data-testid="last-edited" style={{ marginTop: 10 }}>
      Last edited by {change.user_name ?? "someone"} ·{" "}
      <time dateTime={change.created_at}>{when(change.created_at)}</time>
    </p>
  );
}
