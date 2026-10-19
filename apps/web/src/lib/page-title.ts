/** What a platform page puts in the browser tab (§1012).
 *
 * Every page but a module's was "Anchor", from `app/layout.tsx`. A tab bar of
 * five Anchors says nothing, and a screen reader reads the title first on
 * every page it opens - WCAG 2.4.2 asks that it say which page this is. So a
 * page names itself, most specific first and then where it is: "Datasets ·
 * Operations · Anchor".
 *
 * A module names its own tab, from its header (`canvas/module-title.ts`,
 * p.47), and keeps doing so: this is for the pages around modules. */
import { useEffect } from "react";

export const PRODUCT = "Anchor";

/** The parts that are known, in order. A part still loading is left out
 * rather than shown as a blank between two dots. */
export function pageTitle(...parts: (string | null | undefined)[]): string {
  const known = parts.map((p) => p?.trim()).filter((p): p is string => !!p);
  return [...known, PRODUCT].join(" · ");
}

/** Assigns and does not restore, for the reason `useModuleTitle` gives:
 * Next puts the route's own title back on every client-side navigation.
 * `null` leaves the tab to something else to name - a module, inside the
 * application shell, which would otherwise be overwritten: a parent's effect
 * runs after its child's.
 *
 * **And puts it back while the page is open.** Next writes the root layout's
 * "Anchor" into `<title>` when its metadata arrives, which on a cold load
 * can be after this effect has run - one load in eight, in the browser
 * suite, left the tab saying Anchor. Whatever writes it, the page that is on
 * screen says what the tab reads. */
export function useDocumentTitle(title: string | null): void {
  useEffect(() => {
    if (title === null) return;
    const assign = () => {
      if (document.title !== title) document.title = title;
    };
    assign();
    const watch = new MutationObserver(assign);
    watch.observe(document.head, { subtree: true, childList: true, characterData: true });
    return () => watch.disconnect();
  }, [title]);
}

export function usePageTitle(...parts: (string | null | undefined)[]): void {
  useDocumentTitle(pageTitle(...parts));
}
