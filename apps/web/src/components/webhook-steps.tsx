"use client";

/**
 * The calls a webhook makes before its own request (§523; `data-connection`
 * p.234-237), in the webhook's dialog.
 *
 * > "Below is an example of a Task body template that makes two requests: one
 * > to a GET endpoint to retrieve some data, then one to a POST endpoint using
 * > data from the previous call." (p.235)
 *
 * Each call is a method, a path and a body, whether it only reads (p.237's
 * isHttpMethodSafe), and the values it takes from its response. The rules are
 * `lib/webhook-steps.ts`'s; this lays them out.
 */

import { Field } from "@/components/dialog";
import { BODYLESS_METHODS, METHODS } from "@/lib/webhook-form";
import { MAX_STEPS, blankStep, stepSummary, withMethod, type StepDraft } from "@/lib/webhook-steps";

export function StepsEditor({
  steps, onChange,
}: {
  steps: StepDraft[];
  onChange: (next: StepDraft[]) => void;
}) {
  const set = (index: number, next: Partial<StepDraft>) =>
    onChange(steps.map((step, i) => (i === index ? { ...step, ...next } : step)));
  return (
    <Field
      label="Calls before the request"
      hint={'Made in order, before the request below. A value a call extracts can be used by later calls and the request as {{{name}}} (p.235). "." extracts the whole response.'}
    >
      <div data-testid="webhook-steps">
        {steps.map((step, index) => (
          <div key={index} className="card" data-testid="webhook-step" style={{ margin: "6px 0", padding: 8 }}>
            <div className="row-actions" style={{ justifyContent: "space-between" }}>
              <strong data-testid="webhook-step-summary">
                {index + 1}. {stepSummary(step)}
              </strong>
              <button type="button" className="btn quiet" data-testid="webhook-step-remove"
                      onClick={() => onChange(steps.filter((_, i) => i !== index))}>
                Remove
              </button>
            </div>
            <div className="row" style={{ gap: 8, alignItems: "flex-end" }}>
              <select
                aria-label={`Call ${index + 1} method`}
                value={step.method}
                onChange={(e) => onChange(steps.map((s, i) => (i === index ? withMethod(s, e.target.value) : s)))}
              >
                {METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <input
                type="text"
                aria-label={`Call ${index + 1} path`}
                placeholder="path/to/fetchData"
                value={step.path}
                onChange={(e) => set(index, { path: e.target.value })}
              />
              {/* p.237: a POST whose answer the request needs may be marked
                  safe, so the request can still be the one that changes
                  things. A GET is safe already. */}
              {!BODYLESS_METHODS.includes(step.method) && (
                <label className="soft">
                  <input
                    type="checkbox"
                    aria-label={`Call ${index + 1} only reads`}
                    checked={step.safe}
                    onChange={(e) => set(index, { safe: e.target.checked })}
                  />{" "}
                  Only reads
                </label>
              )}
            </div>
            {!BODYLESS_METHODS.includes(step.method) && (
              <textarea
                aria-label={`Call ${index + 1} body`}
                rows={3}
                style={{ fontFamily: "var(--mono, monospace)", width: "100%" }}
                placeholder='{"text": "{{{message}}}"}'
                value={step.bodyText}
                onChange={(e) => set(index, { bodyText: e.target.value })}
              />
            )}
            {step.extract.map((extract, row) => (
              <div key={row} className="row-actions" style={{ gap: 6, marginTop: 4 }}>
                <input
                  type="text"
                  aria-label={`Call ${index + 1} extract ${row + 1} name`}
                  placeholder="request_output"
                  value={extract.api_name}
                  onChange={(e) => set(index, {
                    extract: step.extract.map((x, i) => (i === row ? { ...x, api_name: e.target.value } : x)),
                  })}
                />
                <input
                  type="text"
                  aria-label={`Call ${index + 1} extract ${row + 1} path`}
                  placeholder="json.path.to.output"
                  value={extract.path}
                  onChange={(e) => set(index, {
                    extract: step.extract.map((x, i) => (i === row ? { ...x, path: e.target.value } : x)),
                  })}
                />
              </div>
            ))}
            <button type="button" className="btn quiet" data-testid="webhook-step-extract-add"
                    onClick={() => set(index, { extract: [...step.extract, { api_name: "", path: "" }] })}>
              Extract a value
            </button>
          </div>
        ))}
        {steps.length < MAX_STEPS && (
          <button type="button" className="btn quiet" data-testid="webhook-steps-add"
                  onClick={() => onChange([...steps, blankStep()])}>
            Add a call
          </button>
        )}
      </div>
    </Field>
  );
}
