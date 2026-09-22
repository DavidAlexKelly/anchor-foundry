"use client";

/** p.45-47's Preview and Code tabs, under the graph (§439; `data-lineage`
 * p.45-47).
 *
 * The rules are in `lib/graph-inspector.ts`, which has the tests — vitest
 * cannot parse `.tsx`. What is here is the fetching and the markup.
 *
 * **Under the Details strip, not instead of it.** The strip answers "what is
 * this" for every node kind; these tabs answer "what is in it" and "what made
 * it", and only a dataset or a transform has either. A panel that replaced the
 * strip would leave an object type with nothing at all.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Table } from "@/components/tabular";
import { datasets as datasetApi, models as modelApi, repositories as repoApi } from "@/lib/api";
import {
  TAB_LABELS, columnsNote, fileHref, keepTab, narrow, noCodeNote, previewNote, producerOf,
  tabsFor, type InspectorTab,
} from "@/lib/graph-inspector";
import { authoringSummary } from "@/lib/model-authoring";
import type { PipelineGraph, PipelineNode } from "@/lib/types";

/** Where the panel reads from. Passed only by callers that are looking at a
 *  real project — the review surface draws a *proposed* graph whose datasets
 *  may not exist yet, so it does not pass this and the panel is not drawn.
 *  The same rule `onBuild` follows, for the same reason (§214). */
export interface InspectFrom {
  workspaceId: string;
  projectId: string;
}

/** `"dataset:<uuid>"` → `"<uuid>"`. The graph's ids are prefixed so two kinds
 *  cannot collide; an endpoint wants the bare one. */
function idOf(node: PipelineNode): string {
  return node.id.slice(node.id.indexOf(":") + 1);
}

export function GraphInspector({
  node,
  graph,
  from,
}: {
  node: PipelineNode;
  graph: PipelineGraph;
  from: InspectFrom;
}) {
  const tabs = tabsFor(node, graph);
  // **The open tab is remembered across selections and corrected on arrival**,
  // which is `keepTab`'s whole job: reading rows hop by hop down a pipeline is
  // p.45's workflow, and a panel that reset to Preview every time would undo
  // half of it — while one that simply kept its state would sit on Code over
  // an uploaded dataset and render nothing.
  const [wanted, setWanted] = useState<InspectorTab | null>(null);
  const open = keepTab(tabs, wanted);
  if (tabs.length === 0 || open === null) return null;

  return (
    <div className="gi" data-testid="graph-inspector">
      <div className="gi-tabs" role="tablist" aria-label="Preview and logic">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={tab === open}
            className={`gi-tab${tab === open ? " is-active" : ""}`}
            data-testid={`gi-tab-${tab}`}
            onClick={() => setWanted(tab)}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
        {/* p.47's sentence, beside the tabs that *are* here rather than behind
            one that is not. A reader looking for Code finds out why in the
            place they were looking. */}
        {!tabs.includes("code") && (
          <span className="slug gi-nocode" data-testid="gi-no-code">{noCodeNote(node)}</span>
        )}
      </div>
      {open === "preview"
        ? <PreviewTab node={node} from={from} />
        : <CodeTab node={node} graph={graph} from={from} />}
    </div>
  );
}

function PreviewTab({ node, from }: { node: PipelineNode; from: InspectFrom }) {
  const [query, setQuery] = useState("");
  const preview = useQuery({
    // The key the dataset application's own preview uses, so opening the
    // dataset after reading it here is not a second fetch of the same rows.
    queryKey: ["ds-preview", idOf(node), null],
    queryFn: () => datasetApi.preview(from.workspaceId, from.projectId, idOf(node)),
  });

  if (preview.isPending) return <p className="slug gi-state">Loading the preview…</p>;
  if (preview.isError || !preview.data) {
    return <p className="state error gi-state">Couldn&apos;t read this dataset.</p>;
  }

  const shown = narrow(preview.data, query);
  const note = columnsNote(preview.data, query);
  return (
    <>
      <div className="gi-bar">
        {/* p.47: "search for specific columns using the Search columns… field
            to the right of the preview window." */}
        <input
          className="gi-search"
          value={query}
          placeholder="Search columns…"
          aria-label="Search columns"
          data-testid="gi-column-search"
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="slug" data-testid="gi-rows">{previewNote(preview.data)}</span>
        {note && <span className="slug" data-testid="gi-columns-note">{note}</span>}
      </div>
      {/* §226: an empty table and a dataset with no columns look the same, so
          the note above says which this is and the table is not drawn. */}
      {shown.columns.length > 0 && <Table result={shown} />}
    </>
  );
}

function CodeTab({
  node, graph, from,
}: {
  node: PipelineNode;
  graph: PipelineGraph;
  from: InspectFrom;
}) {
  // A transform's code is its own; a dataset's is the transform that writes
  // it, which the graph's edges already say (`producerOf`).
  const transform = node.kind === "model" ? node : producerOf(graph, node.id);
  const modelId = transform ? idOf(transform) : null;
  const model = useQuery({
    queryKey: ["model", modelId],
    queryFn: () => modelApi.get(from.workspaceId, from.projectId, modelId!),
    enabled: modelId !== null,
  });
  const repository = useQuery({
    queryKey: ["repository", model.data?.source_repo_id],
    queryFn: () =>
      repoApi.get(from.workspaceId, from.projectId, model.data!.source_repo_id!),
    enabled: Boolean(model.data?.source_repo_id),
  });

  if (model.isPending) return <p className="slug gi-state">Loading the transform…</p>;
  if (model.isError || !model.data) {
    return <p className="state error gi-state">Couldn&apos;t read this transform.</p>;
  }

  const href = fileHref(repository.data, model.data.source_path);
  return (
    <>
      <div className="gi-bar">
        <span className="chip">{model.data.language === "python" ? "Python" : "SQL"}</span>
        <span className="slug" data-testid="gi-authoring">{authoringSummary(model.data)}</span>
        {/* p.47's "open the code in the repository". A link, not an editor:
            this platform has one editor for a transform's body and
            `services/models.py` refuses a direct edit to a repository-authored
            one at all (db 0038). */}
        {href && (
          <Link className="btn quiet gi-open" href={href} data-testid="gi-open-file">
            Open in repository
          </Link>
        )}
      </div>
      <pre className="gi-code" data-testid="gi-code">{model.data.code}</pre>
    </>
  );
}
