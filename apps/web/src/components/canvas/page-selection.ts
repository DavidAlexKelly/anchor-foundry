/** Variable-Based Page Selection: a string variable that decides which page
 * of a module is showing (Foundry `workshop` p.81).
 *
 * > "For each page in the module, an event is available to switch to the
 * > chosen page when the event is triggered. If the module is using a string
 * > variable for the **Variable-Based Page Selection** option, **the value of
 * > this variable will not be updated** as a result of a Switch to Page event.
 * > If you wish to keep this variable value in sync with the selected page,
 * > you can use a Set Variable Value event instead." (p.81)
 *
 * That is p.82's sentence with a page id where the boolean was, so this module
 * is `collapse.ts` one row up and deliberately shaped the same way. The rule it
 * inherits, argued in full there: **the most recent instruction wins.** A
 * Switch-to-Page event overrides the variable and stays in force until the
 * variable's own value *changes*, at which point the variable is the newer
 * instruction and takes over again.
 *
 * Two things are genuinely new here, and neither has an analogue one row down.
 *
 * **The variable names a page ID, not a node.** A boolean says everything
 * there is to say about a collapse state; a page has to be identified, and
 * there are two identifiers to choose from. The author-set `pageId` is the
 * right one for the same reason p.197 gives for the URL: a Craft.js node id is
 * generated, means nothing to a person writing the value, and changes when a
 * page is recreated. Picking it would make a variable set from a transform,
 * a URL or a Set Variable Value event silently stop working after an edit
 * nobody would connect to it. It also means the link and the variable name the
 * same page in the same words, which is the only way an author can reason
 * about a module that uses both.
 *
 * **A variable can name a page that is not there.** A boolean cannot be wrong;
 * a string can be a typo, or the ID of a page since deleted. p.197 already
 * answers this for the URL - "users will be returned to the module's default
 * page" - and the same answer is right here, for the same reason: a module
 * that renders nothing because a variable holds a stale value is a blank
 * screen with no way back. Blanking is the one outcome that leaves a reader
 * stuck.
 */

/** The page ID a backing variable's value names, or null for "nothing named".
 *
 * The variable is declared `string` and the server keeps it that way, but a
 * resolved value arrives as JSON and can be written by a transform, a URL
 * parameter or an embedding module. Trimmed, because a page ID in the document
 * is trimmed (`pageIdOf`) and a value that differed only by a space would miss
 * the page it was obviously meant to name.
 *
 * Null and empty are the same answer - "no instruction" - which is what makes
 * clearing the variable fall back to the default page rather than to nothing.
 * A non-string is *not* coerced: `String(42)` would produce a page ID that
 * could in principle match, and a numeric page ID matching by accident is a
 * worse failure than a variable of the wrong type being ignored.
 */
export function asPageId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text === "" ? null : text;
}

/** A Switch-to-Page event's instruction, and the variable value it was given
 * against.
 *
 * The second half is what makes "until the variable changes" checkable without
 * keeping a clock: a stored copy of what the variable said at the time, so a
 * later value that differs is by definition newer. Same shape and same
 * argument as `CollapseOverride`.
 */
export interface PageOverride {
  /** The layout node the event switched to. A node, not a page ID: an event
   * targets a node - `workshop_events.py` validates it against the layout -
   * and a page with no author-set ID is still a page you can switch to. */
  nodeId: string;
  /** The backing variable's page ID when this override was set, or `null` for
   * a module with no backing variable. */
  against: string | null;
}

/** Which page node is showing right now.
 *
 * `variable` is the backing variable's resolved value, or `undefined` when the
 * module has no Variable-Based Page Selection at all - which is not the same
 * as a variable holding `""`, and treating them alike would be harmless here
 * but is kept distinct because `collapse.ts` needs the distinction and two
 * modules answering the same question two ways is how they drift apart.
 *
 * Returns null when there is no page to show, which a caller reads as "let the
 * layout decide" - the same null `CanvasPage` already understands.
 */
export function pageState(
  override: PageOverride | undefined,
  variable: unknown,
  /** The module's default page node — `defaultPageNode(layout)`. */
  defaultNode: string | null,
  /** The node one author-set page ID names — `pageNodeFor(layout, id)`. */
  nodeForPageId: (pageId: string) => string | null,
): string | null {
  if (variable === undefined) {
    // No backing variable: the only instructions are the default and whatever
    // an event last said.
    return override ? override.nodeId : defaultNode;
  }
  const now = asPageId(variable);
  // The override still stands only while the variable says what it said when
  // the override was made. A different value is a newer instruction.
  if (override && override.against === now) return override.nodeId;
  if (now === null) return defaultNode;
  // p.197's rule, reused: a page ID naming nothing opens the default page.
  return nodeForPageId(now) ?? defaultNode;
}
