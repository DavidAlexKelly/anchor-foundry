/**
 * What a proposal does to the datasets its transforms produce
 * (§364; `code-repositories` p.52-55).
 *
 * > "The Impact analysis tab provides information on datasets affected by the
 * >  pull request. By default, it will only show **directly affected**
 * >  datasets." (p.53)
 *
 * `code-repositories.md` §4.1: "Ours reviews text; Foundry reviews the
 * consequences of text."
 *
 * Pure, and in `lib/` rather than beside the panel, because vitest cannot parse
 * `.tsx`: a rule that lives in a component is a rule with no unit test.
 */

/** The three states a file in a proposal can be in — different answers, not
 *  degrees of one. The server's own constants (`services/impact.py`). */
export type ImpactState = "affected" | "never_built" | "new_transform";

export type AffectedDataset = {
  state: ImpactState;
  model_id?: string | null;
  model_name?: string | null;
  path?: string | null;
  dataset?: {
    id: string;
    name: string;
    slug: string;
    row_count: number;
    current_version: number;
  } | null;
};

/**
 * What one row says, in a reviewer's words.
 *
 * **Each state gets its own sentence rather than a shared one with a blank in
 * it.** "No dataset" is true of two of the three and means something different
 * each time: a transform nobody has built yet exists and will produce one; a
 * file that would create a transform has nothing there at all. A reader given
 * the same words for both has to go and find out which.
 */
export function describeImpact(row: AffectedDataset): string {
  if (row.state === "affected" && row.dataset) {
    return `Changes ${row.dataset.name}, currently v${row.dataset.current_version} with ${row.dataset.row_count.toLocaleString()} rows.`;
  }
  if (row.state === "never_built") {
    return "This transform has never been built, so there is no dataset to compare against yet.";
  }
  return "This file would create a transform that does not exist yet, so it has no dataset.";
}

/**
 * The heading for the whole panel: how many datasets this proposal changes.
 *
 * **Counts the datasets, not the files**, because that is p.53's question —
 * and the two differ exactly when something has no dataset behind it, which is
 * the case worth noticing rather than the case to round away.
 */
export function impactSummary(rows: AffectedDataset[]): string {
  const withDatasets = rows.filter((r) => r.state === "affected").length;
  const without = rows.length - withDatasets;
  if (rows.length === 0) return "Nothing to analyse.";
  const head =
    withDatasets === 0
      ? "No datasets change"
      : `${withDatasets} ${withDatasets === 1 ? "dataset changes" : "datasets change"}`;
  if (without === 0) return `${head}.`;
  return `${head}, and ${without} ${without === 1 ? "file has" : "files have"} no dataset yet.`;
}

/**
 * Why this list is only the datasets these files produce.
 *
 * p.53 says Foundry's default is the same — "it will only show directly
 * affected datasets, excluding derived datasets that may be impacted" — and
 * offers **Add datasets to analysis** to go further. That is not built, so the
 * limit is said rather than left for a reader to discover by trusting a short
 * list. A panel that showed a partial answer as though it were the whole one
 * is the §214 failure in its quietest form.
 */
export const DERIVED_NOTE =
  "Only the datasets these transforms produce. Anything built from them downstream is not analysed.";

/** `diff_schemas`' shape, as the server sends it (§365; p.54). */
export type SchemaChange = {
  ok: boolean;
  error?: string | null;
  changes?: {
    added?: { name: string; data_type: string }[];
    removed?: { name: string; data_type: string }[];
    retyped?: { name: string; from: string; to: string }[];
  } | null;
  sampled?: { alias: string; rows_used: number; rows_available: number }[];
  expectations_at_risk?: ExpectationAtRisk[];
};

/** One of the dataset's rules that the proposed columns would stop (§371).
 *
 *  Structural, like everything else in this file: the shape is what the
 *  endpoint sends, and stating it here keeps the wording testable without
 *  dragging the whole API contract into a unit test. */
export type ExpectationAtRisk = {
  rule_type: string;
  column_name: string;
  severity: string;
  outcome: "fail" | "error";
  reason: "removed" | "retyped";
  new_type?: string;
};

/**
 * What the columns do, as lines — or the one line that matters more.
 *
 * **Three answers, and they are not degrees of one.** Code that does not run
 * is reported first and alone: a reviewer who is shown "no column changes" for
 * a transform that fails to compile has been told something true and useless,
 * and will read it as a safe change.
 *
 * "No column changes" is said rather than left blank, because it is the answer
 * a reviewer most wants and an empty space is indistinguishable from a panel
 * that did not load.
 */
export function describeSchemaChange(result: SchemaChange): string[] {
  if (!result.ok) {
    return [result.error?.trim() || "This code does not run."];
  }
  const changes = result.changes;
  if (!changes) return ["No column changes."];
  const lines: string[] = [];
  for (const column of changes.added ?? []) {
    lines.push(`+ ${column.name} (${column.data_type})`);
  }
  for (const column of changes.removed ?? []) {
    lines.push(`− ${column.name} (${column.data_type})`);
  }
  for (const column of changes.retyped ?? []) {
    lines.push(`~ ${column.name}: ${column.from} → ${column.to}`);
  }
  // Unreachable from this server — `diff_schemas` returns null rather than an
  // object with nothing in it — and handled anyway, because the alternative is
  // a heading with no lines under it, which reads as a failure.
  return lines.length > 0 ? lines : ["No column changes."];
}

/**
 * How much of the inputs the answer was computed over.
 *
 * **Said because it is a fact, not because it is a caveat.** The columns do not
 * depend on the sample — measured at 10, 1000 and 5000 rows, where only the
 * count moved — so this is not a disclaimer about the schema. It is there
 * because a reviewer who is told "from a sample" and not told how big a one
 * has been handed a worry instead of a number.
 */
export function describeSample(
  sampled: { alias: string; rows_used: number; rows_available: number }[] | undefined,
): string {
  if (!sampled || sampled.length === 0) return "";
  const partial = sampled.filter((s) => s.rows_used < s.rows_available);
  if (partial.length === 0) return "Run over every input row.";
  return `Run over ${partial
    .map((s) => `${s.rows_used.toLocaleString()} of ${s.rows_available.toLocaleString()} ${s.alias} rows`)
    .join(", ")}. Columns do not depend on how many rows are read.`;
}

/**
 * p.54's **Expectations**, in the words a reviewer needs (§371).
 *
 * > "Build on head branch (development) to validate that the code builds
 * >  properly, the outputs appear as expected, and that **all Data
 * >  Expectations are met**." (p.52)
 *
 * **Two outcomes that look alike and are not**, which the server keeps apart
 * and so does this: a `column_exists` rule on a column the change removes
 * *fails* — that rule's whole job — while every other rule *errors*, because
 * "the column is not there" is not a statement about the data. Saying "fails"
 * for both would tell a reviewer their data went bad when their rule stopped
 * applying, and send them looking in the wrong place.
 *
 * The severity is carried through because it is the difference between a rule
 * that blocks a build and one that notes something (db 0020), and a reviewer
 * deciding whether a change can land needs to know which they are holding.
 */
export function describeExpectationsAtRisk(at_risk: ExpectationAtRisk[]): string[] {
  return at_risk.map((rule) => {
    const what = `${rule.rule_type} on ${rule.column_name}`;
    const said =
      rule.outcome === "fail"
        ? `${what} fails: the column is removed`
        : rule.reason === "removed"
          ? `${what} can no longer run: the column is removed`
          : `${what} can no longer run: the column becomes ${rule.new_type || "another type"}`;
    // The severity last and in its own words, because "error"/"warn" beside a
    // sentence about an error reads as a repetition of it rather than as the
    // separate thing it is.
    return rule.severity === "warn" ? `${said} (a warning)` : `${said} (blocks a build)`;
  });
}

/** One line above the list, or "" when nothing is at risk.
 *
 *  **Silence when there is nothing**, because a heading reading "0 expectations
 *  at risk" on every review of a logic change is a panel that has to be read
 *  and dismissed rather than one that speaks when it matters. */
export function expectationsAtRiskSummary(at_risk: ExpectationAtRisk[]): string {
  if (at_risk.length === 0) return "";
  const blocking = at_risk.filter((r) => r.severity !== "warn").length;
  const count = `${at_risk.length} expectation${at_risk.length === 1 ? "" : "s"}`;
  return blocking === at_risk.length
    ? `${count} would stop this build`
    : blocking === 0
      ? `${count} would stop reporting`
      : `${count} at risk, ${blocking} of which would stop this build`;
}
