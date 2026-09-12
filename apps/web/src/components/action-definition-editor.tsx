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
import { NotifyRuleFields } from "@/components/notify-rule-fields";
import { TypePicker } from "@/components/type-picker";
import { NotifyConfig, blankNotifyConfig, problem as notifyProblem } from "@/lib/notify-rule";
import { WebhookRuleFields } from "@/components/webhook-rule-fields";
import {
  WebhookRuleConfig, blankWebhookConfig, listProblem as webhookListProblem,
  valueOptions,
} from "@/lib/webhook-rule";
import { webhooks as webhookApi } from "@/lib/api";
import { actions as actionApi, objects as objApi, type ActionDefinitionInput } from "@/lib/api";
import {
  COLUMN_CHOICES, availableParameters, blankSection, collapsedInitially,
  conditionDraft, conditionValue, forgetParameters, moveSection, placeParameter,
  removeParameter, renameParameter, sectionSummary, type FormSection,
} from "@/lib/action-sections";
import type { ActionType } from "@/lib/types";

/** `action_parameter_type` (migration 0044): the ontology's property types
 * plus `object`, which p.25 needs for a parameter that takes an object. */
const PARAMETER_TYPES = [
  "string", "integer", "float", "boolean", "date", "timestamp",
  "geopoint", "json", "attachment", "object",
];

/** The rule kinds this build can execute, and what to call them.
 *
 * All five now (§138). `delete_object` was held back while the executor
 * refused it, on the rule that an editor must not let somebody save an action
 * which fails the first time it is clicked; it arrived here the day it ran.
 *
 * **And p.89's sixth** (§258). "Notifications can be added to an action
 * through the Add new rule dropdown menu" — so a notification is a rule here
 * for the same reason it is one in the database. It arrived a unit after the
 * executor could run it, which is the same rule `delete_object` waited on.
 */
const RULE_KINDS = [
  ["modify_object", "Set a property"],
  ["create_object", "Create an object"],
  ["create_link", "Link to an object"],
  ["delete_link", "Remove a link"],
  ["delete_object", "Delete an object"],
  ["notify", "Send a notification"],
  // p.113: "select Add new rule, then select Webhook". The sixth and last
  // kind the executor runs (§260); §262 is what makes it selectable.
  ["webhook", "Call a webhook"],
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

/** The properties of whichever object type a rule writes.
 *
 * Its own component because a rule can now name a type other than the one the
 * action hangs off (§139–§141), and "which properties may I pick" then has a
 * different answer per rule. React Query keys on the type id, so several rules
 * pointing at one type share a single fetch and a fourth rule pointing
 * somewhere else does not re-fetch the first three.
 */
function PropertySelect({
  workspaceId, typeId, value, label, onChange,
}: {
  workspaceId: string;
  typeId: string;
  value: string;
  label: string;
  onChange: (next: string) => void;
}) {
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId),
  });
  return (
    <select value={value} aria-label={label} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose…</option>
      {(type.data?.properties ?? []).map((prop) => (
        <option key={prop.api_name} value={prop.api_name}>
          {prop.display_name || prop.api_name}
        </option>
      ))}
    </select>
  );
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

  // p.122-124's Form tab (§328). **Its own read and its own write**, because
  // a section is about how the form *looks* and the three lists above are
  // about what the action does — an action with every section deleted submits
  // exactly the same values from exactly the same parameters.
  //
  // `null` until the server has answered, which is not the same as "no
  // sections": saving before it arrives must leave the form alone rather than
  // write an empty one over it.
  const savedSections = useQuery({
    queryKey: ["action-sections", action.id],
    queryFn: () => actionApi.sections(workspaceId, action.id),
  });
  const [sections, setSections] = useState<FormSection[] | null>(null);
  if (sections === null && savedSections.data) setSections(savedSections.data);
  const patchSection = (index: number, patch: Partial<FormSection>) =>
    setSections((sections ?? []).map((s, i) => (i === index ? { ...s, ...patch } : s)));

  // Every object type in the workspace, so a rule can name one other than the
  // action's own (§139–§141). Summaries only: the properties of whichever type
  // a given rule names are fetched by `PropertySelect`, because carrying every
  // property of every type here to answer one dropdown would be the list
  // endpoint doing a detail endpoint's job.
  // The type list used to be fetched here for two `<select>`s of every type in
  // the workspace. `TypePicker` owns that read now (§256): the listing is a
  // page, so a control over it has to search the ontology rather than the rows
  // it happened to receive.

  const links = useQuery({
    queryKey: ["link-types", workspaceId],
    queryFn: () => objApi.listLinkTypes(workspaceId),
  });
  // The workspace's webhooks, for the one question the *editor* has to answer
  // rather than the rule: which outputs a writeback above this rule produces
  // (p.110). Fetched once here rather than per rule, and shared with
  // `WebhookRuleFields` through react-query's cache under the same key.
  const workspaceWebhooks = useQuery({
    queryKey: ["workspace-webhooks", workspaceId],
    queryFn: () => webhookApi.listForWorkspace(workspaceId),
  });
  const outputsFor = (id: string) =>
    (workspaceWebhooks.data ?? [])
      .find((w) => w.id === id)?.outputs.map((o) => o.api_name) ?? [];
  // Both ends now (§142). The join property lives on the *from* side: a rule on
  // that side writes its own object's, and a rule on the other side writes the
  // named object's, so a link touching this type at either end is settable. One
  // that touches it at neither, or that no single foreign key can express,
  // still is not. Narrowing the list is a convenience; the server decides.
  const settableLinks = (links.data ?? []).filter(
    (l) =>
      (l.from_object_type_id === action.object_type_id ||
        (l.to_object_type_id === action.object_type_id && l.to_property)) &&
      l.cardinality !== "many_to_many" &&
      l.from_property &&
      l.from_property !== "$primary_key",
  );
  /** Whether a link rule writes the *other* object's row rather than this one's. */
  const isFarSide = (linkTypeId: unknown) => {
    const link = settableLinks.find((l) => l.id === String(linkTypeId ?? ""));
    return !!link && link.from_object_type_id !== action.object_type_id;
  };

  const save = useMutation({
    mutationFn: async () => {
      await actionApi.setDefinition(workspaceId, action.id, { parameters, rules, criteria });
      // **After the definition, and only if it landed.** A section names its
      // parameters by `api_name`, so one holding a parameter this save is
      // adding — or renaming — can only be written once the parameter exists.
      // Two documents, and the dependency runs one way.
      //
      // Skipped entirely while the read is still in flight: `null` means
      // nobody has seen the form yet, and writing `[]` over it would delete an
      // arrangement because somebody saved a rule quickly.
      if (sections !== null) {
        await actionApi.setSections(workspaceId, action.id, sections);
      }
    },
    onSuccess: async () => {
      setFailure(null);
      await queryClient.invalidateQueries({ queryKey: ["action-types", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["action-sections", action.id] });
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
    // And through p.124's form, for the same reason: a section still naming
    // the old parameter makes the server refuse the save, and the refusal is
    // about a row the person did not touch.
    setSections((current) =>
      current === null ? null : renameParameter(current, before ?? "", after));
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
                  onClick={() => {
                    const left = parameters.filter((_, j) => j !== i);
                    setParameters(left);
                    // A section holding a parameter the action no longer
                    // declares is refused by the server — about a section the
                    // person was not looking at.
                    setSections((current) =>
                      current === null ? null : forgetParameters(current, left));
                  }}
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
        What the action does with them. A rule writes the object the action was run
        against, or one a parameter names — several objects, of several types, all in
        one transaction.
      </p>
      <div data-testid="rule-rows">
        {rules.map((r, i) => {
          const config = r.config as Record<string, unknown>;
          const patch = (next: Record<string, unknown>) =>
            setRules(rules.map((rule, j) => (j === i ? { ...rule, config: next } : rule)));
          // Which object this rule writes, and therefore whose properties its
          // pickers offer. Absent `object_type` means the action's own.
          const ruleTypeId = String(config.object_type ?? action.object_type_id);
          /** Point the rule at another type, or back at the subject.
           *
           * Both fields move together: an `object_type` with no `object` names
           * a *set*, which the server refuses, and an `object` left behind when
           * somebody picks "this object" again would silently keep writing
           * somewhere else. The property goes too, because it belonged to the
           * type the rule no longer names.
           */
          const retarget = (typeId: string) => {
            const { object: _o, object_type: _t, property: _p, ...rest } = config;
            patch(typeId ? { ...rest, object_type: typeId } : rest);
          };
          return (
            <div key={i} className="card" style={{ marginBottom: 10 }} data-rule={r.kind}>
              <div className="row" style={{ gap: 8, alignItems: "flex-end" }}>
                <Field label="Rule">
                  <select
                    value={r.kind}
                    aria-label={`Rule ${i + 1} kind`}
                    onChange={(e) =>
                      // The config is dropped rather than carried across: the
                      // shapes have nothing in common, and a leftover
                      // `property` on a link rule is a field the server would
                      // refuse for a reason nobody could see on screen.
                      setRules(rules.map((rule, j) =>
                        j === i
                          ? {
                              kind: e.target.value,
                              // A notify rule's empty config is not `{}`, and
                              // not because `{}` would fail `problem` — a blank
                              // one fails it too, on purpose, because p.89
                              // requires recipients and content and neither has
                              // been chosen yet. It is because the fields below
                              // are *selects*, and a select whose value is
                              // `undefined` is an uncontrolled one that shows
                              // its first option while holding nothing. The
                              // blank config is what makes the form agree with
                              // itself on the first render.
                              config: e.target.value === "notify"
                                ? (blankNotifyConfig() as unknown as Record<string, unknown>)
                                : e.target.value === "webhook"
                                  ? (blankWebhookConfig() as unknown as Record<string, unknown>)
                                  : {},
                            }
                          : rule))
                    }
                  >
                    {RULE_KINDS.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </Field>

                {(r.kind === "modify_object" || r.kind === "delete_object") && (
                  <>
                    <Field label="On">
                      <TypePicker
                        workspaceId={workspaceId}
                        value={config.object_type ? ruleTypeId : ""}
                        label={`Rule ${i + 1} object type`}
                        testId={`rule-${i + 1}-object-type`}
                        placeholder="This object"
                        onChange={retarget}
                      />
                    </Field>
                    {!!config.object_type && (
                      <Field label="Which one">
                        <select
                          value={String(config.object ?? "")}
                          aria-label={`Rule ${i + 1} which object`}
                          onChange={(e) => patch({ ...config, object: e.target.value })}
                        >
                          <option value="">Choose…</option>
                          {/* Only `object` parameters: p.25's type for a
                              parameter that holds an object. A string one would
                              carry a primary key, which is not what the
                              executor looks an instance up by. */}
                          {parameters
                            .filter((p) => p.data_type === "object")
                            .map((p) => (
                              <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                            ))}
                        </select>
                      </Field>
                    )}
                  </>
                )}

                {r.kind === "modify_object" && (
                  <>
                    <Field label="Property">
                      <PropertySelect
                        workspaceId={workspaceId}
                        typeId={ruleTypeId}
                        value={String(config.property ?? "")}
                        label={`Rule ${i + 1} property`}
                        onChange={(next) => patch({ ...config, property: next })}
                      />
                    </Field>
                    <Field label="From parameter">
                      <select
                        value={String(config.parameter ?? "")}
                        aria-label={`Rule ${i + 1} parameter`}
                        onChange={(e) => patch({ ...config, parameter: e.target.value })}
                      >
                        <option value="">Choose…</option>
                        {/* **Not just `parameters`** (§262). p.111's "Writeback
                            response" is a value source for a logic rule, and
                            the executor reads it from the same namespace as a
                            parameter — so a picker offering only parameters
                            would leave p.110's whole point reachable by JSON
                            alone, which is the gap §258 and §252 both closed
                            one level up. Position-dependent, because an output
                            is only available below the writeback that produces
                            it. */}
                        {valueOptions(
                          parameters.map((p) => p.api_name), rules, i, outputsFor,
                        ).map((name) => (
                          <option key={name} value={name}>{name}</option>
                        ))}
                      </select>
                    </Field>
                  </>
                )}

                {r.kind === "create_object" && (
                  <>
                    {/* A create can name any type with a dataset in this
                        project (§139); the properties below then come from
                        *that* type, which is what the server checks against. */}
                    <Field label="Of type">
                      <TypePicker
                        workspaceId={workspaceId}
                        value={config.object_type ? ruleTypeId : ""}
                        label={`Rule ${i + 1} creates type`}
                        testId={`rule-${i + 1}-creates-type`}
                        placeholder="This object type"
                        onChange={(id) => {
                          const { object_type: _t, properties: _p, ...rest } = config;
                          patch(id ? { ...rest, object_type: id } : rest);
                        }}
                      />
                    </Field>
                    {/* The primary key is separate because it is not a
                        property - an object's identity lives in a dataset
                        column, which is frequently mapped to nothing. */}
                    <Field label="Primary key from">
                      <select
                        value={String(config.primary_key ?? "")}
                        aria-label={`Rule ${i + 1} primary key`}
                        onChange={(e) => patch({ ...config, primary_key: e.target.value })}
                      >
                        <option value="">Choose…</option>
                        {parameters.map((p) => (
                          <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Sets property">
                      <PropertySelect
                        workspaceId={workspaceId}
                        typeId={ruleTypeId}
                        value={Object.keys((config.properties as object) ?? {})[0] ?? ""}
                        label={`Rule ${i + 1} creates property`}
                        onChange={(next) => {
                          const parameter = Object.values(
                            (config.properties as Record<string, string>) ?? {},
                          )[0] ?? "";
                          patch({
                            ...config,
                            properties: next ? { [next]: parameter } : {},
                          });
                        }}
                      />
                    </Field>
                    <Field label="From parameter">
                      <select
                        value={Object.values(
                          (config.properties as Record<string, string>) ?? {},
                        )[0] ?? ""}
                        aria-label={`Rule ${i + 1} creates from`}
                        onChange={(e) => {
                          const property = Object.keys((config.properties as object) ?? {})[0] ?? "";
                          patch({
                            ...config,
                            properties: property ? { [property]: e.target.value } : {},
                          });
                        }}
                      >
                        <option value="">Choose…</option>
                        {parameters.map((p) => (
                          <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                        ))}
                      </select>
                    </Field>
                  </>
                )}

                {r.kind === "delete_object" && !config.object_type && (
                  <p className="field-hint" style={{ marginBottom: 0 }}>
                    Deletes the object the action was run against. An action cannot both
                    change and delete the same object.
                  </p>
                )}

                {(r.kind === "create_link" || r.kind === "delete_link") && (
                  <>
                    <Field label="Link">
                      <select
                        value={String(config.link_type ?? "")}
                        aria-label={`Rule ${i + 1} link`}
                        onChange={(e) => {
                          // Both sides' fields go: a link picked on the other
                          // end asks a different question, and the answer to
                          // the old one is refused on save for a reason that
                          // is no longer on screen.
                          const { target: _t, object: _o, ...rest } = config;
                          patch({ ...rest, link_type: e.target.value });
                        }}
                      >
                        <option value="">Choose…</option>
                        {settableLinks.map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.display_name} → {l.to_display_name}
                          </option>
                        ))}
                      </select>
                    </Field>
                    {/* **Which field appears depends on which end this action
                        is on.** On the from side the rule writes its own
                        object's join property and the input is which object to
                        point at (`target`). On the to side there is no column
                        of its own: the input is which object to link
                        (`object`), and the value is this object's, so there is
                        nothing else to ask for (§142). */}
                    {isFarSide(config.link_type) ? (
                      <Field label="Object to link">
                        <select
                          value={String(config.object ?? "")}
                          aria-label={`Rule ${i + 1} link object`}
                          onChange={(e) => {
                            const { target: _t, ...rest } = config;
                            patch({ ...rest, object: e.target.value });
                          }}
                        >
                          <option value="">Choose…</option>
                          {parameters
                            .filter((p) => p.data_type === "object")
                            .map((p) => (
                              <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                            ))}
                        </select>
                      </Field>
                    ) : r.kind === "create_link" ? (
                      <Field label="To object from">
                        <select
                          value={String(config.target ?? "")}
                          aria-label={`Rule ${i + 1} target`}
                          onChange={(e) => {
                            const { object: _o, ...rest } = config;
                            patch({ ...rest, target: e.target.value });
                          }}
                        >
                          <option value="">Choose…</option>
                          {parameters.map((p) => (
                            <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                          ))}
                        </select>
                      </Field>
                    ) : null}
                  </>
                )}

                <button className="btn quiet" onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                  Remove
                </button>
              </div>
              {r.kind === "notify" && (
                <>
                  <NotifyRuleFields
                    workspaceId={workspaceId}
                    index={i + 1}
                    parameters={parameters}
                    config={config as unknown as NotifyConfig}
                    onChange={(next) =>
                      patch(next as unknown as Record<string, unknown>)
                    }
                  />
                  {/* Said here rather than on Save, because a refusal that
                      arrives on Save is a refusal about a form somebody has
                      already left. The server refuses the same cases and
                      several this cannot see — this is the subset a form can
                      answer without the ontology. */}
                  {(() => {
                    const said = notifyProblem(
                      config as unknown as NotifyConfig,
                      parameters.map((p) => p.api_name),
                    );
                    return said ? (
                      <p
                        className="field-hint"
                        data-testid={`rule-${i + 1}-problem`}
                        style={{ color: "var(--danger)" }}
                      >
                        {said}
                      </p>
                    ) : null;
                  })()}
                </>
              )}
              {r.kind === "webhook" && (
                <WebhookRuleFields
                  index={i + 1}
                  parameters={parameters}
                  webhooks={workspaceWebhooks.data ?? []}
                  webhooksLoaded={workspaceWebhooks.isSuccess}
                  config={config as unknown as WebhookRuleConfig}
                  // **Position-dependent**, which is why it is computed here
                  // rather than inside the component: p.110's outputs are only
                  // available to rules *below* the writeback that produces
                  // them, and a rule can only see itself.
                  valueNames={valueOptions(
                    parameters.map((p) => p.api_name), rules, i, outputsFor,
                  )}
                  onChange={(next) =>
                    patch(next as unknown as Record<string, unknown>)
                  }
                />
              )}
              {(r.kind === "create_link" || r.kind === "delete_link") &&
                settableLinks.length === 0 && (
                  <p className="field-hint">
                    No link on this object type can be set by an action — it is
                    many-to-many, or it joins on the primary key, or on nothing.
                  </p>
                )}
            </div>
          );
        })}
      </div>
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

      <h3 className="field-label" style={{ marginTop: 24 }}>Form</h3>
      <p className="field-hint">
        p.122–124’s sections: a logical grouping of the parameters above, with a
        title, an optional description shown in the section itself, one or two
        columns, and hiding — plain, or on a prior parameter. A section changes how
        the form looks and nothing else: an action with every section deleted
        submits exactly the same values.
      </p>
      <div data-testid="section-rows">
        {(sections ?? []).map((s, i) => {
          const draft = conditionDraft(s);
          return (
            <div className="card" key={i} data-section-row={s.title} style={{ marginBottom: 12 }}>
              <div className="row-actions">
                <input
                  value={s.title}
                  aria-label={`Section ${i + 1} title`}
                  onChange={(e) => patchSection(i, { title: e.target.value })}
                />
                <select
                  value={s.columns}
                  aria-label={`Section ${i + 1} columns`}
                  onChange={(e) => patchSection(i, { columns: Number(e.target.value) })}
                >
                  {COLUMN_CHOICES.map((n) => (
                    <option key={n} value={n}>{n === 2 ? "Two columns" : "One column"}</option>
                  ))}
                </select>
                <button
                  className="btn quiet"
                  aria-label={`Move section ${i + 1} up`}
                  disabled={i === 0}
                  onClick={() => setSections(moveSection(sections ?? [], i, -1))}
                >
                  Up
                </button>
                <button
                  className="btn quiet"
                  aria-label={`Move section ${i + 1} down`}
                  disabled={i === (sections ?? []).length - 1}
                  onClick={() => setSections(moveSection(sections ?? [], i, 1))}
                >
                  Down
                </button>
                <button
                  className="btn quiet"
                  aria-label={`Remove section ${i + 1}`}
                  onClick={() => setSections((sections ?? []).filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              </div>
              <span className="field-hint" data-testid="section-summary">
                {sectionSummary(s)}
              </span>
              {/* p.123: "optionally write a user-facing description… will
                  always be shown in the section itself, not in a tooltip." */}
              <Field label="Description">
                <input
                  value={s.description}
                  aria-label={`Section ${i + 1} description`}
                  onChange={(e) => patchSection(i, { description: e.target.value })}
                />
              </Field>
              <div className="row-actions">
                <label className="field-hint">
                  <input
                    type="checkbox"
                    checked={s.collapsible}
                    aria-label={`Section ${i + 1} collapsible`}
                    onChange={(e) => patchSection(i, { collapsible: e.target.checked })}
                  />{" "}
                  Collapsible
                </label>
                {/* **Unreachable unless it can be collapsed**, which is not a
                    validation — it is that the second box means nothing without
                    the first, and a form folded with no way to open it would be
                    p.123’s "hidden entirely" wearing the wrong name. */}
                <label className="field-hint">
                  <input
                    type="checkbox"
                    checked={collapsedInitially(s)}
                    disabled={!s.collapsible}
                    aria-label={`Section ${i + 1} starts folded`}
                    onChange={(e) => patchSection(i, { collapsed: e.target.checked })}
                  />{" "}
                  Starts folded
                </label>
                <label className="field-hint">
                  <input
                    type="checkbox"
                    checked={s.hidden}
                    aria-label={`Section ${i + 1} hidden`}
                    onChange={(e) => patchSection(i, { hidden: e.target.checked })}
                  />{" "}
                  Hidden entirely
                </label>
              </div>
              {/* p.123’s conditional override. Offered as the one case p.123
                  describes — a prior parameter against a value — rather than
                  decision 0007’s whole grammar; a condition this control cannot
                  draw is left exactly as it is rather than reduced to one it
                  can, which would delete a rule on the next save. */}
              {draft.expressible ? (
                <div className="row-actions" data-testid="section-condition">
                  <span className="field-hint">Shown when</span>
                  <select
                    value={draft.parameter}
                    aria-label={`Section ${i + 1} condition parameter`}
                    onChange={(e) => patchSection(i, {
                      visible_when: conditionValue({ ...draft, parameter: e.target.value }),
                    })}
                  >
                    <option value="">Always</option>
                    {parameters.map((p) => (
                      <option key={p.api_name} value={p.api_name}>
                        {p.display_name || p.api_name}
                      </option>
                    ))}
                  </select>
                  <select
                    value={draft.operator}
                    aria-label={`Section ${i + 1} condition operator`}
                    disabled={!draft.parameter}
                    onChange={(e) => patchSection(i, {
                      visible_when: conditionValue({ ...draft, operator: e.target.value }),
                    })}
                  >
                    {OPERATORS.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                  <input
                    value={draft.value}
                    aria-label={`Section ${i + 1} condition value`}
                    disabled={!draft.parameter}
                    onChange={(e) => patchSection(i, {
                      visible_when: conditionValue({ ...draft, value: e.target.value }),
                    })}
                  />
                </div>
              ) : (
                <p className="field-hint" data-testid="section-condition-opaque">
                  This section’s condition was not written here and this panel
                  cannot draw it. It is left as it is; edit it where it came from.
                </p>
              )}
              <Field label="Parameters">
                <div className="row-actions" data-testid="section-parameters">
                  {s.parameters.map((name) => (
                    <button
                      key={name}
                      className="btn quiet"
                      data-section-parameter={name}
                      aria-label={`Take ${name} out of section ${i + 1}`}
                      onClick={() => setSections(removeParameter(sections ?? [], i, name))}
                    >
                      {name} ×
                    </button>
                  ))}
                  <select
                    value=""
                    aria-label={`Add a parameter to section ${i + 1}`}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      setSections(placeParameter(sections ?? [], i, e.target.value));
                    }}
                  >
                    <option value="">Add a parameter…</option>
                    {/* Only what no *other* section holds: p.124 offers two ways
                        to put a parameter in a section and neither is "in both",
                        so the refusal exists and this is why nobody reaches it
                        by the obvious route. */}
                    {availableParameters(parameters, sections ?? [], i)
                      .filter((p) => !s.parameters.includes(p.api_name))
                      .map((p) => (
                        <option key={p.api_name} value={p.api_name}>
                          {p.display_name || p.api_name}
                        </option>
                      ))}
                  </select>
                </div>
              </Field>
            </div>
          );
        })}
      </div>
      <button
        className="btn quiet"
        data-testid="add-section"
        onClick={() => setSections([...(sections ?? []), blankSection(sections ?? [])])}
      >
        Add section
      </button>

      {/* **Beside Save rather than on a rule**, because these two refusals do
          not belong to one: p.106's "only a single webhook as a writeback" is
          broken by the *second* one, and p.110's ordering rule is about where a
          rule sits relative to another. A message pinned to either rule would
          be blaming a line that is fine on its own. */}
      {(() => {
        const said = webhookListProblem(rules, outputsFor);
        return said ? (
          <p
            className="state error"
            data-testid="definition-rules-problem"
          >
            {said}
          </p>
        ) : null;
      })()}

      <div className="row-actions" style={{ marginTop: 20 }}>
        <button className="btn quiet" onClick={onClose}>Cancel</button>
        <button
          className="btn"
          disabled={save.isPending || !!webhookListProblem(rules, outputsFor)}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </Dialog>
  );
}
