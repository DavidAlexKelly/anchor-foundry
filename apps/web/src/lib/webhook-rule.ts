/**
 * Configuring a webhook rule on an action (`action-types` p.105-116; §262).
 *
 * §260 built the rule and left it reachable only by posting JSON, which is the
 * last of the six rule kinds still in that state — §258 closed it for `notify`
 * and this closes it for `webhook`.
 *
 * The division is the usual one: the server owns what is legal
 * (`actions._validate_definition`'s webhook branch), this owns what is offered
 * and what a form can say before a round trip.
 *
 * **The mode is the whole feature and the form has to say so.** p.106's table
 * is two rows that differ in every column — when it runs, whether a failure is
 * shown, how many are allowed — and picking one is not a preference. A
 * selector labelled "writeback / side effect" would be labelled in Foundry's
 * vocabulary rather than in the reader's, so {@link MODES} names what each one
 * *does*.
 */

/** p.106's two, named for their consequence rather than for the document's
 * word. The order is p.114's: "by default, the newly added webhook is
 * configured as a side effect", and the default goes first because a list
 * whose first entry is not the default reads as though the default were a
 * deviation. */
export const MODES = [
  ["side_effect", "After the changes, and cannot undo them"],
  ["writeback", "Before the changes, and can refuse the action"],
] as const;

/** p.114's default, and the safe one: a rule somebody added without reading
 * the selector must not be able to take an action down. */
export const DEFAULT_MODE = "side_effect";

/** Where a writeback's outputs live in the value namespace every rule reads
 * from (p.110-111's "Writeback response"). Mirrors
 * `actions.WEBHOOK_OUTPUT_PREFIX`; an API test asserts the two agree. */
export const OUTPUT_PREFIX = "webhook.";

export function outputName(output: string): string {
  return `${OUTPUT_PREFIX}${output}`;
}

/** How one webhook input gets its value (p.107): "an Action parameter of the
 * same type, a static value, or a property of an object parameter".
 *
 * The third is absent because the server does not read it either — it needs
 * the object the rule names, which the executor resolves and this build does
 * not pass to `webhook_inputs`. Absent rather than offered and ignored (§214).
 */
export interface InputSource {
  parameter?: string;
  value?: string;
}

export interface WebhookRuleConfig {
  webhook: string;
  mode: string;
  inputs: Record<string, InputSource>;
}

export function blankWebhookConfig(): WebhookRuleConfig {
  // `inputs` is an object rather than absent for the reason §258's
  // `blankNotifyConfig` gives about selects: the fields below are controlled,
  // and a control whose value is `undefined` is an uncontrolled one showing
  // its first option while holding nothing.
  return { webhook: "", mode: DEFAULT_MODE, inputs: {} };
}

/** Which inputs a rule must supply for this webhook (p.107: "you must populate
 * all of its required input parameters").
 *
 * Returns the *names*, so a caller can both check and list them. An optional
 * input is not here, which is what makes leaving one out a save rather than a
 * refusal.
 */
export function requiredInputs(
  webhook: { inputs?: { api_name: string; required?: boolean }[] } | undefined,
): string[] {
  return (webhook?.inputs ?? [])
    .filter((input) => input.required !== false)
    .map((input) => input.api_name);
}

/** What is wrong with this rule as typed, in one sentence, or null.
 *
 * The subset of the server's refusals a form can see: the webhook must be
 * chosen, the mode must be one of the two, every input source must be exactly
 * one thing, and a parameter it names must exist. What this cannot see is the
 * *ordering* rule — p.110's "subsequent", which depends on the other rules —
 * and the one-writeback rule, which depends on them too; both are checked
 * against the whole rule list by {@link listProblem}.
 */
export function problem(
  config: WebhookRuleConfig,
  parameterNames: readonly string[],
  webhook: { inputs?: { api_name: string; required?: boolean }[] } | undefined,
): string | null {
  if (!config.webhook) return "Choose the webhook this rule calls.";
  if (!MODES.some(([value]) => value === config.mode)) {
    return "Choose when this webhook runs.";
  }
  const supplied = config.inputs ?? {};
  for (const [name, source] of Object.entries(supplied)) {
    const hasParameter = typeof source?.parameter === "string" && source.parameter !== "";
    const hasValue = typeof source?.value === "string";
    if (hasParameter === hasValue) {
      return `Say where ${name} comes from: a parameter or a fixed value, not both.`;
    }
    if (hasParameter && !parameterNames.includes(source.parameter!)) {
      return `${name} reads ${source.parameter}, which is not a parameter of this action.`;
    }
  }
  const missing = requiredInputs(webhook).filter((name) => !(name in supplied));
  if (missing.length) {
    return `This webhook needs ${missing.join(", ")}.`;
  }
  return null;
}

/** What is wrong with the rules *together*, or null.
 *
 * Two rules that only exist across the list, which is why they are not in
 * {@link problem}:
 *
 * * p.106's "you can only configure a single webhook as a writeback" — the
 *   rule that breaks it is the **second** one, so no single rule is wrong;
 * * p.110's *subsequent* — a rule reading `webhook.x` is fine below the
 *   writeback that produces it and wrong above.
 */
export function listProblem(
  rules: readonly { kind: string; config: Record<string, unknown> }[],
  outputsFor: (webhookId: string) => string[],
): string | null {
  let writebacks = 0;
  const known = new Set<string>();
  for (const rule of rules) {
    if (rule.kind === "webhook") {
      const mode = String(rule.config?.mode ?? DEFAULT_MODE);
      if (mode === "writeback") {
        writebacks += 1;
        if (writebacks > 1) {
          return "An action can have only one writeback webhook — the action stops being applied when one fails.";
        }
        for (const output of outputsFor(String(rule.config?.webhook ?? ""))) {
          known.add(outputName(output));
        }
      }
      continue;
    }
    // **Read after the webhook branch adds its outputs**, so the order of this
    // loop *is* p.110's "subsequent". A pass that collected every writeback's
    // outputs first would turn a real ordering rule into "does this action
    // have a webhook anywhere", which is a different and much weaker claim.
    const parameter = String(rule.config?.parameter ?? "");
    if (parameter.startsWith(OUTPUT_PREFIX) && !known.has(parameter)) {
      return `${parameter} is only available to rules below the writeback webhook that produces it.`;
    }
  }
  return null;
}

/** What the value pickers offer for a rule at this position: the action's
 * parameters, then any writeback outputs available *above* it.
 *
 * Position matters for the same reason `listProblem` walks in order — offering
 * an output to a rule that cannot use it would be offering a save that fails
 * (§214).
 */
export function valueOptions(
  parameterNames: readonly string[],
  rules: readonly { kind: string; config: Record<string, unknown> }[],
  index: number,
  outputsFor: (webhookId: string) => string[],
): string[] {
  const options = [...parameterNames];
  for (let i = 0; i < index; i += 1) {
    const rule = rules[i];
    if (
      rule?.kind === "webhook"
      && String(rule.config?.mode ?? DEFAULT_MODE) === "writeback"
    ) {
      for (const output of outputsFor(String(rule.config?.webhook ?? ""))) {
        options.push(outputName(output));
      }
    }
  }
  return options;
}
