"use client";

/** The variables panel (roadmap phase 2, item 1.2; decision 0002).
 *
 * Canvas's parameters were declared as a *side effect of placing a widget*: a
 * Filter's `name` prop was the only place a parameter came into existence, and
 * a reference was a string that happened to match. This panel is the other
 * design: a variable exists because the module declares it, and every widget
 * points at an id.
 *
 * Three things it is careful about, each the counterpart of a server refusal
 * (`services/workshop_variables.py`):
 *
 *   - **Renaming changes the label, never the id.** That is the entire point
 *     of an opaque id, so the input is labelled "Label" and the id is shown
 *     beside it as unchangeable fact rather than as a field.
 *   - **A variable something uses cannot be deleted**, and the panel says what
 *     uses it *before* offering the button rather than surfacing a 422 after.
 *     The server is still what enforces this; this is the affordance.
 *   - **A derived variable's value is not editable.** It is a function of its
 *     inputs, and a box a person could type into would imply otherwise.
 *
 * Values shown beside each variable come from the server
 * (`canvasApi.evaluateVariables`), so the transformation semantics have one
 * implementation rather than two that drift - see the API route's own note.
 */

import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { canvas as canvasApi } from "@/lib/api";
import type { WorkshopTransform, WorkshopVariable, WorkshopVariableKind } from "@/lib/types";
import { newVariableId, usagesOf } from "@/lib/workshop-module";

const KINDS: WorkshopVariableKind[] = [
  "string",
  "number",
  "boolean",
  "date",
  "timestamp",
  "array",
  "single_object",
  "object_set",
];

/** Matches `TRANSFORMS` in the service. `object_property` and
 * `object_set_aggregation` are deliberately absent - they read the ontology,
 * so the API refuses them until they are built, and offering them here would
 * be offering a choice that fails on save. */
const TRANSFORMS: { value: WorkshopTransform; label: string; arity: string }[] = [
  { value: "concat", label: "Join text", arity: "one or more" },
  { value: "if_else", label: "If / else", arity: "condition, then, else" },
  { value: "cast", label: "Convert type", arity: "one" },
  { value: "is_empty", label: "Is empty", arity: "one" },
  { value: "is_not_empty", label: "Is not empty", arity: "one" },
];

const CAST_TARGETS = ["string", "number", "boolean"] as const;

/** How many inputs each transform takes, so the editor can render the right
 * number of slots instead of a free-form list the server will reject. */
function arityOf(transform: WorkshopTransform): number | "many" {
  if (transform === "concat") return "many";
  if (transform === "if_else") return 3;
  return 1;
}

function slotLabels(transform: WorkshopTransform): string[] {
  if (transform === "if_else") return ["Condition", "Then", "Else"];
  if (transform === "cast") return ["Value"];
  return ["Value"];
}

export function VariablesPanel({
  workspaceId,
  projectId,
  appId,
  variables,
  layout,
  onChange,
  readOnly,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
  variables: Record<string, WorkshopVariable>;
  /** The saved layout, for usage counts. Unsaved widget additions are not in
   * it yet - which is honest: a binding nobody has saved is not yet a reason
   * to refuse a deletion, and the server would agree. */
  layout: unknown;
  onChange: (next: Record<string, WorkshopVariable>) => void;
  readOnly: boolean;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [failure, setFailure] = useState<string | null>(null);

  const ids = useMemo(() => Object.keys(variables), [variables]);

  // Evaluated values, from the server. Refreshed when the set of variables
  // changes, not on every keystroke: this reads the *saved* document, so it
  // cannot show a derivation that has not been saved yet, and pretending
  // otherwise would be worse than showing nothing.
  const evaluate = useMutation({
    mutationFn: () => canvasApi.evaluateVariables(workspaceId, projectId, appId, {}),
    onSuccess: (data) => setValues(data.values),
    onError: () => setValues({}),
  });
  useEffect(() => {
    evaluate.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(",")]);

  function update(id: string, patch: Partial<WorkshopVariable>) {
    const current = variables[id];
    if (!current) return;
    onChange({ ...variables, [id]: { ...current, ...patch } });
  }

  function add() {
    const id = newVariableId();
    onChange({
      ...variables,
      [id]: { id, kind: "string", label: `Variable ${ids.length + 1}` },
    });
    setOpenId(id);
    setFailure(null);
  }

  function remove(id: string) {
    const variable = variables[id];
    if (!variable) return;
    const usages = usagesOf({ format: 2, layout, variables }, id);
    if (usages.length > 0) {
      // Said here rather than after a 422, because the person is about to lose
      // work they cannot see the cost of. The server refuses this too.
      setFailure(
        `${variable.label} is used by ${usages.length} ` +
          `${usages.length === 1 ? "thing" : "things"} ` +
          `(${usages.map((u) => `${u.node}.${u.prop}`).join(", ")}). ` +
          "Unbind it there first.",
      );
      return;
    }
    const next = { ...variables };
    delete next[id];
    onChange(next);
    if (openId === id) setOpenId(null);
    setFailure(null);
  }

  return (
    <div className="vars-panel">
      <div className="vars-head">
        <h3>Variables</h3>
        {!readOnly && (
          <button type="button" className="btn quiet" onClick={add}>
            New
          </button>
        )}
      </div>

      {failure && <p className="state error">{failure}</p>}

      {ids.length === 0 ? (
        <p className="state">
          No variables yet. A variable is what wires widgets to each other — a
          filter sets one, a table reads it.
        </p>
      ) : (
        <ul className="vars-list">
          {ids.map((id) => {
            const variable = variables[id]!; // ids came from variables
            const usages = usagesOf({ format: 2, layout, variables }, id);
            const open = openId === id;
            return (
              <li key={id} className={`vars-item${open ? " on" : ""}`}>
                <button
                  type="button"
                  className="vars-row"
                  onClick={() => setOpenId(open ? null : id)}
                >
                  <span className="vars-name">{variable.label}</span>
                  <span className="vars-kind">{variable.kind}</span>
                  {variable.derivation && <span className="vars-derived">derived</span>}
                  <span className="vars-usage soft">
                    {usages.length === 0 ? "unused" : `used ${usages.length}×`}
                  </span>
                </button>

                {open && (
                  <div className="vars-editor">
                    <label>
                      Label
                      <input
                        value={variable.label}
                        readOnly={readOnly}
                        onChange={(e) => update(id, { label: e.target.value })}
                      />
                    </label>
                    {/* The id is fact, not a field. Renaming that broke every
                        reference is the failure this format removes. */}
                    <p className="vars-id soft">
                      id <code>{id}</code> — never changes, so renaming is free
                    </p>

                    <label>
                      Type
                      <select
                        value={variable.kind}
                        disabled={readOnly}
                        onChange={(e) =>
                          update(id, { kind: e.target.value as WorkshopVariableKind })
                        }
                      >
                        {KINDS.map((k) => (
                          <option key={k} value={k}>
                            {k}
                          </option>
                        ))}
                      </select>
                    </label>

                    {variable.derivation ? (
                      <DerivationEditor
                        variable={variable}
                        variables={variables}
                        readOnly={readOnly}
                        onChange={(derivation) => update(id, { derivation })}
                        onClear={() => {
                          const { derivation: _dropped, ...rest } = variable;
                          onChange({ ...variables, [id]: rest });
                        }}
                      />
                    ) : (
                      <>
                        <label>
                          Default
                          <input
                            value={String(variable.default ?? "")}
                            readOnly={readOnly}
                            placeholder="empty"
                            onChange={(e) =>
                              update(id, { default: e.target.value === "" ? undefined : e.target.value })
                            }
                          />
                        </label>
                        {!readOnly && (
                          <button
                            type="button"
                            className="btn quiet"
                            onClick={() =>
                              update(id, {
                                derivation: { transform: "concat", inputs: [] },
                              })
                            }
                          >
                            Make this derived
                          </button>
                        )}
                      </>
                    )}

                    <p className="vars-value">
                      value{" "}
                      {values[id] === undefined || values[id] === null ? (
                        <span className="soft">empty</span>
                      ) : (
                        <code>{String(values[id])}</code>
                      )}
                      <span className="soft"> (as last saved)</span>
                    </p>

                    {!readOnly && (
                      <button type="button" className="btn danger" onClick={() => remove(id)}>
                        Delete
                      </button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function DerivationEditor({
  variable,
  variables,
  readOnly,
  onChange,
  onClear,
}: {
  variable: WorkshopVariable;
  variables: Record<string, WorkshopVariable>;
  readOnly: boolean;
  onChange: (d: NonNullable<WorkshopVariable["derivation"]>) => void;
  onClear: () => void;
}) {
  const derivation = variable.derivation!;
  const arity = arityOf(derivation.transform);
  // A variable may not read itself, and the server refuses it. Leaving it out
  // of the picker means the refusal is one somebody cannot walk into.
  const candidates = Object.values(variables).filter((v) => v.id !== variable.id);

  function setInput(index: number, value: string) {
    const inputs = [...derivation.inputs];
    inputs[index] = value;
    onChange({ ...derivation, inputs: inputs.filter(Boolean) });
  }

  const slots =
    arity === "many"
      ? [...derivation.inputs, ""]
      : Array.from({ length: arity }, (_, i) => derivation.inputs[i] ?? "");

  return (
    <div className="vars-derivation">
      <label>
        Computed by
        <select
          value={derivation.transform}
          disabled={readOnly}
          onChange={(e) =>
            onChange({
              transform: e.target.value as WorkshopTransform,
              // Inputs are cleared on a transform change rather than carried:
              // three inputs meant as condition/then/else are not three parts
              // of a join, and keeping them would produce a plausible-looking
              // derivation nobody configured.
              inputs: [],
              config: {},
            })
          }
        >
          {TRANSFORMS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>

      {slots.map((value, index) => (
        <label key={index}>
          {arity === "many" ? `Part ${index + 1}` : slotLabels(derivation.transform)[index]}
          <select
            value={value}
            disabled={readOnly}
            onChange={(e) => setInput(index, e.target.value)}
          >
            <option value="">choose a variable…</option>
            {candidates.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        </label>
      ))}

      {derivation.transform === "concat" && (
        <label>
          Separator
          <input
            value={String(derivation.config?.separator ?? "")}
            readOnly={readOnly}
            placeholder="none"
            onChange={(e) =>
              onChange({ ...derivation, config: { ...derivation.config, separator: e.target.value } })
            }
          />
        </label>
      )}

      {derivation.transform === "cast" && (
        <label>
          Convert to
          <select
            value={String(derivation.config?.to ?? "string")}
            disabled={readOnly}
            onChange={(e) =>
              onChange({ ...derivation, config: { ...derivation.config, to: e.target.value } })
            }
          >
            {CAST_TARGETS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      )}

      {!readOnly && (
        <button type="button" className="btn quiet" onClick={onClear}>
          Stop deriving
        </button>
      )}
    </div>
  );
}
