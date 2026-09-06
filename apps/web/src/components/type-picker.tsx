"use client";

/**
 * One object type, chosen from a workspace that may hold hundreds.
 *
 * **The reason this component exists is §256's `LIMIT`.** `GET /object-types`
 * had no bound and seven of its eight call sites were dropdowns that rendered
 * every type in the workspace; §209 measured ~1,400 of them taking seven
 * seconds to open a dialog. Bounding the endpoint alone would have turned a
 * slow picker into a lying one, so the endpoint searches too — and a search
 * that every dropdown re-implements is seven chances to get "the type I
 * already picked vanished" wrong. It is implemented once, here.
 *
 * **A search box that appears only when it is needed.** A workspace with eight
 * object types gets the plain `<select>` it always had; the control grows a
 * search only once the total says a page is hiding something. `lib/type-picker`
 * holds that rule and the three others, because they are the part that can be
 * wrong without a browser.
 *
 * **The search is the server's.** Filtering the rows already fetched would
 * answer the wrong question — it would search the page rather than the
 * ontology — and that is not hypothetical: the Object Explorer grew exactly
 * such a filter over its unbounded list, which was correct only for as long as
 * the list was every type there was.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { objects as objApi } from "@/lib/api";
import {
  PickableType, emptyNote, needsSearch, truncationNote, withSelected,
} from "@/lib/type-picker";
import type { ObjectTypeSummary } from "@/lib/types";

export function TypePicker({
  workspaceId,
  value,
  onChange,
  /** Rendered first, for "choose one…". Absent means the control always holds
   * a type, which is what a required field wants. */
  placeholder,
  /** Narrows what may be chosen at all — a caller that only accepts types with
   * a source, say. Applied to the page the server returned, and so it is a
   * *display* filter over a searched page rather than a second search. */
  filter,
  disabled,
  testId = "type-picker",
  label,
}: {
  workspaceId: string;
  value: string | null | undefined;
  onChange: (typeId: string) => void;
  placeholder?: string;
  filter?: (t: ObjectTypeSummary) => boolean;
  disabled?: boolean;
  testId?: string;
  label?: string;
}) {
  const [query, setQuery] = useState("");

  const page = useQuery({
    queryKey: ["object-types", workspaceId, query],
    queryFn: () => objApi.listTypes(workspaceId, undefined, { q: query || null }),
  });

  // **The chosen type, fetched on its own when the page does not hold it.**
  // A picker opened on a stored value has no reason to expect that value on
  // the first page of an alphabetical listing, and a `<select>` whose value is
  // not among its options renders blank — then writes the blank on the next
  // save. §175 found exactly that in a status dropdown.
  const selected = useQuery({
    queryKey: ["object-type", workspaceId, value],
    queryFn: () => objApi.getType(workspaceId, value!),
    enabled: !!value,
  });

  const all = page.data?.items ?? [];
  const shown = filter ? all.filter(filter) : all;
  // `getType` returns a detail and the page returns summaries; `withSelected`
  // is typed by the two fields an option is drawn from, so both fit without a
  // cast that would also admit anything else.
  const options: PickableType[] = withSelected<PickableType>(
    shown, selected.data ?? null,
  );
  const total = page.data?.total ?? 0;
  // The note counts what the *server* returned against what it says matches;
  // a caller's `filter` narrows the display and is not a claim about the
  // ontology, so folding it in here would report a smaller total than exists.
  const note = truncationNote(all.length, total);

  return (
    <>
      {needsSearch(total, query) && (
        <input
          type="text"
          data-testid={`${testId}-search`}
          aria-label={label ? `Search ${label}` : "Search object types"}
          placeholder="Search object types…"
          value={query}
          disabled={disabled}
          onChange={(e) => setQuery(e.target.value)}
          style={{ marginBottom: 6 }}
        />
      )}
      <select
        data-testid={testId}
        aria-label={label}
        value={value ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((t) => (
          <option key={t.id} value={t.id}>{t.display_name}</option>
        ))}
      </select>
      {note && (
        <p className="field-hint" data-testid={`${testId}-note`}>{note}</p>
      )}
      {page.data && options.length === 0 && (
        <p className="field-hint" data-testid={`${testId}-empty`}>
          {emptyNote(total, query)}
        </p>
      )}
    </>
  );
}
