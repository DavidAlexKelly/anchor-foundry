/**
 * What the Preview panel says when the answer is a job rather than a response
 * (§390; db 0092; `code-repositories.md` §2.2 and §2.4, p.13-14).
 *
 * Foundry: p.13's toolbar button is *"a quick way to preview your code changes
 * on real data"* and p.14's helper *"lets you run your code on a limited sample
 * of the input datasets to quickly preview the code without committing your
 * changes"*. One button, one promise — and two machineries behind it, because
 * decision 0004 keeps customer Python out of the API process. SQL comes back in
 * the response; Python comes back as a row the panel watches.
 *
 * **The point of this module is that the reader should not be able to tell.**
 * `shown` flattens either source into one shape so the table, the row count and
 * the sampling warning are drawn once, from one set of rules. The alternative -
 * a second table under an `if` - is two renderers that agree until the day
 * somebody fixes one of them (§292).
 *
 * The server owns what is *legal* (`services/code_preview_runs.py`), the worker
 * owns what happened (db 0092), and this owns what to *say*.
 */
import type { CodePreviewRun, TransformPreview } from "./types";
import { isSettled, shouldPoll } from "./test-runs";

// Re-exported rather than rewritten: db 0071 and db 0092 define the same five
// statuses, so "has it finished" is one rule with two callers (§292).
export { isSettled, shouldPoll };

/** One input line, already worded. */
export interface ShownInput {
  alias: string;
  label: string;
  sampled: boolean;
}

/** The rows the panel draws, whichever machinery produced them. */
export interface ShownPreview {
  output: string;
  columns: { name: string; data_type: string }[];
  rows: unknown[][];
  rowCount: number;
  truncated: boolean;
  sampled: boolean;
  inputs: ShownInput[];
  /** What this change would do to the dataset the transform already
   * writes, or null when it writes a new one or changes nothing. Both
   * paths carry it, so the drift block is drawn once from one field -
   * the SQL response computes it, the read route computes it for a run. */
  schemaChanges: TransformPreview["schema_changes"];
}

/**
 * The run this press queued, or null when the press was answered outright.
 *
 * **Named rather than inlined as `result.run_id`** because it is the one
 * question the panel asks of the response: SQL is an answer and Python is a
 * receipt, and everything downstream forks on which arrived.
 */
export function queuedRunId(result: TransformPreview | null): string | null {
  return result?.run_id ?? null;
}

function countLabel(used: number, available: number): string {
  return `${used.toLocaleString()} of ${available.toLocaleString()}`;
}

/**
 * Either source, in one shape.
 *
 * A queued run is shown as soon as it exists, but only a *settled* one has
 * rows: reporting `0 rows` over something still running would be a number the
 * reader believes (§214), so an unsettled run flattens to null and the status
 * line is what speaks.
 *
 * **A SQL result that is really a receipt flattens to null too.** The Python
 * path's first response carries `run_id` and empty rows, and treating that as
 * a result would draw an empty table for the second between pressing and the
 * first poll.
 */
export function shown(
  result: TransformPreview | null,
  run: CodePreviewRun | undefined,
): ShownPreview | null {
  if (run !== undefined) {
    if (!isSettled(run) || run.status !== "succeeded") return null;
    return {
      output: run.output,
      columns: run.columns,
      rows: run.rows,
      rowCount: run.row_count,
      truncated: run.truncated,
      sampled: run.sampled,
      inputs: run.inputs.map((i) => ({
        alias: i.alias,
        // No dataset name here, unlike SQL: see `PreviewRunInput`.
        label: i.sampled ? `${i.alias} (${countLabel(i.rows_used, i.rows_available)})` : i.alias,
        sampled: i.sampled,
      })),
      schemaChanges: run.schema_changes,
    };
  }
  if (result === null || result.run_id) return null;
  return {
    output: result.output,
    columns: result.columns,
    rows: result.rows,
    rowCount: result.row_count,
    truncated: result.truncated,
    sampled: result.sampled,
    inputs: result.inputs.map((i) => ({
      alias: i.alias,
      label: i.sampled
        ? `${i.alias} = ${i.dataset} (${countLabel(i.rows_used, i.rows_available)})`
        : `${i.alias} = ${i.dataset}`,
      sampled: i.sampled,
    })),
    schemaChanges: result.schema_changes,
  };
}

/**
 * The sentence under the button while a queued run is in flight, or null when
 * there is nothing to report.
 *
 * `failed` and `errored` say different things because they *are* different
 * things (db 0092): the first is the author's transform raising on their data,
 * the second is the run not having happened. Collapsing them would send
 * somebody to read code that is fine.
 */
export function runStatus(run: CodePreviewRun | undefined): string | null {
  if (run === undefined) return null;
  if (run.status === "queued") return "Waiting to run…";
  if (run.status === "running") return "Running…";
  if (run.status === "errored") return run.error ?? "This preview could not be run.";
  if (run.status === "failed") {
    return run.failure ?? "This transform raised while previewing.";
  }
  return null;
}

/** Whether that sentence is bad news, so the panel can colour it. */
export function runIsAProblem(run: CodePreviewRun | undefined): boolean {
  return run !== undefined && (run.status === "failed" || run.status === "errored");
}

/**
 * The sampling warning, or null when nothing was cut.
 *
 * **One sentence for both languages.** The SQL path had its own copy inline in
 * the panel; a preview over a sample misleads identically whichever engine ran
 * it, so the wording moved here rather than being duplicated (§292). The claim
 * it makes is `preview_transform`'s own: a count over a sample is an answer,
 * not the answer.
 */
export function samplingWarning(view: ShownPreview | null): string | null {
  if (view === null || !view.sampled) return null;
  const cut = view.inputs.filter((i) => i.sampled).map((i) => i.alias);
  return (
    `This ran on a sample of ${cut.join(", ")}. Joins and aggregates over a ` +
    "sample give an answer, not the answer."
  );
}

/**
 * The line above the table: how many rows, and whether that is the number.
 *
 * `truncated` and `sampled` are separate facts and both belong here.
 * "Showing 100 of 40,000" is about this table; "from the sample" is about
 * whether 40,000 is real.
 */
export function rowCountLabel(view: ShownPreview): string {
  const count = `${view.rowCount.toLocaleString()} row${view.rowCount === 1 ? "" : "s"}`;
  const shownRows = view.truncated ? `, showing ${view.rows.length.toLocaleString()}` : "";
  return view.sampled ? `${count} from the sample${shownRows}` : `${count}${shownRows}`;
}

/**
 * What the button says.
 *
 * Named for the state it is in while something is happening, because a button
 * that still said "Preview" over an in-flight run invites a second press the
 * server refuses (`MAX_QUEUED_PER_REPO` is two, and it counts *queued* rows).
 */
export function previewLabel(pending: boolean, run: CodePreviewRun | undefined): string {
  return pending || shouldPoll(run) ? "Running…" : "Preview";
}
