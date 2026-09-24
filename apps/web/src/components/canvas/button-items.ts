/**
 * p.483's button types and the items a Menu or Two-part button carries
 * (`workshop` p.483–486; §462).
 *
 * > "Inline buttons that provide a single option / Menu buttons that provide
 * > multiple options / Two-part buttons that contain a primary button
 * > alongside an additional menu of options." (p.483)
 *
 * > "Add button: Selecting this option adds another button / menu item to this
 * > button group. Duplicate button: … creates a copy of an existing button's
 * > configuration" (p.486)
 *
 * **An item is addressed by id, never by label**, for the reason a variable
 * is: the label is what somebody renames, and an event wired to "Export" would
 * stop firing the day it became "Export as CSV". The server checks an event's
 * item against these ids (`workshop_events.button_items`).
 */

export const BUTTON_TYPES = ["inline", "menu", "twoPart"] as const;
export type ButtonType = (typeof BUTTON_TYPES)[number];

export interface ButtonItem {
  id: string;
  label: string;
  leftIcon?: string;
  description?: string;
}

export function buttonTypeOf(value: unknown): ButtonType {
  return (BUTTON_TYPES as readonly unknown[]).includes(value) ? (value as ButtonType) : "inline";
}

/** The items a document holds, keeping only what is one: an id and a label.
 * Anything else is dropped rather than drawn as a nameless entry that fires
 * nothing - the server refuses an event on it for the same reason. */
export function itemsOf(raw: unknown): ButtonItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is ButtonItem =>
    !!item && typeof item === "object"
    && typeof (item as ButtonItem).id === "string" && !!(item as ButtonItem).id
    && typeof (item as ButtonItem).label === "string");
}

/** The first `i_N` no item has, so ids stay short and never collide. */
export function newItemId(items: readonly ButtonItem[]): string {
  const taken = new Set(items.map((i) => i.id));
  let n = items.length + 1;
  while (taken.has(`i_${n}`)) n += 1;
  return `i_${n}`;
}

/** p.486's Add button: a new item at the end. */
export function addItem(items: readonly ButtonItem[]): ButtonItem[] {
  const id = newItemId(items);
  return [...items, { id, label: `Option ${items.length + 1}` }];
}

/** p.486's Duplicate button: a copy right after the original, with its own id
 * - a copy sharing the id would fire the original's events. */
export function duplicateItem(items: readonly ButtonItem[], id: string): ButtonItem[] {
  const at = items.findIndex((i) => i.id === id);
  if (at < 0) return [...items];
  const copy = { ...items[at]!, id: newItemId(items) };
  return [...items.slice(0, at + 1), copy, ...items.slice(at + 1)];
}

export function removeItem(items: readonly ButtonItem[], id: string): ButtonItem[] {
  return items.filter((i) => i.id !== id);
}

export function renameItem(items: readonly ButtonItem[], id: string, label: string): ButtonItem[] {
  return items.map((i) => (i.id === id ? { ...i, label } : i));
}
