/** The module header, as stored — the one node two surfaces have to read
 * without rendering it (Foundry p.46-47).
 *
 * A Workshop module's header is a node in the layout tree like any other
 * widget, which is right for the builder and awkward for everything else: the
 * browser tab wants the header's *title* before Craft has mounted anything
 * (`module-title.ts`), and the published route wants to know whether viewers
 * may star the module before it has drawn a frame. Both need the same walk
 * over the same node map, and there was one copy of it — so this is §292's
 * rule applied to a traversal rather than to a rule: one implementation,
 * imported by both.
 *
 * **Pure, and it takes the stored map rather than a Craft query.** The two
 * callers reach it from opposite sides — one inside the editor, one on a page
 * with no editor at all — and a helper that needed `useEditor` would be
 * useless to the second.
 */

/** The Craft.js node map, as stored. */
type Layout = Record<string, unknown>;

/**
 * The header's props, or null when the module has no header.
 *
 * **Null and `{}` are different answers**, and the difference is the one this
 * file exists to make: a module with no header has nobody to have made a
 * choice, and a header whose props are empty has an author who left every
 * setting at its default. They happen to agree today on every setting either
 * caller reads, and writing them as one value is how they would stop agreeing
 * silently the first time one of them should not (§210).
 */
export function headerProps(
  layout: Layout | null | undefined,
): Record<string, unknown> | null {
  for (const node of Object.values(layout ?? {})) {
    if (typeof node !== "object" || node === null) continue;
    const record = node as { type?: unknown; props?: Record<string, unknown> };
    // A node's `type` is `{resolvedName}` from the builder and a bare string in
    // hand-written and converted documents. Both are in the stored corpus.
    const type = record.type;
    const name =
      typeof type === "object" && type !== null
        ? (type as { resolvedName?: unknown }).resolvedName
        : type;
    if (String(name ?? "") !== "CanvasHeader") continue;
    return record.props ?? {};
  }
  return null;
}

/**
 * Whether a viewer is offered the star that keeps a shortcut to this module
 * (p.47).
 *
 * > "Toggle the ability for users to favorite the module in view mode."
 *
 * **True unless the builder said otherwise**, including when there is no
 * header at all. p.47 calls this a *toggle*, and a toggle names the setting
 * that turns something off — the ability it governs is one the platform
 * already gives every resource (§436's star, `getting-started` p.34), so the
 * document is asked whether it was taken away rather than whether it was
 * granted. Defaulting the other way would silently strip the star from every
 * module written before this setting existed, which is a change of behaviour
 * disguised as a default.
 *
 * **`!== false`, not `=== true`.** The stored value is whatever a document
 * carries: absent on every module that predates the toggle, and `false` only
 * where somebody unticked it. Anything else — absent, true, a value some older
 * converter left behind — means nobody turned it off.
 */
export function favouriteAllowed(layout: Layout | null | undefined): boolean {
  return headerProps(layout)?.allowFavourite !== false;
}
