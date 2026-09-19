/** p.207-211's Translations: which strings in a module can be translated, and
 * what a reader is served (§399).
 *
 * > "Application builders can now provide translations for supported string
 * > types used within a Workshop application… Viewers will then be presented
 * > with a translated view of the module in their browser's locale if the
 * > Workshop application has been translated into that language." (p.207)
 *
 * > "The following content in a Workshop application can be translated:
 * > Module header Title / Section header Title(s) and Tabs / Static text from
 * > widgets such as: Tabs widget Label, Button Group widget Text and
 * > Description, Metric Card widget Label and Description, Markdown widget
 * > Content, Object Table and Object List widget Column Titles, Pivot Table
 * > widget Aggregation Titles, Filter List widget Section Titles" (p.208)
 *
 * **"Such as" is doing work in that sentence, and §391's note had it wrong.**
 * The note called p.208 "a closed list"; it is not — the widget list is
 * introduced by "such as" and is therefore examples of one rule. The rule is
 * what is closed: *static text an author typed*, as against data, property
 * names and anything a variable produces. So this map carries p.208's named
 * widgets **and** our Text widget, whose whole purpose is static text and
 * which it would be absurd to leave untranslatable on a technicality.
 *
 * **What is translated is the document, once, not each widget.** A reader's
 * layout is this module's output and every widget draws it unchanged, so a
 * widget written before Translations existed is translated too and no widget
 * has to remember to ask. The alternative — a `t()` at each of a hundred-odd
 * render sites — is the version that is wrong the first time somebody adds a
 * widget and forgets.
 */
import type {
  WorkshopTranslationEntry, WorkshopTranslations,
} from "@/lib/types";
import { resolvedNameOf, type LayoutNodes } from "../../lib/workshop-module";

/** The table for one language: source text to what it says instead. */
export type Table = Record<string, WorkshopTranslationEntry>;

/**
 * p.208's list, against the props our widgets actually store (§216, and §398
 * earned that citation the hard way by inventing two).
 *
 * | p.208 | here |
 * | --- | --- |
 * | Module header Title | `CanvasHeader.title` |
 * | Section header Title(s) | `CanvasSection.title` |
 * | Section … and Tabs | `CanvasSection.tabs`, below — one prop, several strings |
 * | Tabs widget Label | `CanvasPage.title` — our Tabs widget has no props of its own; a tab *is* a page, and its label is that page's title |
 * | Button Group Text | `CanvasButton.label` |
 * | Metric Card Label | `CanvasMetricCard.label` |
 * | Markdown Content | `CanvasMarkdown.text` |
 * | Pivot Table Aggregation Titles | `CanvasPivotTable.title` |
 * | Filter List Section Titles | `CanvasFilterList.title` |
 *
 * **Two of p.208's entries have nothing here to point at, and that is a fact
 * about our model rather than a gap in this list.** "Description" on Button
 * Group and Metric Card is a second static string those widgets do not have.
 * And "Object Table and Object List widget Column Titles" is not ours to
 * translate: our `columns` prop holds ontology **api_names**, and a column
 * header is the property's `display_name` from the ontology — so translating
 * it is an ontology feature and doing it here would mean a module quietly
 * renaming a property for one reader. `workshop.md` §9 records both.
 */
const TRANSLATABLE_PROPS: Record<string, readonly string[]> = {
  CanvasHeader: ["title"],
  CanvasPage: ["title"],
  CanvasOverlay: ["title"],
  CanvasSection: ["title"],
  CanvasText: ["text"],
  CanvasMarkdown: ["text"],
  CanvasButton: ["label"],
  CanvasMetricCard: ["label"],
  CanvasPivotTable: ["title"],
  CanvasFilterList: ["title"],
  CanvasObjectSetTitle: ["titleOverride"],
};

/** Props holding several strings in one comma-separated value.
 *
 * A section's tab names are stored as `"Open,Closed,All"` (`tabLabels` splits
 * them). Translated as one string, a translator would be handed a line with
 * commas in it and the result would be one entry that has to keep its comma
 * count — so each label is its own string, and the prop is rebuilt from the
 * parts. The separator is a comma because that is what `tabLabels` reads, and
 * a label containing one cannot be expressed in this prop to begin with.
 */
const LIST_PROPS: Record<string, readonly string[]> = {
  CanvasSection: ["tabs"],
};

/** One place a translatable string occurs. */
export interface Occurrence {
  /** The source text, which is also its key in a table. */
  text: string;
  node: string;
  /** `tabs[1]` for one label inside a list prop, the bare name otherwise. */
  prop: string;
}

function propsOf(node: unknown): Record<string, unknown> {
  const props = (node as { props?: unknown } | undefined)?.props;
  return props && typeof props === "object" ? (props as Record<string, unknown>) : {};
}

/** Every occurrence of a translatable string, in document order.
 *
 * Occurrences rather than strings: a translator wants the distinct list
 * (`sources` below), and a builder wants to know where one came from — the
 * same split `used-colours.ts` makes, for the same reason.
 */
export function occurrences(layout: unknown): Occurrence[] {
  const out: Occurrence[] = [];
  if (!layout || typeof layout !== "object") return out;
  for (const [nodeId, node] of Object.entries(layout as LayoutNodes)) {
    const name = resolvedNameOf(node);
    const props = propsOf(node);
    for (const prop of TRANSLATABLE_PROPS[name] ?? []) {
      const value = props[prop];
      if (typeof value === "string" && value.trim()) {
        out.push({ text: value, node: nodeId, prop });
      }
    }
    for (const prop of LIST_PROPS[name] ?? []) {
      const value = props[prop];
      if (typeof value !== "string") continue;
      value.split(",").forEach((part, index) => {
        // An empty slot is a position, not a string: `"Open,,All"` has a
        // middle tab that `tabLabels` names "Tab 2", and offering a
        // translator an empty box to fill would let them write a label the
        // document has no way to hold.
        if (part.trim()) out.push({ text: part.trim(), node: nodeId, prop: `${prop}[${index}]` });
      });
    }
  }
  return out;
}

/**
 * The distinct strings to translate, in the order they are first met.
 *
 * Document order rather than alphabetical: p.209 has a builder working down a
 * list of "each translatable string detected within the module", and the order
 * the module reads in is the order that lets them keep their place. Sorting
 * would scatter a page's strings through the list.
 */
export function sources(layout: unknown): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const { text } of occurrences(layout)) {
    if (seen.has(text)) continue;
    seen.add(text);
    out.push(text);
  }
  return out;
}

/** What one string says in this table, or the source when nothing does.
 *
 * **An empty translation is not a translation.** A table entry holding `""`
 * is a box a builder opened and did not fill, and serving it would blank the
 * string on screen — which reads as a broken widget rather than as an
 * untranslated one.
 */
export function say(text: string, table: Table | undefined): string {
  const entry = table?.[text];
  return entry && entry.text.trim() ? entry.text : text;
}

/**
 * The layout a reader of this language is served.
 *
 * The same node map with every translatable string replaced, so the whole
 * canvas is translated by one pass over the document. Returns the input
 * untouched when nothing would change, which keeps `<Frame data>` stable for
 * a module with no table.
 */
export function translated(layout: unknown, table: Table | undefined): LayoutNodes {
  const base = (layout && typeof layout === "object" ? layout : {}) as LayoutNodes;
  if (!table || Object.keys(table).length === 0) return base;
  const out: LayoutNodes = {};
  let changed = false;
  for (const [nodeId, node] of Object.entries(base)) {
    const name = resolvedNameOf(node);
    const props = propsOf(node);
    const next: Record<string, unknown> = { ...props };
    let touched = false;
    for (const prop of TRANSLATABLE_PROPS[name] ?? []) {
      const value = props[prop];
      if (typeof value !== "string" || !value.trim()) continue;
      const said = say(value, table);
      if (said === value) continue;
      next[prop] = said;
      touched = true;
    }
    for (const prop of LIST_PROPS[name] ?? []) {
      const value = props[prop];
      if (typeof value !== "string") continue;
      // Rebuilt from the split rather than by replacing substrings: a label
      // that is a prefix of another ("Open" in "Open cases") would otherwise
      // be translated inside it.
      const parts = value.split(",").map((part) => {
        const trimmed = part.trim();
        if (!trimmed) return part;
        const said = say(trimmed, table);
        // The original slice back, spacing and all, when nothing was
        // translated. Returning the trimmed text instead would rewrite
        // `"Open, Closed"` as `"Open,Closed"` on a module with no table for
        // this string at all - a change to a prop this pass did not
        // translate, which is exactly what it must never make.
        return said === trimmed ? part : said;
      });
      const joined = parts.join(",");
      if (joined === value) continue;
      next[prop] = joined;
      touched = true;
    }
    out[nodeId] = touched ? { ...(node as object), props: next } : node;
    changed = changed || touched;
  }
  return changed ? out : base;
}

/**
 * The language to serve, out of the ones this module has.
 *
 * p.207: "in their browser's locale". A browser says `en-GB` or `pt-BR`; a
 * module is usually translated into `fr` or `pt`. So an exact match wins, and
 * otherwise the base language does — a reader on `fr-CA` is much better
 * served by the French table than by English. The reverse also holds: a
 * reader on `pt` takes `pt-BR` if that is the only Portuguese there is, which
 * is the assumption every browser's own `Accept-Language` negotiation makes.
 *
 * **The source language wins over any table**, before either. p.209 has a
 * builder declare what the module is written in; a table stored under that
 * same tag would be a translation of English into English, and serving it
 * would let a stale table override the document.
 */
export function bestLanguage(
  available: readonly string[],
  preferred: readonly string[],
  sourceLanguage?: string,
): string | null {
  const base = (tag: string) => tag.toLowerCase().split("-")[0];
  const source = (sourceLanguage ?? "").trim().toLowerCase();
  for (const want of preferred) {
    const tag = want.trim().toLowerCase();
    if (!tag) continue;
    if (source && (tag === source || base(tag) === base(source))) return null;
    const exact = available.find((a) => a.trim().toLowerCase() === tag);
    if (exact) return exact;
    const sameBase = available.find((a) => base(a.trim()) === base(tag));
    if (sameBase) return sameBase;
  }
  return null;
}

/**
 * The table to serve a reader, or `undefined` for the document as written.
 *
 * `enabled` is checked here rather than at the call site, so there is one
 * answer to "is this reader being translated" and no surface can forget to
 * ask. p.208 makes the toggle the feature's on switch, and a module with a
 * half-entered table and the switch off must reach nobody.
 */
export function tableFor(
  translations: WorkshopTranslations | undefined,
  preferred: readonly string[],
): Table | undefined {
  if (!translations?.enabled) return undefined;
  const languages = translations.languages ?? {};
  const pick = bestLanguage(Object.keys(languages), preferred, translations.source_language);
  return pick ? languages[pick] : undefined;
}

/**
 * p.210's split: what still needs a translator, and what has been reviewed.
 *
 * > "Any new or modified strings detected in the module… will appear in the
 * > To translate section, separating them from the already-translated and
 * > reviewed strings." (p.210)
 *
 * Both halves come from the *document's* strings, so a string that was edited
 * is in `toTranslate` without anything having to notice the edit — its new
 * text is a key nothing has an entry for. `stale` is the other direction:
 * entries for text the module no longer contains, which are not shown to a
 * translator and are not deleted either, because an edit that is undone
 * should not have cost its translations.
 */
export function toTranslate(layout: unknown, table: Table | undefined): string[] {
  return sources(layout).filter((text) => say(text, table) === text);
}

export function done(layout: unknown, table: Table | undefined): string[] {
  return sources(layout).filter((text) => say(text, table) !== text);
}

export function stale(layout: unknown, table: Table | undefined): string[] {
  const live = new Set(sources(layout));
  return Object.keys(table ?? {}).filter((text) => !live.has(text));
}
