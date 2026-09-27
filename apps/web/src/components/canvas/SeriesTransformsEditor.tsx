"use client";

/** The transforms on a time series set variable (§524; `workshop`
 * p.583-586), in the Variables panel under the bucket and the summariser.
 *
 * In order, since p.583's transforms chain: each one reads what the one above
 * it produced. The words and the checks are `series-transforms.ts`'s. */

import {
  KIND_LABELS, MAX_TRANSFORMS, TIME_UNITS, TRANSFORM_KINDS, WINDOW_AGGREGATES, blankTransform,
  transformsProblem, withKind,
  type SeriesTransform, type TimeUnit, type TransformKind, type WindowAggregate,
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
          {(t.kind === "cumulative" || t.kind === "rolling") && (
            <select
              aria-label={`Transform ${index + 1} aggregate`}
              value={t.aggregate}
              disabled={readOnly}
              onChange={(e) => set(index, { ...t, aggregate: e.target.value as WindowAggregate })}
            >
              {WINDOW_AGGREGATES.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          )}
          {t.kind === "rolling" && (
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
          {(t.kind === "rolling" || t.kind === "derivative" || t.kind === "shift") && (
            <select
              aria-label={`Transform ${index + 1} unit`}
              value={t.unit}
              disabled={readOnly}
              onChange={(e) => set(index, { ...t, unit: e.target.value as TimeUnit })}
            >
              {TIME_UNITS.map((u) => (
                <option key={u} value={u}>{t.kind === "derivative" ? `per ${u}` : `${u}s`}</option>
              ))}
            </select>
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
