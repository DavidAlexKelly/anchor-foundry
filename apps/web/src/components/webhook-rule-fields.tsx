"use client";

/**
 * The webhook rule's half of the action definition editor (§262;
 * `action-types` p.105-116).
 *
 * §260 built the rule and left it reachable only by posting JSON — the last of
 * the six rule kinds in that state. §258 closed the same gap for `notify` and
 * this closes it here.
 *
 * **Its own file for §258's reason**, and more so: p.115 is a webhook picker
 * plus one row per declared input, and the number of rows depends on which
 * webhook was picked. Folding that into a component already carrying five rule
 * shapes would make that file about layout rather than about rules.
 *
 * The rules that decide what this offers are in `lib/webhook-rule`, where a
 * wrong answer is a line.
 */

import { useQuery } from "@tanstack/react-query";
import { Field } from "@/components/dialog";
import { webhooks as api } from "@/lib/api";
import {
  MODES, WebhookRuleConfig, problem, requiredInputs,
} from "@/lib/webhook-rule";
import type { Webhook } from "@/lib/types";

export function WebhookRuleFields({
  workspaceId,
  index,
  config,
  parameters,
  valueNames,
  onChange,
}: {
  workspaceId: string;
  index: number;
  config: WebhookRuleConfig;
  parameters: { api_name: string; data_type: string }[];
  /** What a value may be read from at this rule's position — the action's
   * parameters plus any writeback outputs produced *above* it. Computed by the
   * editor rather than here, because it depends on the other rules and this
   * component can only see its own. */
  valueNames: string[];
  onChange: (next: WebhookRuleConfig) => void;
}) {
  // **Workspace-wide, not project-wide** (§262). An action type is a workspace
  // resource and the server resolves a rule's webhook workspace-wide, so a
  // picker fed by the project listing would offer a narrower set than the save
  // accepts — §258's defect, which is what this endpoint was added to avoid.
  const listed = useQuery({
    queryKey: ["workspace-webhooks", workspaceId],
    queryFn: () => api.listForWorkspace(workspaceId),
  });
  const chosen: Webhook | undefined = (listed.data ?? []).find(
    (w) => w.id === config.webhook,
  );

  const patch = (next: Partial<WebhookRuleConfig>) => onChange({ ...config, ...next });
  const setInput = (name: string, source: { parameter?: string; value?: string }) =>
    patch({ inputs: { ...(config.inputs ?? {}), [name]: source } });

  const said = problem(config, parameters.map((p) => p.api_name), chosen);
  const required = new Set(requiredInputs(chosen));

  return (
    <div style={{ width: "100%" }}>
      <Field label="Webhook">
        <select
          data-testid={`rule-${index}-webhook`}
          aria-label={`Rule ${index} webhook`}
          value={config.webhook}
          onChange={(e) =>
            // The inputs go with it: they are keyed by the *previous*
            // webhook's input names, and a leftover key is a field the server
            // refuses for a reason nobody could see on screen — the same
            // argument the rule-kind select one file over makes.
            patch({ webhook: e.target.value, inputs: {} })
          }
        >
          <option value="">Choose…</option>
          {(listed.data ?? []).map((webhook) => (
            <option key={webhook.id} value={webhook.id}>
              {webhook.display_name}
            </option>
          ))}
        </select>
      </Field>
      {/* **Present rather than absent** when there are none: an empty dropdown
          with no explanation reads as a list still loading, and the fix is on
          a different screen. */}
      {listed.isSuccess && listed.data.length === 0 && (
        <p className="field-hint" data-testid={`rule-${index}-no-webhooks`}>
          This workspace has no webhooks yet. Add one on a project&apos;s
          Connections page.
        </p>
      )}

      <Field
        label="When it runs"
        hint="p.106 — a webhook that runs before the changes can refuse the whole action; one that runs after cannot."
      >
        <select
          data-testid={`rule-${index}-webhook-mode`}
          aria-label={`Rule ${index} webhook mode`}
          value={config.mode}
          onChange={(e) => patch({ mode: e.target.value })}
        >
          {MODES.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </Field>

      {chosen && chosen.inputs.length > 0 && (
        <Field
          label="Inputs"
          hint="p.107 — each one is an action parameter of the same type, or a fixed value."
        >
          <div data-testid={`rule-${index}-webhook-inputs`}>
            {chosen.inputs.map((input) => {
              const source = (config.inputs ?? {})[input.api_name] ?? {};
              const usingValue = typeof source.value === "string";
              return (
                <div
                  key={input.api_name}
                  className="row-actions"
                  style={{ gap: 6, marginBottom: 4 }}
                >
                  <span className="slug">
                    {input.api_name}
                    {required.has(input.api_name) ? " *" : ""}
                  </span>
                  <select
                    aria-label={`Rule ${index} ${input.api_name} source`}
                    value={usingValue ? "value" : "parameter"}
                    onChange={(e) =>
                      // Switching source clears the other one, so the rule
                      // never holds both — which the server refuses, and which
                      // `problem` refuses here first.
                      setInput(
                        input.api_name,
                        e.target.value === "value" ? { value: "" } : { parameter: "" },
                      )
                    }
                  >
                    <option value="parameter">From a parameter</option>
                    <option value="value">A fixed value</option>
                  </select>
                  {usingValue ? (
                    <input
                      type="text"
                      aria-label={`Rule ${index} ${input.api_name} value`}
                      value={source.value ?? ""}
                      onChange={(e) =>
                        setInput(input.api_name, { value: e.target.value })
                      }
                    />
                  ) : (
                    <select
                      aria-label={`Rule ${index} ${input.api_name} parameter`}
                      value={source.parameter ?? ""}
                      onChange={(e) =>
                        setInput(input.api_name, { parameter: e.target.value })
                      }
                    >
                      <option value="">Choose…</option>
                      {valueNames.map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  )}
                  {/* An optional input can be taken off the rule entirely,
                      which is what makes p.229's "may or may not be present"
                      expressible — a row that could only be filled in would
                      make every input required in practice. */}
                  {!required.has(input.api_name)
                    && input.api_name in (config.inputs ?? {}) && (
                    <button
                      type="button"
                      className="btn quiet"
                      aria-label={`Rule ${index} clear ${input.api_name}`}
                      onClick={() => {
                        const rest = { ...(config.inputs ?? {}) };
                        delete rest[input.api_name];
                        patch({ inputs: rest });
                      }}
                    >
                      Leave out
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </Field>
      )}

      {chosen && chosen.outputs.length > 0 && config.mode === "writeback" && (
        <p className="field-hint" data-testid={`rule-${index}-webhook-outputs`}>
          {/* p.111's "Writeback response", said rather than left to be
              discovered: the names only appear in *other* rules' dropdowns, so
              the one place somebody would look for them is here. */}
          Rules below this one can read{" "}
          {chosen.outputs.map((o) => `webhook.${o.api_name}`).join(", ")}.
        </p>
      )}

      {said && (
        <p
          className="field-hint"
          data-testid={`rule-${index}-webhook-problem`}
          style={{ color: "var(--danger)" }}
        >
          {said}
        </p>
      )}
    </div>
  );
}
