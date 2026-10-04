/** p.203's warning, before the save that causes it (§740).
 *
 * > "Variable values are stored within a saved state via their external ID.
 * > As a result, modifying a variable's external ID after state saving has
 * > been configured may cause previously configured states to reload
 * > unsuccessfully." (`workshop` p.203)
 *
 * The server says which external IDs this save stops reading and which states
 * hold them (`module_states.orphaned`); this is how the builder's Save words
 * it. A warning with a way through, not a refusal: p.203's next sentence is
 * that changing an external ID is how a module changes over time.
 */

export interface OrphanedKey {
  external_id: string;
  /** Newest first, as the states list is. */
  states: string[];
}

/** "Monday", "Monday and Tuesday", "Monday, Tuesday and 3 more". */
export function heldBy(states: readonly string[], shown = 2): string {
  if (states.length <= shown) {
    return states.length <= 1 ? (states[0] ?? "") : `${states.slice(0, -1).join(", ")} and ${states.at(-1)}`;
  }
  return `${states.slice(0, shown).join(", ")} and ${states.length - shown} more`;
}

/** The dialog's opening sentence: how many states, how many variables. */
export function strandedSummary(keys: readonly OrphanedKey[]): string {
  const states = new Set(keys.flatMap((k) => k.states)).size;
  const variables = keys.length;
  return `${states} saved state${states === 1 ? "" : "s"} will reopen without ` +
    `${variables === 1 ? "a value" : `${variables} values`} this save stops reading.`;
}
