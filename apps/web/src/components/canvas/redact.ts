/** Redact mode (`workshop` p.614-615).
 *
 * > "Redact mode visually obfuscates the visible content of a Workshop
 * > application so you can share the layout and structure of a module without
 * > exposing the underlying data. Use redact mode when you take screenshots or
 * > share your screen and want to hide the underlying data." (p.614)
 *
 * **p.614's warning is part of the feature, not a footnote on it**, and this
 * module carries it as a constant so it reaches the screen:
 *
 * > "Redact mode is a visual aid only and is not a security feature. Workshop
 * > still loads and processes the underlying data; redact mode only changes
 * > how the page renders. Do not rely on redact mode to protect sensitive
 * > information from a determined viewer with access to your browser session."
 * > (p.614)
 *
 * That sentence is why the mode is *cheap*: nothing is withheld, no request
 * changes, no permission is consulted. It is also why a reader has to be told
 * — a blurred page looks like a page that is protecting something, and
 * somebody who believes that will screen-share a DOM that still holds every
 * value.
 *
 * What the rendering does is CSS (`globals.css`, `[data-redact="on"]`); this
 * decides when it is on and what it is called.
 */

/** p.615's parameter, spelled exactly as p.615 spells it:
 *
 * > "Append the query parameter `?workshop_enableRedactMode=true` to the URL
 * > of any Workshop module to enable redact mode." (p.615)
 *
 * A link is the whole interface, so the name is Foundry's rather than ours —
 * an address copied out of their documentation has to work here. */
export const REDACT_PARAM = "workshop_enableRedactMode";

/** p.614's warning, verbatim in substance and short enough to fit a banner. */
export const WARNING =
  "Redact mode is a visual aid, not a security feature — the data is still "
  + "loaded and still in this page.";

/** Whether the address asks for redact mode.
 *
 * **`true` and nothing else.** p.615 gives one spelling, and accepting `1`,
 * `yes` or a bare presence would mean a link that works here and not in
 * Foundry, or the reverse — the one thing a copied address must not do. A
 * value that is not `true` is the mode being off, which is also what a
 * mistyped one should be: failing open on an unreadable value would turn a
 * typo into a redacted screen nobody asked for.
 */
export function redactOn(search: string): boolean {
  return new URLSearchParams(search).get(REDACT_PARAM) === "true";
}

/** The address that enters or leaves redact mode.
 *
 * Shaped like `profilerHref` and for its reason: returned rather than applied,
 * so the decision is testable without a router, and **every other parameter is
 * kept** — a module reached through a routed link (p.197) carries its variable
 * values in the address, and dropping them on the way in would redact a
 * different module state than the one on screen.
 */
export function redactHref(current: string, on: boolean): string {
  const [path, query = ""] = current.split("?");
  const params = new URLSearchParams(query);
  if (on) params.set(REDACT_PARAM, "true");
  else params.delete(REDACT_PARAM);
  const rest = params.toString();
  return rest ? `${path}?${rest}` : (path ?? "");
}

/** p.615: "The parameter persists in the URL across in-application
 * navigation".
 *
 * Routing's own writes already keep it — `RoutingSync` removes only the keys
 * the module owns — so the one navigation that would drop it is p.90's **Open
 * Workshop module**, which builds a fresh address. Carried here rather than
 * left out: a redacted screen share whose first link opens an unredacted
 * module has redacted nothing, and that link is the likeliest thing to be
 * pressed while somebody is demonstrating the layout.
 *
 * The module's own query wins a collision. It cannot legitimately hold this
 * key — it is built from the opened module's interface variables — but if it
 * ever does, the address the event asked for is the one to send.
 */
export function carry(query: Record<string, string>, search: string): Record<string, string> {
  if (!redactOn(search) || REDACT_PARAM in query) return query;
  return { ...query, [REDACT_PARAM]: "true" };
}
