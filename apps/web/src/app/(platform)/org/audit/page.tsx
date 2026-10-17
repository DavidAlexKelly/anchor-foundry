"use client";

/** The organisation's audit log (§988): every change the platform recorded,
 * newest first, narrowed the way an investigation narrows it. Org admins
 * only, as the API is. */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ApiError, api, downloadFile } from "@/lib/api";
import {
  NO_FILTERS, actorText, auditQuery, exportQuery, filterProblem, nextCursor, originText,
  type AuditFilters,
} from "@/lib/audit-log";
import { Field } from "@/components/dialog";

export default function AuditLogPage() {
  const members = useQuery({ queryKey: ["org-members"], queryFn: () => api.orgMembers() });
  // What is typed, and what was last asked for: a search runs when asked,
  // not on every keystroke of an action prefix.
  const [draft, setDraft] = useState<AuditFilters>(NO_FILTERS);
  const [asked, setAsked] = useState<AuditFilters>(NO_FILTERS);
  const problem = filterProblem(draft);

  const log = useInfiniteQuery({
    queryKey: ["org-audit", asked],
    queryFn: ({ pageParam }) => api.orgAudit(auditQuery(asked, pageParam)),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (page) => nextCursor(page),
  });
  const entries = log.data?.pages.flat() ?? [];
  const [open, setOpen] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportProblem, setExportProblem] = useState("");

  async function exportLog() {
    setExporting(true);
    setExportProblem("");
    try {
      const query = exportQuery(asked);
      await downloadFile(`/api/org/audit.csv${query ? `?${query}` : ""}`, "audit-log.csv");
    } catch (error) {
      setExportProblem(
        error instanceof ApiError && error.status === 422
          ? "More entries match than one export holds - narrow the search to export it."
          : "Couldn't export the log. Try again.",
      );
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">
            <Link href="/org">organisation</Link>
          </p>
          <h1>Audit log</h1>
          <p className="sub">Every change the platform recorded, newest first.</p>
        </div>
      </div>

      <form
        className="row"
        style={{ gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 14 }}
        data-testid="audit-filters"
        onSubmit={(e) => {
          e.preventDefault();
          if (!problem) setAsked(draft);
        }}
      >
        <Field label="Action" hint="A prefix: dataset. is every dataset action">
          <input
            data-testid="audit-action"
            value={draft.action}
            maxLength={200}
            onChange={(e) => setDraft({ ...draft, action: e.target.value })}
          />
        </Field>
        <Field label="Who">
          <select
            data-testid="audit-user"
            value={draft.userId}
            onChange={(e) => setDraft({ ...draft, userId: e.target.value })}
          >
            <option value="">Anyone</option>
            {(members.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>{m.display_name || m.email}</option>
            ))}
          </select>
        </Field>
        <Field label="Resource id">
          <input
            data-testid="audit-resource"
            value={draft.resourceId}
            onChange={(e) => setDraft({ ...draft, resourceId: e.target.value })}
          />
        </Field>
        <Field label="From">
          <input type="date" data-testid="audit-since" value={draft.since}
                 onChange={(e) => setDraft({ ...draft, since: e.target.value })} />
        </Field>
        <Field label="To">
          <input type="date" data-testid="audit-until" value={draft.until}
                 onChange={(e) => setDraft({ ...draft, until: e.target.value })} />
        </Field>
        <div className="form-actions" style={{ margin: 0 }}>
          <button type="submit" className="btn" data-testid="audit-search" disabled={!!problem}>
            Search
          </button>
          <button
            type="button"
            className="btn quiet"
            onClick={() => {
              setDraft(NO_FILTERS);
              setAsked(NO_FILTERS);
            }}
          >
            Clear
          </button>
          {/* §989: what was searched for, as a file - the filters last asked,
              not what is typed and not yet searched. */}
          <button
            type="button"
            className="btn quiet"
            data-testid="audit-export"
            disabled={exporting}
            onClick={() => void exportLog()}
          >
            {exporting ? "Exporting…" : "Download CSV"}
          </button>
        </div>
      </form>
      {problem && <p className="field-hint" data-testid="audit-problem">{problem}</p>}
      {exportProblem && (
        <p className="field-hint" data-testid="audit-export-problem">{exportProblem}</p>
      )}

      {log.isPending && <div className="state">Loading the log…</div>}
      {log.isError && (
        <div className="state error" data-testid="audit-error">
          {log.error instanceof ApiError && log.error.status === 403
            ? "Only an organisation's administrators can read its audit log."
            : "Couldn't load the log. Refresh to try again."}
        </div>
      )}
      {log.data && entries.length === 0 && (
        <div className="state" data-testid="audit-empty">Nothing recorded matches.</div>
      )}
      {entries.length > 0 && (
        <table className="table" data-testid="audit-entries">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>Action</th>
              <th>Resource</th>
              <th>From</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr
                key={entry.id}
                data-testid="audit-entry"
                onClick={() => setOpen(open === entry.id ? null : entry.id)}
                style={{ cursor: "pointer", verticalAlign: "top" }}
              >
                <td title={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</td>
                <td>{actorText(entry)}</td>
                <td>
                  <code>{entry.action}</code>
                  {open === entry.id && Object.keys(entry.metadata).length > 0 && (
                    <pre className="soft" data-testid="audit-metadata" style={{ whiteSpace: "pre-wrap" }}>
                      {JSON.stringify(entry.metadata, null, 2)}
                    </pre>
                  )}
                </td>
                <td className="slug">
                  {entry.resource_type}
                  {entry.resource_id && <div>{entry.resource_id}</div>}
                </td>
                <td className="slug" data-testid="audit-origin">{originText(entry)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {log.hasNextPage && (
        <div className="form-actions">
          <button
            type="button"
            className="btn quiet"
            data-testid="audit-older"
            disabled={log.isFetchingNextPage}
            onClick={() => log.fetchNextPage()}
          >
            {log.isFetchingNextPage ? "Loading…" : "Older"}
          </button>
        </div>
      )}
    </main>
  );
}
