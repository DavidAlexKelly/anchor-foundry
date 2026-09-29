/**
 * The Ontology's saved changes, as a person reads them (§683;
 * `ontology-manager` p.8).
 *
 * > "Select the History tab in the homepage sidebar to view a list of all
 * > saved Ontology changes with details on when the changes were made and the
 * > user who applied them. By default, the list of changes are collapsed."
 * >
 * > "You also have the option to consolidate the view by merging changes that
 * > have been made by the same author into a single entry." (p.8)
 *
 * The entries are the server's (`services/ontology_history.py`, the audit log
 * read); this says what each one did in words and does p.8's merge.
 */

import type { OntologyChange } from "@/lib/types";

/** What each kind of resource is called in a sentence. */
export const KINDS: Record<string, string> = {
  object_type: "object type",
  link_type: "link type",
  action_type: "action type",
  interface: "interface",
  shared_property: "shared property",
  value_type: "value type",
  object_type_group: "group",
  object_view: "object view",
  ontology: "ontology",
};

/** The verb for each action this history holds, by the part after the dot.
 * An action this build has not named still reads, as its own words. */
const VERBS: Record<string, string> = {
  create: "Created",
  update: "Edited",
  define: "Edited the rules of",
  delete: "Deleted",
  rename: "Renamed",
  restore_version: "Restored an earlier version of",
  set_interfaces: "Changed the interfaces of",
  set_sections: "Changed the form of",
  set_members: "Changed the members of",
  set_for_type: "Changed the groups of",
  version: "Changed the rule of",
  status: "Changed the status of",
  bulk_status: "Changed the status of",
  bulk_property_status: "Changed property statuses of",
  update_join: "Changed the join of",
  edit_history: "Changed the edit history of",
  enable_log: "Changed the action log of",
  set_log_summary: "Changed the log summary of",
  set: "Configured",
  clear: "Reset",
  import: "Imported a file into",
};

/** One entry as a sentence: what was done, to what. */
export function describe(change: Pick<OntologyChange, "action" | "resource_type" | "resource_name">): string {
  const [prefix = "", rest = ""] = change.action.split(/\.(.*)/s);
  const verb = VERBS[rest] ?? `Changed (${rest.replaceAll("_", " ")})`;
  const kind = KINDS[prefix] ?? prefix.replaceAll("_", " ");
  if (prefix === "ontology") return `${verb} the ontology`;
  if (change.resource_name) return `${verb} ${kind} ${change.resource_name}`;
  // Nothing to call it by: the resource has gone and the record did not name
  // it. Said as that rather than as a blank.
  const some = `${/^[aeiou]/.test(kind) ? "an" : "a"} ${kind}`;
  return rest === "delete" ? `${verb} ${some}` : `${verb} ${some} since deleted`;
}

/** p.8's details, one line each, in a stable order. */
export function details(metadata: Record<string, unknown>): string[] {
  return Object.keys(metadata).sort().map((key) => {
    const value = metadata[key];
    const shown = typeof value === "string" ? value : JSON.stringify(value);
    return `${key.replaceAll("_", " ")}: ${shown}`;
  });
}

/** One author's run of changes, for p.8's merged view. */
export interface AuthorRun {
  user_id: string | null;
  user_name: string | null;
  changes: OntologyChange[];
}

/** Consecutive changes by one author as one entry (p.8). **Consecutive**, so
 * the list stays in time order: two runs by the same person with somebody
 * else's change between them are two entries, not one that jumps back. */
export function mergedByAuthor(changes: readonly OntologyChange[]): AuthorRun[] {
  const out: AuthorRun[] = [];
  for (const change of changes) {
    const last = out[out.length - 1];
    if (last && last.user_id === change.user_id) last.changes.push(change);
    else out.push({ user_id: change.user_id, user_name: change.user_name, changes: [change] });
  }
  return out;
}
