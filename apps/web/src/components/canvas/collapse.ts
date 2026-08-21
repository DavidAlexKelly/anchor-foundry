/** Collapsible sections, and what decides whether one is collapsed
 * (Foundry `workshop` p.55, p.82).
 *
 * > "For each collapsible section in the module, the following three events are
 * > available: **Expand**… **Collapse**… **Toggle**: Expand the section
 * > specified in the event name if it is currently collapsed, or collapse the
 * > specified section if it is currently expanded." (p.82)
 *
 * And immediately after, the sentence this module exists for:
 *
 * > "If the specified section has a Boolean variable backing the collapse
 * > state, **the value of this variable will not be updated** as a result of
 * > one of these events. If you wish to keep this variable value in sync with
 * > the collapse state of the section, you can use a Set Variable Value event
 * > instead." (p.82)
 *
 * So a section can be told two different things at once, and p.82 is explicit
 * that the two are allowed to disagree. Something has to say which one is on
 * screen, and getting it wrong is silent: a Toggle that appears to do nothing,
 * or a variable that appears not to be read.
 *
 * **The reading: the most recent instruction wins.** An event overrides the
 * variable, and stays in force until the variable's own value *changes* - at
 * which point the variable is the newer instruction and takes over again.
 *
 * That is a judgement call and p.82 does not make it, so here is why. The two
 * simpler rules each break one of p.82's own sentences. "The variable always
 * wins" makes Expand and Collapse do nothing at all on exactly the sections
 * p.82 says they are available for. "The event always wins" makes the word
 * *backing* false after the first click - the variable would drive the section
 * once and never again, and a module whose section state is meant to follow a
 * filter would quietly stop following it. Only "the latest instruction wins"
 * leaves both sentences true.
 */

/** Whether a backing variable's value means "collapsed".
 *
 * The variable is declared `boolean` and the server keeps it that way, but a
 * resolved value arrives as JSON and a document can be written by something
 * other than the builder. `"false"` is the case worth naming: it is a
 * non-empty string, so the obvious coercion makes it true, and a section stuck
 * collapsed because somebody's transform produced the *word* false is a bug
 * with nothing to see.
 */
export function asCollapsed(value: unknown): boolean {
  if (typeof value === "string") {
    const text = value.trim().toLowerCase();
    return text !== "" && text !== "false" && text !== "0" && text !== "no";
  }
  return Boolean(value);
}

/** An event's instruction, and the variable value it was given against.
 *
 * The second half is what makes "until the variable changes" checkable without
 * keeping a clock: a stored copy of what the variable said at the time, so a
 * later value that differs is by definition newer.
 */
export interface CollapseOverride {
  collapsed: boolean;
  /** The backing variable's state when this override was set, or `null` for a
   * section with no backing variable. */
  against: boolean | null;
}

/** Whether a section is collapsed right now.
 *
 * `variable` is the backing variable's resolved value, or `undefined` when the
 * section has no backing variable at all - which is not the same as a variable
 * holding `false`, and treating them alike would make `collapsedByDefault`
 * unreachable for every section that names one.
 */
export function collapseState(
  override: CollapseOverride | undefined,
  variable: unknown,
  collapsedByDefault: boolean,
): boolean {
  if (variable === undefined) {
    // No backing variable: the only instructions are the default and whatever
    // an event last said.
    return override ? override.collapsed : collapsedByDefault;
  }
  const now = asCollapsed(variable);
  // The override still stands only while the variable says what it said when
  // the override was made. A different value is a newer instruction.
  if (override && override.against === now) return override.collapsed;
  return now;
}

/** What an effect means for a section that is currently in `collapsed`.
 *
 * Named rather than inlined because Toggle is the one of the three that reads
 * the current state, and a Toggle computed from the wrong "current" - the
 * variable rather than what is on screen - is the mistake that looks like the
 * feature working until an event and a variable disagree.
 */
export function nextCollapsed(
  effect: "expand_section" | "collapse_section" | "toggle_section",
  collapsed: boolean,
): boolean {
  if (effect === "expand_section") return false;
  if (effect === "collapse_section") return true;
  return !collapsed;
}
