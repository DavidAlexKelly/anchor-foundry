/** p.259-263's Object View widget: "detailed information about a single object
 * by displaying an embedded object view within a Workshop module".
 *
 * > "**Object to display**: The input variable that determines the object(s)
 * > that will be displayed. For the full object view form factor, only the
 * > first object will be shown if the object set contains multiple objects. …
 * > **Object View Mode**: Controls which viewing option is displayed (either
 * > standard or configured), with an option to toggle between them. …
 * > **Hide header**: If toggled on, the object view header will be hidden.
 * > **Empty state**: Configures the appearance when the widget's input
 * > variable is empty." (p.261-262)
 *
 * ---
 *
 * **A configured view is not a thing every object type has**, and the mode a
 * document holds is therefore a *preference*: a view can be unpublished, or
 * one can appear where there was none, long after the module was saved.
 *
 * This file used to answer that too — `startsStandard` and `showsToggle`, each
 * taking a `hasConfigured` beside the document's value. **The harness deleted
 * them**, and it was right: `ObjectView` already opens the standard view when
 * there is no configured one and already withholds a switch that leads
 * nowhere, so replacing `hasConfigured` with a constant `true` in the widget
 * changed nothing on screen. Two functions and eight tests were restating a
 * guard that lives one level down and is tested there. What is left is only
 * what a *document* means, which is the part with no other home.
 */

/** p.261's Object View Mode. */
export const VIEW_MODES: Record<string, string> = {
  configured: "Configured view",
  standard: "Standard view",
};

export const DEFAULT_VIEW_MODE = "configured";

export function viewModeOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(VIEW_MODES, raw) ? raw : DEFAULT_VIEW_MODE;
}

/** p.261's "with an option to toggle between them".
 *
 * **Default on**, which is the one default here that is an argument rather
 * than a convention: `object-views` p.2 says the standard view "remains
 * accessible even after a configured Object View is built", so a widget that
 * withheld it by default would make every module that never touched the
 * setting quietly narrower than the platform promises. A builder can still
 * turn it off — p.261 offers the control — but they have to mean it.
 */
export function allowToggleOf(raw: unknown): boolean {
  return raw !== false;
}

/** p.262's Hide header. */
export function hideHeaderOf(raw: unknown): boolean {
  return raw === true;
}

/** p.262's Empty state message. */
export const DEFAULT_EMPTY_MESSAGE = "No object to show";

export function emptyMessageOf(raw: unknown): string {
  return typeof raw === "string" && raw.trim() ? raw.trim() : DEFAULT_EMPTY_MESSAGE;
}
