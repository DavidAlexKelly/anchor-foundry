"use client";

/**
 * p.142-143's Explore screen (`data-connection`; decision 0015; §269).
 *
 * This replaces the Schema dialog, which showed `discover`'s catalogue and
 * nothing else. p.142's own first sentence is what it was missing: "explore the
 * source and the data it contains to **preview syncs before they bring data
 * into Foundry**".
 *
 * Three of p.143's four panels, in one dialog rather than a three-pane layout:
 * the tree with its free-text search (callout 1), the sample (callout 3), and
 * the way out to a sync (callout 4, and p.145's "begin creating syncs directly
 * from the exploration view"). The relationship graph is callout 2 and is not
 * built — decision 0015 §7, and Foundry says of its own graph that it "is not
 * always available".
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
  isSyncable,
  matchNote,
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

  const discover = useQuery({
    queryKey: ["discover", connection.id],
    queryFn: () => connApi.discover(workspaceId, projectId, connection.id),
    retry: false,
  });

  const matches = search(discover.data ?? [], query);
  const groups = bySchema(matches);

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
              {selected ? (
                <TableDetails
                  workspaceId={workspaceId}
                  projectId={projectId}
                  connection={connection}
                  table={selected}
                  onSync={onSync}
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
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  table: DiscoveredTable;
  onSync: (table: DiscoveredTable) => void;
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
