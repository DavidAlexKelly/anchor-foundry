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

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { canvas as canvasApi, objects as objectsApi } from "@/lib/api";
import type { WorkshopTransform, WorkshopVariable, WorkshopVariableKind } from "@/lib/types";
import { newVariableId, usagesOf } from "@/lib/workshop-module";
import { ROUTABLE_KINDS } from "./routing";

/** Mirrors `SAVABLE_KINDS` in `services/workshop_variables.py` (p.205). */
const SAVABLE_KINDS = [
  "string", "number", "boolean", "date", "timestamp",
  "array", "single_object", "object_set",
];

const KINDS: WorkshopVariableKind[] = [
  "string",
  "number",
  "boolean",
  "date",
  "timestamp",
  "array",
  "single_object",
  "object_set",
  "time_series_set",
];

/** p.132's array element types, mirroring `ARRAY_ELEMENTS` in the service.
 *
 * `struct` is absent for the reason `object_set_aggregation` is absent from
 * `TRANSFORMS` below: the API refuses it until there is a kind carrying named
 * fields, and offering a choice that fails on save is the thing these lists
 * exist to avoid. */
const ARRAY_ELEMENTS = ["string", "number", "boolean", "date", "timestamp"] as const;

/** Matches `TRANSFORMS` in the service. `object_set_aggregation` is
 * deliberately absent - it reads the ontology, so the API refuses it until it
 * is built, and offering it here would be offering a choice that fails on
 * save. `object_property` used to be absent for the same reason and is here
 * now (§84): a `single_object` variable holds the object somebody picked, so
 * reading a property off it needs no round trip. */
const TRANSFORMS: { value: WorkshopTransform; label: string; arity: string }[] = [
  { value: "concat", label: "Join text", arity: "one or more" },
  { value: "if_else", label: "If / else", arity: "condition, then, else" },
  { value: "cast", label: "Convert type", arity: "one" },
  { value: "is_empty", label: "Is empty", arity: "one" },
  { value: "is_not_empty", label: "Is not empty", arity: "one" },
  { value: "object_property", label: "A property of an object", arity: "one" },
  // p.444's "reused in widget configurations": `narrow_set` applies filter
  // state to a set, this reads a value back out of it for a heading, a
  // chart title, or an action's default.
  { value: "filter_value", label: "A value chosen in a filter", arity: "one" },
];

/** Offered on `time_series_set` variables, and the only thing offered there -
 * a series is read *through* an object (p.76), so there is nothing else a
 * series variable could be derived from. */
const SERIES_TRANSFORM: WorkshopTransform = "object_series";

/** The service's `time_series.INTERVALS` and `AGGREGATES`, in the order they
 * are declared there. Retyped rather than fetched because they are a closed
 * vocabulary in a builder panel; the server refuses anything outside them, so
 * a copy that drifted would show as a save that fails and names the list. */
const SERIES_INTERVALS = ["none", "hour", "day", "week", "month"] as const;
const SERIES_AGGREGATES = ["avg", "min", "max", "sum", "count", "last"] as const;

/** Offered on `object_set` variables, and the only things offered there -
 * narrowing a set is what a derived object set *is*. Two ways to narrow one:
 * `filter_set` against a value a control holds, `narrow_set` against a list of
 * clauses a Filter List writes. */
const SET_TRANSFORMS: WorkshopTransform[] = ["filter_set", "narrow_set"];

/** The third thing a derived object set can be: the far side of a link from
 * another set (§155). Not in `SET_TRANSFORMS` because it is chosen a level up -
 * "narrowed" and "followed" are different questions, and folding it into the
 * "Narrowed by" list would put "follow a link" among two ways of filtering. */
const TRAVERSE: WorkshopTransform = "traverse_set";

const CAST_TARGETS = ["string", "number", "boolean"] as const;

/** How many inputs each transform takes, so the editor can render the right
 * number of slots instead of a free-form list the server will reject. */
function arityOf(transform: WorkshopTransform): number | "many" {
  if (transform === "concat") return "many";
  if (transform === "if_else") return 3;
  if (transform === "filter_set") return 2;
  return 1;
}

function slotLabels(transform: WorkshopTransform): string[] {
  if (transform === "if_else") return ["Condition", "Then", "Else"];
  if (transform === "filter_set") return ["Set to narrow", "Filter value from"];
  if (transform === "cast") return ["Value"];
  if (transform === "object_property") return ["Object"];
  if (transform === "filter_value") return ["Filter clauses"];
  if (transform === "object_series") return ["Object"];
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

                    <InterfaceEditor
                      variable={variable}
                      readOnly={readOnly}
                      onChange={(patch) => update(id, patch)}
                    />

                    <label>
                      Type
                      <select
                        value={variable.kind}
                        disabled={readOnly}
                        onChange={(e) => {
                          const kind = e.target.value as WorkshopVariableKind;
                          // Retyping to object_set without a set would be a
                          // document the server refuses ("names no object
                          // type"), so the shape follows the kind rather than
                          // leaving somebody to discover it at save.
                          const { object_set: _s, derivation: _d, ...rest } = variable;
                          update(id, {
                            ...rest,
                            kind,
                            ...(kind === "object_set"
                              ? { object_set: { object_type_id: "", filters: [] } }
                              : {}),
                            // Same reason, the other way round: a series
                            // variable with no derivation is a document the
                            // server refuses ("not derived from an object"),
                            // so the shape follows the kind here rather than
                            // being discovered at save.
                            ...(kind === "time_series_set"
                              ? {
                                  derivation: {
                                    transform: SERIES_TRANSFORM,
                                    inputs: [],
                                    config: { interval: "day", aggregate: "avg" },
                                  },
                                }
                              : {}),
                          } as Partial<WorkshopVariable>);
                        }}
                      >
                        {KINDS.map((k) => (
                          <option key={k} value={k}>
                            {k}
                          </option>
                        ))}
                      </select>
                    </label>

                    {/* p.132's array element type. Shown only for an array,
                        because an element on anything else is a setting with
                        no effect and the server refuses it. **"—" is a real
                        choice, not a placeholder**: an untyped array is valid
                        and is what every array written before this is, so the
                        picker has to be able to say so and to go back to it. */}
                    {variable.kind === "array" && (
                      <label>
                        Entries
                        <select
                          data-testid="variable-element"
                          value={variable.element ?? ""}
                          disabled={readOnly}
                          onChange={(e) => {
                            const element = e.target.value;
                            const { element: _drop, ...rest } = variable;
                            update(id, (element
                              ? { ...rest, element }
                              : rest) as Partial<WorkshopVariable>);
                          }}
                        >
                          <option value="">— untyped</option>
                          {ARRAY_ELEMENTS.map((el) => (
                            <option key={el} value={el}>{el}</option>
                          ))}
                        </select>
                        <span className="field-hint">
                          A loop can only iterate an array whose entries have a type
                          (p.132).
                        </span>
                      </label>
                    )}

                    {variable.kind === "object_set" ? (
                      <ObjectSetEditor
                        workspaceId={workspaceId}
                        variable={variable}
                        variables={variables}
                        readOnly={readOnly}
                        onChange={(next) => onChange({ ...variables, [id]: next })}
                      />
                    ) : variable.derivation ? (
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

/** The external ID and the module-interface toggle (Foundry p.163).
 *
 * Two controls rather than one, and the order on screen is the order Foundry
 * describes: "add an external ID, and make sure the toggle for module
 * interface is enabled". They are not independent — the interface is
 * *addressed* by external ID, so the toggle is disabled until there is one,
 * and the hint says why rather than leaving a dead control to puzzle over.
 *
 * The API refuses both halves of this independently (an interface without an
 * external ID, an external ID that would need URL-encoding), so nothing here is
 * the only thing standing between a bad document and the database. This is the
 * copy that makes the refusal unnecessary, not the check that replaces it. */
function InterfaceEditor({
  variable,
  readOnly,
  onChange,
}: {
  variable: WorkshopVariable;
  readOnly: boolean;
  onChange: (patch: Partial<WorkshopVariable>) => void;
}) {
  const externalId = variable.external_id ?? "";
  const published = variable.interface != null;
  const routable = ROUTABLE_KINDS.includes(variable.kind);
  // p.205's list, and wider than the URL's: a state is a document, so it can
  // hold a clause list or a set definition that a query string cannot. Mirrors
  // `SAVABLE_KINDS` in the service, which is what refuses a save.
  const savable = !variable.derivation && SAVABLE_KINDS.includes(variable.kind);

  return (
    <div className="vars-interface">
      <label>
        External ID
        <input
          value={externalId}
          readOnly={readOnly}
          placeholder="status"
          data-testid="variable-external-id"
          onChange={(e) => {
            const next = e.target.value.trim();
            // Clearing the external ID takes the interface with it rather than
            // leaving a published variable with no name to call it by — which
            // is a document the API refuses, so the alternative is a save that
            // fails for a reason two fields away from the one just edited.
            onChange(
              next
                ? { external_id: next }
                : ({ external_id: undefined, interface: undefined } as Partial<WorkshopVariable>),
            );
          }}
        />
      </label>
      <p className="vars-id soft">
        The name a URL and an embedding module use. Letters, digits and
        underscores — it becomes a query parameter.
      </p>

      <label className="vars-toggle">
        <input
          type="checkbox"
          checked={published}
          disabled={readOnly || !externalId}
          data-testid="variable-interface-toggle"
          onChange={(e) =>
            onChange({ interface: e.target.checked ? {} : undefined } as Partial<WorkshopVariable>)
          }
        />
        On the module interface
      </label>
      {!externalId && (
        <p className="vars-id soft">Give it an external ID first — the interface is addressed by one.</p>
      )}

      {published && (
        <>
          <label>
            Display name
            <input
              value={variable.interface?.display_name ?? ""}
              readOnly={readOnly}
              placeholder={variable.label}
              onChange={(e) =>
                onChange({
                  interface: { ...variable.interface, display_name: e.target.value || undefined },
                })
              }
            />
          </label>
          <label>
            Description
            <input
              value={variable.interface?.description ?? ""}
              readOnly={readOnly}
              placeholder="What an embedding module should pass in"
              onChange={(e) =>
                onChange({
                  interface: { ...variable.interface, description: e.target.value || undefined },
                })
              }
            />
          </label>
          <label className="vars-toggle">
            <input
              type="checkbox"
              checked={variable.interface?.required ?? false}
              disabled={readOnly}
              onChange={(e) =>
                onChange({ interface: { ...variable.interface, required: e.target.checked } })
              }
            />
            Required — refuse to save a host that leaves it unmapped
          </label>
          {/* Routing lives here rather than in its own section because it is
              only offered to interface variables: p.198 reads the URL back for
              "the external ID of a module interface variable", so a routed
              variable that is not one would be written out and never read
              back. The server refuses that; not offering it is the same
              refusal without the round trip. */}
          <label>
            In the URL
            <select
              value={variable.url_behavior ?? "never"}
              disabled={readOnly || !routable}
              data-testid="variable-url-behavior"
              onChange={(e) =>
                onChange({
                  url_behavior: e.target.value as WorkshopVariable["url_behavior"],
                })
              }
            >
              <option value="never">Never</option>
              <option value="when_visible">When used by a visible widget</option>
              <option value="always">Always</option>
            </select>
            <span className="field-hint">
              {routable
                ? "Only when it is not the default. Needs routing on, in Layout."
                : /* p.199. Said here rather than left as a disabled control
                     nobody can explain. */
                  `A ${variable.kind} cannot be in the URL — nothing would read it ` +
                  "back. Route a string and use it in this one's definition."}
            </span>
          </label>
        </>
      )}

      {/* p.76's recompute behaviour. Offered only on a derived variable
          without its own object-set definition, which is exactly p.76's list
          ("Function, Object set aggregation, Object property, Variable
          transformation, Object set filter") and its exclusion ("The Object
          set definition variable definition type does not offer recompute
          behavior configuration"). Absent rather than disabled on the rest:
          a static variable has nothing to recompute, so the control would be
          a question with no answer. */}
      {variable.derivation && !variable.object_set && (
        <label>
          Recompute
          <select
            value={variable.recompute ?? "automatic"}
            disabled={readOnly}
            data-testid="variable-recompute"
            onChange={(e) =>
              onChange({
                recompute: e.target.value === "automatic"
                  ? undefined
                  : (e.target.value as WorkshopVariable["recompute"]),
              })
            }
          >
            <option value="automatic">Automatically</option>
            <option value="only_on_event">Only when an event says so</option>
            <option value="on_load_and_event">On load, and when an event says so</option>
          </select>
          <span className="field-hint">
            {(variable.recompute ?? "automatic") === "automatic"
              ? "Recomputes whenever an input changes."
              : "Holds its value until a Recompute event fires. Wire one in Events."}
          </span>
        </label>
      )}

      {/* Outside the interface block, unlike routing: a state is read back by
          this module, by name, so an external ID is the whole requirement and
          interface membership is not one (p.202-203). Offering it only to
          interface variables would refuse a configuration the server accepts. */}
      <label className="vars-toggle">
        <input
          type="checkbox"
          checked={variable.save_state ?? false}
          disabled={readOnly || !externalId || !savable}
          data-testid="variable-save-state"
          onChange={(e) =>
            onChange({ save_state: e.target.checked || undefined } as Partial<WorkshopVariable>)
          }
        />
        Kept in a saved state
      </label>
      {!externalId ? (
        <p className="vars-id soft">
          Give it an external ID first — a state stores values by external ID.
        </p>
      ) : !savable ? (
        <p className="vars-id soft">
          {variable.derivation
            ? "Derived variables are computed from their inputs — save those instead."
            : `A ${variable.kind} cannot be kept in a state.`}
        </p>
      ) : null}
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
  // A series variable has exactly one way to be computed and no undrived
  // form, so its transform is fixed and "Stop deriving" is not offered - both
  // would lead to a document the server refuses (p.76: a series is a property
  // of an object).
  const series = variable.kind === "time_series_set";
  // A variable may not read itself, and the server refuses it. Leaving it out
  // of the picker means the refusal is one somebody cannot walk into.
  const candidates = Object.values(variables).filter(
    (v) =>
      v.id !== variable.id &&
      // A series is read through the object somebody picked, so only those are
      // offerable - any other kind would save and then resolve to a refusal.
      (!series || v.kind === "single_object"),
  );

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
          disabled={readOnly || series}
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
          {(series
            ? [{ value: SERIES_TRANSFORM, label: "A time series on an object" }]
            : TRANSFORMS
          ).map((t) => (
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

      {(derivation.transform === "object_property" ||
        derivation.transform === "filter_value") && (
        <label>
          Property
          <input
            value={String(derivation.config?.property ?? "")}
            readOnly={readOnly}
            placeholder="e.g. name"
            onChange={(e) =>
              onChange({
                ...derivation,
                config: { ...derivation.config, property: e.target.value },
              })
            }
          />
          {derivation.transform === "object_property" ? (
            /* Readable by name because it is not one of the properties: a
               row's key is its own field (`STATUS.md` §84). */
            <span className="field-hint">primary_key reads the object&apos;s key</span>
          ) : (
            <span className="field-hint">
              empty until the viewer filters on it
            </span>
          )}
        </label>
      )}

      {derivation.transform === "object_series" && (
        <>
          <label>
            Time series property
            <input
              value={String(derivation.config?.property ?? "")}
              readOnly={readOnly}
              placeholder="e.g. readings"
              onChange={(e) =>
                onChange({
                  ...derivation,
                  config: { ...derivation.config, property: e.target.value },
                })
              }
            />
            <span className="field-hint">
              a property declared <code>time_series</code> on the object&apos;s type
            </span>
          </label>
          {/* The bucket and the summariser live on the *variable*, not on each
              widget (p.76's "time series transforms"): two charts reading one
              series then agree about what a point means. */}
          <label>
            Bucket
            <select
              value={String(derivation.config?.interval ?? "day")}
              disabled={readOnly}
              onChange={(e) =>
                onChange({
                  ...derivation,
                  config: { ...derivation.config, interval: e.target.value },
                })
              }
            >
              {SERIES_INTERVALS.map((i) => (
                <option key={i} value={i}>
                  {i === "none" ? "every reading" : `by ${i}`}
                </option>
              ))}
            </select>
          </label>
          <label>
            Summarise with
            <select
              value={String(derivation.config?.aggregate ?? "avg")}
              disabled={readOnly}
              onChange={(e) =>
                onChange({
                  ...derivation,
                  config: { ...derivation.config, aggregate: e.target.value },
                })
              }
            >
              {SERIES_AGGREGATES.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      {!readOnly && !series && (
        <button type="button" className="btn quiet" onClick={onClear}>
          Stop deriving
        </button>
      )}
    </div>
  );
}

/** An object-set variable: either a base set drawn from an object type, or a
 * set narrowed from another by a filter variable.
 *
 * Exactly one of the two, because the server refuses a variable that declares
 * both - a set with two answers to "where do these rows come from" has no rule
 * for which wins. The toggle here is what makes that a choice rather than a
 * refusal somebody runs into.
 */
function ObjectSetEditor({
  workspaceId,
  variable,
  variables,
  readOnly,
  onChange,
}: {
  workspaceId: string;
  variable: WorkshopVariable;
  variables: Record<string, WorkshopVariable>;
  readOnly: boolean;
  onChange: (next: WorkshopVariable) => void;
}) {
  const types = useQuery({
    queryKey: ["object-types", workspaceId],
    queryFn: () => objectsApi.listTypes(workspaceId),
  });
  const base = (variable.object_set ?? null) as
    | { object_type_id?: string; filters?: unknown[] }
    | null;
  const derived = !!variable.derivation;

  // Sets this one could narrow. Itself excluded, and so is anything that would
  // read back round to it - the server refuses a cycle, and a picker that
  // offered one would be offering a save that fails.
  const otherSets = Object.values(variables).filter(
    (v) => v.kind === "object_set" && v.id !== variable.id,
  );
  const scalars = Object.values(variables).filter((v) => v.kind !== "object_set");
  const detail = useQuery({
    queryKey: ["object-type", base?.object_type_id],
    queryFn: () => objectsApi.getType(workspaceId, base!.object_type_id!),
    enabled: !!base?.object_type_id,
  });

  const transform = variable.derivation?.transform ?? SET_TRANSFORMS[0]!;
  const byClauses = transform === "narrow_set";
  const traversing = transform === TRAVERSE;
  // Link types are workspace-wide, and which ones apply depends on the *base*
  // set's type - which is a variable reference, so the answer is only known
  // once one is chosen. Fetched whole and filtered here rather than asked for
  // per type: the list is small and the alternative is a request per keystroke
  // in a dropdown.
  const linkTypes = useQuery({
    queryKey: ["link-types", workspaceId],
    queryFn: () => objectsApi.listLinkTypes(workspaceId),
  });
  const baseVariable = variables[variable.derivation?.inputs?.[0] ?? ""];
  const baseTypeId = baseVariable?.object_set?.object_type_id ?? "";
  // A link is offered once per end it touches this type from, because a link
  // between two types can be followed either way and the two land somewhere
  // different. Self-links appear twice on purpose.
  const hops = (linkTypes.data ?? []).flatMap((link) => {
    const out: { key: string; id: string; label: string; toType: string }[] = [];
    if (link.from_object_type_id === baseTypeId) {
      out.push({
        key: `${link.id}:to`, id: link.id, toType: link.to_object_type_id,
        label: `${link.to_side_name || link.display_name} → ${link.to_display_name}`,
      });
    }
    if (link.to_object_type_id === baseTypeId) {
      out.push({
        key: `${link.id}:from`, id: link.id, toType: link.from_object_type_id,
        label: `${link.from_side_name || link.display_name} → ${link.from_display_name}`,
      });
    }
    return out;
  });
  const arrays = Object.values(variables).filter((v) => v.kind === "array");

  function setDerivation(patch: Record<string, unknown>) {
    const d = variable.derivation ?? { transform: SET_TRANSFORMS[0]!, inputs: [], config: {} };
    onChange({ ...variable, derivation: { ...d, ...patch } as WorkshopVariable["derivation"] });
  }

  return (
    <div className="vars-derivation">
      <label>
        This set
        <select
          value={derived ? (traversing ? "followed" : "narrowed") : "type"}
          disabled={readOnly}
          data-testid="set-source"
          onChange={(e) => {
            if (e.target.value === "narrowed") {
              const { object_set: _dropped, ...rest } = variable;
              onChange({
                ...rest,
                derivation: { transform: SET_TRANSFORMS[0]!, inputs: [], config: { op: "eq" } },
              });
            } else if (e.target.value === "followed") {
              const { object_set: _dropped, ...rest } = variable;
              onChange({
                ...rest,
                derivation: { transform: TRAVERSE, inputs: [], config: {} },
              });
            } else {
              const { derivation: _dropped, ...rest } = variable;
              onChange({ ...rest, object_set: { object_type_id: "", filters: [] } });
            }
          }}
        >
          <option value="type">Draws from an object type</option>
          <option value="narrowed">Is another set, narrowed</option>
          <option value="followed">Follows a link from another set</option>
        </select>
      </label>

      {!derived ? (
        <label>
          Object type
          <select
            value={base?.object_type_id ?? ""}
            disabled={readOnly}
            onChange={(e) =>
              onChange({
                ...variable,
                object_set: { object_type_id: e.target.value, filters: [] },
              })
            }
          >
            <option value="">Choose…</option>
            {types.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.display_name}
              </option>
            ))}
          </select>
        </label>
      ) : traversing ? (
        <>
          <label>
            Starting from
            <select
              value={variable.derivation?.inputs?.[0] ?? ""}
              disabled={readOnly}
              data-testid="traversal-base"
              onChange={(e) =>
                // The link is cleared with the base, because which links apply
                // depends on the base's type - keeping one would leave a hop
                // the server refuses, saved by a control that looked fine.
                setDerivation({ inputs: [e.target.value].filter(Boolean), config: {} })
              }
            >
              <option value="">Choose a set…</option>
              {otherSets.map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
          </label>
          <label>
            Following
            <select
              value={
                variable.derivation?.config?.link_type_id
                  ? `${variable.derivation.config.link_type_id}:${
                      variable.derivation.config.object_type_id ?? ""
                    }`
                  : ""
              }
              disabled={readOnly || !baseTypeId}
              data-testid="traversal-link"
              onChange={(e) => {
                const hop = hops.find(
                  (h) => `${h.id}:${h.toType}` === e.target.value,
                );
                setDerivation({
                  // Both, together: the link says which ends exist and the
                  // landing type says which of them this hop took. The server
                  // refuses a pair that disagrees rather than following the
                  // link somewhere the definition did not say.
                  config: hop
                    ? { link_type_id: hop.id, object_type_id: hop.toType }
                    : {},
                });
              }}
            >
              <option value="">Choose a link…</option>
              {hops.map((hop) => (
                <option key={hop.key} value={`${hop.id}:${hop.toType}`}>
                  {hop.label}
                </option>
              ))}
            </select>
            <span className="field-hint">
              {!baseTypeId
                ? "Pick a set that draws from an object type first — which links apply depends on it."
                : hops.length === 0
                  ? "That type has no link types yet."
                  : "The link decides where this lands."}
            </span>
          </label>
        </>
      ) : (
        <>
          <label>
            Set to narrow
            <select
              value={variable.derivation?.inputs?.[0] ?? ""}
              disabled={readOnly}
              onChange={(e) =>
                setDerivation({
                  inputs: [e.target.value, variable.derivation?.inputs?.[1] ?? ""].filter(Boolean),
                })
              }
            >
              <option value="">Choose a set…</option>
              {otherSets.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
          {/* Two ways to narrow a set, and they differ in *who* chooses the
              properties: one filter the app author fixed, or a list the viewer
              builds in a Filter List. `narrow_set` therefore carries no
              property or operator - see `services/workshop_variables.py`. */}
          <label>
            Narrowed by
            <select
              value={transform}
              disabled={readOnly}
              onChange={(e) =>
                setDerivation({
                  transform: e.target.value,
                  // A property and an operator left behind by the other shape
                  // would be saved as debris nobody put there.
                  config: e.target.value === "narrow_set" ? {} : { op: "eq" },
                  inputs: [variable.derivation?.inputs?.[0] ?? ""].filter(Boolean),
                })
              }
            >
              <option value="filter_set">One value, on a property you choose</option>
              <option value="narrow_set">A filter list the viewer builds</option>
            </select>
          </label>
          <label>
            {byClauses ? "Filter clauses from" : "Filter value from"}
            <select
              value={variable.derivation?.inputs?.[1] ?? ""}
              disabled={readOnly}
              onChange={(e) =>
                setDerivation({
                  inputs: [variable.derivation?.inputs?.[0] ?? "", e.target.value].filter(Boolean),
                })
              }
            >
              <option value="">Choose a variable…</option>
              {(byClauses ? arrays : scalars).map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
          {!byClauses && (
            <>
          <label>
            Property
            <input
              value={String(variable.derivation?.config?.property ?? "")}
              readOnly={readOnly}
              placeholder="e.g. region"
              onChange={(e) =>
                setDerivation({
                  config: { ...variable.derivation?.config, property: e.target.value },
                })
              }
            />
          </label>
          {/* Only the operators both stores agree about. `gt` and friends are
              refused by the API because Postgres casts and OpenSearch compares
              text, so an app's results would depend on the deployment. */}
          <label>
            Match
            <select
              value={String(variable.derivation?.config?.op ?? "eq")}
              disabled={readOnly}
              onChange={(e) =>
                setDerivation({ config: { ...variable.derivation?.config, op: e.target.value } })
              }
            >
              <option value="eq">equals</option>
              <option value="neq">does not equal</option>
              <option value="starts_with">starts with</option>
              <option value="in">is one of</option>
            </select>
          </label>
            </>
          )}
          <p className="soft" style={{ margin: 0, fontSize: 11 }}>
            An unset filter shows the whole set rather than nothing.
          </p>
        </>
      )}
      {!derived && detail.data && (
        <p className="soft" style={{ margin: 0, fontSize: 11 }}>
          {detail.data.properties.length} propert
          {detail.data.properties.length === 1 ? "y" : "ies"} available to filter on
        </p>
      )}
    </div>
  );
}
