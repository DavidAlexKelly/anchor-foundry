"use client";

/**
 * p.142-143's Explore screen (`data-connection`; decision 0015; §269).
 *
 * This replaces the Schema dialog, which showed `discover`'s catalogue and
 * nothing else. p.142's own first sentence is what it was missing: "explore the
 * source and the data it contains to **preview syncs before they bring data
 * into Foundry**".
 *
 * p.143's four panels, in one dialog rather than a four-pane layout: the tree
 * with its free-text search (callout 1), the relationship graph (callout 2,
 * §602), the sample (callout 3), and the way out to a sync (callout 4, and
 * p.145's "begin creating syncs directly from the exploration view").
 *
 * **The graph is only drawn for a source type that reports foreign keys.**
 * p.143: it "is not always available… a graph would not appear for
 * exploration of a table-based REST API model as there are no clear relations
 * between objects." An empty graph for such a source would say its tables are
 * unrelated, which is a claim about the data nobody made; the source type's
 * `reports_relations` decides, and the server is the one that knows.
 *
 * **What is on screen beside the rows is not decoration.** A preview is a
 * capped, unordered, occasionally shortened sample, and a table that says none
 * of that is one somebody will read as the data. `source-explorer.ts` owns
 * every one of those sentences and is where they are tested.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, connections as connApi } from "@/lib/api";
import type { Connection, DiscoveredTable } from "@/lib/types";
import {
  bySchema,
  cell,
  graphLayout,
  isSyncable,
  matchNote,
  referenceLabel,
  relatedNotOnGraph,
  relationLabel,
  relationsBetween,
  sampleCaveat,
  sampleSummary,
  search,
  shortenedNote,
  syncBlockedReason,
  tableKey,
  tableLabel,
} from "@/lib/source-explorer";
import { Dialog } from "@/components/dialog";

export function ExploreDialog({
  workspaceId,
  projectId,
  connection,
  onSync,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  /** p.145's path out: sync the table being looked at, without picking it
   * again from a dropdown. */
  onSync: (table: DiscoveredTable) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<DiscoveredTable | null>(null);
  // p.143's "add tables and views… to the graph": by key, in the order added,
  // so the layout only ever respaces rather than reshuffling.
  const [graphKeys, setGraphKeys] = useState<string[]>([]);

  const discover = useQuery({
    queryKey: ["discover", connection.id],
    queryFn: () => connApi.discover(workspaceId, projectId, connection.id),
    retry: false,
  });
  // The connections page's own query, so this is a cache read there.
  const types = useQuery({
    queryKey: ["source-types", workspaceId, projectId],
    queryFn: () => connApi.sourceTypes(workspaceId, projectId),
  });
  const hasGraph =
    types.data?.find((t) => t.type === connection.source_type)?.reports_relations === true;

  const all = discover.data ?? [];
  const matches = search(all, query);
  const groups = bySchema(matches);
  const graph = graphKeys.flatMap((k) => all.filter((t) => tableKey(t) === k));
  // No de-duplication here: both callers offer only tables not already on
  // the graph (the details panel's button, and `relatedNotOnGraph`).
  const addToGraph = (tables: readonly DiscoveredTable[]) =>
    setGraphKeys((keys) => [...keys, ...tables.map(tableKey)]);

  return (
    <Dialog open wide title={`Explore ${connection.name}`} onClose={onClose}>
      <p className="login-note" style={{ marginTop: 0 }}>
        What is in the source, and a sample of it, before anything is synced.
      </p>

      {discover.isPending && <div className="state">Reading the source schema…</div>}
      {discover.isError && (
        <div className="form-error" data-testid="explore-error">
          {discover.error instanceof ApiError
            ? discover.error.message
            : "Couldn't read the schema."}
        </div>
      )}

      {discover.data && (
        <>
          <input
            type="search"
            data-testid="explore-search"
            className="input"
            placeholder="Find a table, a folder, or a column…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: "100%", marginBottom: 10 }}
          />

          {/* `discover-tree` carries the Schema dialog's styling — the folder
              headings, the column table and the `pk` mark — which would
              otherwise have become dead CSS the moment that dialog went. */}
          <div
            className="discover-tree"
            style={{ display: "flex", gap: 16, alignItems: "flex-start" }}
          >
            <div
              data-testid="explore-tree"
              style={{ flex: "0 0 320px", maxHeight: 420, overflowY: "auto" }}
            >
              {matches.length === 0 ? (
                <div className="state" data-testid="explore-no-matches">
                  Nothing here matches “{query}”.
                </div>
              ) : (
                groups.map(([schema, entries]) => (
                  <div key={schema || "/"}>
                    <div className="schema-name">{schema || "/"}</div>
                    {entries.map((match) => {
                      const t = match.table;
                      const note = matchNote(match);
                      const active = selected !== null && tableKey(selected) === tableKey(t);
                      return (
                        <button
                          key={tableKey(t)}
                          type="button"
                          data-testid={`explore-entry-${t.name}`}
                          className={active ? "btn quiet active" : "btn quiet"}
                          onClick={() => setSelected(t)}
                          style={{
                            display: "block",
                            width: "100%",
                            textAlign: "left",
                            padding: "4px 8px",
                            fontSize: 12,
                          }}
                        >
                          {tableLabel(t)}{" "}
                          <span className="count">
                            ({t.kind}, {t.columns.length})
                          </span>
                          {/* Why this row is in a filtered list, when the
                              reason is not visible in its name. A match
                              somebody cannot explain reads as a bug. */}
                          {note && (
                            <div className="slug" data-testid={`explore-why-${t.name}`}>
                              {note}
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                ))
              )}
            </div>

            <div style={{ flex: 1, minWidth: 0 }}>
              {hasGraph && (
                <RelationGraph
                  tables={graph}
                  all={all}
                  selected={selected}
                  onSelect={setSelected}
                  onAdd={addToGraph}
                  onRemove={(t) => {
                    setGraphKeys((keys) => keys.filter((k) => k !== tableKey(t)));
                  }}
                  onSync={onSync}
                />
              )}
              {selected ? (
                <TableDetails
                  workspaceId={workspaceId}
                  projectId={projectId}
                  connection={connection}
                  table={selected}
                  onSync={onSync}
                  onAddToGraph={
                    hasGraph && !graphKeys.includes(tableKey(selected))
                      ? () => addToGraph([selected])
                      : null
                  }
                />
              ) : (
                <div className="state" data-testid="explore-nothing-selected">
                  Choose a table to see its columns and a sample of its rows.
                </div>
              )}
            </div>
          </div>
        </>
      )}

      <div className="form-actions">
        <button className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}

// Close to the pixels the details column has, so the SVG is drawn at about
// its own size rather than shrunk until the labels cannot be read.
const GRAPH_W = 360;
const GRAPH_H = 200;
const NODE_W = 110;
const NODE_H = 24;
const MENU_W = 200;

/** A table's name cut to fit its node; the full label is the node's title. */
function fit(label: string): string {
  return label.length > 15 ? `${label.slice(0, 14)}…` : label;
}

/** p.143's callout 2: "Explore tables and views and the relationships between
 * them. You can also create a sync from the graph by right-clicking on the
 * table. When selecting a table with a relation, the foreign key will be
 * highlighted within the expandable column list and above the link."
 *
 * **Labels only on the selected table's links.** Every edge labelled at once
 * is unreadable past three tables, and p.143 ties the label to selection. The
 * column list below says the same thing for the holder's side, so nothing is
 * only visible here.
 */
function RelationGraph({
  tables,
  all,
  selected,
  onSelect,
  onAdd,
  onRemove,
  onSync,
}: {
  tables: DiscoveredTable[];
  all: DiscoveredTable[];
  selected: DiscoveredTable | null;
  onSelect: (t: DiscoveredTable) => void;
  onAdd: (tables: readonly DiscoveredTable[]) => void;
  onRemove: (t: DiscoveredTable) => void;
  onSync: (t: DiscoveredTable) => void;
}) {
  const [menu, setMenu] = useState<{ table: DiscoveredTable; x: number; y: number } | null>(
    null,
  );
  if (tables.length === 0) {
    return (
      <p className="field-hint" data-testid="explore-graph-empty">
        Add tables to the graph to see the foreign keys between them.
      </p>
    );
  }
  const layout = graphLayout(tables.length, GRAPH_W, GRAPH_H);
  const at = new Map(tables.map((t, i) => [tableKey(t), layout[i]!]));
  const current = selected ? tableKey(selected) : null;
  const edges = relationsBetween(tables);
  const menuRelated = menu ? relatedNotOnGraph(menu.table, all, tables) : [];
  const menuBlocked = menu ? syncBlockedReason(menu.table) : null;

  return (
    <div className="explore-graph" data-testid="explore-graph" onClick={() => setMenu(null)}>
      <svg
        viewBox={`0 0 ${GRAPH_W} ${GRAPH_H}`}
        width="100%"
        role="img"
        aria-label="Tables on the graph and the foreign keys between them"
      >
        <defs>
          <marker
            id="explore-arrow"
            viewBox="0 0 10 10"
            refX="10"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" className="explore-arrow" />
          </marker>
        </defs>
        {edges.map((r) => {
          const a = at.get(r.from)!;
          const b = at.get(r.to)!;
          const lit = current !== null && (r.from === current || r.to === current);
          const cls = lit ? "explore-edge lit" : "explore-edge";
          if (r.from === r.to) {
            // A key into its own table (a manager_id): a loop over the node.
            return (
              <g key={r.id} data-testid={`explore-edge-${r.constraint}`}>
                <path
                  className={cls}
                  d={`M${a.x - 12},${a.y - NODE_H / 2} C${a.x - 30},${a.y - 48} ${a.x + 30},${a.y - 48} ${a.x + 12},${a.y - NODE_H / 2}`}
                  markerEnd="url(#explore-arrow)"
                />
                {lit && (
                  <text className="explore-edge-label" x={a.x} y={a.y - 46} textAnchor="middle">
                    {relationLabel(r)}
                  </text>
                )}
              </g>
            );
          }
          // From edge of box to edge of box, so the arrow is not under a node.
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const len = Math.hypot(dx, dy) || 1;
          const pad = Math.min(
            Math.abs((NODE_W / 2) * (len / (dx || 1e-9))),
            Math.abs((NODE_H / 2) * (len / (dy || 1e-9))),
          );
          const [x1, y1] = [a.x + (dx / len) * pad, a.y + (dy / len) * pad];
          const [x2, y2] = [b.x - (dx / len) * pad, b.y - (dy / len) * pad];
          return (
            <g key={r.id} data-testid={`explore-edge-${r.constraint}`}>
              <line
                className={cls}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                markerEnd="url(#explore-arrow)"
              />
              {/* p.143: "highlighted… above the link". */}
              {lit && (
                <text
                  className="explore-edge-label"
                  data-testid={`explore-edge-label-${r.constraint}`}
                  x={(x1 + x2) / 2}
                  y={(y1 + y2) / 2 - 6}
                  textAnchor="middle"
                >
                  {relationLabel(r)}
                </text>
              )}
            </g>
          );
        })}
        {tables.map((t) => {
          const p = at.get(tableKey(t))!;
          const active = current === tableKey(t);
          return (
            <g
              key={tableKey(t)}
              className={active ? "explore-node active" : "explore-node"}
              data-testid={`explore-node-${t.name}`}
              transform={`translate(${p.x - NODE_W / 2},${p.y - NODE_H / 2})`}
              onClick={(e) => {
                e.stopPropagation();
                setMenu(null);
                onSelect(t);
              }}
              onContextMenu={(e) => {
                // p.143: "create a sync from the graph by right-clicking on
                // the table".
                e.preventDefault();
                e.stopPropagation();
                const box = (e.currentTarget.ownerSVGElement?.parentElement ??
                  e.currentTarget) as Element;
                const r = box.getBoundingClientRect();
                // Opened leftward near the right edge, so it stays inside the
                // dialog rather than under its border.
                const x = Math.max(0, Math.min(e.clientX - r.left, r.width - MENU_W));
                setMenu({ table: t, x, y: e.clientY - r.top });
              }}
            >
              <title>{tableLabel(t)}</title>
              <rect width={NODE_W} height={NODE_H} rx={5} />
              <text x={NODE_W / 2} y={NODE_H / 2 + 4} textAnchor="middle">
                {fit(t.name)}
              </text>
            </g>
          );
        })}
      </svg>
      {menu && (
        <div
          className="explore-menu"
          role="menu"
          data-testid="explore-node-menu"
          style={{ left: menu.x, top: menu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          {menuBlocked ? (
            <div className="field-hint" data-testid="explore-menu-not-syncable">
              {menuBlocked}
            </div>
          ) : (
            <button
              type="button"
              role="menuitem"
              className="btn quiet"
              data-testid="explore-menu-sync"
              onClick={() => onSync(menu.table)}
            >
              Sync this table
            </button>
          )}
          {menuRelated.length > 0 && (
            <button
              type="button"
              role="menuitem"
              className="btn quiet"
              data-testid="explore-menu-related"
              onClick={() => {
                onAdd(menuRelated);
                setMenu(null);
              }}
            >
              Add related tables ({menuRelated.length})
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            className="btn quiet"
            data-testid="explore-menu-remove"
            onClick={() => {
              onRemove(menu.table);
              setMenu(null);
            }}
          >
            Remove from graph
          </button>
        </div>
      )}
    </div>
  );
}

/** p.143's callout 3, plus the columns the old Schema dialog showed.
 *
 * **The sample is fetched on request rather than on selection.** A preview is
 * a real read of somebody else's system with their credentials, and clicking
 * through a tree of forty tables should not be forty queries against a
 * production database. p.18 makes this the check people press deliberately.
 */
function TableDetails({
  workspaceId,
  projectId,
  connection,
  table,
  onSync,
  onAddToGraph,
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  table: DiscoveredTable;
  onSync: (table: DiscoveredTable) => void;
  /** Null when there is no graph, or the table is already on it. */
  onAddToGraph: (() => void) | null;
}) {
  const blocked = syncBlockedReason(table);
  const [wanted, setWanted] = useState<string | null>(null);
  const key = tableKey(table);

  const preview = useQuery({
    // Keyed by the table, so switching selection does not show the previous
    // table's rows under the new table's name while the request is in flight.
    queryKey: ["preview", connection.id, key],
    queryFn: () =>
      connApi.preview(workspaceId, projectId, connection.id, {
        schema: table.schema_name,
        name: table.name,
      }),
    enabled: wanted === key,
    retry: false,
  });

  return (
    <div>
      <h3 style={{ margin: "0 0 6px" }} data-testid="explore-selected">
        {tableLabel(table)}
      </h3>

      <table className="table" data-testid="explore-columns">
        <tbody>
          {table.columns.map((c) => (
            <tr key={c.name}>
              <td>
                {c.name} {c.is_primary_key && <span className="pk-mark">pk</span>}
                {/* p.143: "the foreign key will be highlighted within the
                    expandable column list". */}
                {c.references && (
                  <span className="fk-mark" data-testid={`explore-fk-${c.name}`}>
                    {" "}
                    {referenceLabel(c.references, table)}
                  </span>
                )}
              </td>
              <td>{c.data_type}</td>
              <td>{c.nullable ? "null ok" : "not null"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="row-actions" style={{ marginTop: 8 }}>
        <button
          type="button"
          className="btn quiet"
          data-testid="explore-preview"
          disabled={preview.isFetching}
          onClick={() => setWanted(key)}
        >
          {preview.isFetching ? "Reading…" : "Preview rows"}
        </button>
        {onAddToGraph && (
          <button
            type="button"
            className="btn quiet"
            data-testid="explore-add-to-graph"
            onClick={onAddToGraph}
          >
            Add to graph
          </button>
        )}
        {/* p.145's "begin creating syncs directly from the exploration view".
            A view is offered nothing rather than a button that would 422 —
            §214: a control that cannot work is worse than an absent one — and
            the sentence stays, because "why not this one" is the question. */}
        {blocked ? (
          <span className="field-hint" data-testid="explore-not-syncable">
            {blocked}
          </span>
        ) : (
          <button
            type="button"
            className="btn quiet"
            data-testid="explore-sync"
            onClick={() => onSync(table)}
          >
            Sync this table
          </button>
        )}
      </div>

      {preview.isError && (
        <div className="form-error" data-testid="explore-preview-error">
          {preview.error instanceof ApiError
            ? preview.error.message
            : "Couldn't read a sample."}
        </div>
      )}

      {/* `preview.data` alone, not `&& wanted === key`: the query is keyed by
          the table, so selecting a different one leaves `data` undefined until
          that table's own sample arrives. The extra clause survived §269's
          harness because the query key already refuses what it was guarding
          against (§213), so it went rather than gaining a test. */}
      {preview.data && (
        <div style={{ marginTop: 10 }}>
          <p className="field-hint" data-testid="explore-sample-summary">
            {sampleSummary(preview.data)}
          </p>
          {sampleCaveat(preview.data) && (
            <p className="field-hint" data-testid="explore-sample-caveat">
              {sampleCaveat(preview.data)}
            </p>
          )}
          {shortenedNote(preview.data) && (
            <p className="field-hint" data-testid="explore-sample-shortened">
              {shortenedNote(preview.data)}
            </p>
          )}
          <div style={{ maxHeight: 260, overflow: "auto" }}>
            <table className="table" data-testid="explore-sample">
              <thead>
                <tr>
                  {preview.data.columns.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.data.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((value, j) => {
                      const shown = cell(value);
                      return (
                        <td key={j} className={shown.isNull ? "count" : undefined}>
                          {shown.text}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
