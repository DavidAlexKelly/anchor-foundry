"use client";

/** `workshop` p.511's **Action table** layout of the Inline Action (§702).
 *
 * > "Action tables (previously known as Action grids) are recommended for
 * > large-scale datasets … The table layout offers several benefits,
 * > including keyboard navigation and CSV file upload capabilities." (p.511)
 * > "End-user features: Configure additional user interactions, including
 * > layout switching, row management, and file uploads … Also note that batch
 * > call limits apply to the table layout, as well as the requirement that
 * > edits do not conflict." (p.512)
 *
 * One row is one submission of the action: the object it is about and a cell
 * per parameter the form would draw. **Submit sends the rows in order, after
 * checking every one first** - an object picked, required values filled, no
 * object in two rows, and each row's submission criteria asked of the server
 * (`/check`, which writes nothing). A row the server still refuses is marked
 * with its reason and the rest carry on, since each row is its own
 * submission; a row that went through is marked done and is not sent again.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { PropertyInput } from "@/components/property-value";
import { actions as actionApi, objects as objApi } from "@/lib/api";
import { submittedValues } from "@/lib/array-parameter";
import { multipleChoice } from "@/lib/parameter-constraint";
import type { ActionType } from "@/lib/types";
import {
  csvEntries, csvPlan, nextCell, parseCsv, pendingRows, rowFor, rowProblems, tableColumns,
  type TableRow,
} from "./action-table";
import { invalidateCanvasReads } from "./refresh";

type Subject = { id: string; primary_key: unknown; properties?: Record<string, unknown> };

/** One page of objects this table reads at a time, for a pre-fill or a CSV's
 * keys. */
const PAGE = 200;
type Touched = { object_type_id: string; primary_key: string; change: string };

export function ActionTable({
  workspaceId,
  projectId,
  actionType,
  subjects,
  localDefaults,
  live,
  prefill = null,
  onSubmitted,
}: {
  workspaceId: string;
  projectId: string;
  actionType: ActionType;
  /** The objects a row may be about - the same list the form's Record
   * dropdown offers. */
  subjects: Subject[];
  /** p.512's "Define parameter defaults (table and form)". */
  localDefaults: Record<string, unknown>;
  /** Run mode. In the builder the table is drawn but sends nothing, as the
   * form does. */
  live: boolean;
  /** p.512's "Pre-fill with variable (table only)": an object set whose
   * objects become the rows (§703). */
  prefill?: { definition: unknown } | null;
  /** Every row went through: what they created or modified, for p.513's
   * output set and its "On successful action submit" event. */
  onSubmitted: (touched: Touched[], rows: TableRow[]) => void;
}) {
  const queryClient = useQueryClient();
  const parameters = actionType.parameters ?? [];
  const columns = tableColumns(parameters);
  const limit = actionType.table_row_limit ?? 10_000;
  const nextKey = useRef(1);
  const [rows, setRows] = useState<TableRow[]>(() => [
    rowFor(0, parameters, null, localDefaults),
  ]);
  const [sending, setSending] = useState(false);
  const [checked, setChecked] = useState<Map<number, string>>(new Map());
  const tableRef = useRef<HTMLTableElement>(null);
  // Objects a pre-fill or a CSV brought in, which the 25 the Object dropdown
  // starts with need not include - so a row can show the object it is about.
  const [found, setFound] = useState<Subject[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const options = [...subjects, ...found.filter((f) => !subjects.some((s) => s.id === f.id))];

  const fresh = (subject: Subject | null, values: Record<string, unknown> = {}): TableRow => {
    const made = rowFor(nextKey.current++, parameters, subject, localDefaults);
    // A value the file left empty keeps what the object says rather than
    // blanking it: an empty cell in a spreadsheet is usually "no change".
    for (const [name, value] of Object.entries(values)) {
      if (value !== "") made.values[name] = value;
    }
    return made;
  };
  // Rows that came from somewhere replace a table nobody has touched - the one
  // empty row it opens with - and are added after one somebody has.
  const place = (incoming: TableRow[]) => setRows((all) => {
    const untouched = all.length === 1 && !all[0]!.subjectId && all[0]!.status === "draft";
    return [...(untouched ? [] : all), ...incoming].slice(0, limit);
  });

  // p.512: "Pre-populate table rows by mapping an object set variable to an
  // object reference action parameter. The variable's object type must match
  // the action parameter's defined object type." The object a row is about is
  // this platform's object reference, so the set's objects are the rows.
  const prefillKey = prefill ? JSON.stringify(prefill.definition ?? null) : "";
  useEffect(() => {
    if (!prefill?.definition) return;
    const typeOf = (prefill.definition as { object_type_id?: unknown }).object_type_id;
    if (typeOf !== undefined && String(typeOf) !== String(actionType.object_type_id)) {
      setNote("The pre-fill variable holds a different object type from this action's, so it fills no rows.");
      return;
    }
    let cancelled = false;
    (async () => {
      const objects: Subject[] = [];
      for (let offset = 0; offset < limit; offset += PAGE) {
        const page = await objApi.evaluateObjectSet(
          workspaceId, prefill.definition, { limit: PAGE, offset },
        );
        objects.push(...page.instances);
        if (page.instances.length < PAGE || objects.length >= page.total) break;
      }
      if (cancelled) return;
      setFound((was) => [...was, ...objects]);
      setRows(objects.slice(0, limit).map((o) => fresh(o)));
      setNote(null);
    })().catch((e: Error) => { if (!cancelled) setNote(e.message); });
    return () => { cancelled = true; };
    // `fresh` and `limit` are stable for a given action; the set is the input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillKey]);

  // p.511's "CSV file upload capabilities": a row per line, the object named
  // by its key, cells by parameter name.
  const upload = async (file: File) => {
    const lines = parseCsv(await file.text());
    if (lines.length === 0) {
      setNote("That file has no rows.");
      return;
    }
    const plan = csvPlan(lines[0]!, columns);
    if (plan.keyColumn < 0) {
      setNote("The file needs a column naming each row's object: Object, Primary key or Key.");
      return;
    }
    const entries = csvEntries(lines.slice(1), plan);
    const keys = [...new Set(entries.map((e) => e.key).filter(Boolean))];
    const byKey = new Map<string, Subject>();
    for (let i = 0; i < keys.length; i += PAGE) {
      const page = await objApi.evaluateObjectSet(workspaceId, {
        object_type_id: actionType.object_type_id,
        filters: [{ property: "$primary_key", op: "in", value: keys.slice(i, i + PAGE) }],
      }, { limit: PAGE });
      for (const o of page.instances) byKey.set(String(o.primary_key), o);
    }
    setFound((was) => [...was, ...byKey.values()]);
    place(entries.map((entry) => {
      const subject = byKey.get(entry.key) ?? null;
      const made = fresh(subject, entry.values);
      if (!subject) {
        made.message = entry.key
          ? `No object has the key "${entry.key}".`
          : "This line names no object.";
      }
      return made;
    }));
    const parts = [`Read ${entries.length} row${entries.length === 1 ? "" : "s"}.`];
    if (plan.ignored.length > 0) parts.push(`Not a parameter, so ignored: ${plan.ignored.join(", ")}.`);
    if (rows.length + entries.length > limit) parts.push(`Only the first ${limit} rows are kept.`);
    setNote(parts.join(" "));
  };

  const update = (key: number, change: (row: TableRow) => TableRow) =>
    setRows((all) => all.map((r) => (r.key === key ? change(r) : r)));

  const pickSubject = (key: number, id: string) => {
    const subject = options.find((s) => s.id === id) ?? null;
    // A different object is a different row: its values start at what the
    // object says, as the form's do when another record is picked.
    update(key, () => ({ ...rowFor(key, parameters, subject, localDefaults), key }));
  };

  const addRow = () => {
    if (rows.length >= limit) return;
    const key = nextKey.current++;
    setRows((all) => [...all, rowFor(key, parameters, null, localDefaults)]);
  };

  // p.511's keyboard navigation: Enter goes down a column, Shift+Enter up.
  const onKeyDown = (event: React.KeyboardEvent, rowIndex: number, column: number) => {
    if (event.key !== "Enter") return;
    const to = nextCell(rowIndex, column, rows.length, event.shiftKey ? "up" : "down");
    if (!to) return;
    event.preventDefault();
    const cell = tableRef.current?.querySelector<HTMLElement>(
      `[data-cell="${to.row}:${to.column}"] input, [data-cell="${to.row}:${to.column}"] select`,
    );
    cell?.focus();
  };

  const submit = async () => {
    const problems = rowProblems(rows, columns);
    setChecked(problems);
    if (problems.size > 0) return;
    setSending(true);
    const pending = pendingRows(rows);
    // Every row's criteria first, so a refusal is found before anything is
    // written (p.56's message, from the server that would refuse it).
    const refusals = new Map<number, string>();
    for (const row of pending) {
      const verdict = await actionApi
        .check(workspaceId, projectId, actionType.id, submittedValues(row.values, parameters))
        .catch((e: Error) => ({ ok: false, error: e.message }));
      if (!verdict.ok) refusals.set(row.key, verdict.error ?? "Refused.");
    }
    if (refusals.size > 0) {
      setRows((all) => all.map((r) => (refusals.has(r.key)
        ? { ...r, status: "refused", message: refusals.get(r.key) } : r)));
      setSending(false);
      return;
    }
    const touched: Touched[] = [];
    let allWent = true;
    for (const row of pending) {
      update(row.key, (r) => ({ ...r, status: "submitting", message: undefined }));
      try {
        const result = await actionApi.execute(
          workspaceId, projectId, actionType.id, row.subjectId,
          submittedValues(row.values, parameters),
        );
        if (result.ok) {
          touched.push(...(result.touched ?? []));
          update(row.key, (r) => ({ ...r, status: "done" }));
        } else {
          allWent = false;
          update(row.key, (r) => ({ ...r, status: "refused", message: result.error ?? "Refused." }));
        }
      } catch (e) {
        allWent = false;
        update(row.key, (r) => ({ ...r, status: "refused", message: (e as Error).message }));
      }
    }
    await invalidateCanvasReads(queryClient);
    setSending(false);
    if (allWent) onSubmitted(touched, pending);
  };

  const remaining = pendingRows(rows).length;
  return (
    <div className="canvas-action-table" data-testid="action-table">
      <div className="table-scroll">
        <table className="data-grid" ref={tableRef}>
          <thead>
            <tr>
              <th>Object</th>
              {columns.map((c) => (
                <th key={c.api_name}>
                  {c.display_name || c.api_name}
                  {c.required && <span aria-hidden> *</span>}
                </th>
              ))}
              <th aria-label="Row" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={row.key} data-testid="action-table-row" data-status={row.status}>
                <td data-cell={`${rowIndex}:0`}>
                  <select
                    aria-label={`Row ${rowIndex + 1} object`}
                    value={row.subjectId}
                    disabled={row.status === "done"}
                    onChange={(e) => pickSubject(row.key, e.target.value)}
                    onKeyDown={(e) => onKeyDown(e, rowIndex, 0)}
                  >
                    <option value="">Choose…</option>
                    {options.map((s) => (
                      <option key={s.id} value={s.id}>{String(s.primary_key)}</option>
                    ))}
                  </select>
                </td>
                {columns.map((c, i) => (
                  <td
                    key={c.api_name}
                    data-cell={`${rowIndex}:${i + 1}`}
                    onKeyDown={(e) => onKeyDown(e, rowIndex, i + 1)}
                  >
                    <fieldset disabled={row.status === "done"} className="canvas-action-field">
                      <PropertyInput
                        workspaceId={workspaceId}
                        dataType={c.data_type as never}
                        choices={multipleChoice(c)}
                        value={row.values[c.api_name] ?? null}
                        onChange={(next) => update(row.key, (r) => ({
                          ...r, status: r.status === "refused" ? "draft" : r.status,
                          message: undefined,
                          values: { ...r.values, [c.api_name]: next },
                        }))}
                        label={`Row ${rowIndex + 1} ${c.display_name || c.api_name}`}
                        required={c.required}
                      />
                    </fieldset>
                  </td>
                ))}
                <td>
                  {row.status === "done" && <span data-testid="action-table-done">✓</span>}
                  {row.status === "submitting" && <span>…</span>}
                  {row.status !== "done" && (
                    <button
                      type="button"
                      className="btn quiet"
                      aria-label={`Remove row ${rowIndex + 1}`}
                      disabled={sending}
                      onClick={() => setRows((all) => all.filter((r) => r.key !== row.key))}
                    >
                      ✕
                    </button>
                  )}
                  {(row.message || checked.get(row.key)) && row.status !== "done" && (
                    <p className="form-error" data-testid="action-table-problem">
                      {row.message ?? checked.get(row.key)}
                    </p>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row-actions">
        <label className="btn quiet">
          Upload CSV
          <input
            type="file"
            accept=".csv,text/csv"
            data-testid="action-table-csv"
            style={{ display: "none" }}
            disabled={sending}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) upload(file).catch((err: Error) => setNote(err.message));
            }}
          />
        </label>
        <button
          type="button"
          className="btn quiet"
          data-testid="action-table-add"
          disabled={sending || rows.length >= limit}
          onClick={addRow}
        >
          Add row
        </button>
        <button
          type="button"
          className="btn"
          data-testid="action-table-submit"
          disabled={!live || sending || remaining === 0}
          onClick={() => { void submit(); }}
        >
          {sending ? "Submitting…" : `Submit ${remaining} row${remaining === 1 ? "" : "s"}`}
        </button>
      </div>
      {note && <p className="field-hint" data-testid="action-table-note">{note}</p>}
      {!live && (
        <p className="canvas-widget-empty">
          Submitting is disabled while editing - use Preview to try it.
        </p>
      )}
    </div>
  );
}
