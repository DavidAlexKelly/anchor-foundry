"use client";

/**
 * Editing an action's parameters, rules and criteria (decision 0007; Foundry
 * `action-types` p.25, p.75, p.49–56).
 *
 * The last piece of decision 0007 that a person could not reach: the model,
 * the criteria and the API all landed first (`STATUS.md` §127–§130), and until
 * this existed the only way to declare a hidden parameter or a submission
 * criterion was a `psql` prompt.
 *
 * **One dialog, saved as one document.** The three lists constrain each other -
 * a rule names a parameter, a criterion names a parameter - so there is no
 * per-row save that could not pass through an invalid state. The server
 * validates the same three lists as a unit and this sends them as one PUT.
 *
 * **Nothing is validated twice.** The refusals live on the server (a rule
 * naming an undeclared parameter, a criterion with no message, a rename that
 * would break a Workshop module) and the dialog shows what came back. A
 * browser-side copy of those rules would be a second implementation free to
 * disagree with the first, and the one it would disagree with is the one that
 * decides whether a write happens. The dropdowns are narrowed to what is
 * *declarable* - the parameters that exist, the properties the object type
 * has - because that is a convenience, not a rule.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import { actions as actionApi, objects as objApi, type ActionDefinitionInput } from "@/lib/api";
import type { ActionType } from "@/lib/types";

/** `action_parameter_type` (migration 0044): the ontology's property types
 * plus `object`, which p.25 needs for a parameter that takes an object. */
const PARAMETER_TYPES = [
  "string", "integer", "float", "boolean", "date", "timestamp",
  "geopoint", "json", "attachment", "object",
];

/** p.54–55's operators, named as Foundry names them. */
const OPERATORS = [
  ["is", "is"],
  ["is_not", "is not"],
  ["matches", "matches"],
  ["is_less_than", "is less than"],
  ["is_greater_than_or_equals", "is greater than or equals"],
  ["includes", "includes"],
  ["is_included_in", "is included in"],
];

type Parameter = ActionDefinitionInput["parameters"][number];
type Rule = ActionDefinitionInput["rules"][number];
type Criterion = ActionDefinitionInput["criteria"][number];

function side(spec: unknown): Record<string, unknown> {
  return (spec ?? {}) as Record<string, unknown>;
}

export function ActionDefinitionEditor({
  workspaceId,
  action,
  onClose,
}: {
  workspaceId: string;
  action: ActionType;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [parameters, setParameters] = useState<Parameter[]>(
    action.parameters.map((p) => ({
      api_name: p.api_name,
      display_name: p.display_name,
      data_type: p.data_type,
      required: p.required,
      default_value: p.default_value,
      hidden: p.hidden,
    })),
  );
  const [rules, setRules] = useState<Rule[]>(
    action.rules.map((r) => ({ kind: r.kind, config: r.config })),
  );
  const [criteria, setCriteria] = useState<Criterion[]>(
    action.criteria.map((c) => ({ message: c.message, config: c.config })),
  );
  const [failure, setFailure] = useState<string | null>(null);

  // The object type's properties, so a rule picks a real one. Narrowing what
  // can be *said*, not deciding what is legal - the server does that.
  const type = useQuery({
    queryKey: ["object-type", action.object_type_id],
    queryFn: () => objApi.getType(workspaceId, action.object_type_id),
  });
  const properties = type.data?.properties ?? [];

  const save = useMutation({
    mutationFn: () =>
      actionApi.setDefinition(workspaceId, action.id, { parameters, rules, criteria }),
    onSuccess: async () => {
      setFailure(null);
      await queryClient.invalidateQueries({ queryKey: ["action-types", workspaceId] });
      onClose();
    },
    // Including the refusal that names a Workshop module using a parameter
    // this save would remove (§129). Shown rather than swallowed: it is the
    // one error here that tells somebody what to go and fix.
    onError: (e: Error) => setFailure(e.message),
  });

  /** Edit a parameter, **carrying a rename through everything that names it.**
   *
   * Without this every rename is refused, and for the wrong reason: the rules
   * still point at the old name, so the server answers "a rule reads 'status',
   * which is not a parameter" - true, unhelpful, and about a row the person
   * did not touch. Renaming is the one edit here with consequences elsewhere
   * in the same document, and the document is saved whole.
   *
   * What it deliberately does *not* do is rename the parameter inside a saved
   * Workshop module. That refusal is the server's (§129) and it names the
   * module, because rewriting somebody else's app to make your rename go
   * through is not a thing an editor should do quietly.
   */
  const patchParameter = (index: number, patch: Partial<Parameter>) => {
    const before = parameters[index]?.api_name;
    const after = patch.api_name;
    setParameters(parameters.map((p, i) => (i === index ? { ...p, ...patch } : p)));
    if (after === undefined || after === before) return;
    setRules(
      rules.map((r) =>
        r.config.parameter === before ? { ...r, config: { ...r.config, parameter: after } } : r,
      ),
    );
    setCriteria(
      criteria.map((c) => {
        const config = c.config as Record<string, unknown>;
        const next = { ...config };
        for (const key of ["left", "right"]) {
          const spec = side(config[key]);
          if (spec.kind === "parameter" && spec.parameter === before) {
            next[key] = { ...spec, parameter: after };
          }
        }
        return { ...c, config: next };
      }),
    );
  };
  const patchCriterion = (index: number, config: Record<string, unknown>) =>
    setCriteria(criteria.map((c, i) => (i === index ? { ...c, config } : c)));

  return (
    <Dialog open wide title={`Parameters and rules · ${action.display_name}`} onClose={onClose}>
      {failure && <p className="state error" data-testid="definition-error">{failure}</p>}

      <h3 className="field-label" style={{ marginTop: 0 }}>Parameters</h3>
      <p className="field-hint">
        What the action asks for. A hidden parameter is supplied by whatever runs the
        action and never drawn in the form.
      </p>
      <table className="table" data-testid="parameter-rows">
        <thead>
          <tr>
            <th>Name</th><th>Label</th><th>Type</th><th>Default</th>
            <th>Required</th><th>Hidden</th><th aria-label="Remove" />
          </tr>
        </thead>
        <tbody>
          {parameters.map((p, i) => (
            <tr key={i} data-parameter-row={p.api_name}>
              <td>
                <input
                  value={p.api_name}
                  aria-label={`Parameter ${i + 1} name`}
                  onChange={(e) => patchParameter(i, { api_name: e.target.value })}
                />
              </td>
              <td>
                <input
                  value={p.display_name}
                  aria-label={`Parameter ${i + 1} label`}
                  onChange={(e) => patchParameter(i, { display_name: e.target.value })}
                />
              </td>
              <td>
                <select
                  value={p.data_type}
                  aria-label={`Parameter ${i + 1} type`}
                  onChange={(e) => patchParameter(i, { data_type: e.target.value })}
                >
                  {PARAMETER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </td>
              <td>
                {/* Empty means *no default*, which is not a default of "" -
                    migration 0044 keeps the distinction and so does this. */}
                <input
                  value={p.default_value === null || p.default_value === undefined ? "" : String(p.default_value)}
                  aria-label={`Parameter ${i + 1} default`}
                  onChange={(e) =>
                    patchParameter(i, { default_value: e.target.value === "" ? null : e.target.value })
                  }
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={!!p.required}
                  aria-label={`Parameter ${i + 1} required`}
                  onChange={(e) => patchParameter(i, { required: e.target.checked })}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={!!p.hidden}
                  aria-label={`Parameter ${i + 1} hidden`}
                  onChange={(e) => patchParameter(i, { hidden: e.target.checked })}
                />
              </td>
              <td>
                <button
                  className="btn quiet"
                  onClick={() => setParameters(parameters.filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        className="btn quiet"
        onClick={() =>
          setParameters([
            ...parameters,
            { api_name: "", display_name: "", data_type: "string", required: false, hidden: false },
          ])
        }
      >
        Add a parameter
      </button>

      <h3 className="field-label" style={{ marginTop: 24 }}>Rules</h3>
      <p className="field-hint">
        What the action does with them. This build applies <code>modify_object</code>; the
        other kinds are storable and refused at run time until they are implemented.
      </p>
      <table className="table" data-testid="rule-rows">
        <thead><tr><th>Writes property</th><th>From parameter</th><th aria-label="Remove" /></tr></thead>
        <tbody>
          {rules.map((r, i) => (
            <tr key={i}>
              <td>
                <select
                  value={String(r.config.property ?? "")}
                  aria-label={`Rule ${i + 1} property`}
                  onChange={(e) =>
                    setRules(rules.map((rule, j) =>
                      j === i ? { ...rule, config: { ...rule.config, property: e.target.value } } : rule))
                  }
                >
                  <option value="">Choose…</option>
                  {properties.map((prop) => (
                    <option key={prop.api_name} value={prop.api_name}>
                      {prop.display_name || prop.api_name}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <select
                  value={String(r.config.parameter ?? "")}
                  aria-label={`Rule ${i + 1} parameter`}
                  onChange={(e) =>
                    setRules(rules.map((rule, j) =>
                      j === i ? { ...rule, config: { ...rule.config, parameter: e.target.value } } : rule))
                  }
                >
                  <option value="">Choose…</option>
                  {parameters.map((p) => (
                    <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                  ))}
                </select>
              </td>
              <td>
                <button className="btn quiet" onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        className="btn quiet"
        onClick={() => setRules([...rules, { kind: "modify_object", config: {} }])}
      >
        Add a rule
      </button>

      <h3 className="field-label" style={{ marginTop: 24 }}>Submission criteria</h3>
      <p className="field-hint">
        Conditions that must all hold before anything is written. The message is what
        somebody blocked by it is told.
      </p>
      <div data-testid="criterion-rows">
        {criteria.map((c, i) => {
          const config = c.config as Record<string, unknown>;
          const left = side(config.left);
          const right = side(config.right);
          return (
            <div key={i} className="card" style={{ marginBottom: 10 }}>
              <Field label="Refusal message">
                <input
                  value={c.message}
                  aria-label={`Criterion ${i + 1} message`}
                  onChange={(e) =>
                    setCriteria(criteria.map((cr, j) => (j === i ? { ...cr, message: e.target.value } : cr)))
                  }
                />
              </Field>
              <div className="row" style={{ gap: 8, alignItems: "flex-end" }}>
                <Field label="Parameter">
                  <select
                    value={String(left.parameter ?? "")}
                    aria-label={`Criterion ${i + 1} parameter`}
                    onChange={(e) =>
                      patchCriterion(i, { ...config, left: { kind: "parameter", parameter: e.target.value } })
                    }
                  >
                    <option value="">Choose…</option>
                    {parameters.map((p) => (
                      <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Operator">
                  <select
                    value={String(config.operator ?? "is")}
                    aria-label={`Criterion ${i + 1} operator`}
                    onChange={(e) => patchCriterion(i, { ...config, operator: e.target.value })}
                  >
                    {OPERATORS.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Value">
                  {/* Blank is p.55's "no value", which asks whether the left
                      side is empty - a different question from "equals the
                      empty string", and the only way to express "must be
                      filled in". */}
                  <input
                    value={right.kind === "value" ? String(right.value ?? "") : ""}
                    placeholder="(leave blank for: is empty)"
                    aria-label={`Criterion ${i + 1} value`}
                    onChange={(e) =>
                      patchCriterion(i, {
                        ...config,
                        right: e.target.value === ""
                          ? { kind: "none" }
                          : { kind: "value", value: e.target.value },
                      })
                    }
                  />
                </Field>
                <button
                  className="btn quiet"
                  onClick={() => setCriteria(criteria.filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <button
        className="btn quiet"
        onClick={() =>
          setCriteria([
            ...criteria,
            {
              message: "",
              config: { left: { kind: "parameter", parameter: "" }, operator: "is_not", right: { kind: "none" } },
            },
          ])
        }
      >
        Add a criterion
      </button>

      <div className="row-actions" style={{ marginTop: 20 }}>
        <button className="btn quiet" onClick={onClose}>Cancel</button>
        <button className="btn" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </Dialog>
  );
}
