"use client";

/** The Object Explorer (ROADMAP.md phase 2, item 4.1).
 *
 * Workspace-wide instance search, type filtering, saved searches and link
 * traversal — as a destination of its own rather than as a panel at the bottom
 * of a project's Objects settings page, which is where it lived from
 * `STATUS.md` §32 until now.
 *
 * **Why it moved.** Object types are workspace-wide (db 0003), so the explorer
 * always searched across every project whatever project page you opened it
 * from. Reaching it meant picking a project first, which is asking somebody to
 * guess a filing decision that has no bearing on the answer — the same
 * inversion section 0 exists to undo, and the same argument that put the apps
 * gallery at `/{workspace}/apps`.
 *
 * Three things it is careful about:
 *
 *   1. **A saved search stores the question, never its answer.** "Vessels
 *      flagged NO" reads differently tomorrow. The definition goes to the
 *      server as the explorer's own four parameters and comes back validated
 *      by the same function the explorer route uses, so a search that cannot
 *      run cannot be saved.
 *   2. **The property filter is offered only when exactly one type is
 *      selected**, and says why when it is not. `status` on an Order and
 *      `status` on a Shipment are unrelated columns that share a name; the
 *      server refuses the combination, and a form that let you build it anyway
 *      would be teaching the rule by rejection.
 *   3. **A search naming a deleted type still runs, and keeps naming it.**
 *      Quietly dropping the dead id would broaden the question — the search
 *      would start returning rows it never asked for, and read as though
 *      nothing had happened.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ApiError, objects as objApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { LinkExplorerDialog, type LinkStop } from "@/components/instance-links";
import { displayValue } from "@/components/object-value";
import { CopyLinkButton, useUrlState } from "@/components/use-url-state";
import type { ObjectTypeSummary, SavedSearch } from "@/lib/types";

/** The explorer's whole state, and the whole of what a saved search stores.
 * One shape rather than four `useState`s so that "save what is on screen" and
 * "open what was saved" are each a single assignment. */
export type Criteria = {
  q: string;
  typeIds: string[];
  property: string;
  value: string;
};

const EMPTY: Criteria = { q: "", typeIds: [], property: "", value: "" };
const PAGE = 25;
/** Above this many object types the checkbox list gets a filter of its own. */
const TYPE_FILTER_FROM = 12;

function fromSaved(search: SavedSearch): Criteria {
  return {
    q: search.definition.q ?? "",
    // Including ids the workspace no longer has. See the header: dropping them
    // would widen the question rather than answer it.
    typeIds: search.definition.type_ids ?? [],
    property: search.definition.property ?? "",
    value: search.definition.value ?? "",
  };
}

function toDefinition(criteria: Criteria) {
  const paired = criteria.property.trim() !== "" && criteria.value !== "";
  return {
    q: criteria.q.trim() || null,
    type_ids: criteria.typeIds,
    property: paired ? criteria.property.trim() : null,
    value: paired ? criteria.value : null,
  };
}

function isEmpty(criteria: Criteria): boolean {
  return (
    criteria.q.trim() === "" &&
    criteria.typeIds.length === 0 &&
    criteria.property.trim() === ""
  );
}

/** Is this saved search the one currently on screen?
 *
 * Derived by comparing definitions rather than remembering an id (item 0.4).
 * An id kept alongside the criteria goes stale the moment somebody ticks
 * another type, and then the rail claims you are looking at "Norwegian
 * vessels" while you are looking at something else — and, once the state is in
 * the URL, the *link* claims it too. Order of `type_ids` is not part of the
 * question, so it is not part of the comparison.
 */
function matches(search: SavedSearch, criteria: Criteria): boolean {
  const a = search.definition;
  const b = toDefinition(criteria);
  return (
    (a.q ?? null) === b.q &&
    (a.property ?? null) === b.property &&
    (a.value ?? null) === b.value &&
    [...(a.type_ids ?? [])].sort().join(",") === [...b.type_ids].sort().join(",")
  );
}

/** The part of the form that is actually in effect.
 *
 * A property filter needs exactly one type, so with two ticked it is not part
 * of the question — and everything downstream has to agree about that. Sending
 * it anyway is a 422 where results should be; saving it would store a search
 * the server refuses; marking a saved search by it would compare against
 * something not in effect. The typed filter stays in the URL rather than being
 * deleted, so unticking the second type brings it back instead of asking
 * somebody to type it again, and the form says it is not in effect.
 */
function inEffect(criteria: Criteria): Criteria {
  if (criteria.typeIds.length === 1) return criteria;
  return { ...criteria, property: "", value: "" };
}

function describe(search: SavedSearch): string {
  const parts: string[] = [];
  if (search.definition.q) parts.push(`“${search.definition.q}”`);
  if (search.type_names.length > 0) parts.push(search.type_names.join(", "));
  if (search.definition.property) {
    parts.push(`${search.definition.property} = ${search.definition.value ?? ""}`);
  }
  return parts.join(" · ");
}

export function ObjectExplorer({
  workspaceId,
  workspaceSlug,
  canEdit,
}: {
  workspaceId: string;
  /** Only for the link-subset URL (`object-views` p.11) - this component
   * addresses everything else by id. */
  workspaceSlug: string;
  canEdit: boolean;
}) {
  // The question is the URL (item 0.4). Not a copy of it kept in state and
  // written back: "send me the link to that" is the reason saved searches
  // exist, so the surface they were built for has to be linkable too, and one
  // source of truth is how it stays that way through a paste or a reload.
  const url = useUrlState();
  const criteria: Criteria = {
    q: url.get("q") ?? "",
    typeIds: url.all("type"),
    property: url.get("property") ?? "",
    value: url.get("value") ?? "",
  };
  const pageNo = Math.max(1, Math.trunc(Number(url.get("page"))) || 1);
  const offset = (pageNo - 1) * PAGE;

  const applied = inEffect(criteria);

  // Local, and deliberately not in the link: half-typed text is not a
  // question anybody meant to ask, and the type-list filter is a way of
  // reading the form rather than part of what it asks.
  const [draft, setDraft] = useState(() => criteria.q);
  const [typeFilter, setTypeFilter] = useState("");
  const [saving, setSaving] = useState<Criteria | null>(null);
  const [exploring, setExploring] = useState<LinkStop | null>(null);

  const types = useQuery({
    queryKey: ["object-types", workspaceId],
    queryFn: () => objApi.listTypes(workspaceId),
    enabled: !!workspaceId,
  });
  const byId = new Map((types.data ?? []).map((t) => [t.id, t]));

  const page = useQuery({
    queryKey: ["object-explorer", workspaceId, applied, offset],
    queryFn: () =>
      objApi.explore(workspaceId, {
        q: applied.q.trim() || undefined,
        typeIds: applied.typeIds,
        ...(applied.property.trim() && applied.value !== ""
          ? { property: applied.property.trim(), value: applied.value }
          : {}),
        limit: PAGE,
        offset,
      }),
    enabled: !!workspaceId,
  });

  /** Replace the whole question — opening a saved search, clearing, paging. */
  function write(criteria: Criteria, page?: number) {
    url.set({
      q: criteria.q.trim() || undefined,
      type: criteria.typeIds,
      property: criteria.property.trim() || undefined,
      // Written even without a property beside it. The two are only paired
      // when the query runs and when the search is saved; dropping a value
      // typed before its property name would clear the box under the cursor.
      value: criteria.value || undefined,
      // Any change to the question starts at its first page. A page number
      // carried over from the previous question is a link to nothing.
      page: page && page > 1 ? String(page) : undefined,
    });
  }

  /** The text box is the one control that does not apply as you touch it —
   * a request per keystroke is a different design. Everything that reads the
   * criteria goes through here so an unsubmitted word is never silently
   * dropped, least of all by Save. */
  function applyDraft(next: Partial<Criteria> = {}): Criteria {
    const applied = { ...criteria, q: draft, ...next };
    write(applied);
    return applied;
  }

  /** Change one part of it, and *only* that part.
   *
   * Rewriting the whole question from `criteria` would re-send keys taken from
   * the last render, and a write still in flight has not reached that render
   * yet. Typing a property name and then its value did exactly that: the
   * second write re-sent `property: undefined` from the stale snapshot and
   * deleted it, leaving `?value=NO` — a filter the form displayed and the
   * server was never asked for.
   */
  function update(next: Partial<Criteria>) {
    url.set({
      ...(next.q !== undefined ? { q: next.q.trim() || undefined } : {}),
      ...(next.typeIds !== undefined ? { type: next.typeIds } : {}),
      ...(next.property !== undefined
        ? { property: next.property.trim() || undefined }
        : {}),
      ...(next.value !== undefined ? { value: next.value || undefined } : {}),
      page: undefined,
    });
  }

  /** Ticking a type reads the types from the URL as it stands, not as it was
   * rendered — two ticks in quick succession would otherwise each build on the
   * same list and the first would be lost. */
  function toggleType(typeId: string, on: boolean) {
    url.set((current) => {
      const have = current.getAll("type");
      return {
        type: on ? [...have, typeId] : have.filter((id) => id !== typeId),
        page: undefined,
      };
    });
  }

  function open(search: SavedSearch) {
    const loaded = fromSaved(search);
    setDraft(loaded.q);
    write(loaded);
  }

  function clear() {
    setDraft("");
    write(EMPTY);
  }

  const selected = criteria.typeIds;
  const onlyType = selected.length === 1 ? byId.get(selected[0]!) : undefined;
  const missing = selected.filter((id) => types.data && !byId.has(id));

  // Every property name present in the current page, so a cross-type result
  // set still shows values rather than just ids. Union rather than
  // intersection: a column only some rows have is still worth seeing.
  //
  // **Less the hidden ones** (Foundry `object-link-types` p.111: "a hidden
  // property will not appear in user applications"). Filtered here rather than
  // at the API, because hidden is a display hint and not a permission - the
  // value is still returned, and anything that needs it can still ask.
  //
  // Hidden across *any* selected type hides the column: a cross-type result
  // shares one set of columns, so a property one type hides and another does
  // not has no honest single answer, and hiding is the safer of the two.
  const hiddenProperties = new Set(
    (types.data ?? [])
      .filter((t) => selected.length === 0 || selected.includes(t.id))
      .flatMap((t) => t.hidden_properties ?? []),
  );
  const columns = Array.from(
    new Set((page.data?.items ?? []).flatMap((i) => Object.keys(i.properties))),
  ).filter((c) => !hiddenProperties.has(c)).slice(0, 6);

  return (
    <div className="ox">
      <SavedSearches
        workspaceId={workspaceId}
        canEdit={canEdit}
        criteria={applied}
        onOpen={open}
      />

      <div className="ox-main">
        <form
          className="ox-query"
          onSubmit={(e) => {
            e.preventDefault();
            applyDraft();
          }}
        >
          <div className="row-actions">
            <input
              type="search"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Search any property value…"
              style={{ flex: "1 1 280px", minWidth: 0 }}
              aria-label="Search instances"
            />
            <button className="btn" type="submit">Search</button>
            {(!isEmpty(criteria) || draft !== "") && (
              <button type="button" className="btn quiet" onClick={clear}>
                Clear
              </button>
            )}
            {canEdit && (
              <button
                type="button"
                className="btn quiet"
                onClick={() => setSaving(inEffect(applyDraft()))}
              >
                Save this search
              </button>
            )}
            {/* The lighter half of saving (item 0.4): the question is in the
                URL, so sharing one needs no name and no row in a table. */}
            <CopyLinkButton label="Copy link to this search" />
          </div>

          <fieldset className="ox-types">
            <legend>Object types</legend>
            {types.isPending && <span className="slug">Loading types…</span>}
            {types.data?.length === 0 && (
              <span className="slug">No object types in this workspace yet.</span>
            )}
            {/* A workspace-wide surface sees the whole ontology, and a mature
                one is dozens of types — a flat wall of checkboxes stops being
                a filter and becomes something to scan. Selected types stay
                visible whatever is typed here, so narrowing the list can never
                hide part of the question being asked. */}
            {(types.data?.length ?? 0) > TYPE_FILTER_FROM && (
              <input
                type="search"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                placeholder={`Filter ${types.data?.length} types…`}
                aria-label="Filter the object type list"
                style={{ flex: "1 1 100%", marginBottom: 2 }}
              />
            )}
            <div className="ox-type-list">
              {types.data
                ?.filter(
                  (t) =>
                    selected.includes(t.id) ||
                    t.display_name.toLowerCase().includes(typeFilter.trim().toLowerCase()),
                )
                .map((t) => (
                  <label key={t.id} className="ox-type">
                    <input
                      type="checkbox"
                      checked={selected.includes(t.id)}
                      onChange={(e) => toggleType(t.id, e.target.checked)}
                    />
                    <span>{t.display_name}</span>
                  </label>
                ))}
            </div>
            {missing.length > 0 && (
              <p className="ox-note">
                This search also names {missing.length}{" "}
                {missing.length === 1 ? "object type that no longer exists" :
                  "object types that no longer exist"}, so it matches nothing from{" "}
                {missing.length === 1 ? "it" : "them"}. Untick everything and pick again
                to repair it.
              </p>
            )}
          </fieldset>

          <fieldset className="ox-exact">
            <legend>Exact match on one property</legend>
            {onlyType ? (
              <div className="row-actions">
                <input
                  type="text"
                  value={criteria.property}
                  onChange={(e) => update({ property: e.target.value })}
                  placeholder="property"
                  aria-label="Property name"
                  style={{ maxWidth: 200 }}
                />
                <span className="slug">=</span>
                <input
                  type="text"
                  value={criteria.value}
                  onChange={(e) => update({ value: e.target.value })}
                  placeholder="value"
                  aria-label="Property value"
                  style={{ maxWidth: 220 }}
                />
                <span className="slug">on {onlyType.display_name}</span>
              </div>
            ) : (
              <p className="ox-note">
                {criteria.property.trim() !== "" && (
                  <>
                    {/* Kept, not deleted — untick and it comes back. Saying it
                        is not in effect beats a form showing a filter the
                        results do not reflect. */}
                    <strong>
                      {criteria.property.trim()} = {criteria.value} is not being
                      applied.
                    </strong>{" "}
                  </>
                )}
                Pick exactly one object type to filter on a property. A property
                name only means something within a type — <code>status</code> on
                an Order and <code>status</code> on a Shipment are unrelated
                columns that happen to share a name.
              </p>
            )}
          </fieldset>
        </form>

        {page.isPending && <div className="state">Searching…</div>}
        {page.isError && (
          <div className="state error">
            {page.error instanceof ApiError
              ? page.error.message
              : "Couldn't search instances."}
          </div>
        )}
        {page.data && page.data.total === 0 && (
          <div className="state">
            {isEmpty(applied)
              ? "No instances yet — sync a dataset mapping to create some."
              : "Nothing matches that."}
          </div>
        )}
        {page.data && page.data.total > 0 && (
          <>
            <div className="data-grid">
              <table>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Key</th>
                    {columns.map((c) => <th key={c}>{c}</th>)}
                    <th>Updated</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {page.data.items.map((i) => {
                    const type = byId.get(i.object_type_id);
                    return (
                      <tr key={i.id}>
                        <td>
                          {/* The chip is a link because item 4.2 gave every
                              object type an application to open. */}
                          {type ? (
                            <Link className="chip" href={`/r/${type.resource_id}`}>
                              {i.object_type_display_name}
                            </Link>
                          ) : (
                            <span className="chip">{i.object_type_display_name}</span>
                          )}
                        </td>
                        <td className="slug">{i.primary_key}</td>
                        {columns.map((c) => (
                          <td key={c}>
                            {/* `String(value)` here rendered every geopoint as
                                "[object Object]" — see object-value.ts. */}
                            {displayValue(i.properties[c])}
                          </td>
                        ))}
                        <td className="slug">{new Date(i.updated_at).toLocaleString()}</td>
                        <td>
                          <button
                            className="btn quiet"
                            style={{ padding: "3px 9px", fontSize: 12 }}
                            onClick={() =>
                              setExploring({
                                typeId: i.object_type_id,
                                typeName: i.object_type_display_name,
                                instance: i,
                              })
                            }
                          >
                            Explore
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="row-actions" style={{ marginTop: 8 }}>
              <button
                className="btn quiet"
                disabled={offset === 0}
                onClick={() => write(criteria, pageNo - 1)}
              >
                Previous
              </button>
              <span className="slug">
                {offset + 1}–{Math.min(offset + PAGE, page.data.total)} of {page.data.total}
              </span>
              <button
                className="btn quiet"
                disabled={offset + PAGE >= page.data.total}
                onClick={() => write(criteria, pageNo + 1)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </div>

      {exploring && (
        <LinkExplorerDialog
          workspaceSlug={workspaceSlug}
          workspaceId={workspaceId}
          browseHref={(typeId) => {
            const type = byId.get(typeId);
            return type ? `/r/${type.resource_id}` : null;
          }}
          start={exploring}
          onClose={() => setExploring(null)}
        />
      )}

      {saving && (
        <SaveSearchDialog
          workspaceId={workspaceId}
          criteria={saving}
          types={types.data ?? []}
          onClose={() => setSaving(null)}
          // Nothing to select afterwards: the new search matches what is on
          // screen by construction, so the rail marks it without being told.
          onSaved={() => setSaving(null)}
        />
      )}
    </div>
  );
}

// ---- the saved-search rail ---------------------------------------------------
function SavedSearches({
  workspaceId,
  canEdit,
  criteria,
  onOpen,
}: {
  workspaceId: string;
  canEdit: boolean;
  /** What is on screen, so the rail can say which saved search that *is* —
   *  derived, never remembered. See `matches`. */
  criteria: Criteria;
  onOpen: (search: SavedSearch) => void;
}) {
  const queryClient = useQueryClient();
  const searches = useQuery({
    queryKey: ["object-searches", workspaceId],
    queryFn: () => objApi.listSearches(workspaceId),
    enabled: !!workspaceId,
  });

  const remove = useMutation({
    mutationFn: (id: string) => objApi.deleteSearch(workspaceId, id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["object-searches", workspaceId] });
    },
  });

  return (
    <aside className="ox-saved" aria-label="Saved searches">
      <h2>Saved searches</h2>
      {searches.isPending && <p className="slug">Loading…</p>}
      {searches.isError && <p className="slug">Couldn&apos;t load saved searches.</p>}
      {searches.data?.length === 0 && (
        <p className="ox-note">
          {canEdit
            ? "None yet. Search for something, then Save this search — everyone in the workspace sees it."
            : "None yet. An editor can save one, and it appears here for everybody."}
        </p>
      )}
      <ul className="ox-saved-list">
        {searches.data?.map((s) => (
          <li key={s.id} className={matches(s, criteria) ? "on" : undefined}>
            <button type="button" className="ox-saved-open" onClick={() => onOpen(s)}>
              <strong>{s.name}</strong>
              {describe(s) && <span className="slug">{describe(s)}</span>}
              {s.missing_types.length > 0 && (
                <span className="chip warn">
                  {s.missing_types.length} missing{" "}
                  {s.missing_types.length === 1 ? "type" : "types"}
                </span>
              )}
            </button>
            {canEdit && (
              <button
                type="button"
                className="btn quiet danger"
                style={{ padding: "2px 8px", fontSize: 12 }}
                onClick={() => remove.mutate(s.id)}
                disabled={remove.isPending}
                aria-label={`Delete ${s.name}`}
              >
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>
      {remove.isError && (
        <p className="form-error">
          {remove.error instanceof ApiError
            ? remove.error.message
            : "Couldn't delete that search."}
        </p>
      )}
    </aside>
  );
}

// ---- saving ------------------------------------------------------------------
function SaveSearchDialog({
  workspaceId,
  criteria,
  types,
  onClose,
  onSaved,
}: {
  workspaceId: string;
  criteria: Criteria;
  types: ObjectTypeSummary[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const queryClient = useQueryClient();
  const names = new Map(types.map((t) => [t.id, t.display_name]));

  const create = useMutation({
    mutationFn: () =>
      objApi.createSearch(workspaceId, {
        name: name.trim(),
        description,
        definition: toDefinition(criteria),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["object-searches", workspaceId] });
      onSaved();
    },
  });

  return (
    <Dialog open title="Save this search" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Name" hint="Everyone in the workspace will see it under this name">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={200}
            autoFocus
          />
        </Field>
        <Field label="Description" hint="Optional — what question this answers">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={2000}
          />
        </Field>
        {/* What is being saved, spelled out. A saved search is a question
            somebody else will run months from now, and "Save" over a form they
            have stopped looking at is how the wrong one gets kept. */}
        <dl className="ox-summary">
          <dt>Search text</dt>
          <dd>{criteria.q.trim() || <span className="slug">anything</span>}</dd>
          <dt>Object types</dt>
          <dd>
            {criteria.typeIds.length === 0 ? (
              <span className="slug">all types</span>
            ) : (
              criteria.typeIds.map((id) => names.get(id) ?? id).join(", ")
            )}
          </dd>
          {criteria.property.trim() && (
            <>
              <dt>Exact match</dt>
              <dd>
                {criteria.property.trim()} = {criteria.value}
              </dd>
            </>
          )}
        </dl>
        {create.isError && (
          <div className="form-error">
            {create.error instanceof ApiError
              ? create.error.message
              : "Couldn't save that search."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn" disabled={create.isPending || !name.trim()}>
            {create.isPending ? "Saving…" : "Save search"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
