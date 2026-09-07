/**
 * Configuring a notification rule (Foundry `action-types` p.89-101; §258).
 *
 * §257 built the rule, the delivery and the inbox — and left the rule
 * reachable only by posting JSON, because the action definition editor offers
 * five rule kinds and `notify` was not one of them. A feature the product
 * cannot express is the same shape as §252's *implements* column that could
 * never be non-empty.
 *
 * The division is the usual one. The server owns what is **legal**
 * (`services/notifications.parse`, which refuses every case below and several
 * this cannot see); this owns what is **offered** and what a form says before
 * a round trip. The two overlap deliberately in one place — {@link problem} —
 * because a refusal that arrives on Save is a refusal about a form somebody has
 * already left.
 *
 * **The reference inserter is the piece that is genuinely hard to get right.**
 * p.94: "Click on a parameter to generate the `{{{}}}` syntax to reference that
 * parameter." Somebody typing three braces by hand will get two, and two braces
 * are not a reference — `notifications._REFERENCE` matches three exactly, for
 * the reason the escaping convention in every other templating language gives.
 * So the syntax is generated rather than typed, and {@link insertReference} is
 * where that happens.
 */

/** p.101's two references that are not parameters: "you can select the
 * `Recipient`, `Current User`, and any parameter options from the dropdown
 * list in order to generate the correct reference to those user attributes." */
export const USER_REFERENCES = [
  ["recipient", "Recipient"],
  ["current_user", "Current user"],
] as const;

/** p.90's recipient kinds, less the one that needs Functions.
 *
 * The absent fourth is `From a function`, and it is absent rather than
 * disabled: §1.3 marks Functions ○, so the option's only outcome would be a
 * save that fails (§214). The server's refusal names the same reason, so
 * somebody who reaches it by hand is told why rather than told no. */
export const RECIPIENT_KINDS = [
  ["static", "Specific people"],
  ["parameter", "Whoever a parameter names"],
  ["object_property", "Whoever an object's property names"],
] as const;

/** p.96's two, named for what they do rather than for the words in the source:
 * "Require all users to have permissions" is a mouthful for a dropdown, and
 * what it *means* is that the action does not run. */
export const PERMISSION_MODES = [
  ["all", "Refuse the action if anyone cannot see it"],
  ["any", "Send to whoever can see it"],
] as const;

export interface NotifyConfig {
  recipients: {
    kind: string;
    user_ids?: string[];
    parameter?: string;
    object_type?: string;
    property?: string;
  };
  subject: string;
  body: string;
  link?: { url: string; text: string } | null;
  permissions: string;
}

/** A new rule's config.
 *
 * `static` first because it is the one that needs nothing else to exist — a
 * form whose first state is already valid is a form somebody can save and then
 * refine, and p.101's own advice is to "initially configure the action with
 * hardcoded recipient(s) … to validate the logic". */
export function blankNotifyConfig(): NotifyConfig {
  return {
    recipients: { kind: "static", user_ids: [] },
    subject: "",
    body: "",
    link: null,
    // p.96's default, and the strict one: it cannot quietly send somebody data
    // they may not see.
    permissions: "all",
  };
}

/** What is wrong with this rule as typed, in one sentence, or null.
 *
 * Deliberately the *subset* of `notifications.parse`'s refusals that a form
 * can see without the ontology: the two halves p.89 requires, and a reference
 * naming something that is not a parameter. Everything else — a recipient
 * property that is not a string, a dotted reference the object type does not
 * have — needs the ontology, and the server answers those.
 *
 * A subset rather than a copy, and that is the point: an incomplete mirror
 * that says nothing is right, and a complete one would be a second parser to
 * keep in step.
 */
export function problem(
  config: NotifyConfig,
  parameterNames: readonly string[],
): string | null {
  const recipients = config.recipients ?? { kind: "" };
  if (recipients.kind === "static" && !(recipients.user_ids ?? []).length) {
    return "Choose at least one person to notify.";
  }
  if (
    (recipients.kind === "parameter" || recipients.kind === "object_property") &&
    !recipients.parameter
  ) {
    return "Choose the parameter that names the recipient.";
  }
  if (recipients.kind === "object_property" && !recipients.property) {
    return "Choose the property that holds the user id.";
  }
  if (!config.subject.trim()) return "A notification needs a subject.";

  const known = new Set<string>([
    ...parameterNames,
    ...USER_REFERENCES.map(([value]) => value),
  ]);
  const fields: [string, string][] = [
    ["subject", config.subject],
    ["body", config.body],
  ];
  if (config.link) {
    fields.push(["link", config.link.url], ["link", config.link.text]);
  }
  for (const [field, text] of fields) {
    for (const ref of referencesIn(text)) {
      if (!known.has(ref.split(".", 1)[0]!)) {
        return `The ${field} references ${ref}, which is not a parameter of this action.`;
      }
    }
  }
  if (config.link && (!config.link.url.trim() || !config.link.text.trim())) {
    return "A link needs both an address and the text for its button.";
  }
  return null;
}

/** Every `{{{name}}}` in a template.
 *
 * A second copy of the server's pattern, and the one place this file has one.
 * It is here because the alternative is worse: a form that could not see its
 * own references would report nothing until Save, which is the round trip
 * `problem` exists to avoid. An API test reads this expression back out of the
 * file and asserts it matches the server's (§190). */
export function referencesIn(template: string): string[] {
  return [...(template ?? "").matchAll(/\{\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}\}/g)]
    .map((match) => match[1] as string);
}

/** p.94's "click on a parameter to generate the `{{{}}}` syntax".
 *
 * Returns the new text and where the caret should land — after the inserted
 * reference, so somebody can keep typing the sentence they were in the middle
 * of rather than hunting for their place.
 *
 * A selection is **replaced**, which is what every text field does and what
 * makes "select the wrong word, click the right parameter" work.
 */
export function insertReference(
  text: string, start: number, end: number, name: string,
): { text: string; caret: number } {
  const reference = `{{{${name}}}}`;
  const from = Math.max(0, Math.min(start, text.length));
  const to = Math.max(from, Math.min(end, text.length));
  return {
    text: text.slice(0, from) + reference + text.slice(to),
    caret: from + reference.length,
  };
}

/** What the reference buttons offer, in the order p.101 lists them: the
 * action's parameters, then the two user attributes.
 *
 * Parameters first because they are what the sentence is usually about, and
 * because the user attributes are always the same two — a fixed pair at the
 * end is easier to find than a fixed pair at the start of a list that grows. */
export function referenceOptions(
  parameterNames: readonly string[],
): { value: string; label: string }[] {
  return [
    ...parameterNames.map((name) => ({ value: name, label: name })),
    ...USER_REFERENCES.map(([value, label]) => ({ value, label })),
  ];
}
