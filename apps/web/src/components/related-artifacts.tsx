"use client";

/** The Related artifacts helper, for the graph's selection (§614;
 * `data-lineage` p.10, p.30). The rules are in `lib/related-artifacts.ts`,
 * which has the tests; what is here is the fetch and the markup. */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { models as modelApi } from "@/lib/api";
import {
  EXCLUSION_NOTE, KINDS, SORTS, artifactEntries, askedFor, emptyNote, kindCounts,
  type ArtifactKind, type ArtifactSort,
} from "@/lib/related-artifacts";
import type { InspectFrom } from "@/components/graph-inspector";

export function RelatedArtifacts({
  selected,
  names,
  from,
  onZoom,
}: {
  selected: readonly string[];
  names: ReadonlyMap<string, string>;
  from: InspectFrom;
  /** p.30's node icon: "zoom in on the related dataset". */
  onZoom: (nodeId: string) => void;
}) {
  const asked = askedFor(selected);
  const [sort, setSort] = useState<ArtifactSort>("name");
  const [hidden, setHidden] = useState<ReadonlySet<ArtifactKind>>(new Set());
  // Asked even when nothing in the selection is askable: an empty question
  // has an empty answer, so an `enabled` guard and a second guard on the data
  // could not change what is drawn (§614's sweep).
  const related = useQuery({
    queryKey: ["related-artifacts", from.projectId, asked],
    queryFn: () => modelApi.relatedArtifacts(from.workspaceId, from.projectId, asked),
  });
  const found = related.data ?? [];
  const counts = kindCounts(found);
  const entries = artifactEntries(found, {
    names, currentProject: from.projectId, sort, hidden,
  });

  return (
    <div style={{ marginBottom: 8 }} data-testid="related-artifacts">
      <div className="slug" style={{ marginBottom: 4, display: "flex", gap: 6, flexWrap: "wrap",
                                     alignItems: "center" }}>
        Related artifacts
        {/* p.30's badge: "the number of artifacts related to the selected
            dataset". */}
        <span className="chip" data-testid="related-count">{found.length}</span>
        {KINDS.map(({ kind, label }) => {
          const on = !hidden.has(kind);
          return (
            <button
              key={kind}
              type="button"
              className={on ? "chip on" : "chip"}
              aria-pressed={on}
              data-testid={`related-kind-${kind}`}
              onClick={() => {
                const next = new Set(hidden);
                if (on) next.add(kind);
                else next.delete(kind);
                setHidden(next);
              }}
            >
              {label} <span className="slug">{counts[kind]}</span>
            </button>
          );
        })}
        <label className="slug">
          Sort by{" "}
          <select
            value={sort}
            data-testid="related-sort"
            onChange={(e) => setSort(e.target.value as ArtifactSort)}
          >
            {SORTS.map((s) => <option key={s.sort} value={s.sort}>{s.label}</option>)}
          </select>
        </label>
      </div>
      <div className="soft" data-testid="related-exclusions" style={{ fontSize: 12 }}>
        {EXCLUSION_NOTE}
      </div>
      {asked.length > 0 && related.isPending ? (
        <div className="slug">Looking for what links to the selection…</div>
      ) : related.isError ? (
        <div className="state error">Couldn&apos;t read what links to the selection.</div>
      ) : entries.length === 0 ? (
        <div className="slug" data-testid="related-empty">{emptyNote(asked.length, found.length)}</div>
      ) : (
        <ul className="plain-list" data-testid="related-list" style={{ margin: 0, padding: 0 }}>
          {entries.map((entry) => (
            <li key={entry.key} data-testid={`related-entry-${entry.key}`}
                style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap",
                         fontSize: 13, listStyle: "none" }}>
              <span className="slug">{KINDS.find((k) => k.kind === entry.kind)?.label}</span>
              {/* p.30: "click the resource to open it in the corresponding
                  application in a new tab". */}
              <Link href={entry.href} target="_blank" rel="noopener noreferrer">{entry.label}</Link>
              {entry.project && <span className="soft">in {entry.project}</span>}
              {entry.nodes.map((node) => (
                <button
                  key={node.id}
                  type="button"
                  className="chip"
                  title={`Zoom to ${node.label}`}
                  data-testid={`related-zoom-${node.id}`}
                  onClick={() => onZoom(node.id)}
                >
                  ◎ {node.label}
                </button>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
