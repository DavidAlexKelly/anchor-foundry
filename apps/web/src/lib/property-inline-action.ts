/**
 * A property's inline action (§594; `workshop` p.266, `object-views` p.67).
 *
 *     "To enable inline editing for a property, configure an inline action for
 *      the property in the Ontology Manager. Once the inline action is
 *      configured, users can edit property values directly within the
 *      Property List widget." (p.266)
 *
 * Mirrors `services/property_inline_actions.py`: an inline action is an action
 * type §238 says can back an inline edit, on the property's own type, with a
 * `modify_object` rule on its own object writing the property from a
 * parameter. The Ontology Manager offers only those; a surface re-reads the
 * action and draws no editor when it has stopped being one, since an action
 * can change after it is chosen.
 */
import { eligibleActions, type EditAction } from "../components/canvas/inline-edit";

type WithRules = {
  rules?: readonly { kind: string; config?: Record<string, unknown> | null }[];
};

export type InlineAction = EditAction & WithRules & { object_type_id?: string | null };

/** The parameter `action` writes `property` from, or null. */
export function inlineParameterFor(action: WithRules | null | undefined, property: string): string | null {
  for (const rule of action?.rules ?? []) {
    const config = rule.config ?? {};
    if (rule.kind === "modify_object" && !config.object && config.property === property
        && typeof config.parameter === "string" && config.parameter) {
      return config.parameter;
    }
  }
  return null;
}

/** What the Ontology Manager offers as `property`'s inline action. */
export function inlineActionChoices<T extends InlineAction>(
  actions: readonly T[] | undefined, typeId: string, property: string,
): T[] {
  return eligibleActions(actions).filter(
    (a) => a.object_type_id === typeId && inlineParameterFor(a, property) !== null,
  );
}

/** The parameter an edit in place fills, if `action` still backs `property`;
 * null draws no editor. */
export function liveInlineParameter(
  action: InlineAction | null | undefined, property: string,
): string | null {
  const [live] = eligibleActions(action ? [action] : []);
  return live ? inlineParameterFor(live, property) : null;
}
