/** The layout a reader is served, translated into their language (§399).
 *
 * > "Viewers will then be presented with a translated view of the module in
 * > their browser's locale if the Workshop application has been translated
 * > into that language using this feature." (p.207)
 *
 * **One hook, every reader surface.** A module reaches a reader through four
 * doors — the published route, the saved-version route, an Object View's
 * layout, and an Embedded module inside another module — and p.207 makes no
 * distinction between them. A translation applied at three of the four is the
 * bug this file exists to make impossible: there is one function, and adding
 * a fifth door means calling it.
 *
 * **Not the builder.** p.211 gives edit mode its own preview, reached "by
 * navigating to the Translations tab and selecting the configured language of
 * choice" — an explicit act, because an author editing a French module needs
 * to see the strings they are editing.
 */
// Relative, not `@/`: these are **value** imports and vitest resolves no path
// alias, so `@/` here means this module cannot be unit tested at all. Every
// other tested module under `components/canvas/` imports lib this way; the
// test is what caught the one that did not.
import { layoutOf, translationsOf, type LayoutNodes } from "../../lib/workshop-module";
import { tableFor, translated } from "./translatable";

/** The languages this browser asked for, most wanted first.
 *
 * `navigator.languages` rather than `navigator.language`: a reader who lists
 * Catalan then Spanish is telling us both, and a module translated into
 * Spanish but not Catalan should serve Spanish rather than English.
 *
 * Empty on the server and wherever the API is missing, which resolves to the
 * document as written - the right answer for a surface that does not know who
 * is looking.
 */
export function readerLanguages(): readonly string[] {
  if (typeof navigator === "undefined") return EMPTY;
  const listed = navigator.languages;
  if (listed && listed.length > 0) return listed;
  return navigator.language ? [navigator.language] : EMPTY;
}

// One frozen array rather than a fresh `[]` each call, so a memo keyed on the
// result does not recompute on every render of a module with no table.
const EMPTY: readonly string[] = Object.freeze([]);

/**
 * The node map to render for whoever is looking.
 *
 * **A plain function, not a hook**, and that is the point rather than an
 * omission. Two of the four doors compute their layout after an early return
 * — an Object View bails out to the standard view when the configured one
 * will not load — so a hook here would be a conditional hook call at the one
 * call site hardest to notice it at. There is nothing to memoise anyway:
 * `translated` hands back the very object it was given when no string
 * changes, and every caller serialises the result for `<Frame data>` on each
 * render regardless.
 */
export function readerLayout(definition: unknown): LayoutNodes {
  return translated(
    layoutOf(definition),
    tableFor(translationsOf(definition), readerLanguages()),
  );
}
