"use client";

/** The Ontology Manager (ROADMAP.md phase 2, item 4.2).
 *
 * An object type opens as its own full-page application rather than as a row
 * that expands inside a settings page. This is the last resource kind that
 * resolved to a summary card telling you where to go instead — the inversion
 * section 0 exists for, applied to the one place it had not been.
 *
 * Almost none of this is new behaviour. Properties, links, versions and
 * instances are services that have existed since `STATUS.md` §31–§35. What is
 * new is that they are in one place, keyed by the resource id, so "look at this
 * object type" is a link.
 *
 * Two things it is careful about, and both are about *reading* rather than
 * editing:
 *
 *   1. **A property's type is shown as declared**, not as inferred from a
 *      value. The instance store keeps properties untyped (`STATUS.md` §87),
 *      so a screen that guessed from data would disagree with the declaration
 *      exactly when they had drifted — which is the moment somebody is looking.
 *   2. **A version is shown as it was**, including properties the type no
 *      longer has. That is what a change history is for.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { ApiError, objects as objectsApi } from "@/lib/api";
import type { ObjectTypeVersion, ResolvedResource } from "@/lib/types";

const TABS = ["objects", "properties", "links", "history"] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  objects: "Objects",
  properties: "Properties",
  links: "Links",
  history: "History",
};

export function ObjectTypeApplication({ resource }: { resource: ResolvedResource }) {
  const router = useRouter();
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(raw ?? "") ? (raw as Tab) : "objects";

  const wid = resource.workspace_id;
  const typeId = resource.kind_id;

  function selectTab(next: Tab) {
    const search = new URLSearchParams(params.toString());
    search.set("tab", next);
    router.replace(`?${search.toString()}`, { scroll: false });
  }

  return (
    <div className="ds-app">
      <nav className="ds-tabs" aria-label="Object type views">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            className={`ds-tab${t === tab ? " on" : ""}`}
            aria-current={t === tab}
            onClick={() => selectTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </nav>

      <div className="ds-panel">
        {tab === "objects" && <ObjectsTab wid={wid} typeId={typeId} />}
        {tab === "properties" && <PropertiesTab wid={wid} typeId={typeId} />}
        {tab === "links" && <LinksTab wid={wid} typeId={typeId} />}
        {tab === "history" && <HistoryTab wid={wid} typeId={typeId} />}
      </div>
    </div>
  );
}

const PAGE = 25;

function ObjectsTab({ wid, typeId }: { wid: string; typeId: string }) {
  const [offset, setOffset] = useState(0);
  const type = useQuery({
    queryKey: ["ot", typeId],
    queryFn: () => objectsApi.getType(wid, typeId),
  });
  const page = useQuery({
    queryKey: ["ot-instances", typeId, offset],
    queryFn: () => objectsApi.listInstances(wid, typeId, PAGE, offset),
  });

  if (type.isPending || page.isPending || !type.data) {
    return <p className="state">Loading objects…</p>;
  }
  if (page.isError) return <p className="state error">{(page.error as Error).message}</p>;
  if (page.data.total === 0) {
    return (
      <p className="state">
        No objects of this type yet. They arrive from a dataset source — see
        Sources on the project&apos;s Objects page.
      </p>
    );
  }

  // The declared property order, so two objects of the same type read the same
  // way. Sorting by whatever the first instance happens to hold would make the
  // columns move as data changes.
  const columns = type.data.properties.map((p) => p.api_name);
  const shown = page.data.items.length;

  return (
    <>
      <p className="soft ds-note">
        {page.data.total.toLocaleString()} object{page.data.total === 1 ? "" : "s"}
        {shown < page.data.total &&
          ` · showing ${offset + 1}–${offset + shown}`}
      </p>
      <div className="ds-scroll">
        <table className="ds-table">
          <thead>
            <tr>
              <th scope="col">Key</th>
              {columns.map((c) => (
                <th key={c} scope="col">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {page.data.items.map((row) => (
              <tr key={row.id}>
                <td>
                  <code>{row.primary_key}</code>
                </td>
                {columns.map((c) => {
                  const value = (row.properties as Record<string, unknown>)[c];
                  return (
                    <td key={c}>
                      {value === null || value === undefined ? (
                        <span className="ds-null">—</span>
                      ) : (
                        String(value)
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="ot-paging">
        <button
          type="button"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE))}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={offset + shown >= page.data.total}
          onClick={() => setOffset(offset + PAGE)}
        >
          Next
        </button>
      </div>
    </>
  );
}

function PropertiesTab({ wid, typeId }: { wid: string; typeId: string }) {
  const type = useQuery({
    queryKey: ["ot", typeId],
    queryFn: () => objectsApi.getType(wid, typeId),
  });
  if (type.isPending) return <p className="state">Loading properties…</p>;
  if (type.isError) return <p className="state error">{(type.error as Error).message}</p>;

  const titleId = type.data.title_property_id;
  return (
    <>
      <p className="soft ds-note">
        What this type declares. Types are shown as <em>declared</em> rather than
        as inferred from stored values — the instance store keeps properties
        untyped, so a screen that guessed would disagree with the declaration
        exactly when they had drifted.
      </p>
      <div className="ds-scroll">
        <table className="ds-table">
          <thead>
            <tr>
              <th scope="col">Property</th>
              <th scope="col">Type</th>
              <th scope="col">Required</th>
              <th scope="col">Role</th>
            </tr>
          </thead>
          <tbody>
            {type.data.properties.map((p) => (
              <tr key={p.id}>
                <td>
                  <code>{p.api_name}</code>
                  {p.display_name !== p.api_name && (
                    <span className="soft"> {p.display_name}</span>
                  )}
                </td>
                <td>{p.data_type}</td>
                <td>{p.required ? "yes" : <span className="soft">no</span>}</td>
                <td>
                  {p.id === titleId ? (
                    <span className="chip">title</span>
                  ) : (
                    <span className="soft">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function LinksTab({ wid, typeId }: { wid: string; typeId: string }) {
  const links = useQuery({
    queryKey: ["ot-links", wid],
    queryFn: () => objectsApi.listLinkTypes(wid),
  });
  if (links.isPending) return <p className="state">Loading links…</p>;
  if (links.isError) return <p className="state error">{(links.error as Error).message}</p>;

  // Both directions: a link this type is the *target* of is as much a fact
  // about it as one it is the source of, and showing only one side makes half
  // the ontology invisible from here.
  const mine = links.data.filter(
    (l) => l.from_object_type_id === typeId || l.to_object_type_id === typeId,
  );
  if (mine.length === 0) {
    return <p className="state">Nothing links to or from this type yet.</p>;
  }

  return (
    <>
      <p className="soft ds-note">
        Every link type this one takes part in, in either direction.
      </p>
      <div className="ds-scroll">
        <table className="ds-table">
          <thead>
            <tr>
              <th scope="col">Link</th>
              <th scope="col">Direction</th>
              <th scope="col">Other type</th>
              <th scope="col">Joined on</th>
              <th scope="col">Cardinality</th>
            </tr>
          </thead>
          <tbody>
            {mine.map((l) => {
              const outgoing = l.from_object_type_id === typeId;
              return (
                <tr key={l.id}>
                  <td>{l.display_name}</td>
                  <td>{outgoing ? "from this type" : "to this type"}</td>
                  <td>{outgoing ? l.to_display_name : l.from_display_name}</td>
                  <td>
                    {l.from_property && l.to_property ? (
                      <>
                        <code>{l.from_property}</code> = <code>{l.to_property}</code>
                      </>
                    ) : (
                      // A valid ontology statement that cannot yet be traversed
                      // (db 0027). Saying so beats an empty cell.
                      <span className="soft">no join mapped — not traversable</span>
                    )}
                  </td>
                  <td>{l.cardinality}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function HistoryTab({ wid, typeId }: { wid: string; typeId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState<number | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const versions = useQuery({
    queryKey: ["ot-versions", typeId],
    queryFn: () => objectsApi.listTypeVersions(wid, typeId),
  });
  const restore = useMutation({
    mutationFn: (versionNumber: number) =>
      objectsApi.restoreTypeVersion(wid, typeId, versionNumber),
    onSuccess: () => {
      setFailure(null);
      queryClient.invalidateQueries({ queryKey: ["ot", typeId] });
      queryClient.invalidateQueries({ queryKey: ["ot-versions", typeId] });
    },
    onError: (e: Error) =>
      setFailure(e instanceof ApiError ? e.message : "That didn't work."),
  });

  if (versions.isPending) return <p className="state">Loading history…</p>;
  if (versions.isError) return <p className="state error">{(versions.error as Error).message}</p>;
  if (versions.data.length === 0) return <p className="state">No versions recorded yet.</p>;

  // Newest first, and the list is non-empty by the guard above.
  const current = versions.data[0]!.version_number;
  return (
    <>
      <p className="soft ds-note">
        Every change to this type&apos;s definition. A version is shown as it was —
        including properties the type no longer has, which is what a change
        history is for.
      </p>
      {failure && <p className="state error">{failure}</p>}
      <ul className="ot-history">
        {versions.data.map((v) => (
          <VersionRow
            key={v.id}
            version={v}
            isCurrent={v.version_number === current}
            expanded={open === v.version_number}
            onToggle={() => setOpen(open === v.version_number ? null : v.version_number)}
            onRestore={() => restore.mutate(v.version_number)}
            busy={restore.isPending}
          />
        ))}
      </ul>
    </>
  );
}

function VersionRow({
  version,
  isCurrent,
  expanded,
  onToggle,
  onRestore,
  busy,
}: {
  version: ObjectTypeVersion;
  isCurrent: boolean;
  expanded: boolean;
  onToggle: () => void;
  onRestore: () => void;
  busy: boolean;
}) {
  return (
    <li className={isCurrent ? "on" : undefined}>
      <div className="ot-version-head">
        <button type="button" className="ot-version-toggle" onClick={onToggle}>
          {expanded ? "▾" : "▸"} v{version.version_number}
        </button>
        <span>{version.display_name}</span>
        {isCurrent && <span className="chip">current</span>}
        {version.restored_from != null && (
          <span className="chip brass">restored from v{version.restored_from}</span>
        )}
        <span className="soft ot-version-when">
          {version.created_by_email ?? "unknown"} ·{" "}
          {new Date(version.created_at).toLocaleString()}
        </span>
        {!isCurrent && (
          <button type="button" className="ot-restore" disabled={busy} onClick={onRestore}>
            Restore
          </button>
        )}
      </div>
      {expanded && (
        <table className="ds-table ot-version-props">
          <thead>
            <tr>
              <th scope="col">Property</th>
              <th scope="col">Type</th>
              <th scope="col">Required</th>
            </tr>
          </thead>
          <tbody>
            {version.properties.map((p, i) => (
              <tr key={`${String(p.api_name)}-${i}`}>
                <td>
                  <code>{String(p.api_name)}</code>
                </td>
                <td>{String(p.data_type)}</td>
                <td>{p.required ? "yes" : <span className="soft">no</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </li>
  );
}
