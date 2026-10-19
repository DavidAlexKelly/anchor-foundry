/** A thing drawn as a shape that acts as a button (§1009).
 *
 * A graph's node or a chevron on it is an SVG `<g>` or `<rect>`, which a
 * click reaches and a keyboard does not: it takes no focus, and Enter on it
 * does nothing. `role="button"` alone says it is one without making it one -
 * the lineage chevrons had that and were still out of reach. These are the
 * three things a `<button>` has that the shape lacks. */
import type { KeyboardEvent } from "react";

export function pressKeys(onPress: () => void) {
  return (e: KeyboardEvent) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    // Space would also scroll the page under it.
    e.preventDefault();
    e.stopPropagation();
    onPress();
  };
}

export function pressable(onPress: () => void) {
  return { role: "button", tabIndex: 0, onClick: onPress, onKeyDown: pressKeys(onPress) } as const;
}
