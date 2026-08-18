"use client";

/**
 * The Ontology Manager's header search (parity `docs/parity/ontology.md` §6;
 * Foundry `ontology-manager` p.28).
 *
 * > "Use the search bar in the header … to search across object types,
 * > properties, link types, action types … The search results highlight the
 * > specific field that matched your query."
 *
 * **The highlight is drawn from the server's answer, not re-derived.** Each
 * hit says which field matched and what that field's value is, so this
 * highlights inside *that* string. Re-deriving it here would be a second
 * matcher: it could disagree with the one that decided the row belonged in the
 * list, and the disagreement would show up as a highlight on the wrong word —
 * or on no word at all, which reads as the search being broken.
 *
 * **`Cmd+K` focuses it** (p.28). Bound on the window rather than on the input,
 * because the point of the shortcut is that you do not have to find the box
 * first; and it is skipped while another field has focus, so it cannot steal a
 * keystroke from somebody mid-way through typing an api_name.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { objects as objApi } from "@/lib/api";
import { highlight } from "@/components/ontology-highlight";
import type { OntologySearchHit } from "@/lib/types";

const KIND_LABELS: Record<OntologySearchHit["kind"], string> = {
  object_type: "Object type",
  property: "Property",
  link_type: "Link type",
  action_type: "Action",
  shared_property: "Shared property",
};

export function OntologySearch({
  workspaceId,
  onOpenType,
  onOpenSharedProperty,
}: {
  workspaceId: string;
  /** Where a hit goes. Four of the five kinds belong to an object type, which
   * is the one place all four can be looked at. */
  onOpenType: (typeId: string) => void;
  /** The fifth. A shared property belongs to no object type
   * (`object-link-types` p.178), so it has its own destination rather than a
   * borrowed one — without this a hit would either go nowhere, or go somewhere
   * that has nothing to do with what was searched for. */
  onOpenSharedProperty: (sharedId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "k" || !(event.metaKey || event.ctrlKey)) return;
      const active = document.activeElement;
      // Not while somebody is typing somewhere else - a shortcut that steals a
      // keystroke mid-api_name is worse than no shortcut.
      if (active instanceof HTMLInputElement && active !== input.current) return;
      if (active instanceof HTMLTextAreaElement) return;
      event.preventDefault();
      input.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Blank means blank: the server returns nothing for an empty query, and this
  // does not ask. A search box whose empty state is the whole ontology is a
  // list, and this page already has one below it.
  const results = useQuery({
    queryKey: ["ontology-search", workspaceId, query.trim()],
    queryFn: () => objApi.searchOntology(workspaceId, query.trim()),
    enabled: query.trim().length > 0,
  });
  const hits = results.data ?? [];

  return (
    <div className="ontology-search" data-testid="ontology-search">
      <input
        ref={input}
        type="search"
        value={query}
        aria-label="Search the ontology"
        placeholder="Search object types, properties, links, actions… (⌘K)"
        onChange={(e) => setQuery(e.target.value)}
      />
      {query.trim().length > 0 && (
        <div className="ontology-search-results" data-testid="ontology-search-results">
          {results.isPending && <p className="state">Searching…</p>}
          {results.isError && (
            <p className="state error">Couldn&apos;t search the ontology.</p>
          )}
          {results.data && hits.length === 0 && (
            <p className="login-note" style={{ margin: 0 }}>
              Nothing in this workspace&apos;s ontology matches that.
            </p>
          )}
          {hits.length > 0 && (
            <ul className="link-list">
              {hits.map((hit) => (
                <li key={`${hit.kind}:${hit.id}`}>
                  <button
                    type="button"
                    className="btn quiet"
                    style={{ padding: "4px 10px", fontSize: 12.5, textAlign: "left" }}
                    data-kind={hit.kind}
                    data-matched-field={hit.matched_field}
                    onClick={() =>
                      hit.object_type_id
                        ? onOpenType(hit.object_type_id)
                        : onOpenSharedProperty(hit.id)
                    }
                  >
                    <span className="slug" style={{ marginRight: 8 }}>
                      {KIND_LABELS[hit.kind]}
                    </span>
                    <strong>{hit.display_name || hit.api_name}</strong>
                    {/* Which field matched, and the match itself marked inside
                        it. Naming the field is half of p.28's requirement —
                        "description" and "name" are different reasons to be in
                        this list, and a reader deciding which hit to click
                        needs to know which one they are looking at. */}
                    <span className="slug" style={{ marginLeft: 8 }}>
                      {hit.matched_field}:{" "}
                      {highlight(hit.matched_value, query).map((part, i) =>
                        typeof part === "string" ? (
                          <span key={i}>{part}</span>
                        ) : (
                          <mark key={i}>{part.mark}</mark>
                        ),
                      )}
                    </span>
                    {/* Where it lives, in whichever way is true of it. A
                        shared property has no owner to name, so it says how
                        many properties use it instead — which is the fact
                        somebody about to open it is deciding on. */}
                    {hit.kind === "shared_property" ? (
                      <span className="slug" style={{ marginLeft: 8 }}>
                        used by {hit.usage_count}{" "}
                        {hit.usage_count === 1 ? "property" : "properties"}
                      </span>
                    ) : hit.kind !== "object_type" ? (
                      <span className="slug" style={{ marginLeft: 8 }}>
                        on {hit.object_type_name}
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
