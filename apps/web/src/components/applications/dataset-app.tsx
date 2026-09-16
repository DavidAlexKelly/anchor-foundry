"use client";

/** The dataset application (ROADMAP.md phase 2, item 3.1).
 *
 * Foundry's Dataset Preview is a full application with tabs - Preview, Details
 * (including the schema), History, and lately Time Travel. Anchor already had
 * every one of those answers; they were spread across a list page, a row
 * expander and two dialogs, which is the arrangement this phase exists to
 * undo. So this is mostly re-presentation, which is exactly why it was
 * sequenced first: it proves the application shell against endpoints that are
 * already known to work, rather than co-developing an app and its backend.
 *
 * The tab lives in the URL. A link to a dataset's schema has to be a different
 * link from one to its rows, or "send me the link" means "and then click the
 * third tab".
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, datasets as datasetApi, models as modelApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { branchName, whyNotBranchable } from "@/lib/branch-from-version";
import { rollbackSummary, whyNotRollbackable } from "@/lib/dataset-rollback";
import { useUrlState } from "@/components/use-url-state";
import { PipelineGraphView } from "@/components/pipeline-graph";
import { nodePath } from "@/lib/pipeline-graph";
import type { ResolvedResource, TabularResult } from "@/lib/types";

const TABS = ["preview", "schema", "history", "lineage", "details"] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  preview: "Preview",
  schema: "Schema",
  history: "History",
  lineage: "Lineage",
  details: "Details",
};

export function DatasetApplication({ resource }: { resource: ResolvedResource }) {
  const url = useUrlState();
  const tab = url.oneOf("tab", TABS, "preview");

  const wid = resource.workspace_id;
  const pid = resource.project_id!;
  const did = resource.kind_id;

  // Which version is being read, if not the current one (roadmap 3.3). In the
  // URL beside the tab, so "look at this dataset as it was at v2" is a link
  // rather than a sequence of clicks to describe.
  const versionParam = Number(url.get("version"));
  const version = Number.isInteger(versionParam) && versionParam > 0 ? versionParam : null;

  const setParams = url.set;
  const selectTab = (next: Tab) => setParams({ tab: next });

  return (
    <div className="ds-app">
      <nav className="ds-tabs" aria-label="Dataset views">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            className={`ds-tab${t === tab ? " on" : ""}`}
            aria-current={t === tab}
            onClick={() => selectTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </nav>

      {version !== null && (
        <TimeTravelBanner
          wid={wid}
          pid={pid}
          did={did}
          version={version}
          onLeave={() => setParams({ version: undefined })}
        />
      )}

      <div className="ds-panel">
        {tab === "preview" && <PreviewTab wid={wid} pid={pid} did={did} version={version} />}
        {tab === "schema" && <SchemaTab wid={wid} pid={pid} did={did} version={version} />}
        {tab === "history" && (
          <HistoryTab
            wid={wid}
            pid={pid}
            did={did}
            name={resource.name}
            viewing={version}
            onView={(n) => setParams({ version: String(n), tab: "preview" })}
          />
        )}
        {tab === "lineage" && <LineageTab resource={resource} />}
        {tab === "details" && <DetailsTab wid={wid} pid={pid} did={did} />}
      </div>
    </div>
  );
}

function Table({ result }: { result: TabularResult }) {
  return (
    <div className="ds-scroll">
      <table className="ds-table">
        <thead>
          <tr>
            {result.columns.map((c) => (
              <th key={c.name} scope="col">
                {c.name}
                <span className="ds-coltype">{c.data_type}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>
                  {cell === null ? <span className="ds-null">null</span> : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Says loudly that what is on screen is not the dataset as it is now.
 *
 * Above the panel rather than inside a tab, because every tab under it is
 * showing the same past - a banner one tab has and another does not is how
 * somebody reads an old schema as the current one. */
function TimeTravelBanner({
  wid,
  pid,
  did,
  version,
  onLeave,
}: {
  wid: string;
  pid: string;
  did: string;
  version: number;
  onLeave: () => void;
}) {
  const versions = useQuery({
    queryKey: ["ds-versions", did],
    queryFn: () => datasetApi.versions(wid, pid, did),
  });
  const current = versions.data?.[0]?.version_number;
  const row = versions.data?.find((v) => v.version_number === version);
  return (
    <p className="ds-timetravel">
      Viewing <strong>v{version}</strong>
      {current ? ` of ${current}` : ""}
      {row ? ` — ${row.row_count.toLocaleString()} rows as it was on ${new Date(row.created_at).toLocaleString()}` : ""}
      .{" "}
      <button type="button" onClick={onLeave}>
        Back to the current version
      </button>
    </p>
  );
}

function PreviewTab({
  wid,
  pid,
  did,
  version,
}: {
  wid: string;
  pid: string;
  did: string;
  version: number | null;
}) {
  const preview = useQuery({
    // The version is part of the key: without it, switching versions would
    // serve the previous one's rows from cache under a banner naming the new.
    queryKey: ["ds-preview", did, version],
    queryFn: () => datasetApi.preview(wid, pid, did, version ?? undefined),
  });
  if (preview.isPending) return <p className="state">Loading rows…</p>;
  if (preview.isError) return <p className="state error">{(preview.error as Error).message}</p>;
  return (
    <>
      <p className="soft ds-note">
        {preview.data.truncated
          ? `First ${preview.data.rows.length} rows of ${preview.data.total_rows.toLocaleString()}.`
          : `All ${preview.data.total_rows.toLocaleString()} rows.`}
      </p>
      <Table result={preview.data} />
    </>
  );
}

function SchemaTab({
  wid,
  pid,
  did,
  version,
}: {
  wid: string;
  pid: string;
  did: string;
  version: number | null;
}) {
  // Profiling is computed once per version and cached on the version row
  // (migration 0019), so asking for it here costs nothing after the first
  // time - which is why the schema tab can show statistics rather than just
  // column names, and why profiling an *old* version is cheap to look at twice.
  const profile = useQuery({
    queryKey: ["ds-profile", did, version],
    queryFn: () => datasetApi.profile(wid, pid, did, version ?? undefined),
  });
  if (profile.isPending) return <p className="state">Profiling columns…</p>;
  if (profile.isError) return <p className="state error">{(profile.error as Error).message}</p>;

  const rows = profile.data.row_count;
  return (
    <>
      <p className="soft ds-note">
        Version {profile.data.version_number} · {rows.toLocaleString()} rows ·{" "}
        {profile.data.columns.length} columns
      </p>
      <div className="ds-scroll">
        <table className="ds-table">
          <thead>
            <tr>
              <th scope="col">Column</th>
              <th scope="col">Type</th>
              <th scope="col">Nulls</th>
              <th scope="col">Distinct</th>
              <th scope="col">Min</th>
              <th scope="col">Max</th>
            </tr>
          </thead>
          <tbody>
            {profile.data.columns.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                <td className="ds-coltype-cell">{c.data_type}</td>
                <td>
                  {c.null_count.toLocaleString()}
                  <span className="soft"> ({(c.null_rate * 100).toFixed(1)}%)</span>
                </td>
                <td>{c.distinct_count.toLocaleString()}</td>
                <td className="ds-minmax">{c.min ?? <span className="ds-null">—</span>}</td>
                <td className="ds-minmax">{c.max ?? <span className="ds-null">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = n / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`;
}

/** p.4's **Create branch**, taken from the transaction the reader pressed.
 *
 *  The version is not a field: it is the row. Asking again is what the
 *  datasets list's dropdown does, and moving the action next to the history is
 *  the whole of what p.4 adds over it — everything underneath has existed
 *  since migration 0025.
 */
function BranchDialog({
  wid,
  pid,
  did,
  source,
  version,
  onClose,
}: {
  wid: string;
  pid: string;
  did: string;
  source: string;
  version: number;
  onClose: () => void;
}) {
  const [name, setName] = useState(branchName(source, version));
  const [made, setMade] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const branch = useMutation({
    mutationFn: () =>
      datasetApi.fork(wid, pid, did, { name, version_number: version }),
    onSuccess: async (created) => {
      // Not a redirect. A reader who branched from the history was reading the
      // history, and taking them somewhere else loses the place they were in —
      // so this says what happened and leaves them where they are.
      setMade(created.name);
      await queryClient.invalidateQueries({ queryKey: ["datasets", pid] });
      await queryClient.invalidateQueries({ queryKey: ["project", wid] });
    },
  });

  return (
    <Dialog open title={`Branch from v${version}`} onClose={onClose}>
      {made === null ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            branch.mutate();
          }}
        >
          <p className="login-note" style={{ marginTop: 0 }}>
            A branch is an independent copy of this dataset as it was at v
            {version} — its own versions, its own schema policy, its own data.
            Changing one never changes the other.
          </p>
          <Field label="New dataset name">
            <input
              type="text"
              data-testid="branch-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={200}
            />
          </Field>
          {branch.isError && (
            <div className="form-error" data-testid="branch-error">
              {branch.error instanceof ApiError
                ? branch.error.message
                : "Couldn't branch."}
            </div>
          )}
          <div className="form-actions">
            <button type="button" className="btn quiet" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn" disabled={branch.isPending}>
              {branch.isPending ? "Branching…" : "Create branch"}
            </button>
          </div>
        </form>
      ) : (
        <>
          <p className="login-note" data-testid="branch-made">
            Branched v{version} into <strong>{made}</strong>. It is in this
            project&apos;s datasets, independent from this one.
          </p>
          <div className="form-actions">
            <button type="button" className="btn" onClick={onClose}>
              Done
            </button>
          </div>
        </>
      )}
    </Dialog>
  );
}

/** p.76's confirmation dialog, saying what is true of *this* platform.
 *
 *  The wording is `lib/dataset-rollback`'s, because vitest cannot parse `.tsx`
 *  and a sentence that only a browser test can reach is a sentence with no
 *  unit test. What it says, and what it pointedly does not, is argued there.
 */
function RollbackDialog({
  wid,
  pid,
  did,
  version,
  currentVersion,
  origin,
  onClose,
}: {
  wid: string;
  pid: string;
  did: string;
  version: number;
  currentVersion: number;
  origin: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const roll = useMutation({
    mutationFn: () => datasetApi.rollBack(wid, pid, did, version),
    onSuccess: async () => {
      // Everything that reads the dataset's data is now out of date: the
      // history has a new row, the preview and the profile are a different
      // version's, and the detail row's version number moved.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ds-versions", did] }),
        queryClient.invalidateQueries({ queryKey: ["ds-preview", did] }),
        queryClient.invalidateQueries({ queryKey: ["ds-profile", did] }),
        queryClient.invalidateQueries({ queryKey: ["ds-detail", did] }),
        queryClient.invalidateQueries({ queryKey: ["ds-retention", did] }),
      ]);
      onClose();
    },
  });

  return (
    <Dialog open title={`Roll back to v${version}`} onClose={onClose}>
      <ul className="ds-rollback-summary" data-testid="rollback-summary">
        {rollbackSummary(version, currentVersion, origin).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {roll.isError && (
        <div className="form-error" data-testid="rollback-error">
          {roll.error instanceof ApiError ? roll.error.message : "Couldn't roll back."}
        </div>
      )}
      <div className="form-actions">
        <button type="button" className="btn quiet" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          data-testid="rollback-confirm"
          disabled={roll.isPending}
          onClick={() => roll.mutate()}
        >
          Roll back
        </button>
      </div>
    </Dialog>
  );
}

function HistoryTab({
  wid,
  pid,
  did,
  name,
  viewing,
  onView,
}: {
  wid: string;
  pid: string;
  did: string;
  /** The source dataset's name, which is half of what a branch is called. */
  name: string;
  viewing: number | null;
  onView: (version: number) => void;
}) {
  // Which transaction a branch is being taken from, or null for none. The
  // version is state rather than a field in the dialog, because p.4's flow
  // chooses it by pressing a row — asking again would be the datasets list's
  // dropdown, which is the thing this replaces.
  const [branching, setBranching] = useState<number | null>(null);
  // Which transaction is being rolled back to, chosen the same way and for the
  // same reason (§361; `data-lineage` p.75: "Select the transaction to roll
  // back to. Select Rollback to transaction").
  const [rollingBack, setRollingBack] = useState<number | null>(null);
  const versions = useQuery({
    queryKey: ["ds-versions", did],
    queryFn: () => datasetApi.versions(wid, pid, did),
  });
  // Shares `ds-detail` with the Details tab, so reading the history does not
  // fetch the dataset a second time. Only one field is wanted: whether
  // something rebuilds this dataset, which decides whether p.74's warning
  // about the logic is true of it.
  const detail = useQuery({
    queryKey: ["ds-detail", did],
    queryFn: () => datasetApi.get(wid, pid, did),
  });
  const retention = useQuery({
    queryKey: ["ds-retention", did],
    queryFn: () => datasetApi.retention(wid, pid, did),
  });
  if (versions.isPending) return <p className="state">Loading history…</p>;
  if (versions.isError) return <p className="state error">{(versions.error as Error).message}</p>;
  // The version the dataset is on, bound once. `[0]` rather than a second
  // query: the list is ordered newest first, so the answer is already here,
  // and a separate source for it could disagree with the rows being drawn.
  // Written as a check on the row rather than on the length so the compiler
  // knows it too — the two say the same thing.
  const newest = versions.data[0];
  if (newest === undefined) return <p className="state">No versions recorded yet.</p>;

  return (
    <>
      <p className="soft ds-note">
        Every commit to this dataset. A version&apos;s contents never change once
        written, which is what makes the row counts below comparable — and what
        makes any of them readable years later.
      </p>
      <div className="ds-scroll">
        <table className="ds-table">
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">Rows</th>
              <th scope="col">Columns</th>
              <th scope="col">Produced by</th>
              <th scope="col">Kept</th>
              <th scope="col">When</th>
              <th scope="col"><span className="ds-sr">View</span></th>
            </tr>
          </thead>
          <tbody>
            {versions.data.map((v, i) => {
              const previous = versions.data[i + 1];
              const current = newest.version_number;
              const delta = previous ? v.row_count - previous.row_count : null;
              return (
                <tr key={v.id}>
                  <td>v{v.version_number}</td>
                  <td>
                    {v.row_count.toLocaleString()}
                    {delta !== null && delta !== 0 && (
                      <span className={delta > 0 ? "ds-delta up" : "ds-delta down"}>
                        {delta > 0 ? "+" : ""}
                        {delta.toLocaleString()}
                      </span>
                    )}
                  </td>
                  <td>{v.table_schema.length}</td>
                  <td>
                    {v.produced_by_kind ?? <span className="soft">—</span>}
                    {/* Where a rollback took its data from. Foundry crosses
                        the skipped transactions out (p.70); saying which
                        version came back is the same fact written forwards,
                        and it is the only thing that distinguishes this row
                        from a build nobody can account for. */}
                    {v.rolled_back_to != null && (
                      <span className="soft" data-testid="rolled-back-to">
                        {" "}
                        → v{v.rolled_back_to}
                      </span>
                    )}
                  </td>
                  <td>
                    {v.size_bytes == null ? (
                      // Not the same as "small": the object is not where the
                      // row says it is, so this version cannot be read.
                      <span className="ds-gone">not stored</span>
                    ) : (
                      bytes(v.size_bytes)
                    )}
                  </td>
                  <td>{new Date(v.created_at).toLocaleString()}</td>
                  <td>
                    <button
                      type="button"
                      className="ds-view-version"
                      disabled={viewing === v.version_number || v.size_bytes == null}
                      onClick={() => onView(v.version_number)}
                    >
                      {viewing === v.version_number ? "Viewing" : "View"}
                    </button>
                    {/* p.4's Create branch, on the transaction rather than in
                        a dropdown that asks again which one you meant. The
                        same refusal the View button already makes, for the
                        same reason and in the same place: branching copies
                        the bytes this row could not find.

                        **The disabled half has no browser test, deliberately.**
                        Reaching it needs a version whose object is gone, and
                        nothing the browser can call removes one — the API owns
                        that state (`test_dataset_forks`) and `whyNotBranchable`
                        owns the wording. A test that pretended to exercise it
                        here would be the theatre §213 is about; the enabled
                        half *is* asserted, which is the part a browser can
                        reach. */}
                    <button
                      type="button"
                      className="ds-view-version"
                      data-testid="branch-version"
                      data-version={v.version_number}
                      disabled={whyNotBranchable(v) !== ""}
                      title={whyNotBranchable(v) || undefined}
                      onClick={() => setBranching(v.version_number)}
                    >
                      Branch
                    </button>
                    {/* p.75-76's **Rollback to transaction**, on the row rather
                        than in a menu, for p.4's reason: the version is not a
                        question, it is what was pressed. The wording of the
                        refusal is `whyNotRollbackable`'s, next to the one it
                        shares its shape with. */}
                    <button
                      type="button"
                      className="ds-view-version"
                      data-testid="rollback-version"
                      data-version={v.version_number}
                      disabled={whyNotRollbackable(v, current) !== ""}
                      title={whyNotRollbackable(v, current) || undefined}
                      onClick={() => setRollingBack(v.version_number)}
                    >
                      Roll back
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rollingBack !== null && (
        <RollbackDialog
          wid={wid}
          pid={pid}
          did={did}
          version={rollingBack}
          currentVersion={newest.version_number}
          origin={detail.data?.origin ?? ""}
          onClose={() => setRollingBack(null)}
        />
      )}
      {branching !== null && (
        <BranchDialog
          wid={wid}
          pid={pid}
          did={did}
          source={name}
          version={branching}
          onClose={() => setBranching(null)}
        />
      )}
      {retention.data && (
        <p className="ds-retention">
          Keeping {retention.data.versions} version
          {retention.data.versions === 1 ? "" : "s"} of this dataset costs{" "}
          <strong>{bytes(retention.data.total_bytes)}</strong>. Nothing is deleted
          automatically — old versions are what makes the rows above readable.
          {retention.data.unmeasured > 0 &&
            ` ${retention.data.unmeasured} version${
              retention.data.unmeasured === 1 ? " is" : "s are"
            } no longer in storage and not counted here.`}
        </p>
      )}
    </>
  );
}

function LineageTab({ resource }: { resource: ResolvedResource }) {
  const router = useRouter();
  // The project graph narrowed to this dataset's connected component - one
  // endpoint, because they are the same question. The server does the
  // layering, so this is arithmetic rather than a layout library.
  const graph = useQuery({
    queryKey: ["ds-lineage", resource.kind_id],
    queryFn: () =>
      modelApi.pipeline(resource.workspace_id, resource.project_id!, `dataset:${resource.kind_id}`),
  });
  if (graph.isPending) return <p className="state">Loading lineage…</p>;
  if (graph.isError) return <p className="state error">{(graph.error as Error).message}</p>;

  return (
    <>
      <p className="soft ds-note">
        Everything that feeds this dataset and everything it feeds. The outlined
        node is this one.
      </p>
      <PipelineGraphView
        graph={graph.data}
        maxHeight={520}
        onOpen={(node) => {
          // The dataset itself is what this app is already showing, so only
          // the other kinds navigate — an object type among them since §351
          // (p.32's "view its configuration in a new Ontology manager tab").
          if (node.kind !== "dataset") {
            router.push(
              nodePath(node, resource.workspace_slug, resource.project_slug!),
            );
          }
        }}
      />
    </>
  );
}

function DetailsTab({ wid, pid, did }: { wid: string; pid: string; did: string }) {
  const detail = useQuery({
    queryKey: ["ds-detail", did],
    queryFn: () => datasetApi.get(wid, pid, did),
  });
  const health = useQuery({
    queryKey: ["ds-health", did],
    queryFn: () => datasetApi.health(wid, pid, did),
  });
  if (detail.isPending) return <p className="state">Loading…</p>;
  if (detail.isError) return <p className="state error">{(detail.error as Error).message}</p>;

  const d = detail.data;
  return (
    <div className="ds-details">
      <dl className="app-facts">
        <div>
          <dt>Origin</dt>
          <dd>{d.origin}</dd>
        </div>
        <div>
          <dt>Rows</dt>
          <dd>{d.row_count.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Current version</dt>
          <dd>v{d.current_version}</dd>
        </div>
        <div>
          <dt>Schema policy</dt>
          <dd>
            {d.schema_policy}
            <span className="soft">
              {d.schema_policy === "strict"
                ? " — a new version may not drop or retype a column"
                : " — new columns allowed, existing ones may change"}
            </span>
          </dd>
        </div>
        <div>
          <dt>Slug</dt>
          <dd className="ds-slug">{d.slug}</dd>
        </div>
      </dl>

      <h2 className="ds-h2">Data health</h2>
      {health.isPending && <p className="state">Checking…</p>}
      {health.isError && <p className="soft">No health information available.</p>}
      {health.data && health.data.status === "none" && (
        <p className="soft">
          No expectations defined. Rules live with the dataset and run on every
          new version.
        </p>
      )}
      {health.data && health.data.status !== "none" && (
        <ul className="ds-health">
          {health.data.results.map((r, i) => (
            /* `error` is not `fail`: the rule could not be evaluated, which is
               not the same as the data being bad, and the types say so
               explicitly for exactly this reason. */
            <li key={i} className={r.status}>
              <strong>{r.column_name}</strong> {r.rule_type}
              <span className="ds-health-status">{r.status}</span>
              {r.status !== "pass" && (
                <span className="ds-health-detail">
                  {r.message ??
                    `${r.failing_rows.toLocaleString()} of ${r.rows_checked.toLocaleString()} rows`}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
