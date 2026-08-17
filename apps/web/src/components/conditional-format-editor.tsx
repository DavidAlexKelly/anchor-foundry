"use client";

/**
 * Editing one property's conditional formatting rules (Foundry
 * `object-link-types` p.103–107).
 *
 * > "You will see conditional formatting on the properties pane; select the
 * > Add a rule button … Click on the newly created default rule to open the
 * > Edit conditional formatting rule editor." (p.103–104)
 *
 * **The list is ordered and the order is editable**, because first match wins
 * and p.105's "Always true" fallback is only a fallback if it is last. Moving
 * a rule is therefore a real control, not a convenience — without it, getting
 * the order wrong means deleting rules and retyping them.
 *
 * **Which comparisons a rule may use depends on the compared property's base
 * type** (p.105 label C), and the compared property need not be the one being
 * painted (label B). So the editor takes every property on the type, offers
 * only the comparisons that fit whichever one a rule reads, and resets the
 * comparison when that choice changes — a stale comparison would be a rule the
 * server refuses, saved from a form that looked settled.
 *
 * The rules the Apply button enforces are `services/conditional_format.py`'s,
 * checked here so a filled-in form does not become a 422 after the dialog has
 * closed. Same argument as `value-format-editor.tsx`.
 */

import { useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import type { ConditionalRule, PropertyDataType } from "@/lib/types";
import { conditionalStyle } from "@/lib/conditional-format";

/** p.105 label C, mirroring `COMPARISONS_BY_TYPE` on the server. */
const COMPARISONS: Record<string, [string, string][]> = {
  string: [["string", "String comparison"], ["is_null", "Is null"]],
  integer: [["numeric_range", "Numeric range"], ["numeric_exact", "Exact number"],
            ["is_null", "Is null"]],
  float: [["numeric_range", "Numeric range"], ["numeric_exact", "Exact number"],
          ["is_null", "Is null"]],
  boolean: [["boolean", "Is true / false"], ["is_null", "Is null"]],
  date: [["is_null", "Is null"]],
  timestamp: [["is_null", "Is null"]],
};

const FALLBACK_COMPARISONS: [string, string][] = [["is_null", "Is null"]];

/** p.105 label D. */
const STRING_OPERATORS: [string, string][] = [
  ["is_exactly", "Is exactly"],
  ["contains", "Contains"],
  ["starts_with", "Starts with"],
  ["ends_with", "Ends with"],
];

export interface EditableProperty {
  api_name: string;
  data_type: PropertyDataType;
}

function comparisonsFor(dataType: string | undefined): [string, string][] {
  return COMPARISONS[dataType ?? ""] ?? FALLBACK_COMPARISONS;
}

/** A new rule, in the shape the server accepts: p.104's "newly created default
 * rule". `is_null` is the one comparison every base type allows, so a default
 * rule is legal whatever property it lands on. */
function defaultRule(property: string): ConditionalRule {
  return { kind: "standard", property, comparison: "is_null", colour: "#6b7280" };
}

function isHex(value: string | undefined): boolean {
  return !!value && /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value);
}

/** The server's refusals, in the one place where the answer can still change.
 * Returns the first problem as a sentence, or null. */
export function ruleProblem(
  rules: ConditionalRule[],
  types: Record<string, string>,
): string | null {
  for (const [index, rule] of rules.entries()) {
    const where = `Rule ${index + 1}`;
    if (rule.kind === "always" && index !== rules.length - 1)
      return `${where} always matches, so the rules after it can never apply.`;
    if (!rule.colour && !rule.background && !rule.align)
      return `${where} changes nothing, so it could never be seen.`;
    for (const field of ["colour", "background"] as const) {
      if (rule[field] !== undefined && !isHex(rule[field]))
        return `${where}: ${field} must be a hex colour like #1a7f37.`;
    }
    if (rule.kind === "always") continue;
    const allowed = comparisonsFor(types[rule.property]).map(([v]) => v);
    if (!allowed.includes(rule.comparison))
      return `${where}: ${rule.property} is ${types[rule.property]}, so that comparison does not apply.`;
    if (rule.comparison === "numeric_range") {
      if (rule.min === undefined && rule.max === undefined)
        return `${where} needs a min, a max, or both.`;
      if (rule.min !== undefined && rule.max !== undefined && rule.min > rule.max)
        return `${where}: min cannot be more than max.`;
    }
    if (rule.comparison === "string" || rule.comparison === "numeric_exact") {
      if (rule.value_property === undefined && (rule.value === undefined || rule.value === ""))
        return `${where} needs a value to compare against.`;
    }
  }
  return null;
}

export function ConditionalFormatEditor({
  open,
  onClose,
  propertyName,
  properties,
  value,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  propertyName: string;
  /** Every property on the type — a rule may read any of them (p.105 label B). */
  properties: EditableProperty[];
  value: ConditionalRule[] | null | undefined;
  onSave: (next: ConditionalRule[] | null) => void;
}) {
  const [rules, setRules] = useState<ConditionalRule[]>(value ?? []);
  const types = Object.fromEntries(properties.map((p) => [p.api_name, p.data_type]));
  const problem = ruleProblem(rules, types);

  function patch(index: number, next: Partial<ConditionalRule>) {
    setRules(rules.map((r, i) => (i === index ? ({ ...r, ...next } as ConditionalRule) : r)));
  }
  function move(index: number, by: number) {
    const next = [...rules];
    const [row] = next.splice(index, 1);
    next.splice(index + by, 0, row!);
    setRules(next);
  }

  // p.106's Preview row, against a made-up object: the same evaluator the
  // tables use, so "which rule wins" is answered here rather than guessed.
  const [sample, setSample] = useState("");
  const previewStyle = conditionalStyle(rules, { [propertyName]: sample });

  return (
    <Dialog open={open} title={`Rules for ${propertyName}`} onClose={onClose} wide>
      {rules.length === 0 && (
        <p className="field-hint">
          No rules. Values render exactly as they do now.
        </p>
      )}
      {rules.map((rule, index) => (
        <fieldset key={index} className="cf-rule" data-testid={`rule-${index + 1}`}>
          <legend>Rule {index + 1}</legend>
          <div className="row-actions">
            <select
              data-testid={`rule-${index + 1}-kind`}
              value={rule.kind}
              onChange={(e) =>
                setRules(rules.map((r, i) =>
                  i !== index
                    ? r
                    : e.target.value === "always"
                      ? ({ kind: "always", colour: r.colour, background: r.background,
                           align: r.align } as ConditionalRule)
                      : { ...defaultRule(propertyName), colour: r.colour,
                          background: r.background, align: r.align }))
              }
            >
              <option value="standard">Standard rule</option>
              <option value="always">Always true</option>
            </select>

            {rule.kind === "standard" && (
              <>
                {/* Label B: whose value the rule reads. */}
                <select
                  data-testid={`rule-${index + 1}-property`}
                  value={rule.property}
                  onChange={(e) => {
                    // The comparison goes with the property. Keeping a numeric
                    // range while switching to a string is a rule the server
                    // refuses, from a form that looked settled.
                    const property = e.target.value;
                    const allowed = comparisonsFor(types[property]);
                    patch(index, {
                      property,
                      comparison: allowed[0]![0],
                      operator: undefined, value: undefined, min: undefined,
                      max: undefined, value_property: undefined,
                    } as Partial<ConditionalRule>);
                  }}
                >
                  {properties.map((p) => (
                    <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                  ))}
                </select>

                <select
                  data-testid={`rule-${index + 1}-comparison`}
                  value={rule.comparison}
                  onChange={(e) =>
                    patch(index, {
                      comparison: e.target.value,
                      operator: e.target.value === "string" ? "is_exactly" : undefined,
                      value: e.target.value === "boolean" ? true : undefined,
                      min: undefined, max: undefined, value_property: undefined,
                    } as Partial<ConditionalRule>)
                  }
                >
                  {comparisonsFor(types[rule.property]).map(([v, label]) => (
                    <option key={v} value={v}>{label}</option>
                  ))}
                </select>

                {rule.comparison === "string" && (
                  <select
                    data-testid={`rule-${index + 1}-operator`}
                    value={rule.operator}
                    onChange={(e) =>
                      patch(index, { operator: e.target.value } as Partial<ConditionalRule>)
                    }
                  >
                    {STRING_OPERATORS.map(([v, label]) => (
                      <option key={v} value={v}>{label}</option>
                    ))}
                  </select>
                )}

                {(rule.comparison === "string" || rule.comparison === "numeric_exact") && (
                  <input
                    data-testid={`rule-${index + 1}-value`}
                    placeholder="value"
                    value={rule.value === undefined ? "" : String(rule.value)}
                    onChange={(e) =>
                      patch(index, {
                        value: rule.comparison === "numeric_exact"
                          ? Number(e.target.value)
                          : e.target.value,
                      } as Partial<ConditionalRule>)
                    }
                  />
                )}

                {rule.comparison === "boolean" && (
                  <select
                    data-testid={`rule-${index + 1}-boolean`}
                    value={rule.value ? "true" : "false"}
                    onChange={(e) =>
                      patch(index, { value: e.target.value === "true" } as Partial<ConditionalRule>)
                    }
                  >
                    <option value="true">is true</option>
                    <option value="false">is false</option>
                  </select>
                )}

                {rule.comparison === "numeric_range" && (
                  <>
                    <input
                      type="number" placeholder="min"
                      data-testid={`rule-${index + 1}-min`}
                      value={rule.min ?? ""}
                      onChange={(e) =>
                        patch(index, {
                          min: e.target.value === "" ? undefined : Number(e.target.value),
                        } as Partial<ConditionalRule>)
                      }
                    />
                    <input
                      type="number" placeholder="max"
                      data-testid={`rule-${index + 1}-max`}
                      value={rule.max ?? ""}
                      onChange={(e) =>
                        patch(index, {
                          max: e.target.value === "" ? undefined : Number(e.target.value),
                        } as Partial<ConditionalRule>)
                      }
                    />
                  </>
                )}

                {/* Label F. */}
                <label className="field-inline">
                  <input
                    type="checkbox"
                    data-testid={`rule-${index + 1}-negate`}
                    checked={!!rule.negate}
                    onChange={(e) =>
                      patch(index, { negate: e.target.checked } as Partial<ConditionalRule>)
                    }
                  />
                  <span>invert</span>
                </label>
              </>
            )}

            <input
              data-testid={`rule-${index + 1}-colour`}
              placeholder="#1a7f37"
              value={rule.colour ?? ""}
              onChange={(e) => patch(index, { colour: e.target.value || undefined })}
            />
            <button type="button" className="btn"
                    aria-label={`Move rule ${index + 1} up`}
                    disabled={index === 0}
                    onClick={() => move(index, -1)}>↑</button>
            <button type="button" className="btn"
                    aria-label={`Move rule ${index + 1} down`}
                    disabled={index === rules.length - 1}
                    onClick={() => move(index, 1)}>↓</button>
            <button type="button" className="btn danger"
                    aria-label={`Remove rule ${index + 1}`}
                    onClick={() => setRules(rules.filter((_, i) => i !== index))}>
              Remove
            </button>
          </div>
        </fieldset>
      ))}

      <button
        type="button"
        className="btn"
        data-testid="rule-add"
        onClick={() => setRules([...rules, defaultRule(propertyName)])}
      >
        Add a rule
      </button>

      {rules.length > 0 && (
        <Field label="Preview" hint="p.106 — the same evaluator the tables use.">
          <input
            data-testid="rule-sample"
            placeholder={`a ${propertyName} value`}
            value={sample}
            onChange={(e) => setSample(e.target.value)}
          />
          <output
            data-testid="rule-preview"
            className="format-preview"
            style={previewStyle?.colour ? { color: previewStyle.colour } : undefined}
          >
            {sample || "∅"}
          </output>
        </Field>
      )}

      {problem && <p className="field-hint" data-testid="rule-problem">{problem}</p>}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="rule-save"
          disabled={problem !== null}
          onClick={() => {
            onSave(rules.length ? rules : null);
            onClose();
          }}
        >
          Apply
        </button>
      </div>
    </Dialog>
  );
}
