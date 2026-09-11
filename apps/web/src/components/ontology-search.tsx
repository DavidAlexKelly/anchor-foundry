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
import { memberSummary } from "@/lib/object-type-groups";
import { editedAgo } from "@/lib/recently-edited";
import {
  KIND_LABELS,
  destinationFor,
  implementationSummary,
} from "@/lib/search-destination";

export function OntologySearch({
  workspaceId,
  onOpenType,
  onOpenSharedProperty,
  onOpenGroup,
  onOpenInterface,
}: {
  workspaceId: string;
  /** Where a hit goes. Four of the six kinds belong to an object type, which
   * is the one place all four can be looked at. */
  onOpenType: (typeId: string) => void;
  /** The fifth. A shared property belongs to no object type
   * (`object-link-types` p.178), so it has its own destination rather than a
   * borrowed one — without this a hit would either go nowhere, or go somewhere
   * that has nothing to do with what was searched for. */
  onOpenSharedProperty: (sharedId: string) => void;
  /** The sixth, for the same reason (p.261). A group is not on an object type
   * and cannot borrow one's destination — and the ownerless kinds cannot share
   * a handler either, since a group id opened as a shared property finds
   * nothing and silently does nothing at all. */
  onOpenGroup: (groupId: string) => void;
  /** The seventh, and **the one that proved the sentence above was a rule and
   * not a remark** (§316). §252 made interfaces searchable without giving them
   * a destination, so for sixty-four units an interface hit did exactly what
   * that comment describes: it fell past the group check into
   * `onOpenSharedProperty` and opened an editor for an id that is not a shared
   * property. An interface is implemented *by* object types rather than owned
   * by one (`object-link-types` p.4), so it has no type's screen to borrow. */
  onOpenInterface: (interfaceId: string) => void;
}) {
  const [query, setQuery] = useState("");
  // **Focus, not hover** (§317). p.30 puts the quick links behind a hover, and
  // a hover is a gesture a keyboard and a touchscreen do not have — so the
  // panel opens when the box is focused, which `Cmd+K` does from anywhere and
  // a tap does on a phone. The same links, reachable by everybody who can
  // reach the search they sit inside.
  const [focused, setFocused] = useState(false);
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

  // **p.30's quick links, in the shape this product has for them** (§317).
  //
  //     "Hovering over the Back home button will also bring up quick links to
  //      recently edited object types, link types, and action types." (p.30)
  //
  // There is no Back home button here to hover: this ontology has one page
  // with sections rather than Foundry's separate home (the `ontology.md` row
  // for p.29 says why), so the hover has no host. The box you open when you
  // want to get somewhere does, and it is already the thing people reach for —
  // `Cmd+K` lands here from anywhere on the page.
  //
  // **This does not contradict the comment above it.** "Blank means blank" is
  // about *search results*, and it still holds: an empty query still searches
  // for nothing, because a search box whose empty state is the whole ontology
  // is a list. Eight things somebody edited is not the ontology; it is the
  // shortest possible answer to "take me back to what I was doing".
  const recent = useQuery({
    queryKey: ["ontology-recent", workspaceId],
    queryFn: () => objApi.recentlyEdited(workspaceId),
    enabled: focused && query.trim().length === 0,
  });
  const quickLinks = recent.data ?? [];

  return (
    <div className="ontology-search" data-testid="ontology-search">
      <input
        ref={input}
        type="search"
        value={query}
        aria-label="Search the ontology"
        placeholder="Search object types, properties, links, actions… (⌘K)"
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => setFocused(true)}
        // **On a timer, and the timer is the point.** A `blur` that closed the
        // panel immediately would fire before the click that caused it landed
        // on a button inside the panel — the link would be removed from the
        // document mid-click and nothing would happen, which is the same
        // silent nothing §316 spent sixty-four units being.
        onBlur={() => window.setTimeout(() => setFocused(false), 150)}
      />
      {focused && query.trim().length === 0 && quickLinks.length > 0 && (
        <div className="ontology-search-results" data-testid="ontology-recent">
          <p className="slug" style={{ margin: "0 0 6px" }}>Recently edited</p>
          <ul className="link-list">
            {quickLinks.map((row) => (
              <li key={`${row.kind}:${row.id}`}>
                <button
                  type="button"
                  className="btn quiet"
                  style={{ padding: "4px 10px", fontSize: 12.5, textAlign: "left" }}
                  data-kind={row.kind}
                  data-testid={`recent-${row.api_name}`}
                  /* The same decision the search hits use. All three of p.30's
                     kinds have an owning object type, so all three resolve to
                     one — but routed through `destinationFor` rather than
                     assumed, because "they all go to the same place" is a fact
                     about today's three kinds and not about the function. */
                  onMouseDown={(e) => {
                    // **`mousedown`, not `click`.** The blur that closes this
                    // panel fires first, and a click handler on a button that
                    // is about to be unmounted is a button that does nothing.
                    e.preventDefault();
                    const to = destinationFor(row);
                    if (to?.open === "object_type") onOpenType(to.id);
                  }}
                >
                  <span className="slug" style={{ marginRight: 8 }}>
                    {KIND_LABELS[row.kind]}
                  </span>
                  <strong>{row.display_name || row.api_name}</strong>
                  {/* Where it lives, for the two kinds that live somewhere
                      else. An object type is its own owner, and "Site on Site"
                      is noise. */}
                  {row.kind !== "object_type" && (
                    <span className="slug" style={{ marginLeft: 8 }}>
                      on {row.object_type_name}
                    </span>
                  )}
                  {/* **When**, because the order alone says which is most
                      recent and nothing about whether the top row is four
                      minutes old or four months — and those are different
                      lists. It also keeps the field honest: a response field
                      nothing draws is a field nothing checks. */}
                  <span className="slug" style={{ marginLeft: 8 }}>
                    {editedAgo(row.updated_at, Date.now())}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

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
                    /* **The dispatch is a decision, not a chain of
                       ternaries** (§316). The chain that stood here fell
                       through to the last branch for any kind it did not
                       name, which is how an interface hit came to open a
                       shared property editor. `destinationFor` has a case per
                       kind and no default, so the next kind added to the union
                       is a compile error rather than a click that does
                       nothing. */
                    onClick={() => {
                      const to = destinationFor(hit);
                      if (!to) return;
                      if (to.open === "object_type") onOpenType(to.id);
                      else if (to.open === "group") onOpenGroup(to.id);
                      else if (to.open === "interface") onOpenInterface(to.id);
                      else onOpenSharedProperty(to.id);
                    }}
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
                    ) : hit.kind === "group" ? (
                      /* A group has no owner either, and says its size for the
                         same reason — except that here **zero is worth saying
                         out loud**: p.263 makes a group discoverable whether
                         or not it has members, so an empty one is a real
                         answer rather than a broken row. */
                      <span className="slug" style={{ marginLeft: 8 }}>
                        {memberSummary(hit.usage_count ?? 0)}
                      </span>
                    ) : hit.kind === "interface" ? (
                      /* The third ownerless kind, saying the number that
                         decides whether editing this shape is cheap
                         (§252's argument). Without this branch it fell to the
                         one below and rendered "on " with nothing after it —
                         an interface has no owning type to name. */
                      <span className="slug" style={{ marginLeft: 8 }}>
                        {implementationSummary(hit.usage_count ?? 0)}
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
