"use client";

/**
 * Building a value type's constraint (Foundry `object-link-types` p.233–234).
 *
 * > "Each value type may optionally define a constraint to enforce data
 * > validation… Validators can be regular expressions for `String` types,
 * > enums, ranges, or other validation methods depending on the base type."
 * > (p.224 step 6, p.233)
 *
 * **Only the kinds the base type can carry are offered**, which is p.233's own
 * arrangement — the constraint list is per base type, not a single menu with
 * most of it greyed out. The walk that decides which those are lives in
 * `lib/value-type.ts`, pure and unit-tested; this is the controls around it.
 *
 * **A range says what it bounds.** For every type but `string` that is the
 * value; for a string p.233 constrains the *length*, and one word for two
 * meanings is how somebody ends up believing they bounded the alphabet.
 */

import { useState } from "react";
import { Field } from "@/components/dialog";
import {
  constraintProblem, kindsFor, rangeLabel, type ConstraintKind,
} from "@/lib/value-type";
import type { PropertyDataType, ValueConstraint } from "@/lib/types";

const KIND_LABELS: Record<ConstraintKind, string> = {
  enum: "One of a fixed list",
  range: "Within a range",
  regex: "Matches a pattern",
  uuid: "Is a UUID",
};

/** The bounds are text in the form whatever the base type: a date is typed as
 * `2026-01-31`, and a number typed into a number input still arrives as a
 * string. Converted once, here, so the shape that leaves is the shape the
 * server parses. */
function bound(raw: string, baseType: PropertyDataType): number | string | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  if (baseType === "date" || baseType === "timestamp") return trimmed;
  const n = Number(trimmed);
  return Number.isNaN(n) ? trimmed : n;
}

export function ValueConstraintEditor({
  baseType,
  value,
  onChange,
}: {
  baseType: PropertyDataType;
  value: ValueConstraint | null;
  onChange: (next: ValueConstraint | null) => void;
}) {
  const kinds = kindsFor(baseType);
  // Kept as text so a half-typed "1," or "2026-" is not thrown away on every
  // keystroke by a parse that cannot yet succeed.
  const [enumText, setEnumText] = useState(
    value?.kind === "enum" ? value.values.map(String).join("\n") : "",
  );
  const [minText, setMinText] = useState(
    value?.kind === "range" && value.minimum !== undefined ? String(value.minimum) : "",
  );
  const [maxText, setMaxText] = useState(
    value?.kind === "range" && value.maximum !== undefined ? String(value.maximum) : "",
  );

  if (!kinds.length) {
    return (
      <p className="field-hint" data-testid="constraint-unavailable">
        A {baseType} value type carries meaning but has no constraint to apply —
        p.233 lists none for this base type.
      </p>
    );
  }

  function setKind(kind: string) {
    if (!kind) return onChange(null);
    if (kind === "enum") return onChange({ kind: "enum", values: [] });
    if (kind === "range") return onChange({ kind: "range" });
    if (kind === "regex") return onChange({ kind: "regex", pattern: "" });
    onChange({ kind: "uuid" });
  }

  function setRange(min: string, max: string) {
    onChange({
      kind: "range",
      ...(bound(min, baseType) !== undefined ? { minimum: bound(min, baseType) } : {}),
      ...(bound(max, baseType) !== undefined ? { maximum: bound(max, baseType) } : {}),
    });
  }

  const problem = constraintProblem(value, baseType);

  return (
    <div>
      <Field
        label="Constraint"
        hint="Optional — p.224. A value type carries meaning even with no rule."
      >
        <select
          data-testid="constraint-kind"
          value={value?.kind ?? ""}
          onChange={(e) => setKind(e.target.value)}
        >
          <option value="">No constraint</option>
          {kinds.map((k) => (
            <option key={k} value={k}>{KIND_LABELS[k]}</option>
          ))}
        </select>
      </Field>

      {value?.kind === "enum" && (
        <Field label="Allowed values" hint="One per line.">
          <textarea
            data-testid="constraint-enum"
            value={enumText}
            onChange={(e) => {
              setEnumText(e.target.value);
              const values = e.target.value
                .split("\n")
                .map((v) => v.trim())
                .filter(Boolean)
                // A numeric base type wants numbers, not the text of them:
                // sending "1" where the server expects 1 is refused, and it
                // is refused *after* somebody has typed the whole list.
                .map((v) =>
                  baseType === "integer" || baseType === "float"
                    ? Number(v)
                    : baseType === "boolean"
                      ? v.toLowerCase() === "true"
                      : v,
                );
              onChange({
                kind: "enum",
                values,
                ...(baseType === "string"
                  ? { case_sensitive: value.case_sensitive ?? true }
                  : {}),
              });
            }}
          />
        </Field>
      )}

      {value?.kind === "enum" && baseType === "string" && (
        // p.233 offers this for strings only, so it is drawn for strings only.
        <label style={{ fontSize: 12.5, display: "flex", gap: 6, alignItems: "center" }}>
          <input
            type="checkbox"
            data-testid="constraint-case-sensitive"
            checked={value.case_sensitive ?? true}
            onChange={(e) => onChange({ ...value, case_sensitive: e.target.checked })}
          />
          Case sensitive
        </label>
      )}

      {value?.kind === "range" && (
        <>
          <Field
            label={`Minimum ${rangeLabel(baseType).toLowerCase()}`}
            hint={
              baseType === "string"
                ? "p.233: a string's range bounds how many characters it has."
                : "Leave blank for no lower bound."
            }
          >
            <input
              type="text"
              data-testid="constraint-min"
              value={minText}
              onChange={(e) => {
                setMinText(e.target.value);
                setRange(e.target.value, maxText);
              }}
            />
          </Field>
          <Field label={`Maximum ${rangeLabel(baseType).toLowerCase()}`}>
            <input
              type="text"
              data-testid="constraint-max"
              value={maxText}
              onChange={(e) => {
                setMaxText(e.target.value);
                setRange(minText, e.target.value);
              }}
            />
          </Field>
        </>
      )}

      {value?.kind === "regex" && (
        <>
          <Field label="Pattern" hint="The whole value must match, unless you allow a substring.">
            <input
              type="text"
              data-testid="constraint-pattern"
              value={value.pattern}
              onChange={(e) => onChange({ ...value, pattern: e.target.value })}
            />
          </Field>
          <label style={{ fontSize: 12.5, display: "flex", gap: 6, alignItems: "center" }}>
            <input
              type="checkbox"
              data-testid="constraint-substring"
              checked={value.substring ?? false}
              onChange={(e) => onChange({ ...value, substring: e.target.checked })}
            />
            Pass if it matches anywhere in the value (p.233)
          </label>
        </>
      )}

      {problem && (
        <p className="field-hint" data-testid="constraint-problem">{problem}</p>
      )}
    </div>
  );
}
