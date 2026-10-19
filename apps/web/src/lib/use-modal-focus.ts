/** What a native `<dialog>` does for a modal that is not one (§1010).
 *
 * `components/dialog.tsx` is a `<dialog>` and has these from the browser. A
 * module's overlay and a table's "Submit these edits" are `aria-modal` boxes
 * drawn in the page, and said they were modal while doing none of it: focus
 * stayed on whatever opened them, Tab walked out of them into the page behind,
 * Escape did nothing, and closing one left focus on nothing. So:
 *
 * - opening moves focus into it - to the box itself, so a reader announces
 *   its name before its first control;
 * - Tab and Shift+Tab go round its own controls and no further;
 * - Escape closes it, unless something inside already used the key;
 * - closing puts focus back where it was. */
import { useCallback, useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled])", "select:not([disabled])",
  "textarea:not([disabled])", "[tabindex]:not([tabindex='-1'])",
].join(",");

export function useModalFocus<T extends HTMLElement>(open: boolean, onClose: () => void) {
  const ref = useRef<T | null>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const box = ref.current;
    if (!open || !box) return;
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    box.focus();
    return () => {
      if (before && before.isConnected) before.focus();
    };
  }, [open]);

  const onKeyDown = useCallback((e: KeyboardEvent<T>) => {
    const box = ref.current;
    if (!box) return;
    if (e.key === "Escape") {
      if (e.defaultPrevented) return;
      e.preventDefault();
      e.stopPropagation();
      close.current();
      return;
    }
    if (e.key !== "Tab") return;
    const all = [...box.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null);
    const first = all[0];
    const last = all[all.length - 1];
    if (!first || !last) {
      e.preventDefault();
      return;
    }
    const at = document.activeElement;
    if (e.shiftKey && (at === first || at === box)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && at === last) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  return { ref, onKeyDown, tabIndex: -1 } as const;
}
