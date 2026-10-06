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

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError, api as platformApi, datasets as datasetApi, models as modelApi, resourceTags,
  scheduledSync as scheduledSyncApi,
} from "@/lib/api";
import { addable, tagLabel } from "@/lib/resource-tags";
import { canEditProject } from "@/lib/test-runs";
import { Dialog, Field } from "@/components/dialog";
import { branchName, whyNotBranchable } from "@/lib/branch-from-version";
import { nextSyncNote, rollbackSummary, whyNotRollbackable } from "@/lib/dataset-rollback";
import { madeByText, originHref } from "@/lib/dataset-origin";
import { bytesText } from "@/lib/bytes";
import { uploadIntent, uploadedText } from "@/lib/dataset-files";
import { TRANSACTION_MEANING, currentViewText, olderPage } from "@/lib/dataset-transactions";
import { NO_SCHEDULES, scheduleName, scheduleWhen } from "@/lib/dataset-schedules";
import { currentBytes, sizeText } from "@/lib/dataset-size";
import {
  ENCODINGS,
  storedOptions,
  describeOptions,
  parseNullMarkers,
  parseDateFormats,
  dateFormatsText,
  optionsProblem,
  whyNotParseable,
  DELIMITED_ONLY,
  isJsonFile,
  type ParseOptions,
} from "@/lib/parse-options";
import Link from "next/link";
import { useUrlState } from "@/components/use-url-state";
import {
  NOTHING_NAMES_IT,
  fileHref,
  nameToSend,
  renameProblem,
} from "@/lib/dataset-rename";
import { PipelineGraphView } from "@/components/pipeline-graph";
import { Table } from "@/components/tabular";
import { nodePath } from "@/lib/pipeline-graph";
import type { DatasetReference, ResolvedResource, TabularResult } from "@/lib/types";

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
        {tab === "details" && <DetailsTab wid={wid} pid={pid} did={did} rid={resource.id} />}
      </div>
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
  // The one version being viewed, and the newest number: a page of one,
  // starting just above it (§879), rather than the whole history.
  const versions = useQuery({
    queryKey: ["ds-versions", did, "at", version],
    queryFn: () => datasetApi.versions(wid, pid, did, { before: version + 1, limit: 1 }),
  });
  const current = versions.data?.newest;
  const row = versions.data?.items.find((v) => v.version_number === version);
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
  const [parsing, setParsing] = useState(false);
  const [picked, setPicked] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const preview = useQuery({
    // The version is part of the key: without it, switching versions would
    // serve the previous one's rows from cache under a banner naming the new.
    queryKey: ["ds-preview", did, version],
    queryFn: () => datasetApi.preview(wid, pid, did, version ?? undefined),
  });
  // Shared with the Details and History tabs. Only two fields are wanted here:
  // whether there is an uploaded file to read again, and what it was called.
  const detail = useQuery({
    queryKey: ["ds-detail", did],
    queryFn: () => datasetApi.get(wid, pid, did),
  });
  const uploaded = detail.data?.origin === "upload";
  const files = useQuery({
    queryKey: ["ds-files", did],
    queryFn: () => datasetApi.files(wid, pid, did),
    enabled: uploaded,
  });
  const project = useQuery({
    queryKey: ["project", wid, pid],
    queryFn: () => platformApi.project(wid, pid),
    enabled: uploaded,
  });
  const editor = canEditProject(project.data?.effective_role ?? "viewer");
  if (preview.isPending) return <p className="state">Loading rows…</p>;
  if (preview.isError) return <p className="state error">{(preview.error as Error).message}</p>;
  // p.24 puts the Edit Schema UI on the preview tab, which is the right place
  // for the same reason p.4's Create branch belongs on a History row: this is
  // where somebody is looking at the parse that went wrong.
  //
  // **Offered only where it can work.** `whyNotParseable` is the server's own
  // two refusals, said before the press — a panel that opened and then
  // apologised would be §214's shape.
  const cannotParse = detail.data ? whyNotParseable(detail.data) : "";
  const offerParsing = version === null && detail.data !== undefined && cannotParse === "";
  const held = (files.data ?? []).map((f) => f.filename);
  // p.10's upload into this dataset: an uploaded one that still has its
  // files, read as it is now, by somebody who may change it.
  const offerUpload = version === null && editor && held.length > 0;
  return (
    <div
      data-testid="ds-drop"
      className={dragging ? "ds-drop on" : "ds-drop"}
      // p.11: "Drag and drop the file into the dataset preview window."
      onDragOver={(event) => {
        if (!offerUpload) return;
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      // No drop without the dragover above accepting it, and the panel is
      // shown only where an upload is offered.
      onDrop={(event) => {
        setDragging(false);
        event.preventDefault();
        const dropped = event.dataTransfer.files[0];
        if (dropped) setPicked(dropped);
      }}
    >
      <p className="soft ds-note">
        {preview.data.truncated
          ? `First ${preview.data.rows.length} rows of ${preview.data.total_rows.toLocaleString()}.`
          : `All ${preview.data.total_rows.toLocaleString()} rows.`}
        {offerParsing && (
          <>
            {" "}
            <button
              type="button"
              className="btn quiet"
              data-testid="parse-again"
              onClick={() => setParsing((open) => !open)}
            >
              {parsing ? "Close parsing options" : "Parsing options"}
            </button>
          </>
        )}
        {offerUpload && (
          <>
            {" "}
            <label className="btn quiet" data-testid="file-upload">
              Upload file
              <input
                type="file"
                hidden
                data-testid="file-upload-input"
                onChange={(event) => {
                  const chosen = event.target.files?.[0];
                  if (chosen) setPicked(chosen);
                  event.target.value = "";
                }}
              />
            </label>
          </>
        )}
      </p>
      {picked && offerUpload && (
        <UploadFilePanel
          wid={wid}
          pid={pid}
          did={did}
          held={held}
          file={picked}
          onClose={() => setPicked(null)}
        />
      )}
      {parsing && offerParsing && (
        <ParsePanel
          wid={wid}
          pid={pid}
          did={did}
          filename={detail.data?.original_filename ?? ""}
          filenames={held}
          stored={detail.data?.parse_options}
          onDone={() => setParsing(false)}
        />
      )}
      <Table result={preview.data} />
    </div>
  );
}

/** p.10's upload into an existing dataset, said before it happens (§746).
 *
 *  **Confirmed, not sent on pick**, because the name decides between replacing
 *  a file and adding one, and a replace takes rows away: the sentence says
 *  which before the press. The columns are the server's to check, and its
 *  refusal is shown as it says it.
 */
function UploadFilePanel({
  wid,
  pid,
  did,
  held,
  file,
  onClose,
}: {
  wid: string;
  pid: string;
  did: string;
  held: string[];
  file: File;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const intent = uploadIntent(held, file.name);
  const send = useMutation({
    mutationFn: () => datasetApi.uploadFile(wid, pid, did, file),
    onSuccess: async () => {
      await Promise.all(
        ["ds-preview", "ds-versions", "ds-profile", "ds-detail", "ds-retention", "ds-files"].map(
          (key) => queryClient.invalidateQueries({ queryKey: [key, did] }),
        ),
      );
    },
  });
  return (
    <div className="ds-parse" data-testid="file-upload-panel" data-mode={intent.mode}>
      {send.isSuccess ? (
        <p className="login-note" data-testid="file-uploaded" style={{ margin: 0 }}>
          {uploadedText(send.data)}{" "}
          <button type="button" className="btn quiet" onClick={onClose}>
            Close
          </button>
        </p>
      ) : (
        <>
          <p className="soft ds-note" style={{ marginTop: 0 }} data-testid="file-intent">
            {intent.text}
          </p>
          {send.isError && (
            <div className="form-error" data-testid="file-upload-error">
              {(send.error as Error).message}
            </div>
          )}
          <div className="dialog-actions" style={{ justifyContent: "flex-start" }}>
            <button
              type="button"
              className="btn"
              data-testid="file-upload-confirm"
              disabled={intent.mode === "refused" || send.isPending}
              onClick={() => send.mutate()}
            >
              {send.isPending ? "Uploading…" : intent.mode === "update" ? "Replace" : "Add"}
            </button>
            <button
              type="button"
              className="btn quiet"
              data-testid="file-upload-cancel"
              onClick={onClose}
            >
              Cancel
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/** p.14's parsing options and p.24's rehearsal, on the tab where the parse
 *  that went wrong is visible.
 *
 *  **Preview and Apply are two buttons, not one**, which is p.24's own
 *  arrangement ("this will help visualize the options available and how they
 *  affect the output dataset"): trying an option has to be free, or nobody
 *  tries. The wording of what Apply will do is `lib/parse-options`', because
 *  vitest cannot parse `.tsx`.
 */
function ParsePanel({
  wid,
  pid,
  did,
  filename,
  filenames,
  stored,
  onDone,
}: {
  wid: string;
  pid: string;
  did: string;
  filename: string;
  /** Every file the dataset holds (§746): a re-parse reads them all. */
  filenames: string[];
  stored: Record<string, unknown> | null | undefined;
  onDone: () => void;
}) {
  // Opens on the read that is on screen (§746): the stored options, which a
  // file added later is read with too.
  const [options, setOptions] = useState<ParseOptions>(() => storedOptions(stored));
  const [nulls, setNulls] = useState(() => storedOptions(stored).null_values.join("\n"));
  const [dates, setDates] = useState(() => dateFormatsText(storedOptions(stored).date_formats));
  const queryClient = useQueryClient();
  const dated = parseDateFormats(dates);
  const problem = dated.problem || optionsProblem(options);
  const sent = () => ({
    ...options, null_values: parseNullMarkers(nulls), date_formats: dated.formats,
  });

  const rehearse = useMutation({
    mutationFn: () => datasetApi.previewParse(wid, pid, did, sent()),
  });
  const keep = useMutation({
    mutationFn: () => datasetApi.parseAgain(wid, pid, did, sent()),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ds-preview", did] }),
        queryClient.invalidateQueries({ queryKey: ["ds-versions", did] }),
        queryClient.invalidateQueries({ queryKey: ["ds-profile", did] }),
        queryClient.invalidateQueries({ queryKey: ["ds-detail", did] }),
        queryClient.invalidateQueries({ queryKey: ["ds-retention", did] }),
      ]);
      onDone();
    },
  });

  function set<K extends keyof ParseOptions>(key: K, value: ParseOptions[K]) {
    setOptions((current) => ({ ...current, [key]: value }));
    // A field changed makes the last rehearsal stale, and a preview table
    // sitting under new options is the one thing this panel must not show.
    rehearse.reset();
  }

  const willDo = describeOptions(sent());
  // §510: a JSON file is offered only what applies to it.
  const json = isJsonFile(filename);

  return (
    <div className="ds-parse" data-testid="parse-panel">
      <p className="soft ds-note" style={{ marginTop: 0 }}>
        Read <strong data-testid="parse-files">{(filenames.length ? filenames : [filename]).join(", ")}</strong>{" "}
        again. {filenames.length > 1 ? "The files are the ones" : "The file is the one"} you
        uploaded; this changes how {filenames.length > 1 ? "they are" : "it is"} read, not what{" "}
        {filenames.length > 1 ? "they say" : "it says"}.
      </p>
      <div className="ds-parse-grid">
        {!json && (<>
        <label>
          Delimiter
          <input
            type="text"
            data-testid="parse-delimiter"
            maxLength={1}
            value={options.delimiter ?? ""}
            placeholder="detect"
            onChange={(e) => set("delimiter", e.target.value || null)}
          />
        </label>
        <label>
          Quote character
          <input
            type="text"
            data-testid="parse-quote"
            maxLength={1}
            value={options.quote ?? ""}
            placeholder="detect"
            onChange={(e) => set("quote", e.target.value || null)}
          />
        </label>
        <label>
          Skip lines
          <input
            type="number"
            data-testid="parse-skip"
            min={0}
            max={1000}
            value={options.skip_lines}
            onChange={(e) => set("skip_lines", Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
        </>)}
        <label>
          Encoding
          <select
            data-testid="parse-encoding"
            value={options.encoding}
            onChange={(e) => set("encoding", e.target.value)}
          >
            {ENCODINGS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        {!json && (
        <label className="ds-parse-wide">
          Read as empty
          <textarea
            data-testid="parse-nulls"
            rows={2}
            value={nulls}
            placeholder="one per line, e.g. NA"
            onChange={(e) => {
              setNulls(e.target.value);
              rehearse.reset();
            }}
          />
        </label>
        )}
        {!json && (
        <label className="ds-parse-wide">
          Date formats
          {/* p.26's `dateFormat`: a JodaTime pattern per column (§765). */}
          <textarea
            data-testid="parse-dates"
            rows={2}
            value={dates}
            placeholder="column: pattern, one per line, e.g. when: dd/MM/yyyy"
            onChange={(e) => {
              setDates(e.target.value);
              rehearse.reset();
            }}
          />
        </label>
        )}
      </div>
      <div className="ds-parse-switches">
        {([
          ["header", "First row names the columns"],
          ["drop_bad_rows", "Drop rows that do not fit"],
          ["add_file_path", "Add a file path column"],
          ["add_imported_at", "Add an import time column"],
          ["add_row_number", "Add a row number column"],
          ["add_byte_offset", "Add a byte offset column"],
        ] as const).filter(([key]) => !json || !DELIMITED_ONLY.includes(key)).map(([key, label]) => (
          <label key={key}>
            <input
              type="checkbox"
              data-testid={`parse-${key}`}
              checked={options[key]}
              onChange={(e) => set(key, e.target.checked)}
            />
            {label}
          </label>
        ))}
      </div>

      {problem && (
        <p className="form-error" data-testid="parse-problem">{problem}</p>
      )}
      {willDo.length > 0 && (
        <p className="soft ds-note" data-testid="parse-summary">
          Reading it this way: {willDo.join("; ")}.
        </p>
      )}
      {(rehearse.isError || keep.isError) && (
        <div className="form-error" data-testid="parse-error">
          {(rehearse.error ?? keep.error) instanceof ApiError
            ? ((rehearse.error ?? keep.error) as ApiError).message
            : "Couldn't read the file that way."}
        </div>
      )}
      <div className="form-actions">
        <button
          type="button"
          className="btn quiet"
          data-testid="parse-preview"
          disabled={rehearse.isPending || problem !== ""}
          onClick={() => rehearse.mutate()}
        >
          Preview
        </button>
        <button
          type="button"
          className="btn"
          data-testid="parse-apply"
          // Only after a rehearsal: p.24's point is that you see the effect
          // before choosing it, and a re-parse writes a version.
          disabled={keep.isPending || !rehearse.isSuccess}
          onClick={() => keep.mutate()}
        >
          Apply
        </button>
      </div>
      {rehearse.isSuccess && (
        <div data-testid="parse-result">
          <p className="soft ds-note">
            {rehearse.data.row_count.toLocaleString()} rows,{" "}
            {rehearse.data.columns.length} columns, read this way.
          </p>
          <Table
            result={{
              columns: rehearse.data.columns,
              rows: rehearse.data.rows as unknown[][],
              total_rows: rehearse.data.row_count,
              truncated: rehearse.data.truncated,
            }}
          />
        </div>
      )}
    </div>
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
  // **A page at a time, newest first (§879).** A dataset synced every five
  // minutes has a hundred thousand versions a year, and this asked for every
  // one of them, each with its schema and a storage lookup, on every visit.
  // Each row arrives with what reading it needed the rest for.
  const versions = useInfiniteQuery({
    queryKey: ["ds-versions", did],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => datasetApi.versions(wid, pid, did, { before: pageParam }),
    getNextPageParam: olderPage,
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
  const rows = versions.data.pages.flatMap((p) => p.items);
  const summary = versions.data.pages[0]!;
  const newest = rows[0];
  if (newest === undefined) return <p className="state">No versions recorded yet.</p>;

  return (
    <>
      <p className="soft ds-note">
        Every commit to this dataset. A version&apos;s contents never change once
        written, which is what makes the row counts below comparable — and what
        makes any of them readable years later.
      </p>
      <p className="soft ds-note" data-testid="current-view">{currentViewText(summary)}</p>
      <div className="ds-scroll">
        <table className="ds-table">
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">Rows</th>
              <th scope="col">Columns</th>
              <th scope="col">Produced by</th>
              <th scope="col">Transaction</th>
              <th scope="col">Kept</th>
              <th scope="col">When</th>
              <th scope="col"><span className="ds-sr">View</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((v) => {
              const current = newest.version_number;
              const delta = v.previous_row_count == null ? null : v.row_count - v.previous_row_count;
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
                  {/* p.22's type, with p.26's consequence beside it: a
                      SNAPSHOT (or the first version) begins a view. */}
                  <td
                    data-testid="transaction"
                    data-version={v.version_number}
                    title={TRANSACTION_MEANING[v.transaction_type]}
                  >
                    {v.transaction_type}
                    {v.starts_view && (
                      <span className="soft"> · new view</span>
                    )}
                  </td>
                  <td>
                    {v.size_bytes == null ? (
                      // Not the same as "small": the object is not where the
                      // row says it is, so this version cannot be read.
                      <span className="ds-gone">not stored</span>
                    ) : (
                      bytesText(v.size_bytes)
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
      {/* What this page is of the whole, and the way to the rest (§879): a
          history that stopped at a page and said nothing would read as a
          dataset with fewer versions than it has. */}
      {rows.length < summary.total && (
        <p className="soft ds-note" data-testid="history-more">
          Showing the newest {rows.length.toLocaleString()} of {summary.total.toLocaleString()} versions.{" "}
          <button type="button" className="btn quiet" data-testid="history-older"
                  disabled={versions.isFetchingNextPage || !versions.hasNextPage}
                  onClick={() => void versions.fetchNextPage()}>
            {versions.isFetchingNextPage ? "Loading…" : "Older versions"}
          </button>
        </p>
      )}
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
      {detail.data?.origin === "sync" && detail.data.connection_id && (
        <NextSync wid={wid} pid={pid} did={did} connectionId={detail.data.connection_id} />
      )}
      {retention.data && (
        <p className="ds-retention">
          Keeping {retention.data.versions} version
          {retention.data.versions === 1 ? "" : "s"} of this dataset costs{" "}
          <strong>{bytesText(retention.data.total_bytes)}</strong>. Nothing is deleted
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

/** p.73 and p.77's **Force a snapshot on the next build**, for a dataset an
 * incremental sync writes (§629): where the next sync starts, and the one
 * press that makes it read the whole table. `lib/dataset-rollback.nextSyncNote`
 * says why the next sync is the next build. Nothing for any other dataset. */
function NextSync({ wid, pid, did, connectionId }: {
  wid: string;
  pid: string;
  did: string;
  connectionId: string;
}) {
  const qc = useQueryClient();
  const sync = useQuery({
    queryKey: ["scheduled-sync", connectionId],
    queryFn: () => scheduledSyncApi.get(wid, pid, connectionId),
    retry: false,
  });
  const force = useMutation({
    mutationFn: () => scheduledSyncApi.forgetCursor(wid, pid, connectionId),
    onSuccess: (updated) => qc.setQueryData(["scheduled-sync", connectionId], updated),
  });
  const note = nextSyncNote(sync.data, did);
  if (!note) return null;
  return (
    <div className="ds-note" data-testid="next-sync">
      <p data-testid="next-sync-text">{note.text}</p>
      {!note.forced && (
        <>
          <button
            type="button"
            className="btn"
            data-testid="force-snapshot"
            disabled={force.isPending}
            onClick={() => force.mutate()}
          >
            Force a snapshot on the next sync
          </button>
          <p className="soft">
            Nothing changes until the next sync, which then reads every row and merges
            them by key. The history above stays as it is.
          </p>
        </>
      )}
      {force.isError && (
        <p className="form-error" data-testid="force-snapshot-error">
          {(force.error as Error).message}
        </p>
      )}
    </div>
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
        inspect={{ workspaceId: resource.workspace_id, projectId: resource.project_id! }}
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

/**
 * p.2's rename, and what it would cost (§435).
 *
 * **In Details rather than in a header, because this application has no header
 * of its own.** p.2 puts the file operations beside the name; here the name is
 * the shell's, above every application, and putting a control that changes it
 * into a bar this component does not own would be reaching past the screen.
 * The other facts about the dataset are here, and so is the one that changes
 * one of them.
 *
 * **The cost is on the screen before the button is pressed, and it is on the
 * screen when there is none.** A warning that appears only sometimes is one a
 * reader learns to look for; its absence has to say something too.
 */
function RenameDataset({
  wid, pid, did, current,
}: { wid: string; pid: string; did: string; current: string }) {
  const queryClient = useQueryClient();
  const [typed, setTyped] = useState(current);
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  /** What named this dataset *before* the rename, kept because the live list
   *  is about the new name and immediately says nothing declares it.
   *
   *  **That sentence is true and, on its own, misleading.** The files that
   *  declared the old name are broken at exactly this moment, and a screen
   *  that answered a rename with "renaming it breaks nothing" would be
   *  reassuring somebody about the thing they have just done. So the list
   *  they were warned about stays on screen as what is left to fix. */
  const [broke, setBroke] = useState<
    { name: string; files: DatasetReference[] } | null
  >(null);

  const references = useQuery({
    queryKey: ["ds-references", did],
    queryFn: () => datasetApi.references(wid, pid, did),
  });

  const rename = useMutation({
    mutationFn: (name: string) => datasetApi.update(wid, pid, did, { name }),
    onSuccess: (next) => {
      setFailure(null);
      setDone(next.name);
      setTyped(next.name);
      const named = [
        ...(references.data?.writes ?? []),
        ...(references.data?.reads ?? []),
      ];
      setBroke(named.length > 0 ? { name: current, files: named } : null);
      // The name is on the shell's breadcrumb and in every listing, and the
      // references are keyed on it, so all three have to hear about it.
      queryClient.invalidateQueries({ queryKey: ["ds-detail", did] });
      queryClient.invalidateQueries({ queryKey: ["ds-references", did] });
      queryClient.invalidateQueries({ queryKey: ["datasets", pid] });
      queryClient.invalidateQueries({ queryKey: ["resource", did] });
    },
    onError: (e: Error) =>
      setFailure(e instanceof ApiError ? e.message : "Couldn't rename it."),
  });

  const problem = renameProblem(current, typed);
  const found = references.data;
  const named = (found?.reads.length ?? 0) + (found?.writes.length ?? 0);

  return (
    <section className="ds-rename" data-testid="dataset-rename">
      <h2 className="ds-h2">Name</h2>
      <div className="ds-rename-row">
        <input
          type="text"
          aria-label="Dataset name"
          data-testid="rename-input"
          value={typed}
          onChange={(e) => {
            setTyped(e.target.value);
            setDone(null);
          }}
        />
        <button
          type="button"
          className="btn"
          data-testid="rename-save"
          disabled={problem !== null || rename.isPending}
          onClick={() => rename.mutate(nameToSend(typed))}
        >
          {rename.isPending ? "Renaming…" : "Rename"}
        </button>
      </div>
      {/* The refusal is said rather than only disabling the button: a control
          that is grey for a reason nobody can read is a control that looks
          broken (§214). Not while the name is simply unchanged, which is the
          state the form opens in and needs no explaining. */}
      {problem && typed.trim() !== current && (
        <p className="login-note" data-testid="rename-problem">{problem}</p>
      )}
      {failure && <p className="form-error" data-testid="rename-failure">{failure}</p>}
      {done && (
        <p className="login-note" data-testid="rename-done">
          Renamed to {done}. Its link has not changed.
        </p>
      )}
      {broke && (
        <div className="ds-rename-broke" data-testid="rename-broke">
          <p className="ds-rename-warning">
            {broke.files.length === 1 ? "1 file" : `${broke.files.length} files`}
            {" still declare"}{broke.files.length === 1 ? "s" : ""}{" "}
            <code>{broke.name}</code>. Open each and update the declaration.
          </p>
          <ul className="ds-rename-files">
            {broke.files.map((r) => (
              <li key={`${r.repository_id}:${r.path}`}>
                <Link href={fileHref(r)}>{r.repository} / {r.path}</Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {references.isPending && <p className="soft">Checking what names it…</p>}
      {found && (
        <p
          className={found.warning ? "ds-rename-warning" : "login-note"}
          data-testid="rename-warning"
        >
          {found.warning ?? NOTHING_NAMES_IT}
        </p>
      )}
      {found && named > 0 && (
        <ul className="ds-rename-files" data-testid="rename-files">
          {[...found.writes.map((r) => ({ ...r, writes: true })),
            ...found.reads.map((r) => ({ ...r, writes: false }))].map((r) => (
            <li key={`${r.repository_id}:${r.path}:${r.writes}`}>
              <span className="chip">{r.writes ? "writes" : "reads"}</span>
              <Link href={fileHref(r)}>{r.repository} / {r.path}</Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** p.3's "tags" (§511): the ones this resource carries, and, for an editor
 *  of its project, a way to add and remove them. The workspace's tags are
 *  made on its Tags page (`app-building` p.35). */
function ResourceTags({ wid, pid, rid }: { wid: string; pid: string; rid: string }) {
  const queryClient = useQueryClient();
  const on = useQuery({ queryKey: ["tags-on", rid], queryFn: () => resourceTags.on(wid, rid) });
  const all = useQuery({ queryKey: ["resource-tags", wid], queryFn: () => resourceTags.list(wid) });
  const project = useQuery({
    queryKey: ["project", wid, pid],
    queryFn: () => platformApi.project(wid, pid),
  });
  const editor = canEditProject(project.data?.effective_role ?? "viewer");
  const change = useMutation({
    mutationFn: ({ tid, add }: { tid: string; add: boolean }) =>
      add ? resourceTags.add(wid, rid, tid) : resourceTags.takeOff(wid, rid, tid),
    onSuccess: async (tags) => {
      queryClient.setQueryData(["tags-on", rid], tags);
      await queryClient.invalidateQueries({ queryKey: ["resource-tags", wid] });
    },
  });
  const offer = all.data && on.data ? addable(all.data, on.data) : [];

  return (
    <>
      <h2 className="ds-h2">Tags</h2>
      {on.data && on.data.length === 0 && (
        <p className="soft" data-testid="ds-no-tags">No tags.</p>
      )}
      {on.data && on.data.length > 0 && (
        <ul className="ds-tags" data-testid="ds-tags">
          {on.data.map((tag) => (
            <li key={tag.id} className="chip" data-testid="ds-tag">
              {tagLabel(tag)}
              {editor && (
                <button
                  type="button"
                  className="btn quiet"
                  aria-label={`Remove ${tagLabel(tag)}`}
                  data-testid="ds-tag-remove"
                  onClick={() => change.mutate({ tid: tag.id, add: false })}
                >
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {editor && offer.length > 0 && (
        <select
          data-testid="ds-tag-add"
          value=""
          onChange={(e) => e.target.value && change.mutate({ tid: e.target.value, add: true })}
        >
          <option value="">Add a tag…</option>
          {offer.map((tag) => (
            <option key={tag.id} value={tag.id}>{tagLabel(tag)}</option>
          ))}
        </select>
      )}
      {change.isError && (
        <div className="form-error" data-testid="ds-tag-error">
          {change.error instanceof ApiError ? change.error.message : "Couldn't change the tags."}
        </div>
      )}
    </>
  );
}

function DetailsTab({ wid, pid, did, rid }: { wid: string; pid: string; did: string; rid: string }) {
  const detail = useQuery({
    queryKey: ["ds-detail", did],
    queryFn: () => datasetApi.get(wid, pid, did),
  });
  const health = useQuery({
    queryKey: ["ds-health", did],
    queryFn: () => datasetApi.health(wid, pid, did),
  });
  // p.3's "any tools and input datasets used to create the data" (§506).
  // Keyed on the version, so a new build asks again.
  const origin = useQuery({
    queryKey: ["ds-origin", did, detail.data?.current_version],
    queryFn: () => datasetApi.origin(wid, pid, did),
    enabled: detail.isSuccess,
  });
  // Shares `ds-versions` with the History tab, which already measures every
  // version: p.3's "size of the table" is the current one's (§509).
  // The newest page, which holds the current version (§879).
  const versions = useQuery({
    queryKey: ["ds-versions", did, "newest"],
    queryFn: () => datasetApi.versions(wid, pid, did, { limit: 1 }),
  });
  const schedules = useQuery({
    queryKey: ["ds-schedules", did],
    queryFn: () => datasetApi.schedules(wid, pid, did),
  });
  // The files an uploaded dataset is read from (§746; p.10).
  const files = useQuery({
    queryKey: ["ds-files", did],
    queryFn: () => datasetApi.files(wid, pid, did),
    enabled: detail.data?.origin === "upload",
  });
  if (detail.isPending) return <p className="state">Loading…</p>;
  if (detail.isError) return <p className="state error">{(detail.error as Error).message}</p>;

  const d = detail.data;
  return (
    <div className="ds-details">
      <RenameDataset wid={wid} pid={pid} did={did} current={d.name} />

      <dl className="app-facts">
        <div>
          <dt>Origin</dt>
          <dd>{d.origin}</dd>
        </div>
        {origin.data && (
          <div>
            <dt>Made by</dt>
            <dd data-testid="ds-made-by">
              {origin.data.tool?.resource_id ? (
                <Link href={originHref(origin.data.tool.resource_id)}>
                  {madeByText(origin.data)}
                </Link>
              ) : (
                madeByText(origin.data)
              )}
              {origin.data.note && <span className="soft"> — {origin.data.note}</span>}
            </dd>
          </div>
        )}
        {origin.data && origin.data.inputs.length > 0 && (
          <div>
            <dt>Made from</dt>
            <dd data-testid="ds-made-from">
              {origin.data.inputs.map((input, i) => (
                <span key={input.resource_id}>
                  {i > 0 && ", "}
                  <Link href={originHref(input.resource_id)}>{input.name}</Link>
                </span>
              ))}
            </dd>
          </div>
        )}
        {files.data && files.data.length > 0 && (
          <div>
            <dt>Files</dt>
            <dd>
              <ul className="ds-files" data-testid="ds-files">
                {files.data.map((f) => (
                  <li key={f.filename} data-testid="ds-file">
                    {f.filename}{" "}
                    <span className="soft">
                      — v{f.version_number}
                      {f.uploaded_by_name ? `, ${f.uploaded_by_name}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        <div>
          <dt>Rows</dt>
          <dd>{d.row_count.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Size</dt>
          <dd data-testid="ds-size">
            {sizeText(d.table_schema.length, currentBytes(versions.data?.items, d.current_version))}
          </dd>
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

      {/* p.3's "any configured build schedules that will run to update the
          dataset" (§508). */}
      <ResourceTags wid={wid} pid={pid} rid={rid} />

      <h2 className="ds-h2">Schedules</h2>
      {schedules.isError && <p className="soft">No schedule information available.</p>}
      {schedules.data && schedules.data.length === 0 && (
        <p className="soft" data-testid="ds-no-schedules">{NO_SCHEDULES}</p>
      )}
      {schedules.data && schedules.data.length > 0 && (
        <ul className="ds-health" data-testid="ds-schedules">
          {schedules.data.map((s) => (
            <li key={`${s.kind}-${s.name}`} data-testid="ds-schedule">
              <Link href={`/r/${s.resource_id}`}>{scheduleName(s)}</Link>{" "}
              <span className="soft">{scheduleWhen(s)}</span>
            </li>
          ))}
        </ul>
      )}

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
