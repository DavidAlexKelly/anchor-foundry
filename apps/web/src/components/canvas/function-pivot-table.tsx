"use client";

/**
 * The Pivot Table's function-backed form (Workshop p.335-340; §774): the
 * function called with its inputs as the module holds them, its table placed
 * by `pivotFrom`, and its settings. The grid's rules are `function-pivot.ts`'.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { objects as objApi, ApiError } from "@/lib/api";
import { useCanvasEnv, useCanvasVariables } from "./context";
import { FunctionInputsFields } from "./function-column-editor";
import { versionOf } from "./function-columns";
import { inputValues, unsetRequired } from "./function-inputs";
import type { FunctionLayer } from "./function-layers";
import {
  cellKey, fieldsOf, pivotFrom, pivotProblem, rowKey, shown, visibleRows, type PivotFields,
} from "./function-pivot";

export function FunctionPivotView({ fn, fields, title }: {
  fn: FunctionLayer;
  fields: PivotFields;
  title: string;
}) {
  const { workspaceId } = useCanvasEnv();
  const { resolved } = useCanvasVariables();
  const values = inputValues(fn.inputs, resolved);
  const call = useQuery({
    queryKey: ["canvas-pivot-function", fn.function_id, fn.version, values],
    queryFn: () => objApi.executeFunction(workspaceId, fn.function_id, values, fn.version),
    enabled: !!fn.function_id,
    retry: false,
  });
  const problem = call.data ? pivotProblem(call.data, fields) : null;
  const grid = call.data && !problem ? pivotFrom(call.data, fields) : null;
  const multi = fields.values.length > 1;
  const hasRowTotals = !!grid && grid.rowTotals.size > 0;
  // A pivot across the top only has its one line; its totals have no row.
  const hasColumnTotals = !!grid && fields.rows.length > 0
    && (grid.columnTotals.size > 0 || !!grid.grand);
  const columns = grid?.columnKeys ?? [];
  // p.340's expandable rows: one more column, holding each line's chevron
  // and, for a line opened from another, its own value.
  const expandable = fields.expandable ?? [];
  const deep = expandable.length > 0 && fields.rows.length > 0;
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) => setOpen((was) => {
    const next = new Set(was);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });
  const lines = grid ? (deep ? visibleRows(grid, fields.rows.length, open) : grid.rowKeys) : [];
  const valueCells = (v: Record<string, unknown> | undefined | null, key: string) =>
    fields.values.map((f) => (
      <td key={`${key}-${f}`} className="canvas-pivot-cell">{shown(v?.[f])}</td>
    ));

  return (
    <>
      {title && <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>{title}</h3>}
      {!fn.function_id && (
        <p className="canvas-widget-empty">Pivot table - choose its function in Settings</p>
      )}
      {call.isPending && !!fn.function_id && <p className="canvas-widget-empty">Loading…</p>}
      {call.isError && (
        <p className="canvas-widget-empty" data-testid="pivot-function-problem">
          {call.error instanceof ApiError ? call.error.message : "Couldn't call the function."}
        </p>
      )}
      {problem && (
        <p className="canvas-widget-empty" data-testid="pivot-function-problem">{problem}</p>
      )}
      {grid && (
        <div className="canvas-pivot-scroll">
          <table className="canvas-pivot" data-testid="pivot-function-grid">
            <thead>
              <tr>
                {fields.rows.map((f) => (
                  <th key={f} scope="col" className="canvas-pivot-corner" rowSpan={multi ? 2 : 1}>
                    {f}
                  </th>
                ))}
                {deep && (
                  <th scope="col" className="canvas-pivot-corner" rowSpan={multi ? 2 : 1}>
                    {expandable.join(" › ")}
                  </th>
                )}
                {columns.map((c) => (
                  <th key={c} scope="col" colSpan={fields.values.length}>
                    {fields.column ? c : fields.values.length === 1 ? fields.values[0] : ""}
                  </th>
                ))}
                {hasRowTotals && (
                  <th scope="col" className="canvas-pivot-total" colSpan={fields.values.length}>
                    Total
                  </th>
                )}
              </tr>
              {multi && (
                <tr>
                  {[...columns, ...(hasRowTotals ? ["__total"] : [])].flatMap((c) =>
                    fields.values.map((f) => <th key={`${c}-${f}`} scope="col">{f}</th>))}
                </tr>
              )}
            </thead>
            <tbody>
              {lines.map((key) => (
                <tr key={rowKey(key)} data-testid="pivot-function-line">
                  {key.slice(0, deep ? fields.rows.length : key.length).map((g, i) => (
                    <th key={i} scope="row">{key.length === fields.rows.length || !deep ? g : ""}</th>
                  ))}
                  {deep && (
                    <th scope="row" style={{ paddingLeft: 6 + 14 * (key.length - fields.rows.length) }}>
                      {grid.parents.has(rowKey(key)) && (
                        <button
                          type="button"
                          className="link-button"
                          aria-expanded={open.has(rowKey(key))}
                          aria-label={`${open.has(rowKey(key)) ? "Collapse" : "Expand"} ${key.join(" / ")}`}
                          onClick={() => toggle(rowKey(key))}
                        >
                          {open.has(rowKey(key)) ? "▾" : "▸"}
                        </button>
                      )}{" "}
                      {key.length > fields.rows.length ? key[key.length - 1] : ""}
                    </th>
                  )}
                  {columns.flatMap((c) =>
                    valueCells(grid.cells.get(cellKey(key, c)), `${rowKey(key)}-${c}`))}
                  {hasRowTotals && valueCells(grid.rowTotals.get(rowKey(key)), `${rowKey(key)}-t`)}
                </tr>
              ))}
              {hasColumnTotals && (
                <tr className="canvas-pivot-total">
                  <th scope="row" colSpan={Math.max(fields.rows.length, 1) + (deep ? 1 : 0)}>
                    Total
                  </th>
                  {columns.flatMap((c) => valueCells(grid.columnTotals.get(c), `t-${c}`))}
                  {hasRowTotals && valueCells(grid.grand, "grand")}
                </tr>
              )}
            </tbody>
          </table>
          {grid.rowKeys.length === 0 && (
            <p className="canvas-widget-empty">The function returned nothing to place.</p>
          )}
          {grid.unplaced > 0 && (
            <p className="canvas-widget-empty">
              {grid.unplaced.toLocaleString()} {grid.unplaced === 1 ? "row names" : "rows name"}{" "}
              only some of the row fields, or an expandable field without the one it
              opens from, which this grid has no line for.
            </p>
          )}
          {call.data?.truncated && (
            <p className="canvas-widget-empty">
              Showing the first {(call.data.rows ?? []).length.toLocaleString()} rows the
              function returned.
            </p>
          )}
        </div>
      )}
    </>
  );
}

/** The settings for a function-backed pivot (p.336): the function, its
 * version, its inputs, and the group-by and value fields. */
export function FunctionPivotSettings({ fn, rows, expand, column, values, onChange }: {
  fn: FunctionLayer;
  rows: string;
  expand: string;
  column: string;
  values: string;
  onChange: (next: { fn?: FunctionLayer; fnRows?: string; fnExpand?: string;
                     fnColumn?: string; fnValues?: string }) => void;
}) {
  const { workspaceId } = useCanvasEnv();
  const list = useQuery({
    queryKey: ["functions", workspaceId],
    queryFn: () => objApi.listFunctions(workspaceId),
  });
  const detail = useQuery({
    queryKey: ["function", fn.function_id],
    queryFn: () => objApi.getFunction(workspaceId, fn.function_id),
    enabled: !!fn.function_id,
  });
  const version = versionOf(detail.data, fn.version);
  const issue = !fn.function_id ? "Choose the function this pivot reads."
    : detail.data && !version ? `${detail.data.api_name} has no version ${fn.version}.`
    : version && version.output.kind !== "table"
      ? `${detail.data!.api_name} returns ${version.output.kind}; a pivot table reads a table.`
    : version ? unsetRequired(version, fn.inputs)
    : null;
  return (
    <>
      <label className="field">
        <span className="field-label">Function</span>
        <select
          aria-label="Pivot function"
          value={fn.function_id}
          onChange={(e) => onChange({ fn: { function_id: e.target.value, version: null,
                                            inputs: {} } })}
        >
          <option value="">Choose a function…</option>
          {(list.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.api_name}</option>)}
        </select>
      </label>
      {detail.data && (
        <label className="field">
          <span className="field-label">Version</span>
          <select
            aria-label="Pivot function version"
            value={fn.version ?? ""}
            onChange={(e) => onChange({ fn: { ...fn, version: e.target.value || null } })}
          >
            <option value="">Newest ({detail.data.versions[0]?.version})</option>
            {detail.data.versions.map((v) => (
              <option key={v.id} value={v.version}>{v.version}</option>
            ))}
          </select>
        </label>
      )}
      <FunctionInputsFields
        label="Pivot"
        parameters={version?.parameters ?? []}
        inputs={fn.inputs}
        onChange={(inputs) => onChange({ fn: { ...fn, inputs } })}
      />
      <label className="field">
        <span className="field-label">Row fields</span>
        <input
          aria-label="Pivot row fields"
          placeholder="region, product"
          value={rows}
          onChange={(e) => onChange({ fnRows: e.target.value })}
        />
      </label>
      <label className="field">
        <span className="field-label">Expandable rows</span>
        <input
          aria-label="Pivot expandable rows"
          placeholder="product_type, product_name (optional)"
          value={expand}
          onChange={(e) => onChange({ fnExpand: e.target.value })}
        />
        <span className="field-hint">
          Fields a row opens into, outermost first (Workshop p.340). A row naming the
          first of them sits under the row without it.
        </span>
      </label>
      <label className="field">
        <span className="field-label">Column field</span>
        <input
          aria-label="Pivot column field"
          placeholder="year (optional)"
          value={column}
          onChange={(e) => onChange({ fnColumn: e.target.value.trim() })}
        />
      </label>
      <label className="field">
        <span className="field-label">Value fields</span>
        <input
          aria-label="Pivot value fields"
          placeholder="total_sales"
          value={values}
          onChange={(e) => onChange({ fnValues: e.target.value })}
        />
        <span className="field-hint">
          The function&apos;s table, one row per data point. A row with the column field
          empty is its row&apos;s total, one with the row fields empty its column&apos;s
          (Workshop p.338) — what GROUP BY ROLLUP gives.
        </span>
      </label>
      {issue && <p className="field-hint" data-testid="pivot-settings-problem">{issue}</p>}
    </>
  );
}

/** The fields a saved pivot names. */
export function pivotFieldsOf(rows: string | null, column: string | null,
                              values: string | null, expand: string | null = null): PivotFields {
  return { rows: fieldsOf(rows), column: (column ?? "").trim() || null, values: fieldsOf(values),
           expandable: fieldsOf(expand) };
}
