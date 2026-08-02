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

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { datasets as datasetApi, models as modelApi } from "@/lib/api";
import { PipelineGraphView } from "@/components/pipeline-graph";
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
  const router = useRouter();
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(raw ?? "") ? (raw as Tab) : "preview";

  const wid = resource.workspace_id;
  const pid = resource.project_id!;
  const did = resource.kind_id;

  function selectTab(next: Tab) {
    const search = new URLSearchParams(params.toString());
    search.set("tab", next);
    // replace, not push: flicking between tabs should not bury the page the
    // reader arrived from under a stack of back-button steps.
    router.replace(`?${search.toString()}`, { scroll: false });
  }

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

      <div className="ds-panel">
        {tab === "preview" && <PreviewTab wid={wid} pid={pid} did={did} />}
        {tab === "schema" && <SchemaTab wid={wid} pid={pid} did={did} />}
        {tab === "history" && <HistoryTab wid={wid} pid={pid} did={did} />}
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

function PreviewTab({ wid, pid, did }: { wid: string; pid: string; did: string }) {
  const preview = useQuery({
    queryKey: ["ds-preview", did],
    queryFn: () => datasetApi.preview(wid, pid, did),
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

function SchemaTab({ wid, pid, did }: { wid: string; pid: string; did: string }) {
  // Profiling is computed once per version and cached on the version row
  // (migration 0019), so asking for it here costs nothing after the first
  // time - which is why the schema tab can show statistics rather than just
  // column names.
  const profile = useQuery({
    queryKey: ["ds-profile", did],
    queryFn: () => datasetApi.profile(wid, pid, did),
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

function HistoryTab({ wid, pid, did }: { wid: string; pid: string; did: string }) {
  const versions = useQuery({
    queryKey: ["ds-versions", did],
    queryFn: () => datasetApi.versions(wid, pid, did),
  });
  if (versions.isPending) return <p className="state">Loading history…</p>;
  if (versions.isError) return <p className="state error">{(versions.error as Error).message}</p>;
  if (versions.data.length === 0) return <p className="state">No versions recorded yet.</p>;

  return (
    <>
      <p className="soft ds-note">
        Every commit to this dataset. A version&apos;s contents never change once
        written, which is what makes the row counts below comparable.
      </p>
      <div className="ds-scroll">
        <table className="ds-table">
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">Rows</th>
              <th scope="col">Columns</th>
              <th scope="col">Produced by</th>
              <th scope="col">When</th>
            </tr>
          </thead>
          <tbody>
            {versions.data.map((v, i) => {
              const previous = versions.data[i + 1];
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
                  <td>{v.produced_by_kind ?? <span className="soft">—</span>}</td>
                  <td>{new Date(v.created_at).toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
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
          if (node.kind === "model") {
            router.push(
              `/${resource.workspace_slug}/${resource.project_slug}/models`,
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
