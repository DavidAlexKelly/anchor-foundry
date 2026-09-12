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
 * changes; this platform's import also *declines* to remove what the file
 * leaves out, and a reader who does not know that will believe a copy replaced
 * their ontology when it only added to it.
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
    return "This file matches the ontology as it is. Nothing to apply.";
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

/**
 * The warning about what an import will *not* do.
 *
 * §326 declines to delete what the file leaves out — an object type's removal
 * takes its objects with it, immediately and with no review. p.66's reader is
 * told the import "will recreate the entire working state", so somebody
 * arriving from the page expects a replacement; the one thing they must not
 * believe is that these types are gone.
 *
 * `""` when there is nothing to warn about, so the line is absent rather than
 * reassuring somebody about a risk they do not have.
 */
export function leftAloneWarning(plan: OntologyPlan): string {
  const absent = plan.sections.object_types.absent_from_file;
  if (absent.length === 0) return "";
  const which = absent.length === 1 ? "1 object type" : `${absent.length} object types`;
  return (
    `${which} in this workspace are not in the file and will be left alone. `
    + "Delete them from Ontology cleanup if you meant to remove them."
  );
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
