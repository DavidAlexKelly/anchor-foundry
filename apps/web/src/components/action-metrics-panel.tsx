"use client";

/**
 * p.164's action metrics, on the action type's own page (§323;
 * `action-types` p.164-166).
 *
 * > "Action metrics display the near real-time usage of an action type over
 * > the last 30 days… Success/failure metrics… P95 duration metric… You are
 * > also able to access run history, which provides a complete view of a given
 * > action's executions over the past seven days." (p.164)
 *
 * **Two windows on one screen, and both are labelled.** p.164 gives the counts
 * thirty days and the history seven, which is a difference a reader will
 * otherwise discover by wondering why the numbers disagree with the list. The
 * window is read off each answer rather than written here, so the label cannot
 * drift from what was counted.
 *
 * The wording — the rate, the durations, p.166's category names — is in
 * `lib/action-metrics.ts`; this draws it.
 */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { actions as actionsApi } from "@/lib/api";
import {
  breakdown,
  durationText,
  idleMessage,
  isIdle,
  needsAttention,
  runAuthor,
  runSummary,
  successText,
} from "@/lib/action-metrics";

/**
 * The metrics for **one** of an object type's actions, and the chooser.
 *
 * p.164 is about an action type, and this build has no page per action type —
 * an object type's page is where its actions live. So the section picks one
 * rather than stacking a panel per action: four actions would be four sets of
 * counts under one heading, and the reader would have to check which heading
 * each number belonged to.
 *
 * **Absent entirely when there are no actions**, rather than drawn empty. An
 * object type with no action has no action metrics — an empty panel would be
 * §214's control that looks like it works, inviting somebody to wonder why the
 * numbers never move.
 */
export function ActionMetricsSection({
  workspaceId,
  actionTypes,
}: {
  workspaceId: string;
  actionTypes: readonly { id: string; display_name: string }[];
}) {
  const [chosen, setChosen] = useState(actionTypes[0]?.id ?? "");
  const active = actionTypes.find((a) => a.id === chosen) ?? actionTypes[0];

  // **The slot is always here; what goes in it is not.** An early `return null`
  // leaves nothing for a test to point at, so "no panel is drawn" could only be
  // checked as the absence of the panel's own test id — which a stray heading,
  // a spinner or a placeholder would all satisfy while being visible on the
  // page. A mutant replacing the null with a line of text survived the browser
  // sweep on exactly that. With an empty slot the claim is positive: this
  // region is empty.
  return (
    <div data-testid="action-metrics-slot">
      {active && <ActionMetricsFor active={active} actionTypes={actionTypes}
                                   workspaceId={workspaceId}
                                   onChoose={setChosen} />}
    </div>
  );
}

function ActionMetricsFor({
  active,
  actionTypes,
  workspaceId,
  onChoose,
}: {
  active: { id: string; display_name: string };
  actionTypes: readonly { id: string; display_name: string }[];
  workspaceId: string;
  onChoose: (id: string) => void;
}) {
  return (
    <section data-testid="action-metrics-section" style={{ marginTop: 24 }}>
      {actionTypes.length > 1 && (
        <label className="field" style={{ maxWidth: 320 }}>
          <span>Action</span>
          <select
            data-testid="metrics-action-picker"
            value={active.id}
            onChange={(e) => onChoose(e.target.value)}
          >
            {actionTypes.map((a) => (
              <option key={a.id} value={a.id}>{a.display_name}</option>
            ))}
          </select>
        </label>
      )}
      {/* **Keyed on the action.** Without it React reuses the panel across a
          change of action, and the previous action's numbers stay on screen
          while the new ones load — which is worse than a spinner, because a
          stale number is indistinguishable from a fresh one. */}
      <ActionMetricsPanel
        key={active.id}
        workspaceId={workspaceId}
        actionTypeId={active.id}
      />
    </section>
  );
}

export function ActionMetricsPanel({
  workspaceId,
  actionTypeId,
}: {
  workspaceId: string;
  actionTypeId: string;
}) {
  const metrics = useQuery({
    queryKey: ["action-metrics", actionTypeId],
    queryFn: () => actionsApi.metrics(workspaceId, actionTypeId),
  });
  const history = useQuery({
    queryKey: ["action-history", actionTypeId],
    queryFn: () => actionsApi.history(workspaceId, actionTypeId),
  });

  if (metrics.isPending) return <p className="state">Loading metrics…</p>;
  if (metrics.isError || !metrics.data) {
    // **Said, not hidden.** A panel that vanished on failure would be
    // indistinguishable from "nobody has run this action", and those are
    // opposite answers to the question somebody is asking.
    return (
      <p className="state error" data-testid="metrics-error">
        Couldn&apos;t load metrics for this action.
      </p>
    );
  }

  const data = metrics.data;
  const rows = breakdown(data.failures);

  return (
    <section data-testid="action-metrics" style={{ marginTop: 24 }}>
      <div className="page-head">
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Metrics</h2>
          <p className="sub">Over the last {data.window_days} days.</p>
        </div>
      </div>

      {isIdle(data) ? (
        <p className="login-note" data-testid="metrics-idle">{idleMessage(data)}</p>
      ) : (
        <>
          <dl className="stat-row" data-testid="metrics-figures">
            <div>
              <dt>Success rate</dt>
              <dd data-testid="metrics-success-rate">{successText(data)}</dd>
            </div>
            <div>
              <dt>Succeeded</dt>
              <dd data-testid="metrics-succeeded">{data.succeeded}</dd>
            </div>
            <div>
              <dt>Failed</dt>
              <dd data-testid="metrics-failed">{data.failed}</dd>
            </div>
            <div>
              {/* p.164's own name for it, kept rather than translated to
                  "slowest": P95 is not the slowest run, and calling it that
                  would overstate what the number says. */}
              <dt>P95 duration</dt>
              <dd data-testid="metrics-p95">{durationText(data.p95_seconds)}</dd>
            </div>
          </dl>

          {/* **Drawn only when it is true**, so an indicator that is always
              lit does not become one people stop reading. The rule for when
              it is true is in the lib, where it can be tested. */}
          {needsAttention(data) && (
            <p className="login-note" data-testid="metrics-attention">
              {data.failed} of these runs failed. The breakdown below says why.
            </p>
          )}

          {rows.length > 0 && (
            <table className="table" data-testid="metrics-failures">
              <thead>
                <tr><th>Failure</th><th>Runs</th><th>Share</th></tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.category} data-testid={`metrics-failure-${row.category}`}>
                    <td>
                      {row.label}
                      {row.hint && <div className="slug">{row.hint}</div>}
                    </td>
                    <td className="count">{row.failures}</td>
                    <td className="count">{row.share.toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      <div className="page-head" style={{ marginTop: 24 }}>
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Run history</h2>
          {/* The history's own window, from the history's own answer — p.164
              gives it seven days where the counts get thirty, and a reader
              who thinks both are thirty will read the list as a contradiction
              of the numbers above it. */}
          <p className="sub">The last 7 days.</p>
        </div>
      </div>

      {history.isError ? (
        <p className="state error" data-testid="history-error">
          Couldn&apos;t load this action&apos;s run history.
        </p>
      ) : (history.data ?? []).length === 0 ? (
        <p className="login-note" data-testid="history-empty">
          No runs in the last 7 days.
        </p>
      ) : (
        <table className="table" data-testid="run-history">
          <thead>
            <tr><th>When</th><th>Outcome</th><th>Took</th><th>Submitted by</th></tr>
          </thead>
          <tbody>
            {(history.data ?? []).map((run) => (
              <tr key={run.id} data-testid={`run-${run.id}`}>
                <td>{new Date(run.started_at).toLocaleString()}</td>
                <td data-testid="run-outcome">
                  {runSummary(run)}
                  {/* The engine's or the criterion's own words, under the
                      category rather than instead of it: the summary is what
                      a scan needs and this is what a diagnosis needs. */}
                  {run.error && <div className="slug">{run.error}</div>}
                </td>
                <td className="count">{durationText(run.seconds)}</td>
                {/* A run whose author has left the workspace still happened,
                    and a blank cell would read as a bug in the page rather
                    than a fact about the person (§322's `authorLabel`). The
                    rule is in the lib, where a departed author can be written
                    down rather than arranged for. */}
                <td>{runAuthor(run)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
