"use client";

/** The Changelog panel (Foundry `workshop` p.193).
 *
 * > "Use the Changelog panel to visualize differences between module versions.
 * > You can select: **Range selection**… **Single selection**: Select a single
 * > version to compare it to the previous version."
 *
 * Both selections are here, and they are one control rather than two modes: a
 * version is chosen, and an optional *from* narrows it. Single selection is the
 * common case and is what a bare click gives you, because "what did this save
 * change" is the question somebody has while looking at a list of saves.
 *
 * **The panel fetches; the diff is a pure function.** `changelog.ts` holds the
 * arithmetic and is tested directly; this is the part that knows which two
 * documents to ask for and what to draw. Version 1 has no predecessor, and
 * saying so is better than diffing it against nothing and reporting the whole
 * module as additions.
 *
 * **Not built, and named rather than implied:** p.193's JSON diff view and its
 * visual hierarchy. This answers *what* changed; showing the exact modification
 * is a second piece of work. The rebasing UI p.193 describes reuses this panel
 * and needs branching, which this build does not have.
 */

import { useQueries } from "@tanstack/react-query";
import { canvas as canvasApi } from "@/lib/api";
import { diffModules, isEmptyChangelog, type Change } from "@/components/canvas/changelog";

const KIND_LABELS: Record<Change["kind"], string> = {
  added: "added",
  deleted: "deleted",
  changed: "changed",
  moved: "moved",
  unused: "no longer used",
};

function Section({ title, changes }: { title: string; changes: Change[] }) {
  if (changes.length === 0) return null;
  return (
    <div className="changelog-section">
      <h4 className="field-label">{title}</h4>
      <ul className="changelog-list">
        {changes.map((change) => (
          <li key={`${change.kind}-${change.id}`} data-change={change.kind}>
            <span className={`chip chip-${change.kind}`}>{KIND_LABELS[change.kind]}</span>{" "}
            {change.label}
            <span className="slug"> {change.id}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ChangelogPanel({
  workspaceId,
  projectId,
  appId,
  from,
  to,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
  /** The start of a range (p.193). Defaults to `to - 1`, which is p.193's
   * single selection: "compare it to the previous version". */
  from?: number | null;
  to: number;
}) {
  const start = from ?? to - 1;

  // Both versions in one hook, so the panel has one pending state rather than
  // two and cannot draw half a diff.
  const results = useQueries({
    queries: [start, to].map((version) => ({
      queryKey: ["canvas-version", appId, version],
      queryFn: () => canvasApi.getVersion(workspaceId, projectId, appId, version),
      enabled: version >= 1,
    })),
  });
  const before = results[0]!;
  const after = results[1]!;

  if (start < 1) {
    return (
      <p className="canvas-widget-empty" data-testid="changelog-empty">
        v{to} is the first version — there is nothing before it to compare against.
      </p>
    );
  }
  if (before.isPending || after.isPending) {
    return <p className="state">Reading both versions…</p>;
  }
  if (before.isError || after.isError) {
    return <p className="state error">Couldn&apos;t read one of these versions.</p>;
  }

  const changelog = diffModules(before.data.definition, after.data.definition);
  return (
    <div className="changelog" data-testid="changelog">
      <p className="sub">
        v{start} → v{to}
      </p>
      {isEmptyChangelog(changelog) ? (
        // Reachable, and worth saying: saving a module with nothing changed is
        // allowed, and so is reverting to a version identical to the current
        // one. Three empty lists would read as a panel that failed to load.
        <p className="canvas-widget-empty" data-testid="changelog-empty">
          Nothing changed between these versions.
        </p>
      ) : (
        <>
          <Section title="Widgets" changes={changelog.widgets} />
          <Section title="Variables" changes={changelog.variables} />
          <Section title="Events" changes={changelog.events} />
        </>
      )}
    </div>
  );
}
