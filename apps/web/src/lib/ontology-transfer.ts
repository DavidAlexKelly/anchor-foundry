/**
 * Reading an ontology file's plan (§327; `ontology-manager` p.65-67).
 *
 *     "You can export your Ontology working state by selecting the Advanced
 *      settings page from the application's home page and then selecting
 *      Export." (p.66)
 *
 *     "Next, select Import, which will recreate the entire working state from
 *      the JSON file in the application. **You will see the number of changes
 *      made in the file that need to be saved** in the application header."
 *      (p.66)
 *
 * The server decides what the file would do (§326's `plan`); this decides how
 * to say it. Same division as every other lib here.
 *
 * **The wording carries one warning the count cannot.** p.66's screen counts
 * changes; this platform's import removes what the file leaves out only when
 * the reader ticks the box that says so (§799), and a reader who does not know
 * which way it will go will believe a copy replaced their ontology when it only
 * added to it - or the other way round.
 */
import type { OntologyPlan } from "./types";

/** What an exported file is called when it lands in somebody's downloads.
 *
 * The workspace and the date, because p.65's second workflow is copying one
 * ontology into another and the folder will end up with several. `ontology.json`
 * for every export would make the reader open them to tell them apart.
 */
export function exportFilename(
  workspaceSlug: string,
  now: Date = new Date(),
): string {
  const day = now.toISOString().slice(0, 10);
  return `${workspaceSlug}-ontology-${day}.json`;
}

/**
 * p.66's count, as the sentence above the Apply button.
 *
 * **Zero is its own sentence.** "0 changes" beside an enabled button invites
 * somebody to press it and wonder what happened; a file that would change
 * nothing is the *expected* answer for p.65's edit-and-put-back workflow when
 * you have not edited anything yet.
 */
export function planHeadline(plan: OntologyPlan): string {
  if (plan.changes === 0) {
    // What the file leaves out is not "nothing": the box below can delete it.
    return hasAbsent(plan)
      ? "Everything in this file matches the ontology as it is."
      : "This file matches the ontology as it is. Nothing to apply.";
  }
  return plan.changes === 1
    ? "1 change to apply."
    : `${plan.changes} changes to apply.`;
}

/** One section's line, or "" when that section has nothing to say. */
export function sectionSummary(
  label: string,
  counts: { added: string[]; changed: string[] },
): string {
  const parts: string[] = [];
  if (counts.added.length) parts.push(`${counts.added.length} new`);
  if (counts.changed.length) parts.push(`${counts.changed.length} changed`);
  return parts.length ? `${label}: ${parts.join(", ")}` : "";
}

/** Each kind the file leaves out, as "2 object types": object types, then
 * link types, then action types. */
function absentKinds(plan: OntologyPlan): string[] {
  const kinds: [string[], string, string][] = [
    [plan.sections.object_types.absent_from_file, "object type", "object types"],
    [plan.sections.link_types.absent_from_file, "link type", "link types"],
    [plan.sections.action_types.absent_from_file, "action type", "action types"],
  ];
  return kinds.filter(([names]) => names.length > 0)
    .map(([names, one, many]) => `${names.length} ${names.length === 1 ? one : many}`);
}

/** "a, b and c". */
function listed(parts: string[]): string {
  const last = parts[parts.length - 1] ?? "";
  return parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${last}` : last;
}

/** Whether the file leaves anything out that applying could delete (§799). */
export function hasAbsent(plan: OntologyPlan): boolean {
  return absentKinds(plan).length > 0;
}

/**
 * What applying will do with what the file leaves out (§326, §799).
 *
 * p.66's import "will recreate the entire working state", which removes what
 * the file does not carry. Here that is the reader's choice, made on this
 * screen: an object type's removal takes its objects with it, immediately
 * and with no review, so it happens only when they tick the box that says
 * so - and this sentence says which way it will go before they press Apply.
 *
 * `""` when there is nothing left out, so the line is absent rather than
 * reassuring somebody about a risk they do not have.
 */
export function leftAloneWarning(plan: OntologyPlan, deleting = false): string {
  const kinds = absentKinds(plan);
  if (kinds.length === 0) return "";
  const { object_types, link_types, action_types } = plan.sections;
  const one = object_types.absent_from_file.length + link_types.absent_from_file.length
    + action_types.absent_from_file.length === 1;
  if (deleting) {
    const types = object_types.absent_from_file.length;
    return `Applying deletes ${listed(kinds)} that ${one ? "is" : "are"} not in the file`
      + (types ? `, and every object of ${types === 1 ? "that type" : "those types"}` : "")
      + ". This cannot be undone.";
  }
  return `${listed(kinds)} in this workspace ${one ? "is" : "are"} not in the file `
    + "and will be left alone. "
    + "Tick \"Delete what the file leaves out\" to remove them with the import, "
    + "or delete them from Ontology cleanup.";
}

/**
 * Whether the file came from this workspace.
 *
 * **Said, rather than left to two uuids on a screen.** p.65's two workflows
 * read the same plan differently: "nothing changed" is reassuring for an
 * edit-and-put-back and suspicious for a copy into a fresh ontology, so the
 * reader needs to know which one they are looking at before the count means
 * anything.
 */
export function originNote(plan: OntologyPlan): string {
  if (plan.is_round_trip) return "This file was exported from this workspace.";
  const from = plan.from_workspace?.name || plan.from_workspace?.slug;
  return from
    ? `This file was exported from ${from}, not from this workspace.`
    : "This file does not say which workspace it came from.";
}

/**
 * What a refused file says.
 *
 * The server's own sentence when there is one: §326's refusals name the
 * property, link or action that is wrong, and that is the only part somebody
 * editing JSON in a text editor can act on (p.65's whole premise).
 */
export function refusalText(message: string | null | undefined): string {
  return message?.trim() || "This file could not be read as an ontology.";
}

/** What an import report is a report *of*, as one sentence (§340, §344).
 *
 * **The three kinds are counted separately** rather than added together,
 * because they are applied by three different passes and any one of them can be
 * refused on its own — so "4 applied" over a report whose action half failed
 * would be a number that reads as success.
 *
 * A kind with nothing in it is left out rather than shown as a zero. The line
 * is a receipt for what happened, and "0 link types" is not something that
 * happened.
 */
export function appliedSummary(report: {
  added: string[];
  updated: string[];
  links_added: string[];
  links_updated: string[];
  actions_added: string[];
  actions_updated: string[];
  /** §799's removals, when the import was asked to make them. */
  deleted?: { object_types: string[]; link_types: string[]; action_types: string[] };
}): string {
  const count = (n: number, one: string, many: string) =>
    `${n} ${n === 1 ? one : many}`;
  const kinds: [string, string, string[], string[]][] = [
    ["object type", "object types", report.added, report.updated],
    ["link type", "link types", report.links_added, report.links_updated],
    ["action type", "action types",
     report.actions_added, report.actions_updated],
  ];
  const parts = kinds
    .filter(([, , made, changed]) => made.length + changed.length > 0)
    .map(([one, many, made, changed]) =>
      `${count(made.length + changed.length, one, many)} `
      + `(${made.length} new, ${changed.length} updated)`);
  const gone = report.deleted
    ? kinds.map(([one, many], i) => {
      const names = [report.deleted!.object_types, report.deleted!.link_types,
                     report.deleted!.action_types][i]!;
      return names.length ? count(names.length, one, many) : "";
    }).filter(Boolean)
    : [];
  const deleted = gone.length ? `Deleted ${listed(gone)}.` : "";
  if (parts.length === 0) return deleted || "Nothing needed applying.";
  // "a, b and c" rather than "a and b and c" once there are three kinds.
  return [`Applied ${listed(parts)}.`, deleted].filter(Boolean).join(" ");
}
