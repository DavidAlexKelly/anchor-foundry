"use client";

/** p.185's Metrics tab: how a module is being used (§396).
 *
 * > "From the Metrics tab in the Workshop editor's left sidebar, you can view
 * > action submission counts and layout view counts to understand which parts
 * > of your module are most active and how usage trends change over time."
 * > (p.185)
 *
 * The action half. Layout view metrics are p.186-188's other half and are not
 * built - they need an opt-in toggle, a recorded view on every navigation and
 * a daily aggregation, which is a unit of its own and is named in
 * `workshop.md` §9 rather than implied by an empty section here.
 *
 * What the numbers mean is `lib/workshop-metrics.ts`'s, including the sentence
 * that keeps the panel honest about what it is counting.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { canvas as canvasApi } from "@/lib/api";
import {
  changeLabel, DEFAULT_PERIOD, emptyReason, layoutName, PERIODS, previousTotal,
  previousViews, rising, scopeNote, share, total, totalViews, usageLabel,
  viewShare, viewsEmptyReason,
} from "@/lib/workshop-metrics";

export function MetricsPanel({
  workspaceId,
  projectId,
  appId,
  /** Page and overlay labels from the document, so the layout list names what
   * a builder named rather than making them match node ids by eye. The panel
   * has the counts; only the editor has the tree. */
  layoutNames = {},
  readOnly = false,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
  layoutNames?: Record<string, string>;
  readOnly?: boolean;
}) {
  const [days, setDays] = useState<number>(DEFAULT_PERIOD);
  const metrics = useQuery({
    queryKey: ["canvas-usage-metrics", appId, days],
    queryFn: () => canvasApi.usageMetrics(workspaceId, projectId, appId, days),
  });

  const client = useQueryClient();
  const rows = metrics.data?.actions ?? [];
  const layouts = metrics.data?.layouts ?? [];
  const tracking = metrics.data?.tracking ?? false;
  const viewsEmpty = viewsEmptyReason(tracking, layouts);
  const viewsNow = totalViews(layouts);
  const viewsBefore = previousViews(layouts);
  const viewsDelta = changeLabel(viewsNow, viewsBefore);

  const setTracking = useMutation({
    mutationFn: (on: boolean) =>
      canvasApi.setUsageTracking(workspaceId, projectId, appId, on),
    // **The saved value, straight into the panel**, and then a refetch for
    // the rest. Waiting on the refetch alone left the section saying "not
    // being recorded" under a ticked box for as long as that read took, and
    // under load in CI that was longer than a reader (or a test) waits.
    onSuccess: (_detail, on) => {
      client.setQueriesData<{ tracking: boolean }>(
        { queryKey: ["canvas-usage-metrics", appId] },
        (old) => (old ? { ...old, tracking: on } : old),
      );
      client.invalidateQueries({ queryKey: ["canvas-usage-metrics", appId] });
    },
  });
  const now = total(rows);
  const before = previousTotal(rows);
  const delta = changeLabel(now, before);
  const up = rising(now, before);
  const empty = emptyReason(rows);

  return (
    <div className="canvas-metrics" data-testid="metrics-panel">
      <label className="field">
        <span className="field-label">Period</span>
        <select
          data-testid="metrics-period"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          {PERIODS.map((p) => (
            <option key={p} value={p}>{`Last ${p} days`}</option>
          ))}
        </select>
      </label>

      {metrics.isPending && <p className="soft">Loading…</p>}
      {metrics.isError && (
        <p className="state error">Couldn&apos;t load this module&apos;s metrics.</p>
      )}

      {metrics.data && empty && <p className="soft" data-testid="metrics-empty">{empty}</p>}

      {metrics.data && !empty && (
        <>
          {/* p.185's overview card: the total across the module, and the
              change against the prior equivalent period. */}
          <div className="canvas-metrics-card" data-testid="metrics-total">
            <strong>{now.toLocaleString()}</strong>
            <span className="soft">
              submission{now === 1 ? "" : "s"}
              {delta === null ? "" : " · "}
            </span>
            {delta !== null && (
              <span
                className={up === null ? "soft" : up ? "good" : "warn"}
                data-testid="metrics-change"
              >
                {delta}
              </span>
            )}
          </div>
          {/* Always, not only when it would change a reading: a caveat that
              appears conditionally is one a reader learns to expect the
              absence of. */}
          <p className="soft" data-testid="metrics-scope">{scopeNote()}</p>

          <ul className="canvas-metrics-rows" data-testid="metrics-rows">
            {rows.map((row) => (
              <li key={row.action_type_id}>
                <span className="canvas-metrics-name">{row.display_name}</span>
                <span className="canvas-metrics-track">
                  <span
                    className="canvas-metrics-bar"
                    style={{ width: `${share(row, rows)}%` }}
                  />
                </span>
                <span>{row.submissions.toLocaleString()}</span>
                {/* p.185: "select an action to view which widgets in the
                    module use that action". Shown rather than behind a click:
                    the answer is one short phrase, and a disclosure that hides
                    a phrase costs more than it saves. */}
                <span className="soft">{usageLabel(row)}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {/* p.186's layout views. Its own section rather than a second table in
          the same list: an action submission and a page view are different
          units, and a single list would invite somebody to compare them. */}
      <p className="field-label">Layout views</p>
      {/* p.187's Usage Metrics Tracking, in the Metrics tab where p.187 puts
          it. Shown whatever the state, because "off" is the explanation for an
          empty section and a toggle that only appeared when there was nothing
          to see would hide the way to turn it back off. */}
      <label className="field-inline">
        <input
          type="checkbox"
          data-testid="metrics-tracking"
          // **The asked-for value while the ask is in flight.** A controlled
          // checkbox bound to the server's answer does not move until a round
          // trip completes, which reads as a control that does not work - the
          // mirror of §214's control that looks like it does. React Query
          // hands back the variable it is sending, so the box moves at once
          // and settles on what the server says.
          checked={setTracking.isPending ? setTracking.variables : tracking}
          disabled={readOnly || setTracking.isPending}
          onChange={(e) => setTracking.mutate(e.target.checked)}
        />
        <span>Record layout views</span>
      </label>
      {/* Said, not swallowed: a save that failed reverts the box, and a box
          that reverts without a word reads as a control that does nothing. */}
      {setTracking.isError && (
        <p className="state error" data-testid="metrics-tracking-error">
          Couldn&apos;t change whether layout views are recorded.
        </p>
      )}

      {metrics.data && viewsEmpty && (
        <p className="soft" data-testid="views-empty">{viewsEmpty}</p>
      )}

      {metrics.data && !viewsEmpty && (
        <>
          <div className="canvas-metrics-card" data-testid="views-total">
            <strong>{viewsNow.toLocaleString()}</strong>
            <span className="soft">
              view{viewsNow === 1 ? "" : "s"}
              {viewsDelta === null ? "" : " · "}
            </span>
            {viewsDelta !== null && <span className="soft">{viewsDelta}</span>}
          </div>
          <ul className="canvas-metrics-rows" data-testid="views-rows">
            {layouts.map((row) => (
              <li key={row.node_id}>
                <span className="canvas-metrics-name">
                  {layoutName(row.node_id, layoutNames)}
                </span>
                <span className="canvas-metrics-track">
                  <span
                    className="canvas-metrics-bar"
                    style={{ width: `${viewShare(row, layouts)}%` }}
                  />
                </span>
                <span>{row.views.toLocaleString()}</span>
                <span className="soft" />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
