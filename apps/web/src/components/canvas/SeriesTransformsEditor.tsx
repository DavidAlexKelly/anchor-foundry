"use client";

/** The transforms on a time series set variable (§524; `workshop`
 * p.583-586), in the Variables panel under the bucket and the summariser.
 *
 * In order, since p.583's transforms chain: each one reads what the one above
 * it produced. The words and the checks are `series-transforms.ts`'s. */

import {
  FORMULA_FUNCTIONS, INTEGRATION_METHODS, KIND_LABELS, MAX_FORMULA, MAX_TRANSFORMS, TIME_UNITS, TRANSFORM_KINDS, WINDOW_AGGREGATES,
  WINDOW_TYPES, blankTransform, transformsProblem, withKind,
  type IntegrationMethod, type SeriesTransform, type TimeUnit, type TransformKind,
  type WindowAggregate, type WindowType,
} from "./series-transforms";

export function SeriesTransformsEditor({
  transforms, readOnly, onChange,
}: {
  transforms: SeriesTransform[];
  readOnly: boolean;
  onChange: (next: SeriesTransform[]) => void;
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
          {t.kind !== "cumulative" && t.kind !== "range" && t.kind !== "formula" && (
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
          {t.kind === "formula" && (
            <input
              aria-label={`Transform ${index + 1} formula`}
              title={`x is the series; + - * / ** and ${FORMULA_FUNCTIONS.join(", ")}`}
              value={t.expression}
              readOnly={readOnly}
              maxLength={MAX_FORMULA}
              onChange={(e) => set(index, { ...t, expression: e.target.value })}
            />
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
