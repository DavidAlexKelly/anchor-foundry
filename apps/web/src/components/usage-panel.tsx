"use client";

/**
 * p.33's usage summary for one object type (§320; `ontology-manager` p.32-34).
 *
 * > "A usage graph on the Overview tab: High-level summary of usage over the
 * > last 30 days, enabling Ontology users to quickly understand the
 * > implications of making a breaking change to this resource." (p.33)
 *
 * **On the type's own page, next to the thing it is about.** p.33 puts this on
 * an Overview tab and offers a second, dedicated Usage tab behind a "See more"
 * link. There is one page per type here rather than a tabbed resource view, so
 * the split would be a navigation step invented to match a layout — the
 * summary and the breakdown are both short, and both are here.
 *
 * The wording is in `lib/usage-metrics.ts`; this draws it.
 */

import { useQuery } from "@tanstack/react-query";
import { objects as objApi } from "@/lib/api";
import {
  applicationLabel,
  applicationSummary,
  emptyMessage,
  hasAudience,
  headline,
  isUnused,
} from "@/lib/usage-metrics";

export function UsagePanel({
  workspaceId,
  typeId,
}: {
  workspaceId: string;
  typeId: string;
}) {
  const usage = useQuery({
    queryKey: ["object-type-usage", typeId],
    queryFn: () => objApi.usage(workspaceId, typeId),
  });
  const applications = useQuery({
    queryKey: ["object-type-usage-apps", typeId],
    queryFn: () => objApi.usageByApplication(workspaceId, typeId),
  });

  if (usage.isPending) return <p className="state">Loading usage…</p>;
  if (usage.isError || !usage.data) {
    // **Said, not hidden.** A panel that vanished on failure would be
    // indistinguishable from p.33's "No usage for the last 30 days" — and
    // those are opposite answers to the question somebody is asking.
    return <p className="state error">Couldn&apos;t load usage for this type.</p>;
  }

  const data = usage.data;
  const rows = applications.data ?? [];

  return (
    <section data-testid="usage-panel" style={{ marginTop: 24 }}>
      <div className="page-head">
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Usage</h2>
          <p className="sub" data-testid="usage-headline">{headline(data)}</p>
        </div>
      </div>

      {isUnused(data) ? (
        <p className="login-note" data-testid="usage-empty">
          {emptyMessage(data)}
        </p>
      ) : (
        <>
          {/* p.32's four numbers. **Active users first**, because it is the
              one that decides whether a breaking change needs a conversation
              — see `headline`'s note on the ordering. */}
          <dl className="stat-row" data-testid="usage-figures">
            <div>
              <dt>Active users</dt>
              <dd data-testid="usage-active-users">{data.active_users}</dd>
            </div>
            <div>
              <dt>Interactions</dt>
              <dd data-testid="usage-interactions">{data.interactions}</dd>
            </div>
            <div>
              <dt>Reads</dt>
              <dd data-testid="usage-reads">{data.reads}</dd>
            </div>
            <div>
              <dt>Writes</dt>
              <dd data-testid="usage-writes">{data.writes}</dd>
            </div>
          </dl>

          {/* **The warning p.33's whole feature exists to produce.** Drawn only
              when more than one person is involved: a type one person uses is
              a change they can make, and a banner on every row would be a
              banner nobody reads. */}
          {hasAudience(data) && (
            <p className="login-note" data-testid="usage-audience">
              {data.active_users} people have used this type in the last{" "}
              {data.window_days} days. A breaking change here reaches all of
              them.
            </p>
          )}

          {rows.length > 0 && (
            <table className="table" data-testid="usage-applications">
              <thead>
                <tr><th>Application</th><th>Usage</th><th>People</th></tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.application} data-testid={`usage-app-${row.application}`}>
                    <td>{applicationLabel(row.application)}</td>
                    <td className="count">{applicationSummary(row)}</td>
                    <td className="count">{row.active_users}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
