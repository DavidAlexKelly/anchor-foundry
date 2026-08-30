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
 * **A configured view is not a thing every object type has**, and that is what
 * these functions are really about. p.261 lets a builder ask for one; whether
 * there is one to give is a fact about the object type, discovered at read
 * time and able to change after the module was saved — a view can be
 * unpublished, or one can appear where there was none. So the mode a document
 * holds is a *preference*, and every question here takes `hasConfigured`
 * beside it rather than trusting the document alone.
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

export interface ViewChoice {
  /** What the document asks for. */
  mode: unknown;
  /** Whether this object type actually has a configured view right now. */
  hasConfigured: boolean;
}

/** Which view opens.
 *
 * **A type with no configured view opens on the standard one whatever the
 * document says.** The alternative is a widget that renders nothing because it
 * was pointed at a view somebody has since unpublished, which is the failure
 * `ObjectView` already refuses one level down: the object stays viewable.
 */
export function startsStandard({ mode, hasConfigured }: ViewChoice): boolean {
  return !hasConfigured || viewModeOf(mode) === "standard";
}

/** Whether the reader is offered the switch.
 *
 * Never when there is nothing to switch *to*: two buttons where one of them
 * leads nowhere is a control that lies about what the platform has.
 */
export function showsToggle(
  { allowToggle, hasConfigured }: { allowToggle: unknown; hasConfigured: boolean },
): boolean {
  return hasConfigured && allowToggleOf(allowToggle);
}
