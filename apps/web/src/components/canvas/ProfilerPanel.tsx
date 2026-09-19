"use client";

/** p.178's Profiler panel: what a module's load cost (§394).
 *
 * > "The profiler will display: The total module load time. The timeline view
 * > as widget and variables load or reload. The breakdown of load time by
 * > widgets and variables." (p.178)
 *
 * Three things, drawn in that order. Every decision about what they *say*
 * lives in `profiler.ts`; this draws the answer.
 *
 * **What this panel is honest about**, because a profiler that overstates is
 * worse than none (p.177's whole purpose is diagnosis): a row is a variable or
 * a *request*, not a widget. Sixteen widget types share one query cache and a
 * key names the request rather than the widget that asked for it, so the
 * column says "Request" and a reader is not invited to believe a number is
 * attributable to a component. `profiler.ts` sets out why.
 */

import {
  breakdown, durationLabel, isSlow, span, summary, timeline, totalMs,
} from "./profiler";
import { useProfiler } from "./ProfilerRecorder";

export function ProfilerPanel({ href }: { href: string }) {
  const { on, events, clear } = useProfiler();
  const total = totalMs(events);

  if (!on) {
    return (
      <div className="canvas-profiler" data-testid="profiler-panel">
        <p className="soft">
          Profiling records what a module loads, from its first request onward.
        </p>
        {/* A link rather than a button, because entering is a *navigation*:
            p.177 refreshes the page so recording starts at initialisation, and
            a button that did the same thing would hide that from the reader
            and from the address bar they could otherwise share. */}
        <a className="btn" data-testid="profiler-enter" href={href}>
          Reload in Profiler Mode
        </a>
      </div>
    );
  }

  return (
    <div className="canvas-profiler" data-testid="profiler-panel">
      <div className="canvas-profiler-bar">
        <strong data-testid="profiler-total">{summary(events)}</strong>
        <button
          type="button"
          className="btn quiet"
          data-testid="profiler-clear"
          onClick={clear}
          disabled={events.length === 0}
        >
          Clear
        </button>
      </div>

      {events.length > 0 && (
        <>
          <p className="field-label">Timeline</p>
          <ul className="canvas-profiler-timeline" data-testid="profiler-timeline">
            {timeline(events).map((event) => {
              const bar = span(event, total);
              return (
                <li key={`${event.kind}:${event.id}`}>
                  <span className="canvas-profiler-name">{event.name}</span>
                  <span className="canvas-profiler-track">
                    <span
                      className={`canvas-profiler-span${isSlow(event) ? " slow" : ""}`}
                      style={{ left: `${bar.left}%`, width: `${bar.width}%` }}
                    />
                  </span>
                  <span className="soft">{durationLabel(event.ms)}</span>
                </li>
              );
            })}
          </ul>

          <p className="field-label">Breakdown</p>
          <table className="canvas-profiler-table" data-testid="profiler-breakdown">
            <thead>
              <tr>
                <th>What</th>
                <th>Kind</th>
                <th>Loads</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {breakdown(events).map((event) => (
                <tr key={`${event.kind}:${event.id}`} className={isSlow(event) ? "warn" : ""}>
                  <td>{event.name}</td>
                  <td className="soft">
                    {event.kind === "variable" ? "Variable" : "Request"}
                  </td>
                  {/* Blank rather than "1": a count is worth reading only when
                      it is not one, and a column of ones is a column of noise
                      over the number that matters. */}
                  <td className="soft">{event.loads > 1 ? event.loads : ""}</td>
                  <td>{durationLabel(event.ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

/** p.177's banner: "A banner will be displayed at the top of the page, letting
 * builders know that they are currently in Profiler mode and that load events
 * are actively being recorded."
 *
 * It says both halves, because they are different reassurances — one explains
 * why the page looks the way it does, the other explains why it is worth
 * waiting. And it carries the way out, which p.177 puts here as well as in the
 * panel: a mode whose exit is only in a panel you may have scrolled away from
 * is a mode people get stuck in. */
export function ProfilerBanner({ href }: { href: string }) {
  return (
    <div className="canvas-profiler-banner" role="status" data-testid="profiler-banner">
      <span>Profiler mode — load events are being recorded.</span>
      <a className="btn quiet" data-testid="profiler-exit" href={href}>
        Exit
      </a>
    </div>
  );
}
