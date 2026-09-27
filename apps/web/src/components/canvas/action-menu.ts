/**
 * p.512's several actions in one Inline Action widget (§556).
 *
 * > "Select an Action: Select Add item to include multiple actions, each
 * > requiring individual configuration. When multiple actions are implemented
 * > in the same widget frame, users will see a selection menu upfront." (p.512)
 *
 * The widget's own action, title and parameter defaults are the first item -
 * so every Inline Action saved before this is a one-item widget with no menu,
 * unchanged. `actions` holds the rest, each with its own action and title
 * (and defaults, which only a document can set, as for the first). What the
 * widget does around the form - the object it edits, the header, the output
 * set - is the widget's, shared by every item.
 *
 * Pure: the widget and its panel do the drawing.
 */

export interface MoreAction {
  actionTypeId: string | null;
  title: string;
  parameterDefaults?: Record<string, unknown>;
}

export interface ActionItem {
  actionTypeId: string;
  title: string;
  parameterDefaults: Record<string, unknown>;
}

function defaultsOf(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? (raw as Record<string, unknown>) : {};
}

/** The stored further actions, read defensively. An item still being set up
 * in the panel - no action chosen yet - is kept here, so the panel can show
 * it, and left out of `actionItemsOf`, so the menu never offers nothing. */
export function moreActionsOf(raw: unknown): MoreAction[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const { actionTypeId, title, parameterDefaults } = item as Record<string, unknown>;
    return [{
      actionTypeId: typeof actionTypeId === "string" && actionTypeId ? actionTypeId : null,
      title: typeof title === "string" ? title : "",
      ...(parameterDefaults !== undefined ? { parameterDefaults: defaultsOf(parameterDefaults) } : {}),
    }];
  });
}

/** Every action the widget offers, its own first. */
export function actionItemsOf(
  primary: { actionTypeId?: string | null; title?: string; parameterDefaults?: unknown },
  more: unknown,
): ActionItem[] {
  const first: ActionItem[] = primary.actionTypeId
    ? [{ actionTypeId: primary.actionTypeId, title: primary.title ?? "",
         parameterDefaults: defaultsOf(primary.parameterDefaults) }]
    : [];
  return [
    ...first,
    ...moreActionsOf(more).flatMap((m) => m.actionTypeId
      ? [{ actionTypeId: m.actionTypeId, title: m.title,
           parameterDefaults: defaultsOf(m.parameterDefaults) }]
      : []),
  ];
}

/** Which item is showing: the one picked, held inside the list when an item
 * is removed from under it. */
export function activeIndexOf(active: number, count: number): number {
  return Math.max(0, Math.min(active, count - 1));
}

/** What the menu calls an item: its title, else its action's name. */
export function menuLabelOf(
  item: ActionItem, actionTypes: readonly { id: string; display_name: string }[],
): string {
  return item.title.trim()
    || actionTypes.find((a) => a.id === item.actionTypeId)?.display_name
    || "Action";
}

/** p.512's "Add item": a further action, not chosen yet. */
export function withAddedAction(raw: unknown): MoreAction[] {
  return [...moreActionsOf(raw), { actionTypeId: null, title: "" }];
}

export function withMoreAction(raw: unknown, index: number, patch: Partial<MoreAction>): MoreAction[] {
  return moreActionsOf(raw).map((m, i) => (i === index ? { ...m, ...patch } : m));
}

export function withoutMoreAction(raw: unknown, index: number): MoreAction[] {
  return moreActionsOf(raw).filter((_, i) => i !== index);
}
