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
  canEdit,
}: {
  workspaceId: string;
  canEdit: boolean;
}) {
  const [criteria, setCriteria] = useState<Criteria>(EMPTY);
  const [draft, setDraft] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [openedFrom, setOpenedFrom] = useState<SavedSearch | null>(null);
  const [saving, setSaving] = useState<Criteria | null>(null);
  const [exploring, setExploring] = useState<LinkStop | null>(null);

  const types = useQuery({
    queryKey: ["object-types", workspaceId],
    queryFn: () => objApi.listTypes(workspaceId),
    enabled: !!workspaceId,
  });
  const byId = new Map((types.data ?? []).map((t) => [t.id, t]));

  const page = useQuery({
    queryKey: ["object-explorer", workspaceId, criteria, offset],
    queryFn: () =>
      objApi.explore(workspaceId, {
        q: criteria.q.trim() || undefined,
        typeIds: criteria.typeIds,
        ...(criteria.property.trim() && criteria.value !== ""
          ? { property: criteria.property.trim(), value: criteria.value }
          : {}),
        limit: PAGE,
        offset,
      }),
    enabled: !!workspaceId,
  });

  /** The text box is the one control that does not apply as you touch it —
   * a request per keystroke is a different design. Everything that reads the
   * criteria goes through here so an unsubmitted word is never silently
   * dropped, least of all by Save. */
  function applyDraft(next: Partial<Criteria> = {}): Criteria {
    const applied = { ...criteria, q: draft, ...next };
    setCriteria(applied);
    setOffset(0);
    return applied;
  }

  function update(next: Partial<Criteria>) {
    setCriteria({ ...criteria, ...next });
    setOffset(0);
  }

  function open(search: SavedSearch) {
    const loaded = fromSaved(search);
    setCriteria(loaded);
    setDraft(loaded.q);
    setOffset(0);
    setOpenedFrom(search);
  }

  function clear() {
    setCriteria(EMPTY);
    setDraft("");
    setOffset(0);
    setOpenedFrom(null);
  }

  const selected = criteria.typeIds;
  const onlyType = selected.length === 1 ? byId.get(selected[0]!) : undefined;
  const missing = selected.filter((id) => types.data && !byId.has(id));

  // Every property name present in the current page, so a cross-type result
  // set still shows values rather than just ids. Union rather than
  // intersection: a column only some rows have is still worth seeing.
  const columns = Array.from(
    new Set((page.data?.items ?? []).flatMap((i) => Object.keys(i.properties))),
  ).slice(0, 6);

  return (
    <div className="ox">
      <SavedSearches
        workspaceId={workspaceId}
        canEdit={canEdit}
        openedId={openedFrom?.id ?? null}
        onOpen={open}
        onClosed={() => setOpenedFrom(null)}
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
                onClick={() => setSaving(applyDraft())}
              >
                Save this search
              </button>
            )}
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
                      onChange={(e) =>
                        update({
                          typeIds: e.target.checked
                            ? [...selected, t.id]
                            : selected.filter((id) => id !== t.id),
                        })
                      }
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
            {isEmpty(criteria)
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
                            {i.properties[c] === undefined || i.properties[c] === null
                              ? "∅"
                              : String(i.properties[c])}
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
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                Previous
              </button>
              <span className="slug">
                {offset + 1}–{Math.min(offset + PAGE, page.data.total)} of {page.data.total}
              </span>
              <button
                className="btn quiet"
                disabled={offset + PAGE >= page.data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </div>

      {exploring && (
        <LinkExplorerDialog
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
          onSaved={(search) => {
            setSaving(null);
            setOpenedFrom(search);
          }}
        />
      )}
    </div>
  );
}

// ---- the saved-search rail ---------------------------------------------------
function SavedSearches({
  workspaceId,
  canEdit,
  openedId,
  onOpen,
  onClosed,
}: {
  workspaceId: string;
  canEdit: boolean;
  openedId: string | null;
  onOpen: (search: SavedSearch) => void;
  onClosed: () => void;
}) {
  const queryClient = useQueryClient();
  const searches = useQuery({
    queryKey: ["object-searches", workspaceId],
    queryFn: () => objApi.listSearches(workspaceId),
    enabled: !!workspaceId,
  });

  const remove = useMutation({
    mutationFn: (id: string) => objApi.deleteSearch(workspaceId, id),
    onSuccess: async (_r, id) => {
      if (id === openedId) onClosed();
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
          <li key={s.id} className={s.id === openedId ? "on" : undefined}>
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
  onSaved: (search: SavedSearch) => void;
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
    onSuccess: async (search) => {
      await queryClient.invalidateQueries({ queryKey: ["object-searches", workspaceId] });
      onSaved(search);
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
