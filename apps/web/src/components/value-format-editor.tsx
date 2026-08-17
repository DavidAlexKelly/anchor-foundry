"use client";

/**
 * Configuring one property's value formatter (Foundry `object-link-types`
 * p.95–100).
 *
 * > "On the right hand side panel of the properties pane, you will see a type
 * > of formatting depending on the base type of the property … As you select
 * > the available formatting options, you will see a **preview** for how values
 * > of the property will be rendered with the new formatting applied." (p.95–96)
 *
 * **The preview is the feature, not decoration.** p.98's own description of
 * the preview box is "Add any number in the input that is similar to what
 * you'd expect to see in your property's values" — because nobody can read
 * "maximum significant digits: 3" and picture `3.14`. It costs nothing here:
 * `formatValue` is pure, so the preview is the same function the tables will
 * use rather than an approximation of it.
 *
 * **Which options exist depends on the property's base type** (p.95). A
 * timestamp gets p.99's styles and a timezone; a number gets p.97–98's. A
 * property that is neither is offered nothing at all, with a sentence saying
 * so — the server refuses the mismatch, and an editor that let somebody build
 * one would be an editor whose Apply button is a trap.
 */

import { useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import type { PropertyDataType, ValueFormat } from "@/lib/types";
import { formatValue } from "@/lib/value-format";

const NUMERIC: PropertyDataType[] = ["integer", "float"];
const TEMPORAL: PropertyDataType[] = ["date", "timestamp"];

/** Whether a property of this base type can carry a formatter at all (p.95). */
export function formattable(dataType: PropertyDataType): boolean {
  return NUMERIC.includes(dataType) || TEMPORAL.includes(dataType);
}

type NumberFormat = ValueFormat & { kind: "number" };

const NUMBER_STYLES: [NumberFormat["style"], string][] = [
  ["plain", "Plain number"],
  ["currency", "Currency"],
  ["unit", "Unit"],
  ["percent", "Percentage"],
  ["affix", "Prefix / suffix"],
];

const DATE_STYLES: [(ValueFormat & { kind: "datetime" })["style"], string][] = [
  ["date", "Date"],
  ["datetime_long", "Date and time (long)"],
  ["datetime_short", "Date and time (short)"],
  ["iso", "ISO instant"],
  ["relative", "Relative to now"],
  ["time", "Time"],
];

const NOTATIONS: [NonNullable<NumberFormat["notation"]>, string][] = [
  ["standard", "Standard"],
  ["compact", "Compact (123K)"],
  ["scientific", "Scientific"],
  ["engineering", "Engineering"],
];

/** p.98's digit options, with the page's own worked examples as hints. */
const DIGITS: [
  "minimum_integer_digits" | "minimum_fraction_digits" | "maximum_fraction_digits"
  | "minimum_significant_digits" | "maximum_significant_digits",
  string,
  string,
][] = [
  ["minimum_integer_digits", "Min integer digits", "5 → 05"],
  ["minimum_fraction_digits", "Min fraction digits", "3.5 → 3.50"],
  ["maximum_fraction_digits", "Max fraction digits", "3.14159 → 3.14"],
  ["minimum_significant_digits", "Min significant digits", ""],
  ["maximum_significant_digits", "Max significant digits", "3.14159 → 3.14"],
];

/** An empty box means "not set", not zero — the server tells those apart and
 * so must this, or clearing a digit count would silently mean "pad to none". */
function digitsOf(value: string): number | undefined {
  if (value.trim() === "") return undefined;
  const n = Number(value);
  return Number.isInteger(n) ? n : undefined;
}

/** Why Apply is shut: the same rules `services/value_format.py` enforces, in
 * the one place where saying so is still useful. Null means the draft is fine.
 */
function incomplete(draft: ValueFormat | null): string | null {
  if (!draft) return null;
  if (draft.kind === "datetime") return null;
  if (draft.style === "currency" && (draft.currency ?? "").length !== 3)
    return "A currency needs a three-letter code, like USD.";
  if (draft.style === "unit" && !(draft.unit ?? "").trim())
    return "A unit formatter needs a unit, like kilogram.";
  if (draft.style === "affix" && !(draft.prefix ?? "") && !(draft.suffix ?? ""))
    return "Prefix / suffix needs a prefix or a suffix.";
  const pairs: [keyof typeof draft, keyof typeof draft, string][] = [
    ["minimum_fraction_digits", "maximum_fraction_digits", "fraction"],
    ["minimum_significant_digits", "maximum_significant_digits", "significant"],
  ];
  for (const [lo, hi, what] of pairs) {
    const low = draft[lo] as number | undefined;
    const high = draft[hi] as number | undefined;
    if (low !== undefined && high !== undefined && low > high)
      return `Min ${what} digits cannot be more than max ${what} digits.`;
  }
  return null;
}

export function ValueFormatEditor({
  open,
  onClose,
  propertyName,
  dataType,
  value,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  propertyName: string;
  dataType: PropertyDataType;
  value: ValueFormat | null | undefined;
  onSave: (next: ValueFormat | null) => void;
}) {
  const numeric = NUMERIC.includes(dataType);
  const [draft, setDraft] = useState<ValueFormat | null>(value ?? null);
  // p.98's "Preview result … add any number in the input that is similar to
  // what you'd expect to see in your property's values".
  const [sample, setSample] = useState(numeric ? "123456.789" : "2020-07-22T13:00:00Z");

  const preview = draft ? formatValue(sample, draft) : sample;
  // **What the server would refuse, refused here first.** Every branch below
  // is a rule in `services/value_format.py`; an Apply button that sent one of
  // them would turn a form somebody had filled in into a 422 on save, with the
  // dialog already closed. Same list, checked where the answer can still be
  // changed.
  const missing = incomplete(draft);

  return (
    <Dialog open={open} title={`Format ${propertyName}`} onClose={onClose}>
      {!formattable(dataType) ? (
        <p className="field-hint">
          Value formatting applies to numbers, dates and timestamps. This
          property is a {dataType}.
        </p>
      ) : (
        <>
          <Field label="Formatting">
            <select
              data-testid="format-on"
              value={draft ? "on" : "off"}
              onChange={(e) =>
                setDraft(
                  e.target.value === "off"
                    ? null
                    : numeric
                      ? { kind: "number", style: "plain" }
                      : { kind: "datetime", style: "datetime_short" },
                )
              }
            >
              <option value="off">None</option>
              <option value="on">{numeric ? "Numeric" : "Date and time"}</option>
            </select>
          </Field>

          {draft?.kind === "number" && (
            <>
              <Field label="Base type" hint="p.97's Base type — what the number means.">
                <select
                  data-testid="format-style"
                  value={draft.style}
                  onChange={(e) => {
                    // The style's own field goes with the style. Keeping a
                    // currency code on a switch to Unit would send the server
                    // an option it refuses, from a form that looked settled.
                    const style = e.target.value as NumberFormat["style"];
                    const { currency: _c, unit: _u, prefix: _p, suffix: _s, ...rest } = draft;
                    setDraft({
                      ...rest,
                      style,
                      // No invented currency or unit. A pre-filled "USD"
                      // is a guess that saves silently and renders every
                      // number in a currency nobody chose; blank plus a
                      // disabled Apply asks the question instead.
                      ...(style === "currency" ? { currency: "" } : {}),
                      ...(style === "unit" ? { unit: "" } : {}),
                      ...(style === "affix" ? { prefix: "", suffix: "" } : {}),
                    });
                  }}
                >
                  {NUMBER_STYLES.map(([v, label]) => (
                    <option key={v} value={v}>{label}</option>
                  ))}
                </select>
              </Field>
              {draft.style === "currency" && (
                <Field label="Currency" hint="A three-letter code, like USD.">
                  <input
                    data-testid="format-currency"
                    value={draft.currency ?? ""}
                    onChange={(e) =>
                      setDraft({ ...draft, currency: e.target.value.toUpperCase() })
                    }
                  />
                </Field>
              )}
              {draft.style === "unit" && (
                <Field label="Unit" hint="An Intl unit, like kilogram or mile-per-hour.">
                  <input
                    data-testid="format-unit"
                    value={draft.unit ?? ""}
                    onChange={(e) => setDraft({ ...draft, unit: e.target.value })}
                  />
                </Field>
              )}
              {draft.style === "affix" && (
                <>
                  <Field label="Prefix">
                    <input
                      data-testid="format-prefix"
                      value={draft.prefix ?? ""}
                      onChange={(e) => setDraft({ ...draft, prefix: e.target.value })}
                    />
                  </Field>
                  <Field label="Suffix">
                    <input
                      data-testid="format-suffix"
                      value={draft.suffix ?? ""}
                      onChange={(e) => setDraft({ ...draft, suffix: e.target.value })}
                    />
                  </Field>
                </>
              )}
              <Field label="Notation">
                <select
                  data-testid="format-notation"
                  value={draft.notation ?? "standard"}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      notation: e.target.value as NonNullable<NumberFormat["notation"]>,
                    })
                  }
                >
                  {NOTATIONS.map(([v, label]) => (
                    <option key={v} value={v}>{label}</option>
                  ))}
                </select>
              </Field>
              <label className="field-inline">
                <input
                  type="checkbox"
                  data-testid="format-grouping"
                  checked={draft.grouping ?? true}
                  onChange={(e) => setDraft({ ...draft, grouping: e.target.checked })}
                />
                <span>Use grouping (123456 → 123,456)</span>
              </label>
              {DIGITS.map(([field, label, hint]) => (
                <Field key={field} label={label} hint={hint}>
                  <input
                    type="number"
                    data-testid={`format-${field}`}
                    value={draft[field] ?? ""}
                    onChange={(e) =>
                      setDraft({ ...draft, [field]: digitsOf(e.target.value) })
                    }
                  />
                </Field>
              ))}
            </>
          )}

          {draft?.kind === "datetime" && (
            <>
              <Field label="Style">
                <select
                  data-testid="format-style"
                  value={draft.style}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      style: e.target.value as (ValueFormat & { kind: "datetime" })["style"],
                    })
                  }
                >
                  {DATE_STYLES.map(([v, label]) => (
                    <option key={v} value={v}>{label}</option>
                  ))}
                </select>
              </Field>
              {dataType === "timestamp" && (
                // p.100 offers a static zone *or* the reader's own. Empty is
                // the reader's, which is why the hint says so rather than
                // leaving an empty box looking unfinished.
                <Field
                  label="Timezone"
                  hint="Leave empty to use each reader's own timezone."
                >
                  <input
                    data-testid="format-timezone"
                    placeholder="Europe/London"
                    value={draft.timezone ?? ""}
                    onChange={(e) =>
                      setDraft({ ...draft, timezone: e.target.value.trim() || undefined })
                    }
                  />
                </Field>
              )}
            </>
          )}

          {draft && (
            <Field label="Preview" hint="p.96 — the same formatter the tables use.">
              <input
                data-testid="format-sample"
                value={sample}
                onChange={(e) => setSample(e.target.value)}
              />
              <output data-testid="format-preview" className="format-preview">
                {preview ?? "∅"}
              </output>
            </Field>
          )}
        </>
      )}

      {missing && (
        <p className="field-hint" data-testid="format-problem">{missing}</p>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          disabled={missing !== null}
          data-testid="format-save"
          onClick={() => {
            onSave(draft);
            onClose();
          }}
        >
          Apply
        </button>
      </div>
    </Dialog>
  );
}
