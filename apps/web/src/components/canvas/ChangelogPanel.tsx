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
 * **§183 finished p.193's sentence.** "You can inspect JSON diffs to see the
 * exact modifications and review a visual hierarchy to understand how changes
 * relate to nested components": every entry expands to the leaves that
 * differ, and the widget list is drawn as the layout tree rather than flat.
 * The rebasing UI p.193 also describes reuses this panel and needs branching,
 * which this build still does not have.
 */

import { useQueries } from "@tanstack/react-query";
import { canvas as canvasApi } from "@/lib/api";
import {
  changeDetail, changeTree, diffModules, isEmptyChangelog,
  type Change, type ChangeArea, type ChangeNode, type FieldChange,
} from "@/components/canvas/changelog";

const KIND_LABELS: Record<Change["kind"], string> = {
  added: "added",
  deleted: "deleted",
  changed: "changed",
  moved: "moved",
  unused: "no longer used",
};

type Doc = Record<string, unknown> | null | undefined;

/** One value, as JSON and on one line.
 *
 * Compact rather than pretty-printed: these sit inside a list item, and a
 * multi-line block per leaf would push the next change off the panel - which
 * is the readability p.193's "inspect" is asking for, not the completeness. */
function value(entry: unknown): string {
  return entry === undefined ? "—" : JSON.stringify(entry);
}

/** p.193's JSON diff, opened on demand.
 *
 * A `<details>` rather than a toggle of our own: the summary stays keyboard
 * reachable and the whole panel keeps working before any JavaScript of ours
 * runs. Collapsed by default, because the list answers "what changed" and this
 * answers "how", and only one of those is the question somebody arrives with.
 */
function Detail({ fields }: { fields: FieldChange[] }) {
  if (fields.length === 0) return null;
  return (
    <details className="changelog-detail" data-testid="changelog-detail">
      <summary className="slug">
        {fields.length === 1 ? "1 modification" : `${fields.length} modifications`}
      </summary>
      <table className="changelog-fields">
        <tbody>
          {fields.map((field) => (
            <tr key={field.path} data-field={field.path}>
              <th scope="row"><code>{field.path || "(whole)"}</code></th>
              <td className="changelog-before"><code>{value(field.before)}</code></td>
              <td aria-hidden="true">→</td>
              <td className="changelog-after"><code>{value(field.after)}</code></td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function Entry({
  change, before, after, area,
}: {
  change: Change; before: Doc; after: Doc; area: ChangeArea;
}) {
  return (
    <>
      <span className={`chip chip-${change.kind}`}>{KIND_LABELS[change.kind]}</span>{" "}
      {change.label}
      <span className="slug"> {change.id}</span>
      <Detail fields={changeDetail(before, after, change, area)} />
    </>
  );
}

function Section({
  title, changes, before, after, area,
}: {
  title: string; changes: Change[]; before: Doc; after: Doc; area: ChangeArea;
}) {
  if (changes.length === 0) return null;
  return (
    <div className="changelog-section">
      <h4 className="field-label">{title}</h4>
      <ul className="changelog-list">
        {changes.map((change) => (
          <li key={`${change.kind}-${change.id}`} data-change={change.kind}>
            <Entry change={change} before={before} after={after} area={area} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** p.193's visual hierarchy: the widget changes in their nesting.
 *
 * A node with no `kind` is an ancestor carrying a changed descendant - drawn
 * without a chip, because labelling it would claim a change nobody made, and
 * omitting it would lose the "how changes relate to nested components" the
 * page asks for.
 */
function Tree({ nodes, before, after }: { nodes: ChangeNode[]; before: Doc; after: Doc }) {
  return (
    <ul className="changelog-list changelog-tree">
      {nodes.map((node) => (
        <li key={node.id} data-change={node.kind ?? "context"} data-node={node.id}>
          {node.kind ? (
            <Entry
              change={{ id: node.id, label: node.label, kind: node.kind }}
              before={before}
              after={after}
              area="widgets"
            />
          ) : (
            <>
              {node.label}
              <span className="slug"> {node.id}</span>
            </>
          )}
          {node.children.length > 0 && (
            <Tree nodes={node.children} before={before} after={after} />
          )}
        </li>
      ))}
    </ul>
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

  const beforeDoc = before.data.definition as Doc;
  const afterDoc = after.data.definition as Doc;
  const changelog = diffModules(beforeDoc, afterDoc);
  const tree = changeTree(beforeDoc, afterDoc, changelog.widgets);
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
          {/* Widgets are the half that nests, so they get p.193's hierarchy;
              variables and events are flat in the document and drawing them
              as trees would be indentation standing for nothing. */}
          {tree.length > 0 && (
            <div className="changelog-section" data-testid="changelog-hierarchy">
              <h4 className="field-label">Widgets</h4>
              <Tree nodes={tree} before={beforeDoc} after={afterDoc} />
            </div>
          )}
          <Section
            title="Variables" changes={changelog.variables}
            before={beforeDoc} after={afterDoc} area="variables"
          />
          <Section
            title="Events" changes={changelog.events}
            before={beforeDoc} after={afterDoc} area="events"
          />
        </>
      )}
    </div>
  );
}
