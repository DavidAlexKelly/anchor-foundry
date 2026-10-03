"use client";

/** Workshop — the module builder as its own application (parity stage 1a,
 * `docs/parity/workshop.md`).
 *
 * This is a move, not a rewrite. The Craft.js `<Editor>`, the three panels, the
 * palette and the viewer are the same ones that ran at
 * `/[workspace]/[project]/canvas/[appId]`; what changed is where they render.
 * Foundry's rule is that "each resource type opens in a different platform
 * application" (`docs/pal/foundry_getting-started.pdf` p.37), and a builder
 * with three panels of its own competing with a project sidebar for the same
 * screen was the one place we had not applied it.
 *
 * Two things are deliberately different from the page it replaces:
 *
 *   1. **No breadcrumb, no title, no eyebrow.** `ApplicationShell` draws all
 *      three for every application. Keeping the builder's own copies would put
 *      the module's name on screen twice, one of them linking somewhere the
 *      breadcrumb already goes.
 *   2. **Ids come from the resolved resource, not from slugs.** The old page
 *      read `useParams` and resolved workspace and project slugs to ids on
 *      every load. A resolved resource already carries both ids and the app's
 *      own `kind_id`, so the only lookup left is the one that answers "may this
 *      person edit or publish" - which is a role on a cached summary row, not
 *      an identity.
 */

import { Editor, Element, Frame, useEditor } from "@craftjs/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import { heldBy, strandedSummary, type OrphanedKey } from "@/lib/state-impact";
import { ChangelogPanel } from "@/components/canvas/ChangelogPanel";
import { diffModules } from "@/components/canvas/changelog";
import {
  describeConflict, rebase, type MergeChoice, type MergeConflict,
} from "@/components/canvas/module-merge";
import { CheckAccessPanel } from "@/components/canvas/CheckAccessPanel";
import {
  CanvasEnvProvider, CanvasParameterProvider, useCanvasEnv,
} from "@/components/canvas/context";
import type { DerivedColumn } from "@/components/canvas/derived-columns";
import { useSearchParams } from "next/navigation";
import { seedFromQuery } from "@/components/canvas/pure";
import { VariableBridge } from "@/components/canvas/VariableBridge";
import type { WorkshopEventDef } from "@/components/canvas/events";
import {
  EventsPanel,
  TRIGGER_WIDGETS,
  type ActionCandidate,
  type ModuleCandidate,
  type PageCandidate,
  type TriggerCandidate,
} from "@/components/canvas/EventsPanel";
import { LayoutPanel } from "@/components/canvas/LayoutPanel";
import type { Clipping } from "@/components/canvas/clipboard";
import { tabLabels } from "@/components/canvas/tab-selection";
import { CanvasNode, SettingsPanel } from "@/components/canvas/SettingsPanel";
import { VariablesPanel } from "@/components/canvas/VariablesPanel";
import { ProfilerRecorder } from "@/components/canvas/ProfilerRecorder";
import { MetricsPanel } from "@/components/canvas/MetricsPanel";
import { ProfilerBanner, ProfilerPanel } from "@/components/canvas/ProfilerPanel";
import { RedactBanner } from "@/components/canvas/RedactBanner";
import { TranslationPreview } from "@/components/canvas/TranslationPreview";
import { TranslationsPanel } from "@/components/canvas/TranslationsPanel";
import { UsedColoursPanel } from "@/components/canvas/UsedColoursPanel";
import { profilerHref, profilerOn } from "@/components/canvas/profiler";
import { redactHref, redactOn } from "@/components/canvas/redact";
import { CANVAS_RESOLVER, CanvasContainer, PALETTE, PaletteItem } from "@/components/canvas/widgets";
import {
  emptyNote as paletteEmptyNote, grouped, matching,
} from "@/lib/widget-palette";
import { useProjectById, useWorkspaceById } from "@/components/use-workspace";
import {
  ApiError, actions as actionApi, api, canvas as canvasApi, objects as objApi,
} from "@/lib/api";
import {
  autoRefreshOf, derivedPropertiesOf, eventsOf, hasLayout, layoutOf, moduleFrom, pageSelectionOf, routingOf,
  savedColoursOf,
  stateSavingOf,
  translationsOf,
  kioskOf,
  variablesOf,
} from "@/lib/workshop-module";
import {
  settingsOf as autoRefreshSettings, registrable, type AutoRefresh,
} from "@/components/canvas/auto-refresh";
import { useModuleTitle } from "@/components/canvas/module-title";
import type {
  CanvasAppBranch,
  CanvasAppBranchDetail,
  CanvasAppDetail,
  CanvasPublishScope,
  Group,
  ResolvedResource,
  WorkshopEvent,
  WorkshopVariable,
} from "@/lib/types";
import { buttonTypeOf, itemsOf } from "@/components/canvas/button-items";
import { layersOf as timelineLayersOf, overridingLayers } from "@/components/canvas/timeline";
import {
  overridingTypes as overridingReferenceTypes, referenceTypesOf,
} from "@/components/canvas/markdown-references";
import { markdownClickItems } from "@/components/canvas/markdown-annotations";

/** The Versions dialog (Foundry p.191-192).
 *
 * > "The Versions dialog is where builders can view a history of the saved
 * > versions for a module. Each saved version displays a timestamp, editor, and
 * > description if available."
 *
 * §88 made publishing mean something — saving does not move viewers, publishing
 * does. This is the surface around that: which version viewers are on, moving
 * them to a *chosen* one rather than the newest, and getting back to a version
 * that worked.
 *
 * **Revert saves the old document as a new version rather than rewinding**
 * (p.192), so the history in between survives and reverting a revert is another
 * save rather than an archaeology problem.
 */
function VersionsDialog({
  workspaceId,
  projectId,
  app,
  canEdit,
  canProtect,
  onView,
  onReverted,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  app: CanvasAppDetail;
  canEdit: boolean;
  /** Workspace admin: p.617's protection is the check on editors, so it is
   * not theirs to switch off. */
  canProtect: boolean;
  onView: (version: number) => void;
  /** Called after a revert, so the canvas can be remounted against the new
   * document — see the comment on `reloadToken`. */
  onReverted: () => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  // p.193's Changelog panel. Null until somebody asks: a diff is two more
  // fetches, and the dialog's first job is the list of versions.
  const [comparing, setComparing] = useState<{ from: number | null; to: number } | null>(null);

  const versions = useQuery({
    queryKey: ["canvas-versions", app.id],
    queryFn: () => canvasApi.listVersions(workspaceId, projectId, app.id),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["canvas-versions", app.id] });
    await queryClient.invalidateQueries({ queryKey: ["canvas-app", app.id] });
  };
  const fail = (e: Error) => setFailure(e.message);

  const publishVersion = useMutation({
    mutationFn: (n: number) => canvasApi.publishVersion(workspaceId, projectId, app.id, n),
    onSuccess: refresh, onError: fail,
  });
  const revert = useMutation({
    mutationFn: (n: number) => canvasApi.revertToVersion(workspaceId, projectId, app.id, n),
    // The refetch has to land *before* the remount, or the canvas reloads
    // against the definition it already had and the revert looks like it did
    // nothing - which is the bug this callback exists to fix.
    onSuccess: async () => { await refresh(); onReverted(); onClose(); }, onError: fail,
  });
  const describe = useMutation({
    mutationFn: (input: { n: number; description: string }) =>
      canvasApi.describeVersion(workspaceId, projectId, app.id, input.n, input.description),
    onSuccess: async () => { setEditing(null); await refresh(); }, onError: fail,
  });
  const settings = useMutation({
    mutationFn: (next: { auto_publish_on_save?: boolean; prompt_for_description?: boolean }) =>
      canvasApi.setVersionSettings(workspaceId, projectId, app.id, next),
    onSuccess: refresh, onError: fail,
  });
  const protect = useMutation({
    mutationFn: (on: boolean) => canvasApi.setProtection(workspaceId, projectId, app.id, on),
    onSuccess: refresh, onError: fail,
  });

  return (
    <Dialog open title={`Versions of ${app.name}`} onClose={onClose}>
      {failure && <p className="state error">{failure}</p>}
      <table className="rb-table" data-testid="versions-table">
        <thead>
          <tr><th>Version</th><th>Saved</th><th>By</th><th>Description</th><th /></tr>
        </thead>
        <tbody>
          {(versions.data ?? []).map((v) => (
            <tr key={v.id} data-version={v.version_number}>
              <td>
                v{v.version_number}
                {v.version_number === app.published_version && (
                  <span className="pill" data-testid="published-pill"> published</span>
                )}
              </td>
              <td>{new Date(v.created_at).toLocaleString()}</td>
              {/* Null when the account that saved it has since been deleted -
                  the version outlives the account, so it says so rather than
                  showing an empty cell. */}
              <td>{v.created_by_name ?? "(deleted user)"}</td>
              <td>
                {editing === v.version_number ? (
                  <input
                    value={draft}
                    autoFocus
                    data-testid="description-input"
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={() => describe.mutate({ n: v.version_number, description: draft })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") describe.mutate({ n: v.version_number, description: draft });
                      if (e.key === "Escape") setEditing(null);
                    }}
                  />
                ) : (
                  <span
                    className={v.description ? "" : "soft"}
                    onClick={() => {
                      if (!canEdit) return;
                      setEditing(v.version_number);
                      setDraft(v.description);
                    }}
                  >
                    {v.description || (canEdit ? "Add a description" : "—")}
                  </span>
                )}
              </td>
              <td>
                <div className="row-actions">
                  <button
                    type="button" className="btn quiet"
                    onClick={() => { onView(v.version_number); onClose(); }}
                  >
                    View
                  </button>
                  {/* p.193's single selection - "compare it to the previous
                      version". The range form is the same panel with a `from`,
                      and the row's own button is the question people actually
                      have while reading a list of saves. */}
                  <button
                    type="button" className="btn quiet"
                    data-testid={`changes-v${v.version_number}`}
                    onClick={() =>
                      setComparing(
                        comparing?.to === v.version_number && comparing?.from === null
                          ? null
                          : { from: null, to: v.version_number },
                      )
                    }
                  >
                    Changes
                  </button>
                  {canEdit && v.version_number !== app.published_version && (
                    <button
                      type="button" className="btn quiet"
                      data-testid={`publish-v${v.version_number}`}
                      onClick={() => publishVersion.mutate(v.version_number)}
                    >
                      Publish
                    </button>
                  )}
                  {canEdit && v.version_number !== app.current_version && (
                    <button
                      type="button" className="btn quiet"
                      data-testid={`revert-v${v.version_number}`}
                      onClick={() => revert.mutate(v.version_number)}
                    >
                      Revert
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {comparing && (
        <ChangelogPanel
          workspaceId={workspaceId}
          projectId={projectId}
          appId={app.id}
          from={comparing.from}
          to={comparing.to}
        />
      )}

      {canEdit && (
        <>
          <label className="vars-toggle field">
            <input
              type="checkbox"
              checked={app.auto_publish_on_save}
              data-testid="auto-publish"
              onChange={(e) => settings.mutate({ auto_publish_on_save: e.target.checked })}
            />
            Automatically publish when saving
          </label>
          {/* Said plainly, because this undoes the default that makes saving
              safe: with it on, every save is immediately what viewers see. */}
          <p className="login-note" style={{ marginTop: 0 }}>
            With this on, every save is what viewers see straight away.
          </p>
          <label className="vars-toggle field">
            <input
              type="checkbox"
              checked={app.prompt_for_description}
              data-testid="prompt-description"
              onChange={(e) => settings.mutate({ prompt_for_description: e.target.checked })}
            />
            Always prompt for a description when saving
          </label>
        </>
      )}
      {canProtect && (
        <>
          {/* p.617's protected module. Here rather than in Publish because it
              is about how main changes, which is this dialog's subject. */}
          <label className="vars-toggle field">
            <input
              type="checkbox"
              checked={app.protected ?? false}
              data-testid="protect-module"
              onChange={(e) => protect.mutate(e.target.checked)}
            />
            Protect main
          </label>
          <p className="login-note" style={{ marginTop: 0 }}>
            Changes are saved to a branch, proposed, and merged once another editor
            approves them.
          </p>
        </>
      )}
    </Dialog>
  );
}

/** One historic version, read-only, with the banner p.191 requires.
 *
 * > "View this version: View the module at that specific version. When viewing
 * > a non-published version, a warning banner will appear at the top of the
 * > module."
 *
 * The banner is conditional exactly as documented — viewing the *published*
 * version is viewing what everybody else sees, which needs no warning, and a
 * banner that appeared every time would be one people learn to ignore.
 */
function ViewingVersion({
  workspaceId,
  projectId,
  app,
  version,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  app: CanvasAppDetail;
  version: number;
  onClose: () => void;
}) {
  const detail = useQuery({
    queryKey: ["canvas-version", app.id, version],
    queryFn: () => canvasApi.getVersion(workspaceId, projectId, app.id, version),
  });

  const definition = detail.data?.definition;
  const isPublished = version === app.published_version;

  return (
    <div data-testid="version-view" data-version={version}>
      <div className="ws-actions">
        <p className="sub">Viewing v{version} of {app.name}</p>
        <div className="spacer" />
        <button type="button" className="btn quiet" onClick={onClose}>
          Back to editing
        </button>
      </div>
      {!isPublished && (
        <p className="state error" role="status" data-testid="unpublished-banner">
          This is v{version}, which is not the version your viewers see
          {app.published_version ? ` (they are on v${app.published_version})` : " (nothing is published)"}.
          Nothing here can be edited.
        </p>
      )}
      {detail.isPending && <div className="state">Loading that version…</div>}
      {detail.isError && (
        <div className="state error">Couldn&apos;t load v{version}.</div>
      )}
      {definition && (
        <Editor resolver={CANVAS_RESOLVER} enabled={false} onRender={CanvasNode}>
          <CanvasEnvBridge
            workspaceId={workspaceId}
            projectId={projectId}
            appId={app.id}
            variables={variablesOf(definition)}
            events={eventsOf(definition)}
          >
            <Frame data={JSON.stringify(layoutOf(definition))} />
          </CanvasEnvBridge>
        </Editor>
      )}
    </div>
  );
}

function PublishDialog({
  workspaceId,
  projectId,
  app,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  app: CanvasAppDetail;
  onClose: () => void;
}) {
  const [scope, setScope] = useState<CanvasPublishScope>(app.publish_scope);
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const queryClient = useQueryClient();

  const groups = useQuery({ queryKey: ["org-groups"], queryFn: api.orgGroups, enabled: scope === "groups" });
  const shares = useQuery({
    queryKey: ["canvas-shares", app.id],
    queryFn: () => canvasApi.listShares(workspaceId, projectId, app.id),
    enabled: scope === "groups",
  });

  const publish = useMutation({
    mutationFn: () => canvasApi.publish(workspaceId, projectId, app.id, { scope, group_ids: groupIds }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["canvas-app", app.id] });
      onClose();
    },
  });

  const selectedGroupIds = groupIds.length > 0 ? groupIds : (shares.data?.map((s) => s.group_id) ?? []);

  return (
    <Dialog open title={`Publish ${app.name}`} onClose={onClose}>
      <p className="login-note" style={{ marginTop: 0 }}>
        Private apps are visible only to this project. Publishing lists the app under the
        workspace&apos;s Apps page, read-only, for everyone here or for specific groups.
        It shares the layout, not access to the data: every widget still reads as whoever
        is looking. Publishing pins the version they see: saving afterwards does not
        change their view until you publish again.
      </p>
      {app.publish_scope !== "private" && app.published_version !== app.current_version && (
        <p className="login-note">
          They are on v{app.published_version ?? 0}; you are editing v{app.current_version}.
          Publishing again moves them to it.
        </p>
      )}
      <Field label="Visibility">
        <select value={scope} onChange={(e) => setScope(e.target.value as CanvasPublishScope)}>
          <option value="private">Private - this project only</option>
          <option value="workspace">Whole workspace</option>
          <option value="groups">Specific groups</option>
        </select>
      </Field>
      {scope === "groups" && (
        <Field label="Groups" hint="Members of any checked group can open this app">
          <div>
            {groups.data?.map((g: Group) => (
              <label key={g.id} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <input
                  type="checkbox"
                  checked={selectedGroupIds.includes(g.id)}
                  onChange={(e) => {
                    const base = selectedGroupIds;
                    setGroupIds(e.target.checked ? [...base, g.id] : base.filter((id) => id !== g.id));
                  }}
                />
                {g.name}
              </label>
            ))}
            {groups.data && groups.data.length === 0 && (
              <p className="canvas-widget-empty">No groups yet - create one under Organisation settings.</p>
            )}
          </div>
        </Field>
      )}
      {publish.isError && (
        <div className="form-error">
          {publish.error instanceof ApiError ? publish.error.message : "Couldn't update publishing."}
        </div>
      )}
      <div className="form-actions">
        <button type="button" className="btn quiet" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          disabled={publish.isPending || (scope === "groups" && selectedGroupIds.length === 0)}
          onClick={() => publish.mutate()}
        >
          {publish.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </Dialog>
  );
}

/** Which saved document the editor is on: main at a version, or a branch at
 * a save. Compared, never parsed - it is what `ownSave` recognises its own
 * write by (§698). */
function headKey(
  branchName: string | null,
  saved: number | undefined | { id: string; save_count: number; base_version: number },
): string {
  if (branchName === null) return `main:${saved ?? ""}`;
  const b = typeof saved === "object" ? saved : undefined;
  return `${branchName}:${b?.id ?? ""}:${b?.save_count ?? ""}:${b?.base_version ?? ""}`;
}

/** p.618's "Review proposed changes" (§700).
 *
 * > "Within the Changelog tab, reviewers can see the changes made to the
 * > module. Reviewers can then approve or reject the change by selecting the
 * > appropriate Approve or Reject button on the left panel in the Review
 * > proposed changes section." (p.618)
 *
 * The changes are §183's changelog between main and the branch - the same
 * five kinds the Changelog panel uses, because a reviewer reading "moved"
 * here and "changed" there for the same edit would be reading two products.
 * Shown only to somebody who may review (`can_review`), so an author never
 * sees buttons that would refuse them.
 */
function ReviewPanel({
  main,
  branch,
  pending,
  onReview,
}: {
  main: Record<string, unknown>;
  branch: Record<string, unknown>;
  pending: boolean;
  onReview: (approve: boolean) => void;
}) {
  const changes = diffModules(main, branch);
  const rows = [
    ...changes.widgets.map((c) => ({ ...c, section: "Widget" })),
    ...changes.variables.map((c) => ({ ...c, section: "Variable" })),
    ...changes.events.map((c) => ({ ...c, section: "Event" })),
  ];
  return (
    <div className="ws-rebase" data-testid="review-panel">
      <p><strong>Review proposed changes.</strong></p>
      {rows.length === 0 ? (
        <p className="sub">This branch makes no changes to main.</p>
      ) : (
        <ul>
          {rows.map((c) => (
            <li key={`${c.section}:${c.id}`} data-testid="review-change">
              <span>{c.section} <strong>{c.label}</strong></span>
              <span>{c.kind}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="row-actions">
        <button type="button" className="btn" data-testid="approve-branch"
                disabled={pending} onClick={() => onReview(true)}>
          Approve
        </button>
        <button type="button" className="btn quiet" data-testid="reject-branch"
                disabled={pending} onClick={() => onReview(false)}>
          Reject
        </button>
      </div>
    </div>
  );
}

/** The rebase, in progress (§699; p.619-621).
 *
 * > "While resolving conflicts, you can switch the module between three states
 * > to evaluate outcomes in real time: Main … Branch … Modification: Changes
 * > you make after beginning the rebase to reconcile differences." (p.608)
 *
 * Main and Branch are a choice per conflict, and choosing rebuilds the module
 * from the three documents; **Modification is the editor itself** - the
 * canvas under this panel is the merged module, and anything edited there is
 * what Save keeps. Rebuilding discards those edits, which the panel says,
 * because p.621's example resolves a conflict by picking a side *first* and
 * editing after ("first select main, then manually add the Action required
 * column").
 */
function RebasePanel({
  branch,
  mainVersion,
  conflicts,
  choices,
  onChoose,
  onCancel,
}: {
  branch: string;
  mainVersion: number;
  conflicts: MergeConflict[];
  choices: Record<string, MergeChoice>;
  onChoose: (key: string, choice: MergeChoice) => void;
  onCancel: () => void;
}) {
  return (
    <div className="ws-rebase" data-testid="rebase-panel">
      <p>
        <strong>Rebasing {branch} onto main v{mainVersion}.</strong>{" "}
        {conflicts.length === 0
          ? "No conflicts: the branch's changes apply to main as they are."
          : `${conflicts.length} conflict${conflicts.length === 1 ? "" : "s"} - each starts on main's side.`}{" "}
        Save to finish the rebase.
      </p>
      {conflicts.length > 0 && (
        <ul>
          {conflicts.map((c) => {
            const chosen = choices[c.key] ?? "main";
            return (
              <li key={c.key} data-testid="rebase-conflict" data-key={c.key}>
                <span><strong>{c.label}</strong> - {describeConflict(c)}</span>
                <span role="radiogroup" aria-label={`Resolve ${c.label}`}>
                  {(["main", "branch"] as const).map((side) => (
                    <label key={side}>
                      <input
                        type="radio"
                        name={`rebase-${c.key}`}
                        checked={chosen === side}
                        onChange={() => onChoose(c.key, side)}
                      />{" "}
                      {side === "main" ? "Main" : "Branch"}
                    </label>
                  ))}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <p className="sub">
        Modification: edit the module below as usual. Switching a conflict rebuilds the
        module from main and the branch, and discards those edits. Variable values follow
        the saved branch until the rebase is saved.
      </p>
      <button type="button" className="btn quiet" onClick={onCancel}>
        Cancel rebase
      </button>
    </div>
  );
}

/** The builder's own controls, under the shell's header rather than instead of
 * it. What is left after the breadcrumb and title moved up: the version state,
 * which is Workshop's alone and is the one thing an author of a published
 * module has to be able to see, and the three buttons. */
function ActionBar({
  app,
  workspaceId,
  projectId,
  canEdit,
  canPublish,
  variables,
  events,
  routing,
  pageSelection,
  stateSaving,
  translations,
  kiosk,
  autoRefresh,
  derivedProperties,
  savedColours,
  onView,
  onReverted,
  onSaved,
  branch,
  branches,
  onBranch,
  onMerged,
  mainDefinition,
  rebasing,
  onRebase,
  onChoose,
  onRebaseEnd,
}: {
  app: CanvasAppDetail;
  workspaceId: string;
  projectId: string;
  canEdit: boolean;
  canPublish: boolean;
  /** The branch being edited (§698), or null for main. When set, `app`'s
   * definition is the branch's and Save writes to the branch. */
  branch: CanvasAppBranchDetail | null;
  branches: CanvasAppBranch[];
  /** Switch heads: a branch name, or null for main. */
  onBranch: (name: string | null) => void;
  /** Main changed underneath the editor - a merge landed on it. */
  onMerged: () => void;
  /** Main's document, which a reviewer compares the branch against (p.618's
   * "reviewers can see the changes made to the module"). */
  mainDefinition: Record<string, unknown>;
  /** A rebase under way (§699), or null. */
  rebasing: {
    mainVersion: number;
    conflicts: MergeConflict[];
    choices: Record<string, MergeChoice>;
  } | null;
  onRebase: () => Promise<void>;
  onChoose: (key: string, choice: MergeChoice) => void;
  /** The rebase was saved, or abandoned. */
  onRebaseEnd: () => void;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEvent>;
  routing: boolean;
  /** The variable backing page selection (p.81), or "" for none. */
  pageSelection: string;
  stateSaving: NonNullable<import("@/lib/types").WorkshopModule["state_saving"]>;
  /** Auto-refresh (p.576-580). In the save for the same reason as the rest:
   * it registers variables that live in the document, so a save without it
   * would drop the registration a builder just made. */
  autoRefresh: import("@/lib/types").WorkshopModule["auto_refresh"];
  /** Derived properties (p.168-172). In the save for the rest's reason: a
   * column list in the layout names one, so a save without them would drop
   * the declaration the column depends on. */
  derivedProperties: import("@/lib/types").WorkshopModule["derived_properties"];
  /** p.214's Saved colors. In the save for the rest's reason: a widget's
   * background holds a reference into this palette, so a save without it would
   * leave every one of those references naming nothing. */
  savedColours: import("@/lib/types").WorkshopModule["saved_colours"];
  /** Translations (p.207-211). In the save for the same reason as the other
   * two: the tables translate strings that live in the layout, so they have
   * to travel with it or a save would drop every translation a builder
   * entered. */
  translations: NonNullable<import("@/lib/types").WorkshopModule["translations"]>;
  /** p.610's Kiosk Mode toggle (§684), carried in the save like the rest. */
  kiosk: boolean;
  onView: (version: number) => void;
  onReverted: () => void;
  /** The head this Save wrote (`headKey`), told to the builder before the
   * refetch it triggers lands - see `ownSave` there. */
  onSaved: (head: string) => void;
}) {
  const { enabled, actions, query } = useEditor((state) => ({ enabled: state.options.enabled }));
  const [showPublish, setShowPublish] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // p.203's warning (§740): the save waiting on it, and what it would strand.
  const [stranded, setStranded] = useState<{ description: string; keys: OrphanedKey[] } | null>(null);
  const queryClient = useQueryClient();

  // The document as the editor holds it. One function because three things
  // write it - a save to main, a save to a branch, and Save to new branch -
  // and a copy that left a part out would silently discard it on that path.
  const currentDocument = () =>
    moduleFrom(app.definition, {
      layout: query.getSerializedNodes(),
      variables,
      events,
      routing: { enabled: routing },
      pageSelection,
      stateSaving,
      translations,
      kiosk: { enabled: kiosk },
      autoRefresh,
      derivedProperties,
      savedColours,
    });

  const save = useMutation({
    // All three parts in one save. The layout comes from Craft.js, the
    // variables and events from their panels, and a save carrying only some of
    // them would silently discard the rest.
    //
    // **On a branch, to the branch** (§698): main's document, version and
    // viewers are what a branch exists to leave alone. A branch has no
    // version descriptions - its record is the merge's description on main.
    mutationFn: async (description: string) => {
      if (branch) {
        // p.621's "save the module to finish rebasing": the merged document,
        // and the main version it was merged against as the branch's new base.
        const saved = await canvasApi.saveBranch(
          workspaceId, projectId, app.id, branch.name, currentDocument(),
          rebasing?.mainVersion,
        );
        // With no rebase token: a save on a branch ends any rebase under way,
        // so the head it lands on is the branch with none open.
        return `${headKey(saved.name, saved)}:`;
      }
      const saved = await canvasApi.saveDefinition(
        workspaceId, projectId, app.id, currentDocument(), description,
      );
      return headKey(null, saved.current_version);
    },
    onSuccess: async (saved) => {
      setFailure(null);
      onSaved(saved);
      await queryClient.invalidateQueries({ queryKey: ["canvas-app", app.id] });
      await queryClient.invalidateQueries({ queryKey: ["canvas-app-branch", app.id] });
      await queryClient.invalidateQueries({ queryKey: ["canvas-app-branches", app.id] });
      // After the refetch, not before: ending the rebase remounts the editor,
      // and remounting on the branch's previous document would show the rebase
      // as undone.
      if (rebasing) onRebaseEnd();
    },
    // The server refuses a cycle or a binding to a variable that is not
    // declared. Surfaced here rather than swallowed: the save did not happen,
    // and a Save button that goes quiet is a Save button people trust wrongly.
    onError: (e: Error) => setFailure(e.message),
  });

  // p.203: "modifying a variable's external ID after state saving has been
  // configured may cause previously configured states to reload
  // unsuccessfully". Asked before a save to main, which is what the states
  // are opened against; a branch's save changes nothing they read. A failed
  // question saves anyway - the warning is a courtesy, and a save blocked by
  // it would be a save lost to it.
  const beginSave = async (description: string) => {
    if (!branch) {
      const keys = await canvasApi
        .stateImpact(workspaceId, projectId, app.id, currentDocument())
        .catch(() => []);
      if (keys.length > 0) {
        setStranded({ description, keys });
        return;
      }
    }
    save.mutate(description);
  };

  // p.617-618's **Save to new branch**: "Name the branch", and the document
  // the builder holds is what the branch starts as - so edits made on main
  // before deciding they belonged on a branch go with it.
  const toBranch = useMutation({
    mutationFn: (name: string) =>
      canvasApi.createBranch(workspaceId, projectId, app.id, name, currentDocument()),
    onSuccess: async (made) => {
      setFailure(null);
      await queryClient.invalidateQueries({ queryKey: ["canvas-app-branches", app.id] });
      onBranch(made.name);
    },
    onError: (e: Error) => setFailure(e.message),
  });

  // Merge into main. The server refuses (409) while main has moved past the
  // branch's base; the button says so before anybody presses it.
  const merge = useMutation({
    mutationFn: (name: string) => canvasApi.mergeBranch(workspaceId, projectId, app.id, name),
    onSuccess: async () => {
      setFailure(null);
      await queryClient.invalidateQueries({ queryKey: ["canvas-app", app.id] });
      await queryClient.invalidateQueries({ queryKey: ["canvas-app-branches", app.id] });
      onBranch(null);
      onMerged();
    },
    onError: (e: Error) => setFailure(e.message),
  });

  // p.618's proposal and its review (§700).
  const refreshBranch = async () => {
    setFailure(null);
    await queryClient.invalidateQueries({ queryKey: ["canvas-app-branch", app.id] });
    await queryClient.invalidateQueries({ queryKey: ["canvas-app-branches", app.id] });
  };
  const propose = useMutation({
    mutationFn: (name: string) => canvasApi.proposeBranch(workspaceId, projectId, app.id, name),
    onSuccess: refreshBranch,
    onError: (e: Error) => setFailure(e.message),
  });
  const review = useMutation({
    mutationFn: (input: { name: string; approve: boolean }) =>
      canvasApi.reviewBranch(workspaceId, projectId, app.id, input.name, input.approve),
    onSuccess: refreshBranch,
    onError: (e: Error) => setFailure(e.message),
  });
  // p.618's merge requirement, said on the button before anybody presses it.
  const awaitingApproval = !!app.protected && !!branch && branch.proposal_status !== "approved";

  const dropBranch = useMutation({
    mutationFn: (name: string) => canvasApi.deleteBranch(workspaceId, projectId, app.id, name),
    onSuccess: async () => {
      setFailure(null);
      await queryClient.invalidateQueries({ queryKey: ["canvas-app-branches", app.id] });
      onBranch(null);
    },
    onError: (e: Error) => setFailure(e.message),
  });

  return (
    <div className="ws-actions">
      {/* The branch selector (§698; p.617 "use the branch selector to switch to
          that branch"). Switching heads remounts the editor on the other
          document, so it is beside Save rather than inside a dialog. */}
      <select
        aria-label="Branch"
        data-testid="branch-select"
        value={branch?.name ?? ""}
        onChange={(e) => onBranch(e.target.value || null)}
      >
        <option value="">main</option>
        {branches.map((b) => (
          <option key={b.id} value={b.name}>{b.name}</option>
        ))}
      </select>
      <p className="sub">
        {branch && (
          <span data-testid="branch-status">
            branch {branch.name} · from v{branch.base_version}
            {/* p.193's "if main has changed since your last save", said where
                the person who has to rebase will see it. */}
            {branch.needs_rebase && ` · main is at v${app.current_version}, rebase required`}
            {" · "}
          </span>
        )}
        {branch?.proposal_status && (
          <span data-testid="proposal-status">
            {branch.proposal_status === "open"
              ? "proposal open"
              : `proposal ${branch.proposal_status}${branch.reviewed_by_name ? ` by ${branch.reviewed_by_name}` : ""}`}
            {" · "}
          </span>
        )}
        {!branch && app.protected && (
          <span data-testid="protected-status">protected · </span>
        )}
        v{app.current_version}
        {app.publish_scope !== "private" && ` · published (${app.publish_scope})`}
        {/* The one thing an author of a published app has to be able to see:
            whether what they are looking at is what everyone else is. Saving
            no longer moves viewers (§88), which is only an improvement if the
            difference is visible. */}
        {app.publish_scope !== "private" &&
          app.published_version !== app.current_version &&
          ` · viewers see v${app.published_version ?? 0}`}
        {save.isSuccess && !failure && " · saved"}
      </p>
      {failure && <p className="state error">{failure}</p>}
      <div className="spacer" />
      <div className="row-actions">
        <button
          type="button"
          className="btn quiet"
          onClick={() => actions.setOptions((o) => (o.enabled = !enabled))}
        >
          {enabled ? "Preview" : "Back to editing"}
        </button>
        {/* p.617: "protected Workshop modules show a Save to new branch option
            instead of Save" - on main, that is the only way to save. */}
        {canEdit && enabled && (branch || !app.protected) && (
          <button
            type="button"
            className="btn"
            disabled={save.isPending}
            onClick={() => {
              // p.192's "Always prompt to add a version description when
              // saving". A prompt, never a requirement - the server accepts an
              // empty description whatever this setting says, because a save
              // refused for want of a sentence is a save somebody loses.
              if (app.prompt_for_description) {
                const said = window.prompt("What changed in this version?", "");
                if (said === null) return;  // cancelled the prompt, not the save
                void beginSave(said);
                return;
              }
              void beginSave("");
            }}
          >
            {save.isPending ? "Saving…" : branch ? "Save to branch" : "Save"}
          </button>
        )}
        {canEdit && enabled && !branch && (
          <button
            type="button"
            className={app.protected ? "btn" : "btn quiet"}
            disabled={toBranch.isPending}
            onClick={() => {
              const name = window.prompt("Name the branch", "");
              if (name === null || !name.trim()) return;
              toBranch.mutate(name.trim());
            }}
          >
            Save to new branch
          </button>
        )}
        {canEdit && branch && (
          <button
            type="button"
            className="btn quiet"
            data-testid="merge-branch"
            disabled={merge.isPending || branch.needs_rebase || awaitingApproval}
            title={
              branch.needs_rebase
                ? `Main has changed since this branch was taken from v${branch.base_version}. Rebase it first.`
                : awaitingApproval
                  ? "This module is protected: the branch merges once its proposal is approved."
                  : "Make this branch the next version of main"
            }
            onClick={() => merge.mutate(branch.name)}
          >
            Merge into main
          </button>
        )}
        {canEdit && branch && branch.proposal_status !== "open"
          && branch.proposal_status !== "approved" && (
          <button
            type="button"
            className="btn quiet"
            data-testid="propose-branch"
            disabled={propose.isPending}
            onClick={() => propose.mutate(branch.name)}
          >
            Propose
          </button>
        )}
        {canEdit && enabled && branch?.needs_rebase && !rebasing && (
          <button
            type="button"
            className="btn"
            data-testid="begin-rebase"
            onClick={() => {
              // p.619's "Save before rebasing": "any in-progress edits that
              // have not been saved will be lost".
              if (!window.confirm(
                "Unsaved edits on this branch are not kept through a rebase. Start the rebase?",
              )) return;
              onRebase().catch((e: Error) => setFailure(e.message));
            }}
          >
            Rebase onto main
          </button>
        )}
        {canEdit && branch && (
          <button
            type="button"
            className="btn quiet"
            disabled={dropBranch.isPending}
            onClick={() => {
              if (!window.confirm(`Delete branch ${branch.name}? Its changes are not on main.`)) return;
              dropBranch.mutate(branch.name);
            }}
          >
            Delete branch
          </button>
        )}
        <button type="button" className="btn quiet" onClick={() => setShowVersions(true)}>
          Versions
        </button>
        {canPublish && (
          <button type="button" className="btn quiet" onClick={() => setShowPublish(true)}>
            Publish
          </button>
        )}
      </div>
      {branch && branch.can_review && !rebasing && (
        <ReviewPanel
          main={mainDefinition}
          branch={branch.definition}
          pending={review.isPending}
          onReview={(approve) => review.mutate({ name: branch.name, approve })}
        />
      )}
      {branch && rebasing && (
        <RebasePanel
          branch={branch.name}
          mainVersion={rebasing.mainVersion}
          conflicts={rebasing.conflicts}
          choices={rebasing.choices}
          onChoose={onChoose}
          onCancel={onRebaseEnd}
        />
      )}
      {showVersions && (
        <VersionsDialog
          workspaceId={workspaceId}
          projectId={projectId}
          app={app}
          canEdit={canEdit}
          canProtect={canPublish}
          onView={onView}
          onReverted={onReverted}
          onClose={() => setShowVersions(false)}
        />
      )}
      {showPublish && (
        <PublishDialog workspaceId={workspaceId} projectId={projectId} app={app} onClose={() => setShowPublish(false)} />
      )}
      {stranded && (
        <Dialog open title="Saved states will not fully reopen" onClose={() => setStranded(null)}>
          <div data-testid="state-impact">
            <p>{strandedSummary(stranded.keys)}</p>
            <ul>
              {stranded.keys.map((k) => (
                <li key={k.external_id} data-testid="state-impact-key">
                  <code>{k.external_id}</code> — held by {heldBy(k.states)}
                </li>
              ))}
            </ul>
            <p className="field-hint">
              A saved state keeps values by external ID, so one this module no
              longer saves is left out when the state is opened (p.203). Keep the
              external ID on whichever variable replaces it and the states carry on.
            </p>
            <div className="form-actions">
              <button type="button" className="btn quiet" data-testid="state-impact-cancel"
                onClick={() => setStranded(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn"
                data-testid="state-impact-save"
                onClick={() => {
                  const description = stranded.description;
                  setStranded(null);
                  save.mutate(description);
                }}
              >
                Save anyway
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function CanvasEnvBridge({
  workspaceId,
  projectId,
  appId,
  variables,
  events,
  seed,
  routing = false,
  autoRefresh,
  derivedProperties,
  savedColours,
  layout,
  pageSelection,
  stateSaving,
  branch,
  children,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEventDef>;
  seed?: Record<string, unknown>;
  /** Whether this module writes its state to the URL (p.195). */
  routing?: boolean;
  /** The module's auto-refresh setting (p.576-580), passed to the
   * variable bridge because what it watches is what the variables
   * resolve to. */
  autoRefresh?: unknown;
  /** The module's derived properties (p.168-172), passed to the canvas
   * env because p.168 declares them at the module level — a widget
   * names one in its column list rather than carrying the
   * declaration. */
  derivedProperties?: unknown;
  /** p.214's Saved colors, as stored. Passed to `CanvasEnv` rather than to
   * each widget for p.214's own reason: the palette is module-level, and a
   * copy on every node is the copying that "the change propagates" abolishes. */
  savedColours?: unknown;
  /** The **saved** layout, which is what routing reads page IDs and per-page
   * bindings from. An unsaved page ID therefore does not appear in the URL
   * until it is saved — the same rule the Variables panel follows for usage
   * counts, and for the same reason: a link is a thing you hand to somebody
   * else, and it should describe the module they will open. */
  layout?: unknown;
  /** The variable backing Variable-Based Page Selection (p.81), or "" for
   * none. Preview only, for routing's reason: in Edit every page is on screen
   * at once, so a variable choosing one would hide the rest from the author
   * arranging them. */
  pageSelection?: string;
  /** State-saving settings (p.201). Offered in Preview only, for the reason
   * routing is: p.200 calls this a feature for module *consumers*, and an
   * author arranging widgets has no reading state worth naming. */
  stateSaving?: import("@/lib/types").WorkshopModule["state_saving"];
  /** The branch being edited (§698), so variables resolve its document. */
  branch?: string;
  children: React.ReactNode;
}) {
  const { enabled, actions } = useEditor((state) => ({ enabled: state.options.enabled }));
  const search = useSearchParams();
  const profiling = profilerOn(search.toString());
  // **Profiler mode is Preview, and that is p.178 rather than a convenience.**
  // "Only widgets and variables that affect the on-screen display are
  // calculated… This mirrors the behavior and performance that users
  // experience in View mode." In edit mode every page of this module is on
  // screen at once and the lazy rule is off, so a profile taken there would be
  // an accurate measurement of a program no reader runs - the exact objection
  // that kept this feature unbuilt until §392.
  useEffect(() => {
    if (profiling && enabled) actions.setOptions((o) => (o.enabled = false));
  }, [profiling, enabled, actions]);
  return (
    <ProfilerRecorder on={profiling}>
    <CanvasEnvProvider value={{
      workspaceId, projectId, mode: enabled ? "edit" : "run",
      derivedColumns: derivedProperties,
      savedColours,
    }}>
      {/* Parameter state lives inside the env provider and outside the editor
          tree, so a filter set in Preview survives switching back to Edit -
          the alternative resets every filter each time the mode flips, which
          makes a filter impossible to actually try out. */}
      <CanvasParameterProvider seed={seed}>
        {/* Resolves what the viewer has selected into what each variable is
            worth. The builder passes its *working* variables, not the saved
            ones, so a set configured a moment ago drives the table without a
            save first - which is the difference between building an app and
            guessing at one. */}
        <VariableBridge
          workspaceId={workspaceId}
          projectId={projectId}
          appId={appId}
          declared={variables}
          events={events}
          // Preview is run mode inside the builder, and is where a routed
          // module should behave like one. Edit mode is not: every page is on
          // screen at once, so "the current page" has no answer.
          routing={routing && !enabled}
          autoRefresh={autoRefresh}
          layout={layout}
          // p.75's lazy rule, and Preview only for the third time on this
          // element: in edit mode every page is on screen at once, so a walk
          // answering "what is visible" would name one page and blank the
          // widgets on all the others while an author was arranging them.
          lazy={!enabled}
          branch={branch}
          // The builder resolves what it is editing, not what was last saved.
          working
          // Preview only, by the same argument as routing one line up: in
          // edit mode every page is on screen, so a variable choosing one
          // would hide the others from the author arranging them.
          pageSelection={enabled ? undefined : pageSelection || undefined}
          stateSaving={enabled ? undefined : stateSaving}
        >
          {children}
        </VariableBridge>
      </CanvasParameterProvider>
    </CanvasEnvProvider>
    </ProfilerRecorder>
  );
}

/** The left column: what the module is made of, then what can be added to it.
 *
 * Stacked rather than tabbed, unlike the right-hand column. The two panels on
 * the right answer different questions about different things (this widget /
 * this module) and one is usually irrelevant; these two are both about the
 * document in front of you, and an author dropping a widget wants to see
 * where it landed. Hiding either behind a tab would trade a scroll for a
 * click on every single edit. */
function Toolbox({
  routing,
  onRoutingChange,
  pageSelection,
  onPageSelectionChange,
  stringVariables,
  clipboard,
  onClipboardChange,
  variables,
  onVariablesChange,
  events,
  onEventsChange,
  stateSaving,
  onStateSavingChange,
  autoRefresh,
  onAutoRefreshChange,
  translations,
  kiosk,
  onKioskChange,
  onTranslationsChange,
  derivedProperties,
  onDerivedPropertiesChange,
  savedColours,
  onSavedColoursChange,
}: {
  routing: boolean;
  onRoutingChange: (next: boolean) => void;
  /** p.214's Saved colors, for the Used colors panel below. */
  savedColours: NonNullable<import("@/lib/types").WorkshopModule["saved_colours"]>;
  onSavedColoursChange: (
    next: NonNullable<import("@/lib/types").WorkshopModule["saved_colours"]>,
  ) => void;
  derivedProperties: Record<string, DerivedColumn[]>;
  onDerivedPropertiesChange: (next: Record<string, DerivedColumn[]>) => void;
  pageSelection: string;
  onPageSelectionChange: (next: string) => void;
  stringVariables: { id: string; label: string }[];
  clipboard: Clipping | null;
  onClipboardChange: (next: Clipping | null) => void;
  variables: Record<string, WorkshopVariable>;
  onVariablesChange: (next: Record<string, WorkshopVariable>) => void;
  events: Record<string, WorkshopEvent>;
  onEventsChange: (next: Record<string, WorkshopEvent>) => void;
  stateSaving: NonNullable<import("@/lib/types").WorkshopModule["state_saving"]>;
  autoRefresh: AutoRefresh;
  onAutoRefreshChange: (next: AutoRefresh) => void;
  onStateSavingChange: (
    next: NonNullable<import("@/lib/types").WorkshopModule["state_saving"]>,
  ) => void;
  translations: NonNullable<import("@/lib/types").WorkshopModule["translations"]>;
  onTranslationsChange: (next: NonNullable<import("@/lib/types").WorkshopModule["translations"]>) => void;
  kiosk: boolean;
  onKioskChange: (next: boolean) => void;
}) {
  // p.168 declares a derived property *per object type*, so the panel needs
  // the types this module actually reads and each one's properties — an
  // expression is checked against them. The object set variables are where a
  // module says which types it reads, so they are the source.
  const { workspaceId } = useCanvasEnv();
  const derivableTypeIds = useMemo(() => {
    const out = new Set<string>();
    for (const v of Object.values(variables)) {
      const set = (v as { object_set?: { object_type_id?: unknown } }).object_set;
      const id = set?.object_type_id;
      if (typeof id === "string" && id) out.add(id);
    }
    return [...out].sort();
  }, [variables]);
  const derivableQuery = useQuery({
    queryKey: ["canvas-derivable-types", workspaceId, derivableTypeIds.join(",")],
    queryFn: () => Promise.all(
      derivableTypeIds.map((id) => objApi.getType(workspaceId, id)),
    ),
    enabled: derivableTypeIds.length > 0,
  });
  const derivableTypes = (derivableQuery.data ?? []).map((type) => ({
    id: String(type.id),
    label: type.display_name || type.api_name,
    properties: (type.properties ?? []).map((prop) => ({
      api_name: prop.api_name, data_type: prop.data_type,
    })),
  }));
  return (
    <div className="canvas-toolbox">
      <LayoutPanel
        routing={routing}
        onRoutingChange={onRoutingChange}
        pageSelection={pageSelection}
        onPageSelectionChange={onPageSelectionChange}
        stringVariables={stringVariables}
        clipboard={clipboard}
        onClipboardChange={onClipboardChange}
        variables={variables}
        onVariablesChange={onVariablesChange}
        events={events}
        onEventsChange={onEventsChange}
        stateSaving={stateSaving}
        onStateSavingChange={onStateSavingChange}
        autoRefresh={autoRefresh}
        onAutoRefreshChange={onAutoRefreshChange}
        objectSetVariables={registrable(variables).map((v) => ({
          id: v.id, label: v.label || v.id,
        }))}
        derivedProperties={derivedProperties}
        onDerivedPropertiesChange={onDerivedPropertiesChange}
        derivableTypes={derivableTypes}
        translations={translations}
        onTranslationsChange={onTranslationsChange}
        kiosk={kiosk}
        onKioskChange={onKioskChange}
      />
      {/* p.213 reaches Used colors "by navigating to a module's Settings tab
          in edit mode", and this column is that tab: it is where the module's
          own switches live. Below them and above the palette, because it
          describes the document rather than offering anything to drag. */}
      <UsedColoursPanel palette={savedColours} onPaletteChange={onSavedColoursChange} />
      <p className="field-label canvas-toolbox-heading">Widgets</p>
      <WidgetPalette />
    </div>
  );
}

/**
 * p.64's widget selector, grouped and filterable (§447).
 *
 * The categories and the filter are `lib/widget-palette.ts`'s and are tested
 * without a browser. What is here is the markup and the one piece of state.
 *
 * **A panel rather than p.64's modal**, with the reasoning written out in
 * that module: a modal buys room, and grouping buys the same thing without
 * taking the canvas away while somebody chooses.
 */
function WidgetPalette() {
  const [query, setQuery] = useState("");
  const groups = grouped(matching(PALETTE, query));
  return (
    <div className="canvas-palette" data-testid="widget-palette">
      <input
        className="canvas-palette-search"
        value={query}
        placeholder="Search widgets…"
        aria-label="Search widgets"
        data-testid="widget-search"
        onChange={(e) => setQuery(e.target.value)}
      />
      {groups.length === 0 && (
        <p className="canvas-widget-empty" data-testid="widget-palette-empty">
          {paletteEmptyNote(query)}
        </p>
      )}
      {groups.map((group) => (
        <section key={group.category.id} data-testid={`widget-group-${group.category.id}`}>
          <p className="canvas-palette-group">
            {group.category.label}
            {/* Where the grouping comes from. Foundry's categories are its
                own, and a builder who wants to know why the Markdown widget
                is under Visualization can go and read p.276. */}
            <span className="soft"> {group.category.source}</span>
          </p>
          {group.items.map((item) => (
            <PaletteItem
              key={item.key}
              componentKey={item.key as Parameters<typeof PaletteItem>[0]["componentKey"]}
              label={item.label}
              hint={item.hint}
            />
          ))}
        </section>
      ))}
    </div>
  );
}

export function WorkshopApplication({ resource }: { resource: ResolvedResource }) {
  // Interface variables initialised from the URL (Foundry p.165). The same
  // external IDs an embedding module maps - one mechanism, three consumers.
  const search = useSearchParams();
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  // **Craft's `<Frame data>` is read once, at mount.** Changing it afterwards
  // does nothing, which is fine for a save (the tree already *is* what was
  // saved) and wrong for a revert: the document changed underneath the editor,
  // and without a remount the canvas keeps drawing the old one. The symptom is
  // a Revert button that appears to do nothing until the page is reloaded.
  //
  // Bumped only by revert rather than keyed on `current_version`, so an
  // ordinary save does not throw away the selection and scroll position of
  // somebody who is still working.
  const [reloadToken, setReloadToken] = useState(0);
  const workspaceId = resource.workspace_id;
  const projectId = resource.project_id;
  const appId = resource.kind_id;

  // Roles, not identities. Both come from summary lists the app already holds.
  const { workspace } = useWorkspaceById(workspaceId);
  const { project } = useProjectById(workspaceId, projectId);

  const appQuery = useQuery({
    queryKey: ["canvas-app", appId],
    queryFn: () => canvasApi.get(workspaceId, projectId!, appId),
    enabled: !!projectId,
  });

  // The head being edited (§698): null for main, or a branch's name. Read
  // from `?branch=` once, so a link to a branch opens on it.
  const [branchName, setBranchName] = useState<string | null>(search.get("branch"));
  const branchesQuery = useQuery({
    queryKey: ["canvas-app-branches", appId],
    queryFn: () => canvasApi.listBranches(workspaceId, projectId!, appId),
    enabled: !!projectId,
  });
  const branchQuery = useQuery({
    queryKey: ["canvas-app-branch", appId, branchName],
    queryFn: () => canvasApi.getBranch(workspaceId, projectId!, appId, branchName!),
    enabled: !!projectId && !!branchName,
  });
  const branch = branchName ? branchQuery.data ?? null : null;
  // A rebase in progress (§699; p.619-621): the three documents it merges
  // and the side each conflict has been given. Held here, beside the branch,
  // because the document it produces is what the editor shows - and dropped
  // on a switch of head, since it is a rebase of *that* branch.
  const [rebasing, setRebasing] = useState<RebaseState | null>(null);
  useEffect(() => setRebasing(null), [branchName]);
  const merged = useMemo(
    () => (rebasing && branch
      ? rebase(rebasing.base, rebasing.main, branch.definition, rebasing.choices)
      : null),
    [rebasing, branch],
  );
  // The document the editor works on: the rebase's while one is under way,
  // else the branch's when one is open. Every reader below takes it from
  // here, so main's document cannot leak into a branch's editor through a
  // prop somebody forgot.
  const headDefinition = merged
    ? merged.document
    : branchName ? branch?.definition : appQuery.data?.definition;

  // The tab name (p.47). Above the early returns because it is a hook, and
  // fed the *saved* document rather than the editor's live node map: retyping
  // a header title should not rewrite the tab on every keystroke.
  useModuleTitle(layoutOf(appQuery.data?.definition), resource.name);

  const canEdit = project ? project.effective_role !== "viewer" : false;
  const canPublish = workspace?.effective_role === "admin";

  // What a `run_action` effect may run (§60). Fetched here rather than inside
  // the panel because the panel is given what the layout and the workspace
  // contain and does not reach out for either - the same reason `triggerNodes`
  // and `pages` arrive as props.
  const actionTypes = useQuery({
    queryKey: ["action-types", workspaceId],
    queryFn: () => actionApi.listTypes(workspaceId),
  });
  const actionCandidates: ActionCandidate[] = (actionTypes.data ?? []).map((a) => ({
    id: a.id,
    // **The subject, whichever kind it is** (§451). `object_type_name` is null
    // on an interface action, and a template literal renders that as the word
    // "null" — a label TypeScript is perfectly happy with.
    label: `${a.display_name} · ${a.subject_name}`,
    editable: a.editable_properties,
  }));

  // p.165's Open Workshop module: which modules this one may open. Fetched here
  // for `actionTypes`'s reason - the panel is given what the workspace contains
  // and does not reach out for it.
  //
  // **Addressed by resource id, because that is where a module opens** (`/r/…`,
  // §115). The app id is what the API takes and the resource id is what a
  // reader's URL says; an event storing the wrong one would build a link that
  // 404s, and the two are both uuids so nothing would look wrong.
  const projectModules = useQuery({
    queryKey: ["canvas-apps", workspaceId, projectId],
    queryFn: () => canvasApi.list(workspaceId, projectId!),
    // Same guard the definition query above uses: the project comes from the
    // resource, so it is null for the first render.
    enabled: !!projectId,
  });
  const moduleCandidates: ModuleCandidate[] = (projectModules.data ?? [])
    // Not itself: a module that opens itself in a new tab is a loop a builder
    // can create by accident and cannot see until they click it.
    .filter((m) => m.id !== appId)
    .map((m) => ({ id: m.resource_id, appId: m.id, label: m.name }));

  // The variables half of the document. Held here rather than in the panel
  // because the Save button has to write both halves at once - and reseeded
  // only when a *new version* arrives, so a refetch cannot discard edits
  // somebody has made but not saved.
  const [variables, setVariables] = useState<Record<string, WorkshopVariable>>({});
  const [events, setEvents] = useState<Record<string, WorkshopEvent>>({});
  // Routing is one switch for the whole module (p.195) and rides along with
  // the same save, for the same reason: it is part of the document, not a
  // setting on the row beside it.
  const [routing, setRouting] = useState(false);
  // p.81's Variable-Based Page Selection: one variable id for the whole
  // module, saved with the document beside routing and for the same reason.
  const [pageSelection, setPageSelection] = useState("");
  const [stateSaving, setStateSaving] = useState(() => stateSavingOf(undefined));
  // p.576-580's auto-refresh, held with the other module-wide settings so
  // the Save button carries it - and so a version revert takes the switch
  // back with the variables it registers.
  const [autoRefresh, setAutoRefresh] = useState(() => autoRefreshSettings(undefined));
  // p.168-172's derived properties, held with the other module-wide
  // settings so the Save button carries them and a revert takes them back
  // with the layout that names them.
  const [derivedProperties, setDerivedProperties] = useState<
    NonNullable<import("@/lib/types").WorkshopModule["derived_properties"]>
  >({});
  // p.214's Saved colors, held here for `derivedProperties`' reason: a widget's
  // background holds `saved:c1`, so the Save button has to carry the palette
  // and a revert has to take it back with the layout that references it.
  const [savedColours, setSavedColours] = useState<
    NonNullable<import("@/lib/types").WorkshopModule["saved_colours"]>
  >([]);
  // p.207-211's tables, held here with the other two module-wide settings so
  // the Save button carries them. Never edited by this component - the switch
  // is the Settings panel's and the tables are written through the API until
  // p.209's Translations tab exists.
  const [translations, setTranslations] = useState(() => translationsOf(undefined));
  const [kiosk, setKiosk] = useState(false);
  // p.211's preview: the language being previewed and the document as it
  // stood when preview opened. Held together because a snapshot without a
  // language is nothing to translate it with, and a language without a
  // snapshot has nothing to translate.
  const [previewing, setPreviewing] = useState<
    { language: string; snapshot: Record<string, unknown> } | null
  >(null);
  const savedVersion = appQuery.data?.current_version;
  // Reseeded when the head's *saved* document changes - a new main version, a
  // branch save, or a switch of head - and never on a plain refetch, which
  // would discard edits somebody has made but not saved.
  const savedHead = branchName
    ? `${headKey(branchName, branch ?? undefined)}:${rebasing?.token ?? ""}`
    : headKey(null, savedVersion);
  // **The head this builder's own Save wrote.** The refetch a Save triggers
  // brings back exactly what was sent, so resetting the panels from it can
  // only lose something: an edit made in the moment between the PUT returning
  // and the refetch landing went back to the saved value, and the next Save
  // wrote the old value over it (#468, a test that kept editing). A revert, a
  // merge, a switch of head, a rebase or a first load is a head this builder
  // did not write, and still resets. Keyed on the head rather than main's
  // version since §698, because a branch save is the same race.
  const ownSave = useRef<string | null>(null);
  useEffect(() => {
    if (!appQuery.data || !headDefinition) return;
    if (savedHead === ownSave.current) return;
    setVariables(variablesOf(headDefinition));
    setEvents(eventsOf(headDefinition));
    setRouting(routingOf(headDefinition));
    setPageSelection(pageSelectionOf(headDefinition));
    setStateSaving(stateSavingOf(headDefinition));
    setTranslations(translationsOf(headDefinition));
    setKiosk(kioskOf(headDefinition));
    setAutoRefresh(autoRefreshSettings(autoRefreshOf(headDefinition)));
    setDerivedProperties(
      (derivedPropertiesOf(headDefinition) as typeof derivedProperties) ?? {},
    );
    setSavedColours(
      (savedColoursOf(headDefinition) as typeof savedColours) ?? [],
    );
  }, [savedHead, appQuery.data?.id]);

  // A module always lives in a project. A resolved `canvas_app` without one is
  // a registry row that disagrees with its own table, and saying so beats
  // rendering a builder whose every write would 404.
  if (!projectId) {
    return <div className="state error">This module is not in a project, so it cannot be opened.</div>;
  }
  if (appQuery.isPending) {
    return <div className="state">Loading app…</div>;
  }
  if (appQuery.isError) {
    return <div className="state error">Couldn&apos;t load this app. It may have been deleted.</div>;
  }

  if (branchName && branchQuery.isPending) {
    return <div className="state">Loading branch {branchName}…</div>;
  }
  if (branchName && branchQuery.isError) {
    return (
      <div className="state error">
        Couldn&apos;t load branch {branchName}. It may have been merged or deleted.{" "}
        <button type="button" className="btn quiet" onClick={() => setBranchName(null)}>
          Open main
        </button>
      </div>
    );
  }

  // On a branch, the module *as the editor sees it* is main's row with the
  // branch's document - the id, the version main is at and the publish state
  // stay main's, because they are.
  const app: CanvasAppDetail = branch
    ? { ...appQuery.data, definition: merged?.document ?? branch.definition }
    : appQuery.data;

  // p.619's "Start the rebase": the base is the main version the branch was
  // taken from, and main is read fresh rather than from the cache - a rebase
  // onto a main somebody saved past a minute ago is a rebase onto the wrong
  // thing, and the server would refuse to finish it.
  const beginRebase = async () => {
    if (!branch) return;
    const [main, base] = await Promise.all([
      canvasApi.get(workspaceId, projectId, appId),
      branch.base_version > 0
        ? canvasApi.getVersion(workspaceId, projectId, appId, branch.base_version)
          .then((v) => v.definition)
        : Promise.resolve({}),
    ]);
    setRebasing({
      base, main: main.definition, mainVersion: main.current_version,
      choices: {}, token: Date.now(),
    });
  };

  // "View this version" (p.191). Rendered instead of the builder rather than
  // inside it: a historic document in an *editable* canvas is one Save away
  // from silently becoming the current one, and the person who did it would
  // have thought they were only looking.
  if (viewingVersion !== null) {
    return (
      <ViewingVersion
        workspaceId={workspaceId}
        projectId={projectId}
        app={app}
        version={viewingVersion}
        onClose={() => setViewingVersion(null)}
      />
    );
  }

  return (
    <>
    {/* p.211's preview, **beside** the builder rather than instead of it.
        The builder's Editor stays mounted below, so its tree, its selection
        and everything the author has not saved are still there when they
        exit - which is the hazard §400 refused to ship into. Its own Editor
        is `enabled={false}` and has no Save, so the translated nodes cannot
        reach the document. */}
    {previewing && (
      <TranslationPreview
        snapshot={previewing.snapshot}
        language={previewing.language}
        table={translations.languages?.[previewing.language]}
        variables={variables}
        events={eventsOf(app.definition)}
        resolver={CANVAS_RESOLVER}
        onRender={CanvasNode}
        envelope={(children: React.ReactNode) => (
          <CanvasEnvBridge
            workspaceId={workspaceId}
            projectId={projectId}
            appId={app.id}
            variables={variables}
            events={eventsOf(app.definition)}
          >
            {children}
          </CanvasEnvBridge>
        )}
        onExit={() => setPreviewing(null)}
      />
    )}
    <Editor
      // Remounted on a switch of head as well as on a revert: Craft reads
      // `<Frame data>` once, so the other head's document would otherwise
      // never reach the canvas.
      key={`${reloadToken}:${branchName ?? ""}:${rebasing?.token ?? ""}`}
      resolver={CANVAS_RESOLVER}
      enabled={canEdit}
      onRender={CanvasNode}
    >
      <CanvasEnvBridge
        workspaceId={workspaceId}
        projectId={projectId}
        appId={app.id}
        variables={variables}
        events={eventsOf(app.definition)}
        seed={seedFromQuery(variables, search)}
        routing={routing}
        layout={layoutOf(app.definition)}
        pageSelection={pageSelection}
        stateSaving={stateSaving}
        autoRefresh={autoRefresh}
        derivedProperties={derivedProperties}
        savedColours={savedColours}
        branch={branchName ?? undefined}
      >
        <ActionBar
          app={app}
          workspaceId={workspaceId}
          projectId={projectId}
          canEdit={canEdit}
          canPublish={canPublish}
          variables={variables}
          events={events}
          routing={routing}
          pageSelection={pageSelection}
          stateSaving={stateSaving}
          translations={translations}
          kiosk={kiosk}
          autoRefresh={autoRefresh.enabled ? autoRefresh : undefined}
          derivedProperties={derivedProperties}
          savedColours={savedColours}
          onView={setViewingVersion}
          onReverted={() => setReloadToken((n) => n + 1)}
          onSaved={(head) => { ownSave.current = head; }}
          branch={branch}
          branches={branchesQuery.data ?? []}
          onBranch={setBranchName}
          onMerged={() => setReloadToken((n) => n + 1)}
          mainDefinition={appQuery.data.definition}
          rebasing={rebasing && merged
            ? { mainVersion: rebasing.mainVersion, conflicts: merged.conflicts,
                choices: rebasing.choices }
            : null}
          onRebase={beginRebase}
          onChoose={(key, choice) => setRebasing((r) => r && {
            ...r, choices: { ...r.choices, [key]: choice }, token: Date.now(),
          })}
          onRebaseEnd={() => setRebasing(null)}
        />
        <CanvasBody
          hasSavedLayout={hasLayout(app.definition)}
          definition={app.definition}
          canEdit={canEdit}
          workspaceId={workspaceId}
          projectId={projectId}
          appId={app.id}
          variables={variables}
          onVariablesChange={setVariables}
          events={events}
          onEventsChange={setEvents}
          routing={routing}
          onRoutingChange={setRouting}
          pageSelection={pageSelection}
          onPageSelectionChange={setPageSelection}
          stateSaving={stateSaving}
          onStateSavingChange={setStateSaving}
          autoRefresh={autoRefresh}
          onAutoRefreshChange={setAutoRefresh}
          derivedProperties={derivedProperties}
          onDerivedPropertiesChange={setDerivedProperties}
          savedColours={savedColours}
          onSavedColoursChange={setSavedColours}
          translations={translations}
          onTranslationsChange={setTranslations}
          kiosk={kiosk}
          onKioskChange={setKiosk}
          onPreview={(language, snapshot) => setPreviewing({ language, snapshot })}
          actions={actionCandidates}
          modules={moduleCandidates}
        />
      </CanvasEnvBridge>
    </Editor>
    </>
  );
}

/** A rebase under way (§699): the base and main it merges the branch onto,
 * the main version that becomes the branch's base when it is saved, and the
 * side each conflict has been given. `token` changes whenever the merged
 * document does, which is what remounts the editor on it. */
interface RebaseState {
  base: Record<string, unknown>;
  main: Record<string, unknown>;
  mainVersion: number;
  choices: Record<string, MergeChoice>;
  token: number;
}

/** The editor sidebar's tabs. Named rather than written twice: the state and
 * the list that fills it went out of step the first time a tab was added. */
type WorkshopTab =
  | "widget" | "variables" | "events" | "profiler" | "metrics" | "translations"
  | "access";

function CanvasBody({
  hasSavedLayout,
  definition,
  canEdit,
  workspaceId,
  projectId,
  appId,
  variables,
  onVariablesChange,
  events,
  onEventsChange,
  routing,
  onRoutingChange,
  pageSelection,
  onPageSelectionChange,
  stateSaving,
  onStateSavingChange,
  autoRefresh,
  onAutoRefreshChange,
  derivedProperties,
  onDerivedPropertiesChange,
  savedColours,
  onSavedColoursChange,
  translations,
  kiosk,
  onKioskChange,
  onTranslationsChange,
  onPreview,
  actions,
  modules,
}: {
  hasSavedLayout: boolean;
  definition: Record<string, unknown>;
  canEdit: boolean;
  workspaceId: string;
  projectId: string;
  appId: string;
  variables: Record<string, WorkshopVariable>;
  onVariablesChange: (next: Record<string, WorkshopVariable>) => void;
  events: Record<string, WorkshopEvent>;
  onEventsChange: (next: Record<string, WorkshopEvent>) => void;
  routing: boolean;
  onRoutingChange: (next: boolean) => void;
  pageSelection: string;
  onPageSelectionChange: (next: string) => void;
  stateSaving: NonNullable<import("@/lib/types").WorkshopModule["state_saving"]>;
  autoRefresh: AutoRefresh;
  onAutoRefreshChange: (next: AutoRefresh) => void;
  derivedProperties: Record<string, DerivedColumn[]>;
  onDerivedPropertiesChange: (next: Record<string, DerivedColumn[]>) => void;
  /** p.214's Saved colors, edited in the Used colors panel. */
  savedColours: NonNullable<import("@/lib/types").WorkshopModule["saved_colours"]>;
  onSavedColoursChange: (
    next: NonNullable<import("@/lib/types").WorkshopModule["saved_colours"]>,
  ) => void;
  onStateSavingChange: (
    next: NonNullable<import("@/lib/types").WorkshopModule["state_saving"]>,
  ) => void;
  translations: NonNullable<import("@/lib/types").WorkshopModule["translations"]>;
  onTranslationsChange: (next: NonNullable<import("@/lib/types").WorkshopModule["translations"]>) => void;
  kiosk: boolean;
  onKioskChange: (next: boolean) => void;
  /** p.211's preview. Serialised **inside** the Editor, because that is the
   * only place the live document exists - the builder's unsaved tree is
   * Craft's node map, and nothing above this component has it.
   */
  onPreview: (language: string, snapshot: Record<string, unknown>) => void;
  actions: ActionCandidate[];
  modules: ModuleCandidate[];
}) {
  const { query } = useEditor();
  const { enabled, triggerNodes, pageNodes, sectionNodes, tabSectionNodes } = useEditor((state) => {
    // Read from the editor's own node map rather than from the saved
    // definition: a widget dropped a moment ago is wireable, and a widget
    // deleted a moment ago is not - which is what somebody wiring an event
    // has just done and expects to see.
    const triggers: TriggerCandidate[] = [];
    const pages: PageCandidate[] = [];
    const sections: PageCandidate[] = [];
    const tabs: { id: string; label: string; tabs: string[] }[] = [];
    for (const [id, node] of Object.entries(state.nodes)) {
      const name = node?.data?.name;
      if (!name) continue;
      const props = (node.data.props ?? {}) as Record<string, unknown>;
      const label = String(
        props.label || props.title || props.text || node.data.displayName || name,
      ).slice(0, 40);
      if (TRIGGER_WIDGETS.includes(name)) {
        // A Menu or Two-part button carries its items, so an event can be
        // aimed at one of them (p.483; §462).
        const kind = name === "CanvasButton" ? buttonTypeOf(props.buttonType) : "inline";
        // p.243's custom right-click menu (§613): a table's menu items are
        // clicks the way a Menu button's are, and only when it is customised.
        // p.322's actions on highlighted text (§638), the same shape, and its
        // On hover interactions (§669) after them.
        const menu = name === "CanvasObjectTable" && props.customMenu
          ? itemsOf(props.menuItems)
          : name === "CanvasMarkdown" ? markdownClickItems(props.highlightActions, props.hoverActions) : [];
        // p.349's Override selection event (§616): a timeline's overriding
        // layers are row selections of their own, beside the widget's.
        const layers = name === "CanvasTimeline"
          ? overridingLayers(timelineLayersOf(props.layers)) : [];
        // p.320's per-type Override event on selection (§665): a Markdown
        // widget's overriding types are row selections beside its clicks.
        const types = name === "CanvasMarkdown"
          ? overridingReferenceTypes(referenceTypesOf(props.referenceTypes)) : [];
        triggers.push({
          id, label: `${node.data.displayName ?? name} · ${label}`, widget: name,
          ...(types.length ? { selectItems: types } : {}),
          ...(kind !== "inline"
            ? { buttonType: kind, items: itemsOf(props.items).map((i) => ({ id: i.id, label: i.label })) }
            : menu.length
              ? { buttonType: "menu" as const, items: menu.map((i) => ({ id: i.id, label: i.label })) }
              : layers.length
                ? { buttonType: "twoPart" as const, items: layers, itemsOn: "row_select",
                    noItemLabel: "Every other layer" }
                : {}),
        });
      }
      if (name === "CanvasPage" || name === "CanvasOverlay") {
        pages.push({ id, label: `${node.data.displayName ?? name} · ${label}` });
      }
      // p.82 offers its three events "for each collapsible section", so the
      // picker lists exactly those - the server refuses the rest, and offering
      // a choice that fails on save is the thing this list exists to avoid.
      if (name === "CanvasSection" && props.collapsible) {
        sections.push({ id, label: `Section · ${String(props.title || label)}`.slice(0, 60) });
      }
      // p.84 offers Switch-to-tab "for each Tab section", so the picker lists
      // exactly those - and carries each one's tab names, because the event
      // addresses a tab by name and the names are a function of the section's
      // `tabs` prop and how many children it has.
      if (name === "CanvasSection" && props.direction === "tabs") {
        tabs.push({
          id,
          label: `Tabs · ${String(props.title || label)}`.slice(0, 60),
          tabs: tabLabels(props.tabs as string | undefined, (node.data.nodes ?? []).length),
        });
      }
    }
    return {
      enabled: state.options.enabled,
      triggerNodes: triggers,
      pageNodes: pages,
      sectionNodes: sections,
      tabSectionNodes: tabs,
    };
  });
  // **Profiler mode keeps the chrome while the canvas drops to run mode**, and
  // the two halves come apart here on purpose. p.177 has you reading the
  // Profiler panel *while* profiling ("select Exit at the top of the Profiler
  // panel or in the Profiler mode banner"), so the settings column has to
  // stay; p.178 wants the measurement to be of what a viewer experiences, so
  // the canvas must not be in edit mode. Tying both to Craft's `enabled` flag
  // hid the panel the moment it had something to say - which is how this was
  // found, by four browser tests that could not reach the tab they had just
  // pressed a button on.
  // The address as it stands, which is what entering and leaving profiler
  // mode edit. Read here rather than in the panel so the two controls - the
  // tab's link and the banner's Exit - cannot disagree about what "this page"
  // means (§292).
  const shellSearch = useSearchParams().toString();
  const shellHref = `${typeof window === "undefined" ? "" : window.location.pathname}${
    shellSearch ? `?${shellSearch}` : ""}`;
  const profiling = profilerOn(shellSearch);
  // p.614's redact mode. On the shell rather than on the canvas: "visually
  // obfuscates the visible content of a Workshop application", and a builder
  // screen-sharing has the settings column open beside the widgets.
  const redacting = redactOn(shellSearch);
  // **Profiler mode keeps the chrome while the canvas drops to run mode**, and
  // the two halves come apart here on purpose. p.177 has you reading the
  // Profiler panel *while* profiling ("select Exit at the top of the Profiler
  // panel or in the Profiler mode banner"), so the settings column has to
  // stay; p.178 wants the measurement to be of what a viewer experiences, so
  // the canvas must not be in edit mode. Tying both to Craft's `enabled` flag
  // hid the panel the moment it had something to say - which is how this was
  // found, by four browser tests that could not reach the tab they had just
  // pressed a button on.
  const showChrome = (enabled || profiling) && canEdit;
  // Three things want the right-hand column: the selected widget's settings,
  // the module's variables, and its events. Tabbed rather than stacked - a
  // variable list that pushed the settings below the fold would make
  // configuring a widget worse in service of a panel most edits do not touch.
  // Profiling opens on the Profiler tab, because the reload that got here was
  // pressed *from* it (p.177) and coming back to Widget loses the reader's
  // place in the one flow this mode has.
  const [tab, setTab] = useState<WorkshopTab>(
    profilerOn(typeof window === "undefined" ? "" : window.location.search)
      ? "profiler"
      : "widget",
  );
  // p.55's clipboard. **Module-scoped and never persisted**: p.68 offers copy
  // and paste for reuse "anywhere in the module", and a clipping holds node
  // ids and variable definitions from *this* document, so carrying one to
  // another module would paste references to variables that are not there.
  const [clipboard, setClipboard] = useState<Clipping | null>(null);
  return (
    <div
      className={showChrome ? "canvas-shell" : "canvas-shell canvas-shell--full"}
      data-redact={redacting ? "on" : undefined}
      // **What the builder's own marks hang off** (§460): the hover outline
      // on a widget, the dashed frame round each page and overlay. They are
      // for arranging a module, and Preview is where an author checks what a
      // reader sees - so they belong to editing, not to the shell. Scoped to
      // `.canvas-shell` alone, they drew in Preview; scoped to
      // `.canvas-frame-area`, the hover one drew on the reader's route too.
      data-editing={enabled ? "true" : undefined}
    >
      {/* Above the profiler's, because it is the one that says something is
          being hidden - and `globals.css` exempts it from the blur, or the
          warning would be the least readable thing on the page. */}
      {redacting && <RedactBanner href={redactHref(shellHref, false)} />}
      {/* p.177: "A banner will be displayed at the top of the page". At the
          top of the *shell* rather than inside the settings column, because it
          is about the whole page and because its Exit has to be reachable from
          wherever somebody has scrolled to. */}
      {profiling && <ProfilerBanner href={profilerHref(shellHref, false)} />}
      {showChrome && (
        <Toolbox
          routing={routing}
          onRoutingChange={onRoutingChange}
          pageSelection={pageSelection}
          onPageSelectionChange={onPageSelectionChange}
          // p.81 says "a string variable", so the picker offers exactly
          // those. The server refuses the rest - offering a choice that
          // fails on save is what this filter exists to avoid, the same
          // argument the section picker two blocks up makes.
          stringVariables={Object.values(variables)
            .filter((v) => v.kind === "string")
            .map((v) => ({ id: v.id, label: v.label }))}
          clipboard={clipboard}
          onClipboardChange={setClipboard}
          variables={variables}
          onVariablesChange={onVariablesChange}
          events={events}
          onEventsChange={onEventsChange}
          stateSaving={stateSaving}
          onStateSavingChange={onStateSavingChange}
          autoRefresh={autoRefresh}
          onAutoRefreshChange={onAutoRefreshChange}
          translations={translations}
          onTranslationsChange={onTranslationsChange}
          kiosk={kiosk}
          onKioskChange={onKioskChange}
          derivedProperties={derivedProperties}
          onDerivedPropertiesChange={onDerivedPropertiesChange}
          savedColours={savedColours}
          onSavedColoursChange={onSavedColoursChange}
        />
      )}
      <div className="canvas-frame-area">
        {hasSavedLayout ? (
          <Frame data={JSON.stringify(layoutOf(definition))} />
        ) : (
          <Frame>
            <Element is={CanvasContainer} canvas />
          </Frame>
        )}
      </div>
      {showChrome && (
        <div className="canvas-settings">
          <nav className="ds-tabs canvas-panel-tabs">
            {/* p.92's Check access is in this list without a guard of its own:
                its route is editor-only, and `showChrome` above already keeps
                this whole column from anybody who cannot edit. A second
                `canEdit` here would be a check that cannot fail (§213). */}
            {(["widget", "variables", "events", "profiler", "metrics",
               "translations", "access"] satisfies WorkshopTab[]).map((t) => (
              <button
                key={t}
                type="button"
                className={`ds-tab${t === tab ? " on" : ""}`}
                aria-current={t === tab}
                onClick={() => setTab(t)}
              >
                {t === "widget"
                  ? "Widget"
                  : t === "variables"
                    ? `Variables (${Object.keys(variables).length})`
                    : t === "events"
                      ? `Events (${Object.keys(events).length})`
                      : t === "profiler"
                        ? "Profiler"
                        : t === "metrics"
                          ? "Metrics"
                          // p.208: "a new Translations tab will appear".
                          // Named for the feature, with the count of
                          // languages the way Variables and Events carry
                          // theirs.
                          : t === "translations"
                            ? `Translations (${Object.keys(translations.languages ?? {}).length})`
                            : "Check access"}
              </button>
            ))}
          </nav>
          {tab === "events" && (
            <EventsPanel
              events={events}
              variables={variables}
              triggerNodes={triggerNodes}
              pages={pageNodes}
              tabSections={tabSectionNodes}
              sections={sectionNodes}
              actions={actions}
              modules={modules}
              workspaceId={workspaceId}
              projectId={projectId}
              onChange={onEventsChange}
              readOnly={!canEdit}
            />
          )}
          {tab === "access" && (
            <CheckAccessPanel
              workspaceId={workspaceId}
              projectId={projectId}
              appId={appId}
            />
          )}
          {tab === "widget" ? (
            <SettingsPanel />
          ) : tab === "metrics" ? (
            // p.185 puts this in the editor's sidebar beside the rest.
            <MetricsPanel
              workspaceId={workspaceId}
              projectId={projectId}
              appId={appId}
              // Pages and overlays by the names their author gave them. The
              // panel has the counts and the editor has the tree, so the names
              // come from here rather than the panel guessing.
              layoutNames={Object.fromEntries(
                pageNodes.map((p) => [p.id, p.label]),
              )}
              readOnly={!canEdit}
            />
          ) : tab === "profiler" ? (
            // p.177: "enter Edit mode, open the Profiler tab, and select
            // Reload in Profiler Mode". The panel knows whether it is
            // recording; the address is what it offers to change.
            <ProfilerPanel
              href={profilerHref(shellHref, true)}
              // The filter names pages the way the rest of the builder does.
              // The panel has the events and not the document, so the name
              // comes from here - a profiler that invented its own naming
              // would make a reader match node ids by eye.
              labelFor={(nodeId) =>
                pageNodes.find((p) => p.id === nodeId)?.label ?? nodeId}
            />
          ) : tab === "translations" ? (
            // p.208 puts this tab in the editor's sidebar beside the rest,
            // and p.209-210 are what it draws.
            <TranslationsPanel
              translations={translations}
              onChange={onTranslationsChange}
              // Serialised here, inside the Editor: the builder's unsaved
              // tree is Craft's node map and nothing above this has it.
              onPreview={(language) =>
                onPreview(language, query.getSerializedNodes() as Record<string, unknown>)}
              readOnly={!canEdit}
            />
          ) : tab === "variables" ? (
            <VariablesPanel
              workspaceId={workspaceId}
              projectId={projectId}
              appId={appId}
              variables={variables}
              layout={layoutOf(definition)}
              onChange={onVariablesChange}
              readOnly={!canEdit}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}
