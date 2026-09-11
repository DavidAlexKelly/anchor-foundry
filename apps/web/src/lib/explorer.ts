/**
 * What the Explorer helper offers (§303; p.13).
 *
 *     "The Foundry Explorer helper is a file navigation interface that lets you
 *      quickly browse all files and folders. Once you select a specific
 *      dataset, you can click 'Open' to view the full dataset."
 *
 * **Ours browses the platform, not the repository.** Foundry's Explorer is a
 * file tree because in Foundry the repository *is* a folder in a filesystem
 * that also holds datasets; here a repository's files are already on screen —
 * the Files tab is a file tree and a second one would be a second answer to
 * "what is in this repository". What the editor has no way to see is
 * everything *outside* it, which is what a transform reads and writes.
 *
 * So this is p.13's sentence read for what it is for: **the editor should be
 * able to see the platform without leaving the editor.** The row in
 * `code-repositories.md` §2.4 says so — "browse datasets and object types from
 * inside the editor" — and calls it small and disproportionately valuable.
 *
 * The server owns the listing, the search and the permissions; this file owns
 * what to *offer*, the division `protected-branches.ts`, `tags.ts` and
 * `branch-columns.ts` already take.
 */
import type { Resource, ResourceKind } from "./types";

/**
 * The kinds the Explorer lists, and the reason it is not every kind.
 *
 * A transform reads and writes **datasets**, and an object type is what a
 * dataset becomes when the ontology is pointed at it — those are the two
 * things a person writing a transform needs to name. The registry holds four
 * more. `code_repo` is the thing you are already inside; `canvas_app` and
 * `model` are downstream of a transform rather than nameable by one; a
 * `connection` is reached through a sync, never by a transform directly.
 *
 * Listing them anyway would make the panel a second resource browser that
 * happens to be narrower — and the platform already has that screen, one
 * click away, with sorting and paging this panel will never have.
 */
export const EXPLORER_KINDS: ResourceKind[] = ["dataset", "object_type"];

/**
 * Whether the listing has to reach past the project.
 *
 * **Object types belong to the workspace, not to a project** (`Resource`'s own
 * comment: `project_id` is null for them). So a listing that asked only for
 * this project's resources would show an Object types section that is empty in
 * every project in the platform, forever, and look like a feature that does
 * not work rather than a request that was never made.
 *
 * Derived from the kinds rather than hard-coded true, so that narrowing the
 * panel to datasets alone stops asking for workspace-level rows instead of
 * silently going on paying for them.
 */
export function needsWorkspaceLevel(kinds: readonly ResourceKind[]): boolean {
  return kinds.includes("object_type");
}

/**
 * Where Open goes.
 *
 * **By `id`, never by name** — §291's lesson, and it is sharper here: a
 * dataset's name is what the transform declaration uses, so a name is exactly
 * what is on screen beside the button, and building the link from it is the
 * mistake that looks correct.
 */
export function openHref(resource: Resource): string {
  return `/r/${resource.id}`;
}

/** The word for a kind, in the singular, as a heading. */
export function kindLabel(kind: ResourceKind): string {
  return kind === "object_type" ? "Object types" : "Datasets";
}

/**
 * The line under a row's name.
 *
 * The description when there is one. Otherwise **nothing** rather than the
 * kind repeated: the rows are already under a heading that says which kind
 * they are, and a subtitle that only restates its heading trains people to
 * stop reading subtitles.
 */
export function subtitle(resource: Resource): string | null {
  const said = resource.description?.trim();
  return said ? said : null;
}

/**
 * Whether a query is worth sending.
 *
 * Empty means *everything*, which is the panel's resting state and a request
 * worth making. A single character is not a search anybody meant — it matches
 * most of a platform — but it is also not an error, so the panel keeps showing
 * the unfiltered list rather than emptying.
 *
 * The **server** decides what matches; this only decides when to ask.
 */
export function shouldSearch(query: string): boolean {
  return query.trim().length >= 2;
}

/**
 * What the panel says when it lists nothing.
 *
 * **Three absences with three different remedies**, and telling them apart is
 * the whole job: a search that matched nothing is fixed by typing something
 * else, a project with no datasets is fixed somewhere else entirely, and a
 * panel that has not been asked yet is fixed by waiting. A single "Nothing
 * here" would send everybody to the wrong one of those.
 */
export function emptyReason(count: number, query: string): string | null {
  if (count > 0) return null;
  if (shouldSearch(query)) {
    return `Nothing here matches ${query.trim()}.`;
  }
  return (
    "No datasets or object types yet. A transform reads and writes datasets, " +
    "so this fills up as the project does."
  );
}

/**
 * The rows of one kind, in the order the panel draws them.
 *
 * **By name, not by the server's order.** The listing is sorted for a resource
 * browser — most recently updated first, which is right when you are looking
 * for what you just changed. This panel is read to find a name you already
 * know so you can type it into a declaration, and alphabetical is the only
 * order that lets somebody stop scanning early.
 */
export function ofKind(resources: readonly Resource[], kind: ResourceKind): Resource[] {
  return resources
    .filter((r) => r.kind === kind)
    .sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * The sections the panel draws, kinds with nothing in them included.
 *
 * **An empty section is drawn, not skipped**, and that is the opposite of the
 * usual rule. "This project has no object types" and "this panel does not do
 * object types" look identical when the heading is missing, and only one of
 * them is something the reader can act on — the same argument
 * `ResourceKindCounts` makes one file over when it says every kind is present
 * "so a caller never has to tell 'none of these' from 'no such kind'".
 */
export function sections(
  resources: readonly Resource[],
  kinds: readonly ResourceKind[] = EXPLORER_KINDS,
): { kind: ResourceKind; label: string; rows: Resource[] }[] {
  return kinds.map((kind) => ({
    kind,
    label: kindLabel(kind),
    rows: ofKind(resources, kind),
  }));
}

/**
 * Whether Insert is offered for this file at all (§304; p.13).
 *
 * **Only the two languages that declare.** The server refuses anything else,
 * and this is the browser not offering a button whose only outcome is that
 * refusal — §214's rule, that a control which looks like it works is worse
 * than one that is absent.
 *
 * Everything *else* the server refuses — a file that declares no output yet, a
 * decorator whose inputs are code, an alias already taken — is deliberately
 * **not** predicted here. Each needs the file's declaration read, and reading
 * it here would be a second parser disagreeing with the one that matters. The
 * button is offered and the refusal is shown, which is a sentence explaining
 * what to do rather than a control that quietly is not there.
 */
export function canInsert(path: string | undefined): boolean {
  if (!path) return false;
  return path.endsWith(".sql") || path.endsWith(".py");
}

/**
 * The alias to offer for a dataset, before anybody edits it.
 *
 * **An alias is a name the transform refers to**, so it is narrower than a
 * dataset name: `raw-orders` is a fine dataset and `raw-orders` is not a fine
 * variable. The server refuses the difference (`unwritable`); suggesting a
 * name that will be refused would make the common case an error message.
 *
 * A leading digit is prefixed rather than dropped: `2024_totals` is a dataset
 * somebody named on purpose, and `024_totals` would be a different thing that
 * looks like a typo.
 */
export function suggestedAlias(datasetName: string): string {
  const cleaned = datasetName.trim().replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  if (cleaned === "") return "input";
  return /^[0-9]/.test(cleaned) ? `d_${cleaned}` : cleaned;
}

/**
 * What the Insert button says it will do, before it does it.
 *
 * Named with both halves, because the alias is the part being *chosen* — the
 * dataset was chosen by clicking the row — and it is the name the query will
 * use. A button saying only "Insert" would be asking somebody to accept a
 * variable name they never saw.
 */
export function insertLabel(alias: string, path: string | undefined): string {
  const language = path?.endsWith(".py") ? "#" : "--";
  return `Insert ${language} input: ${alias}`;
}
