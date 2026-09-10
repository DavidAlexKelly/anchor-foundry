"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  ApiError,
  code as codeApi,
  datasets as dsApi,
  models as modelApi,
  repositories as repoApi,
} from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { Model } from "@/lib/types";
import { authoredInRepository, canAdopt, pathProblem, readOnlyReason } from "@/lib/model-authoring";
import { canMove, chosen, defaultMessage, moveLabel } from "@/lib/bulk-adoption";
import { attribution, emptyNote, isChangeSet, scopeLabel } from "@/lib/transform-history";
import {
  describe as describeProposal,
  unrepositoried,
  unrepositoriedNote,
} from "@/lib/pull-requests";
import { ReviewSurface } from "@/components/code/review-surface";
import { useUrlState } from "@/components/use-url-state";

/** A unified diff, coloured by line kind.
 *
 * Carried over from `code/page.tsx` when §291 deleted it, because the version
 * diff went with it and nothing else could render one. The classes are the
 * ones `globals.css` already defines. */
function DiffText({ text, testId }: { text: string; testId?: string }) {
  if (!text.trim()) {
    return (
      <p className="canvas-widget-empty" data-testid={testId}>
        No difference between these versions.
      </p>
    );
  }
  return (
    <pre className="code-diff" data-testid={testId}>
      {text.split("\n").map((line, i) => {
        const kind =
          line.startsWith("+++") || line.startsWith("---")
            ? "meta"
            : line.startsWith("@@")
              ? "hunk"
              : line.startsWith("+")
                ? "add"
                : line.startsWith("-")
                  ? "del"
                  : "ctx";
        return (
          <span key={i} className={`diff-line diff-${kind}`}>
            {line || " "}
          </span>
        );
      })}
    </pre>
  );
}

const DEFAULT_SQL = "SELECT *\n  FROM orders\n LIMIT 100";
const DEFAULT_PYTHON = "output = orders.copy()\n";

function RunBadge({ model }: { model: Model }) {
  if (!model.last_run_status) {
    return <span className="status-unconfigured"><span className="status-dot" /><span className="status-label">Never run</span></span>;
  }
  const cls = model.last_run_status === "succeeded" ? "status-ok"
    : model.last_run_status === "failed" ? "status-error" : "status-testing";
  return (
    <span className={cls}>
      <span className="status-dot" />
      <span className="status-label">{model.last_run_status}</span>
    </span>
  );
}

function ScheduleSummary({ model }: { model: Model }) {
  if (model.trigger_mode === "upstream") {
    // The watermark is the newest input version already reacted to; until
    // it's set the model has never fired, which is the same "due now" the
    // cron branch shows for a NULL next_run_at.
    const since = model.upstream_watermark
      ? `since ${new Date(model.upstream_watermark).toLocaleString()}`
      : "due now";
    const names = model.inputs.map((i) => i.dataset_name).join(", ");
    return (
      <span title={names ? `Watching ${names}` : undefined}>
        <span className="chip">on new input data</span>
        <div className="slug">{since}</div>
      </span>
    );
  }
  if (model.trigger_mode !== "cron") return <span className="count">manual</span>;
  const next = model.next_run_at ? new Date(model.next_run_at).toLocaleString() : "due now";
  return (
    <span title={model.cron_schedule ?? undefined}>
      <span className="chip">{model.cron_schedule}</span>
      <div className="slug">next: {next}</div>
    </span>
  );
}

function HistoryDialog({
  workspaceId,
  projectId,
  model,
  canEdit,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  model: Model;
  canEdit: boolean;
  onClose: () => void;
}) {
  const [open, setOpen] = useState<{ version: number; view: "code" | "diff" } | null>(
    null,
  );
  const queryClient = useQueryClient();
  const history = useQuery({
    queryKey: ["model-versions", model.id],
    queryFn: () => modelApi.versions(workspaceId, projectId, model.id),
  });
  // **The last thing that lived only on the Code pillar page (§291).** §278's
  // table listed `changeSet` + `diff` together and §280 moved only the first:
  // the history dialog could show what a version *is* and not what it
  // *changed*. Deleting the page without this would have taken "what changed"
  // away from every transform outside a repository - silently, which is the
  // exact failure §278 stopped.
  const diff = useQuery({
    queryKey: ["code-diff", model.id, open?.version],
    queryFn: () =>
      codeApi.diff(workspaceId, projectId, model.id, (open!.version - 1) || null, open!.version),
    enabled: open?.view === "diff",
  });
  const restore = useMutation({
    mutationFn: (versionNumber: number) =>
      modelApi.restoreVersion(workspaceId, projectId, model.id, versionNumber),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["model-versions", model.id] });
      await queryClient.invalidateQueries({ queryKey: ["models", projectId] });
    },
  });

  return (
    <Dialog open wide title={`${model.name} — history`} onClose={onClose}>
      <p className="login-note" style={{ marginTop: 0 }}>
        Every saved definition, newest first. Restoring writes a new version
        rather than deleting the ones after it, so the record stays true.
      </p>
      {history.isPending && <div className="state">Loading history…</div>}
      {restore.isError && (
        <div className="form-error">
          {restore.error instanceof ApiError ? restore.error.message : "Couldn't restore."}
        </div>
      )}
      <div className="data-grid">
        <table>
          <thead>
            <tr>
              <th>Version</th>
              <th>Saved</th>
              <th>By</th>
              <th>Inputs</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {history.data?.map((v, index) => (
              <tr key={v.id}>
                <td>
                  <strong>v{v.version_number}</strong>
                  {index === 0 && <span className="chip"> current</span>}
                  {v.restored_from !== null && (
                    <div className="slug">reverted to v{v.restored_from}</div>
                  )}
                </td>
                <td>{new Date(v.created_at).toLocaleString()}</td>
                <td className="slug">{v.created_by_email ?? "—"}</td>
                <td className="slug">
                  {v.inputs.map((i) => i.input_alias).join(", ") || "none"}
                </td>
                <td>
                  <div className="row-actions">
                    <button
                      className="btn quiet"
                      style={{ padding: "3px 9px", fontSize: 12 }}
                      data-testid={`version-${v.version_number}-code`}
                      onClick={() =>
                        setOpen(
                          open?.version === v.version_number && open.view === "code"
                            ? null
                            : { version: v.version_number, view: "code" },
                        )
                      }
                    >
                      {open?.version === v.version_number && open.view === "code"
                        ? "Hide"
                        : "Code"}
                    </button>
                    {/* **What it changed**, which is a different question from
                        what it is - and the one a history is usually read to
                        answer. Not offered on v1: there is no version before
                        it, and a diff of everything against nothing is the
                        file, which the button next door already shows. */}
                    {v.version_number > 1 && (
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        data-testid={`version-${v.version_number}-changes`}
                        onClick={() =>
                          setOpen(
                            open?.version === v.version_number && open.view === "diff"
                              ? null
                              : { version: v.version_number, view: "diff" },
                          )
                        }
                      >
                        {open?.version === v.version_number && open.view === "diff"
                          ? "Hide"
                          : "Changes"}
                      </button>
                    )}
                    {canEdit && index > 0 && (
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        disabled={restore.isPending}
                        onClick={() => restore.mutate(v.version_number)}
                      >
                        Restore
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open?.view === "code" && (
        <pre
          className="sql-box"
          style={{ marginTop: 10, whiteSpace: "pre-wrap", maxHeight: 240, overflow: "auto" }}
        >
          {history.data?.find((v) => v.version_number === open.version)?.code}
        </pre>
      )}
      {open?.view === "diff" && (
        <div style={{ marginTop: 10, maxHeight: 240, overflow: "auto" }}>
          {diff.isPending && <div className="state">Loading…</div>}
          {diff.isSuccess && (
            <DiffText text={diff.data.diff} testId={`version-${open.version}-diff`} />
          )}
        </div>
      )}
      <div className="form-actions">
        <button className="btn quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}

function ModelDialog({
  workspaceId,
  projectId,
  existing,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  existing: Model | null;
  onClose: () => void;
}) {
  // **The project's gate is the second reason a body can be read-only** (§277),
  // and it is a different sentence from the first: db 0038 sends the reader to
  // a file, `require_code_review` sends them to make one. Queried here rather
  // than passed in, because every dialog wants it and the answer is cached.
  const policy = useQuery({
    queryKey: ["code-review-policy", projectId],
    queryFn: () => codeApi.reviewPolicy(workspaceId, projectId),
  });
  // Null when this screen may edit the body. A sentence naming the file when
  // it may not - the reader's next move is to open it, so the message says
  // where it is rather than only that this is read-only.
  const locked = existing
    ? readOnlyReason(existing, {
        reviewRequired: policy.data?.require_code_review ?? false,
      })
    : null;
  const [name, setName] = useState(existing?.name ?? "");
  const [language, setLanguage] = useState<"sql" | "python">(existing?.language ?? "sql");
  const [code, setCode] = useState(existing?.code ?? DEFAULT_SQL);
  const [inputs, setInputs] = useState<{ dataset_id: string; input_alias: string }[]>(
    existing?.inputs.map((i) => ({ dataset_id: i.dataset_id, input_alias: i.input_alias })) ?? [],
  );
  const [triggerMode, setTriggerMode] = useState<"manual" | "cron" | "upstream">(
    existing?.trigger_mode ?? "manual",
  );
  const [cronSchedule, setCronSchedule] = useState(existing?.cron_schedule ?? "0 * * * *");
  const [healthPolicy, setHealthPolicy] = useState<"ignore" | "warn" | "block">(
    existing?.input_health_policy ?? "ignore",
  );
  const queryClient = useQueryClient();

  const availableDatasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });

  const save = useMutation({
    mutationFn: () =>
      existing
        ? modelApi.update(workspaceId, projectId, existing.id, {
            name,
            code,
            inputs,
            trigger_mode: triggerMode,
            cron_schedule: triggerMode === "cron" ? cronSchedule : null,
            input_health_policy: healthPolicy,
          })
        : modelApi.create(workspaceId, projectId, { name, language, code, inputs }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["models", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
      onClose();
    },
  });

  function aliasFor(datasetId: string): string {
    const ds = availableDatasets.data?.find((d) => d.id === datasetId);
    const base = (ds?.slug ?? "input").replace(/[^a-z0-9_]/g, "_").replace(/^[0-9]+/, "");
    return base || "input";
  }

  return (
    <Dialog open wide title={existing ? `Edit ${existing.name}` : "New model"} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Name">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={200}
          />
        </Field>
        {existing ? (
          <Field label="Language">
            <span className="chip">{existing.language === "python" ? "Python" : "SQL"}</span>
          </Field>
        ) : (
          <Field label="Language" hint="Can't be changed once the model is created">
            <select
              value={language}
              onChange={(e) => {
                const next = e.target.value as "sql" | "python";
                setLanguage(next);
                if (code === DEFAULT_SQL || code === DEFAULT_PYTHON) {
                  setCode(next === "python" ? DEFAULT_PYTHON : DEFAULT_SQL);
                }
              }}
            >
              <option value="sql">SQL</option>
              <option value="python">Python</option>
            </select>
          </Field>
        )}
        <Field
          label="Input datasets"
          hint="Each input is a table (SQL) or a pandas DataFrame (Python), named by its alias"
        >
          <div>
            {inputs.map((input, index) => (
              <div key={index} className="row-actions" style={{ marginBottom: 6 }}>
                <select
                  value={input.dataset_id}
                  onChange={(e) => {
                    const next = [...inputs];
                    next[index] = {
                      dataset_id: e.target.value,
                      input_alias: input.input_alias || aliasFor(e.target.value),
                    };
                    setInputs(next);
                  }}
                  required
                >
                  <option value="">Choose a dataset…</option>
                  {availableDatasets.data?.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 12.5,
                    padding: "4px 8px",
                    border: "1px solid var(--line-strong)",
                    borderRadius: "var(--radius)",
                    width: 140,
                  }}
                  value={input.input_alias}
                  onChange={(e) => {
                    const next = [...inputs];
                    next[index] = { ...input, input_alias: e.target.value };
                    setInputs(next);
                  }}
                  placeholder="alias"
                  required
                />
                <button
                  type="button"
                  className="btn danger"
                  style={{ padding: "3px 9px", fontSize: 12 }}
                  onClick={() => setInputs(inputs.filter((_, i) => i !== index))}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn quiet"
              style={{ padding: "4px 10px", fontSize: 12.5 }}
              onClick={() => setInputs([...inputs, { dataset_id: "", input_alias: "" }])}
            >
              Add input
            </button>
          </div>
        </Field>
        <Field
          label={(existing?.language ?? language) === "python" ? "Python" : "SQL"}
          hint={
            // **The reason, when there is one.** `models.update` refuses a body
            // edit to a repository-authored transform (db 0038), and until §275
            // this page offered the edit anyway - `source_repo_id` was on the
            // wire from §94 and absent from the shared type, so no screen could
            // read it. A control that looks like it works is §214's shape.
            locked
              ? locked
              : (existing?.language ?? language) === "python"
                ? "Each input alias is a pandas DataFrame; set an `output` DataFrame with the result"
                : "Query the inputs by their aliases; the result becomes the output dataset"
          }
        >
          <textarea
            className="sql-box"
            style={{ minHeight: 140 }}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            spellCheck={false}
            readOnly={Boolean(locked)}
            data-testid="model-code"
          />
        </Field>
        {existing && (
          <Field
            label="Trigger"
            hint={
              triggerMode === "upstream"
                ? "Runs when any input dataset gains a new version — chain models by pointing one at another's output"
                : "Scheduled and upstream runs are queued for the background worker, same as Python"
            }
          >
            <div className="row-actions">
              <select
                value={triggerMode}
                onChange={(e) =>
                  setTriggerMode(e.target.value as "manual" | "cron" | "upstream")
                }
              >
                <option value="manual">Manual only</option>
                <option value="cron">On a schedule</option>
                <option value="upstream">When inputs change</option>
              </select>
              {triggerMode === "cron" && (
                <input
                  type="text"
                  style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, width: 140 }}
                  value={cronSchedule}
                  onChange={(e) => setCronSchedule(e.target.value)}
                  placeholder="0 * * * *"
                  required
                />
              )}
            </div>
          </Field>
        )}
        {existing && (
          <Field
            label="Input data quality"
            hint="Checks come from each input dataset's Checks tab; only a failing check counts"
          >
            <select
              value={healthPolicy}
              onChange={(e) =>
                setHealthPolicy(e.target.value as "ignore" | "warn" | "block")
              }
            >
              <option value="ignore">Run regardless</option>
              <option value="warn">Run, but record failing checks</option>
              <option value="block">Don&apos;t run if an input failed its checks</option>
            </select>
          </Field>
        )}
        {save.isError && (
          <div className="form-error">
            {save.error instanceof ApiError ? save.error.message : "Couldn't save the model."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn"
            disabled={
              save.isPending ||
              Boolean(locked) ||
              !name.trim() ||
              !code.trim() ||
              // An upstream model with nothing to watch would never fire;
              // the API refuses it with a 422, this just says so sooner.
              (triggerMode === "upstream" && !inputs.some((i) => i.dataset_id))
            }
          >
            {save.isPending ? "Saving…" : existing ? "Save changes" : "Create model"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function AdoptDialog({
  workspaceId,
  projectId,
  model,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  model: Model;
  onClose: () => void;
}) {
  const params = useParams<{ workspace: string; project: string }>();
  const [repositoryId, setRepositoryId] = useState("");
  const [branch, setBranch] = useState("main");
  const [path, setPath] = useState("");
  const queryClient = useQueryClient();

  const repositories = useQuery({
    queryKey: ["repositories", projectId],
    queryFn: () => repoApi.list(workspaceId, projectId),
  });

  const adopt = useMutation({
    mutationFn: () =>
      modelApi.adopt(workspaceId, projectId, model.id, {
        repository_id: repositoryId,
        branch,
        // **Empty means "you choose".** The server derives a path from the
        // model's name through `datasets.slugify`; deriving it here would be a
        // second copy of that rule, and the disagreement would be a file
        // written where this screen did not predict (§191).
        path: path.trim() || null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["models", projectId] });
      onClose();
    },
  });

  const problem = pathProblem(path, model.language);
  const noRepositories = repositories.isSuccess && repositories.data.length === 0;

  return (
    <Dialog open title={`Move ${model.name} into a repository`} onClose={onClose}>
      <p className="login-note" style={{ marginTop: 0 }}>
        The transform is written to a file with a declaration above it, and
        edited there from now on. Its code is copied through unchanged, so
        nothing about what it computes changes — but a direct edit here will be
        refused afterwards, because the repository would otherwise describe a
        pipeline that is not the one running.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          adopt.mutate();
        }}
      >
        <Field label="Repository">
          {noRepositories ? (
            // Not an empty picker: a control with nothing in it reads as
            // broken, and the thing to do about it is elsewhere.
            //
            // **And it is a link, because it was a lie.** This said "create
            // one on the Code screen" while the Code screen had no such
            // control - §290's shape, a pointer at a place that cannot do
            // what it says. §291 gave that screen the control; the link is
            // what makes the two testable together rather than two sentences
            // that have to be kept in agreement by hand.
            <p className="login-note" data-testid="adopt-no-repositories">
              This project has no repositories yet.{" "}
              <Link href={`/${params.workspace}/${params.project}/code`}>
                Create one on the Code screen
              </Link>
              , then move this transform into it.
            </p>
          ) : (
            <select
              value={repositoryId}
              data-testid="adopt-repository"
              onChange={(e) => setRepositoryId(e.target.value)}
              required
            >
              <option value="">Choose a repository…</option>
              {repositories.data?.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Branch" hint="The commit lands here; publish it when you are ready.">
          <input
            type="text"
            value={branch}
            data-testid="adopt-branch"
            onChange={(e) => setBranch(e.target.value)}
            required
          />
        </Field>
        <Field
          label="Path"
          hint={problem ?? "Leave empty to derive one from the transform's name."}
        >
          <input
            type="text"
            value={path}
            data-testid="adopt-path"
            placeholder={`src/… ${model.language === "python" ? ".py" : ".sql"}`}
            onChange={(e) => setPath(e.target.value)}
          />
        </Field>
        {adopt.isError && (
          // The server's sentence, not a summary of it. Its refusals name the
          // value that cannot be written, and a screen that replaced them with
          // "could not move" would throw away the only part that helps.
          <div className="form-error" data-testid="adopt-error">
            {adopt.error instanceof ApiError ? adopt.error.message : "Couldn't move it."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn"
            data-testid="adopt-confirm"
            disabled={adopt.isPending || !repositoryId || Boolean(problem)}
          >
            {adopt.isPending ? "Moving…" : "Move it"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ModelRow({
  workspaceId,
  projectId,
  model,
  canEdit,
  selected,
  onSelect,
}: {
  workspaceId: string;
  projectId: string;
  model: Model;
  canEdit: boolean;
  /** Null when this transform cannot be moved, so the cell is empty rather
   *  than holding a control that answers nothing (§289). */
  selected: boolean | null;
  onSelect: (on: boolean) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [adopting, setAdopting] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const queryClient = useQueryClient();
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["models", projectId] });
    await queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
    await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
  };

  const run = useMutation({
    mutationFn: () => modelApi.run(workspaceId, projectId, model.id),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => modelApi.remove(workspaceId, projectId, model.id),
    onSuccess: refresh,
  });

  const result = run.data;

  return (
    <tr>
      {/* **Empty rather than disabled when it cannot move** (§289). A greyed
          checkbox invites the question "why not"; nothing there says the row
          is not part of this, and the row already says why - it is authored in
          a repository. */}
      <td style={{ width: 28 }}>
        {selected !== null && (
          <input
            type="checkbox"
            checked={selected}
            aria-label={`Move ${model.name} into a repository`}
            data-testid="model-pick"
            onChange={(e) => onSelect(e.target.checked)}
          />
        )}
      </td>
      <td>
        <strong>{model.name}</strong>
        <div className="slug">
          {model.inputs.map((i) => i.input_alias).join(", ") || "no inputs"} →{" "}
          {model.output_dataset_id ? "output dataset" : "not yet run"}
        </div>
        {authoredInRepository(model) && (
          // Said on the row rather than only inside the dialog, because the
          // question "why can I not edit this one" is asked from out here.
          <div className="slug" data-testid="model-authored-in">
            authored in a repository · {model.source_path}
          </div>
        )}
        {result && result.status === "queued" && (
          <p className="login-note" style={{ margin: "6px 0 0" }}>
            Queued - Python models run on the background worker. Check back for the result.
          </p>
        )}
        {result && result.status !== "queued" && !result.ok && (
          <div className="form-error" style={{ marginTop: 6 }}>{result.error}</div>
        )}
        {result && result.status !== "queued" && result.ok && result.output_dataset && (
          <p className="login-note" style={{ margin: "6px 0 0" }}>
            Produced {result.rows_produced.toLocaleString()} rows → {result.output_dataset.name}{" "}
            v{result.output_dataset.current_version} (see Datasets)
          </p>
        )}
      </td>
      <td>
        <RunBadge model={model} />
        {result && !result.ok && result.error?.startsWith("blocked:") && (
          <div className="slug" style={{ color: "var(--danger)" }}>
            input data quality
          </div>
        )}
      </td>
      <td>
        <ScheduleSummary model={model} />
        {model.input_health_policy !== "ignore" && (
          <div className="slug" title="Migration 0022: only a failing check gates a run">
            {model.input_health_policy === "block"
              ? "blocks on failing input"
              : "warns on failing input"}
          </div>
        )}
      </td>
      <td>
        {canEdit && (
          <div className="row-actions">
            <button
              className="btn"
              style={{ padding: "3px 11px", fontSize: 12 }}
              disabled={run.isPending}
              onClick={() => run.mutate()}
            >
              {run.isPending ? "Running…" : "Run"}
            </button>
            <button
              className="btn quiet"
              style={{ padding: "3px 9px", fontSize: 12 }}
              onClick={() => setEditing(true)}
            >
              Edit
            </button>
            <button
              className="btn quiet"
              style={{ padding: "3px 9px", fontSize: 12 }}
              onClick={() => setShowHistory(true)}
            >
              History
            </button>
            {canAdopt(model) && (
              <button
                className="btn quiet"
                style={{ padding: "3px 9px", fontSize: 12 }}
                data-testid="model-adopt"
                onClick={() => setAdopting(true)}
              >
                Move into a repository
              </button>
            )}
            <button
              className="btn danger"
              style={{ padding: "3px 9px", fontSize: 12 }}
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Delete ${model.name}? Its output dataset is kept.`)) {
                  remove.mutate();
                }
              }}
            >
              Delete
            </button>
          </div>
        )}
        {showHistory && (
          <HistoryDialog
            workspaceId={workspaceId}
            projectId={projectId}
            model={model}
            canEdit={canEdit}
            onClose={() => setShowHistory(false)}
          />
        )}
        {editing && (
          <ModelDialog
            workspaceId={workspaceId}
            projectId={projectId}
            existing={model}
            onClose={() => setEditing(false)}
          />
        )}
        {adopting && (
          <AdoptDialog
            workspaceId={workspaceId}
            projectId={projectId}
            model={model}
            onClose={() => setAdopting(false)}
          />
        )}
      </td>
    </tr>
  );
}

export default function ModelsPage() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const [creating, setCreating] = useState(false);
  const [showProjectHistory, setShowProjectHistory] = useState(false);
  // **Which transforms to move together** (§289). Ids rather than models, so a
  // refetch that replaces the row objects does not silently empty the
  // selection - the thing being chosen is the transform, not the render of it.
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const list = useQuery({
    queryKey: ["models", project?.id],
    queryFn: () => modelApi.list(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });

  const canEdit = project ? project.effective_role !== "viewer" : false;

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · models</p>
          <h1>Models</h1>
        </div>
        <div className="row-actions">
          {/* **The project's transform history, not one model's** (§280). The
              per-model History button in each row is `model_versions` for that
              model; this is every transform in the project, with the change
              sets that group them — decision 0001's "one genuinely new
              concept", which §278 found lived only on the page B.1 deletes. */}
          <button
            className="btn quiet"
            data-testid="project-history"
            onClick={() => setShowProjectHistory(true)}
          >
            Change history
          </button>
          {canEdit && (
            <button className="btn" onClick={() => setCreating(true)}>
              New model
            </button>
          )}
        </div>
      </div>
      {showProjectHistory && workspace && project && (
        <ProjectHistoryDialog
          workspaceId={workspace.id}
          projectId={project.id}
          modelCount={list.data?.length ?? 0}
          onClose={() => setShowProjectHistory(false)}
        />
      )}

      {list.isPending && <div className="state">Loading models…</div>}
      {list.isError && (
        <div className="state error">Couldn&apos;t load models. Refresh to try again.</div>
      )}
      {list.data && list.data.length === 0 && (
        <div className="empty">
          <h2>No models yet</h2>
          <p>
            Models transform datasets into new datasets with SQL - joins, filters,
            aggregations. Every run is versioned and lineage is tracked automatically.
          </p>
          {canEdit && (
            <button className="btn" onClick={() => setCreating(true)}>
              Create model
            </button>
          )}
        </div>
      )}
      {workspace && project && (
        <DirectProposals workspaceId={workspace.id} projectId={project.id} />
      )}
      {list.data && workspace && project && picked.size > 0 && (
        <MoveTogetherBar
          workspaceId={workspace.id}
          projectId={project.id}
          models={list.data}
          picked={picked}
          onDone={() => setPicked(new Set())}
        />
      )}
      {list.data && list.data.length > 0 && workspace && project && (
        <table className="table">
          <thead>
            <tr>
              <th aria-label="Move together" />
              <th>Model</th>
              <th>Last run</th>
              <th>Trigger</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {list.data.map((m) => (
              <ModelRow
                key={m.id}
                workspaceId={workspace.id}
                projectId={project.id}
                model={m}
                canEdit={canEdit}
                selected={canAdopt(m) ? picked.has(m.id) : null}
                onSelect={(on) =>
                  setPicked((current) => {
                    const next = new Set(current);
                    if (on) next.add(m.id);
                    else next.delete(m.id);
                    return next;
                  })
                }
              />
            ))}
          </tbody>
        </table>
      )}
      {creating && workspace && project && (
        <ModelDialog
          workspaceId={workspace.id}
          projectId={project.id}
          existing={null}
          onClose={() => setCreating(false)}
        />
      )}
    </main>
  );
}

/**
 * The project's transform history (§280).
 *
 * **Not the same list as a model's History**, which is `model_versions` for one
 * model, and not the same as the repository application's History tab, which is
 * commits in one repository. This is every transform in the project — including
 * ones in no repository at all — with the **change sets** that group them.
 *
 * §278 found it living only on the Code pillar page B.1 deletes. Decision 0001
 * called the change set "the one genuinely new concept": before it, *"these
 * three transforms changed together, for one reason"* could not be said.
 */
function ProjectHistoryDialog({
  workspaceId,
  projectId,
  modelCount,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  modelCount: number;
  onClose: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);

  const history = useQuery({
    queryKey: ["code-history", projectId],
    queryFn: () => codeApi.history(workspaceId, projectId),
  });
  const detail = useQuery({
    queryKey: ["code-change-set", open],
    queryFn: () => codeApi.changeSet(workspaceId, projectId, open!),
    enabled: Boolean(open),
  });

  const entries = history.data ?? [];

  return (
    <Dialog open wide title="Transform change history" onClose={onClose}>
      <p className="login-note" style={{ marginTop: 0 }}>
        Every saved transform definition in this project, newest first. A
        change set is several transforms saved together for one reason; a
        single save is still an edit and is listed the same way, without a
        message.
      </p>
      {history.isPending && <div className="state">Loading history…</div>}
      {history.isSuccess && entries.length === 0 && (
        <p className="login-note" data-testid="project-history-empty">
          {emptyNote(modelCount)}
        </p>
      )}
      <ul className="code-log" data-testid="project-history-list">
        {entries.map((entry) => (
          <li key={`${entry.kind}-${entry.id}`}>
            <button
              type="button"
              className="code-log-entry"
              data-testid={`history-${entry.id}`}
              // Only a change set has contents to open; a version row is
              // already the whole entry, and a button that expanded to nothing
              // would be a control that looks like it works.
              disabled={!isChangeSet(entry)}
              onClick={() => setOpen(open === entry.id ? null : entry.id)}
            >
              <span className="code-log-summary">{entry.summary}</span>
              <span className="code-log-meta">
                <span className="chip brass">{scopeLabel(entry)}</span>
                {attribution(entry)} · {new Date(entry.created_at).toLocaleString()}
              </span>
            </button>
            {open === entry.id && (
              <div className="slug" data-testid={`history-${entry.id}-detail`}>
                {detail.isPending && "Loading…"}
                {detail.data?.models.map((m) => (
                  <div key={m.model_id}>
                    {m.model_name} → v{m.version_number}
                  </div>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="form-actions">
        <button className="btn quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}


/** Move several transforms into a repository as one commit (§289).
 *
 * **This is what a change set becomes.** Decision 0001 called the change set
 * "the one genuinely new concept" — *"these three transforms changed together,
 * for one reason"* — and B.1 deletes the only screen that can make one. A
 * commit says the same thing about a repository's files, so the successor is
 * to adopt them together and commit together.
 *
 * The successor is only real if adopting is *together*: six adoptions are six
 * commits and six unrelated moves in the history, and a migration costing six
 * clicks per transform is one a project with forty of them will not do — which
 * strands them in practice even though nothing refused.
 */
function MoveTogetherBar({
  workspaceId,
  projectId,
  models,
  picked,
  onDone,
}: {
  workspaceId: string;
  projectId: string;
  models: Model[];
  picked: Set<string>;
  onDone: () => void;
}) {
  const [repositoryId, setRepositoryId] = useState("");
  const [branch, setBranch] = useState("main");
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const repositories = useQuery({
    queryKey: ["repositories", projectId],
    queryFn: () => repoApi.list(workspaceId, projectId),
  });

  const going = chosen(models, picked);
  // **Prefilled, and sent only if edited.** Leaving it alone sends nothing and
  // the server writes the same sentence; a browser that always sent its own
  // would be a second implementation of the rule, and the two would drift.
  //
  // They agree today, so nothing can *observe* the difference - which is why a
  // mutant that sends this instead of `undefined` is equivalent. The reason it
  // is still wrong to send: the server derives from the names it has now, and
  // this from the ones it rendered, so a transform somebody else renamed
  // between load and submit is the one case where they part - and the commit
  // message should describe what moved, not what was on screen.
  const suggestion = defaultMessage(going.map((m) => m.name));

  const move = useMutation({
    mutationFn: () =>
      modelApi.adoptMany(workspaceId, projectId, {
        model_ids: going.map((m) => m.id),
        repository_id: repositoryId,
        branch,
        message: message.trim() ? message.trim() : undefined,
      }),
    onSuccess: async () => {
      setFailure(null);
      await queryClient.invalidateQueries({ queryKey: ["models", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["repo-tree"] });
      onDone();
    },
    onError: (e: Error) =>
      setFailure(e instanceof ApiError ? e.message : "Couldn't move them."),
  });

  return (
    <section className="move-together" data-testid="move-together">
      <p className="field-label">{moveLabel(going.length)}</p>
      <p className="login-note" style={{ margin: "0 0 8px" }}>
        They move as one commit, which is what says they moved together — the
        successor to saving several transforms as one change.
      </p>
      <div className="row-actions" style={{ flexWrap: "wrap", gap: 8 }}>
        <select
          aria-label="Repository"
          data-testid="move-repository"
          value={repositoryId}
          onChange={(e) => setRepositoryId(e.target.value)}
        >
          <option value="">Choose a repository…</option>
          {repositories.data?.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
        <input
          aria-label="Branch"
          data-testid="move-branch"
          value={branch}
          onChange={(e) => setBranch(e.target.value)}
        />
        <input
          aria-label="Commit message"
          data-testid="move-message"
          style={{ flex: "1 1 260px" }}
          placeholder={suggestion}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <button
          className="btn"
          data-testid="move-confirm"
          disabled={!canMove(going.length, repositoryId) || move.isPending}
          onClick={() => move.mutate()}
        >
          {move.isPending ? "Moving…" : moveLabel(going.length)}
        </button>
        <button className="btn quiet" onClick={onDone}>
          Cancel
        </button>
      </div>
      {repositories.data && repositories.data.length === 0 && (
        <p className="login-note" data-testid="move-no-repositories">
          This project has no repositories yet, so there is nowhere to move them.
        </p>
      )}
      {failure && (
        <div className="form-error" data-testid="move-error">
          {failure}
        </div>
      )}
    </section>
  );
}


/** Proposals against transforms that are in no repository (§290).
 *
 * **They have to be reachable somewhere before the Code pillar page can go.**
 * §276 gave the repository application a Pull requests tab and deliberately
 * left these out — a proposal belonging to no repository cannot honestly be
 * listed under one — and pointed at the Code screen instead, which B.1
 * deletes. So they live here, beside the transforms they change.
 *
 * **Nothing creates them any more.** §277 and §289 made the answer for a
 * transform outside a repository "move it into one", so what is left is a
 * finite set of open ones — and stranding those would be deleting somebody's
 * review rather than deleting a screen.
 */
function DirectProposals({
  workspaceId,
  projectId,
}: {
  workspaceId: string;
  projectId: string;
}) {
  const url = useUrlState();
  const openId = url.get("proposal") ?? undefined;
  const setParams = url.set;
  const queryClient = useQueryClient();

  const proposals = useQuery({
    queryKey: ["code-proposals", projectId],
    queryFn: () => codeApi.proposals(workspaceId, projectId, "open"),
  });
  const mine = unrepositoried(proposals.data ?? []);

  if (openId) {
    return (
      <section className="code-review-mode" data-testid="direct-review">
        <div className="canvas-settings-head">
          <strong>Reviewing a change to a transform</strong>
          <button
            type="button"
            className="btn quiet"
            style={{ padding: "3px 9px", fontSize: 12 }}
            data-testid="direct-back"
            onClick={() => setParams({ proposal: undefined })}
          >
            Back to models
          </button>
        </div>
        <ReviewSurface
          workspaceId={workspaceId}
          projectId={projectId}
          proposalId={openId}
          canReview
          onChanged={() => {
            queryClient.invalidateQueries({ queryKey: ["code-proposals", projectId] });
            queryClient.invalidateQueries({ queryKey: ["models", projectId] });
          }}
        />
      </section>
    );
  }

  // **Silent when there are none and there never will be.** A permanent empty
  // section for a shape nothing creates is a section that teaches people to
  // look past this part of the screen.
  if (!proposals.isSuccess || mine.length === 0) return null;

  return (
    <section className="code-open-proposals" data-testid="direct-proposals">
      <p className="field-label">Changes to transforms outside a repository</p>
      <p className="login-note" style={{ margin: "0 0 8px" }}>
        {unrepositoriedNote(mine.length)}
      </p>
      <ul className="code-log">
        {mine.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              className="code-log-entry"
              data-testid={`direct-${p.id}`}
              onClick={() => setParams({ proposal: p.id })}
            >
              <span className="code-log-summary">{p.summary}</span>
              <span className="code-log-meta">
                <span className="chip brass">{describeProposal(p)}</span>
                {p.created_by_email ?? "unknown"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
