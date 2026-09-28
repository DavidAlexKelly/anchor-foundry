"use client";

/** The transforms on a time series set variable (§524; `workshop`
 * p.583-586), in the Variables panel under the bucket and the summariser.
 *
 * In order, since p.583's transforms chain: each one reads what the one above
 * it produced. The words and the checks are `series-transforms.ts`'s. */

import {
  FILTER_OPERATORS, FILTER_WORDS, SAMPLE_METHODS, type FilterOperator, type SampleMethod,
  COMBINE_AGGREGATES, COMBINE_WORDS, type CombineAggregate,
  FORMULA_FUNCTIONS, INTEGRATION_METHODS, KIND_LABELS, MAX_FORMULA, MAX_FORMULA_INPUTS, MAX_TRANSFORMS, TIME_UNITS,
  TRANSFORM_KINDS, WINDOW_AGGREGATES, WINDOW_TYPES, blankTransform, transformsProblem, withInput, withKind,
  withoutInput,
  type IntegrationMethod, type SeriesTransform, type TimeUnit, type TransformKind,
  type WindowAggregate, type WindowType,
} from "./series-transforms";

export function SeriesTransformsEditor({
  transforms, readOnly, onChange, seriesVariables,
}: {
  transforms: SeriesTransform[];
  readOnly: boolean;
  onChange: (next: SeriesTransform[]) => void;
  /** The time series set variables a formula may add as inputs (§561), where
   * there are variables to name: the Variables panel. An Object Table's
   * column has none, and offers none. */
  seriesVariables?: { id: string; label: string }[];
}) {
  const set = (index: number, next: SeriesTransform) =>
    onChange(transforms.map((t, i) => (i === index ? next : t)));
  const problem = transformsProblem(transforms);
  return (
    <div data-testid="series-transforms">
      <span>Transforms</span>
      {transforms.map((t, index) => (
        <div key={index} className="row-actions" data-testid="series-transform"
             style={{ gap: 6, flexWrap: "wrap", marginTop: 4 }}>
          <span className="soft">{index + 1}.</span>
          <select
            aria-label={`Transform ${index + 1} kind`}
            value={t.kind}
            disabled={readOnly}
            onChange={(e) => set(index, withKind(t, e.target.value as TransformKind))}
          >
            {TRANSFORM_KINDS.map((k) => <option key={k} value={k}>{KIND_LABELS[k]}</option>)}
          </select>
          {(t.kind === "cumulative" || t.kind === "rolling" || t.kind === "periodic") && (
            <select
              aria-label={`Transform ${index + 1} aggregate`}
              value={t.aggregate}
              disabled={readOnly}
              onChange={(e) => set(index, { ...t, aggregate: e.target.value as WindowAggregate })}
            >
              {WINDOW_AGGREGATES.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          )}
          {(t.kind === "rolling" || t.kind === "periodic") && (
            <input
              type="number" min={1}
              aria-label={`Transform ${index + 1} window`}
              value={Number.isFinite(t.window) ? t.window : ""}
              readOnly={readOnly}
              onChange={(e) => set(index, { ...t, window: Number(e.target.value) })}
            />
          )}
          {t.kind === "shift" && (
            <input
              type="number"
              aria-label={`Transform ${index + 1} shift`}
              value={Number.isFinite(t.by) ? t.by : ""}
              readOnly={readOnly}
              onChange={(e) => set(index, { ...t, by: Number(e.target.value) })}
            />
          )}
          {t.kind === "sample" && (
            <input
              type="number" min={1}
              aria-label={`Transform ${index + 1} step`}
              value={Number.isFinite(t.every) ? t.every : ""}
              readOnly={readOnly}
              onChange={(e) => set(index, { ...t, every: Number(e.target.value) })}
            />
          )}
          {t.kind !== "cumulative" && t.kind !== "range" && t.kind !== "formula" && t.kind !== "filter"
            && t.kind !== "combine" && t.kind !== "event_statistics" && (
            <select
              aria-label={`Transform ${index + 1} unit`}
              value={t.unit}
              disabled={readOnly}
              onChange={(e) => set(index, { ...t, unit: e.target.value as TimeUnit })}
            >
              {TIME_UNITS.map((u) => (
                <option key={u} value={u}>{t.kind === "derivative" ? `per ${u}` : t.kind === "integral" ? `in ${u}s` : `${u}s`}</option>
              ))}
            </select>
          )}
          {t.kind === "periodic" && (
            <>
              <select
                aria-label={`Transform ${index + 1} window type`}
                value={t.window_type}
                disabled={readOnly}
                onChange={(e) => set(index, { ...t, window_type: e.target.value as WindowType })}
              >
                {WINDOW_TYPES.map((w) => (
                  <option key={w} value={w}>{w === "start" ? "stamped at the start" : "stamped at the end"}</option>
                ))}
              </select>
              <input
                type="datetime-local"
                aria-label={`Transform ${index + 1} alignment`}
                title="Windows start here and every window length either side of it; empty lines them up on 1970"
                value={t.align ?? ""}
                readOnly={readOnly}
                onChange={(e) => set(index, { ...t, align: e.target.value || null })}
              />
            </>
          )}
          {t.kind === "integral" && (
            <select
              aria-label={`Transform ${index + 1} method`}
              value={t.method}
              disabled={readOnly}
              onChange={(e) => set(index, { ...t, method: e.target.value as IntegrationMethod })}
            >
              {INTEGRATION_METHODS.map((m) => (
                <option key={m} value={m}>{m === "linear" ? "linear" : `${m}-hand sum`}</option>
              ))}
            </select>
          )}
          {t.kind === "sample" && (
            <select
              aria-label={`Transform ${index + 1} sample method`}
              value={t.method}
              disabled={readOnly}
              onChange={(e) => set(index, { ...t, method: e.target.value as SampleMethod })}
            >
              {SAMPLE_METHODS.map((m) => (
                <option key={m} value={m}>{m === "previous" ? "the reading before" : "interpolated"}</option>
              ))}
            </select>
          )}
          {t.kind === "filter" && (
            <>
              <select
                aria-label={`Transform ${index + 1} keep`}
                value={t.keep ? "keep" : "remove"}
                disabled={readOnly}
                onChange={(e) => set(index, { ...t, keep: e.target.value === "keep" })}
              >
                <option value="keep">keep readings</option>
                <option value="remove">remove readings</option>
              </select>
              <select
                aria-label={`Transform ${index + 1} comparison`}
                value={t.op}
                disabled={readOnly}
                onChange={(e) => set(index, { ...t, op: e.target.value as FilterOperator })}
              >
                {FILTER_OPERATORS.map((o) => <option key={o} value={o}>{FILTER_WORDS[o]}</option>)}
              </select>
              <input
                type="number"
                aria-label={`Transform ${index + 1} value`}
                value={Number.isFinite(t.value) ? t.value : ""}
                readOnly={readOnly}
                onChange={(e) => set(index, { ...t, value: Number(e.target.value) })}
              />
            </>
          )}
          {t.kind === "formula" && (
            <input
              aria-label={`Transform ${index + 1} formula`}
              title={`x is the series${seriesVariables ? ", and each input its name" : ""}; + - * / ** and ${FORMULA_FUNCTIONS.join(", ")}`}
              value={t.expression}
              readOnly={readOnly}
              maxLength={MAX_FORMULA}
              onChange={(e) => set(index, { ...t, expression: e.target.value })}
            />
          )}
          {/* p.586's Add input (§561): each input a series variable, named
              in the formula. */}
          {t.kind === "event_statistics" && (
            <>
              <select
                aria-label={`Transform ${index + 1} aggregate`}
                value={t.aggregate}
                disabled={readOnly}
                onChange={(e) => set(index, { ...t, aggregate: e.target.value as WindowAggregate })}
              >
                {WINDOW_AGGREGATES.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              <span className="soft">over each time e is</span>
              <select
                aria-label={`Transform ${index + 1} comparison`}
                value={t.op}
                disabled={readOnly}
                onChange={(e) => set(index, { ...t, op: e.target.value as FilterOperator })}
              >
                {FILTER_OPERATORS.map((o) => <option key={o} value={o}>{FILTER_WORDS[o]}</option>)}
              </select>
              <input
                type="number"
                aria-label={`Transform ${index + 1} value`}
                value={Number.isFinite(t.value) ? t.value : ""}
                readOnly={readOnly}
                onChange={(e) => set(index, { ...t, value: Number(e.target.value) })}
              />
              {seriesVariables && (
                <select
                  aria-label={`Transform ${index + 1} input e`}
                  value={typeof t.inputs?.e === "string" ? t.inputs.e : ""}
                  disabled={readOnly}
                  onChange={(e) => set(index, { ...t, inputs: { e: e.target.value } })}
                >
                  <option value="">Choose a series…</option>
                  {seriesVariables.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                </select>
              )}
            </>
          )}
          {t.kind === "combine" && (
            <select
              aria-label={`Transform ${index + 1} combine by`}
              value={t.aggregate}
              disabled={readOnly}
              onChange={(e) => set(index, { ...t, aggregate: e.target.value as CombineAggregate })}
            >
              {COMBINE_AGGREGATES.map((a) => <option key={a} value={a}>{`${COMBINE_WORDS[a]} where they meet`}</option>)}
            </select>
          )}
          {(t.kind === "formula" || t.kind === "combine") && seriesVariables && (
            <span className="row-actions" data-testid="formula-inputs" style={{ gap: 6, flexWrap: "wrap" }}>
              {Object.entries(t.inputs ?? {}).map(([name, chosen]) => (
                <span key={name} className="row-actions" style={{ gap: 4 }}>
                  <code>{name}</code> =
                  <select
                    aria-label={`Transform ${index + 1} input ${name}`}
                    value={typeof chosen === "string" ? chosen : ""}
                    disabled={readOnly}
                    onChange={(e) => set(index, { ...t, inputs: { ...t.inputs, [name]: e.target.value } })}
                  >
                    <option value="">Choose a series…</option>
                    {seriesVariables.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                  </select>
                  {!readOnly && (
                    <button type="button" className="btn quiet"
                            aria-label={`Remove input ${name} of transform ${index + 1}`}
                            onClick={() => set(index, withoutInput(t, name))}>
                      ×
                    </button>
                  )}
                </span>
              ))}
              {!readOnly && Object.keys(t.inputs ?? {}).length < MAX_FORMULA_INPUTS && (
                <button type="button" className="btn quiet"
                        aria-label={`Add an input to transform ${index + 1}`}
                        onClick={() => set(index, withInput(t))}>
                  Add input
                </button>
              )}
            </span>
          )}
          {t.kind === "range" && (
            <>
              <input
                type="datetime-local"
                aria-label={`Transform ${index + 1} start`}
                value={t.start ?? ""}
                readOnly={readOnly}
                onChange={(e) => set(index, { ...t, start: e.target.value || null })}
              />
              <input
                type="datetime-local"
                aria-label={`Transform ${index + 1} end`}
                value={t.end ?? ""}
                readOnly={readOnly}
                onChange={(e) => set(index, { ...t, end: e.target.value || null })}
              />
            </>
          )}
          {!readOnly && (
            <button type="button" className="btn quiet" aria-label={`Remove transform ${index + 1}`}
                    onClick={() => onChange(transforms.filter((_, i) => i !== index))}>
              Remove
            </button>
          )}
        </div>
      ))}
      {problem && <span className="field-hint" data-testid="series-transforms-problem">{problem}</span>}
      {!readOnly && transforms.length < MAX_TRANSFORMS && (
        <select
          aria-label="Add a transform"
          value=""
          onChange={(e) => {
            if (e.target.value) onChange([...transforms, blankTransform(e.target.value as TransformKind)]);
          }}
        >
          <option value="">Add a transform…</option>
          {TRANSFORM_KINDS.map((k) => <option key={k} value={k}>{KIND_LABELS[k]}</option>)}
        </select>
      )}
      <span className="field-hint">
        Applied in order to the bucketed series, each to what the one above produced (p.583).
      </span>
    </div>
  );
}
