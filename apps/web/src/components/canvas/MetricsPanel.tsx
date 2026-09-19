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
import { useQuery } from "@tanstack/react-query";
import { canvas as canvasApi } from "@/lib/api";
import {
  changeLabel, DEFAULT_PERIOD, emptyReason, PERIODS, previousTotal, rising,
  scopeNote, share, total, usageLabel,
} from "@/lib/workshop-metrics";

export function MetricsPanel({
  workspaceId,
  projectId,
  appId,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
}) {
  const [days, setDays] = useState<number>(DEFAULT_PERIOD);
  const metrics = useQuery({
    queryKey: ["canvas-usage-metrics", appId, days],
    queryFn: () => canvasApi.usageMetrics(workspaceId, projectId, appId, days),
  });

  const rows = metrics.data?.actions ?? [];
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
    </div>
  );
}
