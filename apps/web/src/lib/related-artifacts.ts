/**
 * The Related artifacts helper on the lineage graph (§614; `data-lineage`
 * p.10, p.30).
 *
 *     "The related artifacts helper displays artifacts directly linked to the
 *      nodes selected on the graph. Deleted and automatically saved files are
 *      excluded from the list unless chosen otherwise." (p.10)
 *
 *     "The Related items icon will show a badge with the number of artifacts
 *      related to the selected dataset… Click on the node icon next to a
 *      resource to zoom in on the related dataset, or click the resource to
 *      open it in the corresponding application in a new tab. You can filter
 *      the list of related artifacts to include different item types and sort
 *      the list by oldest, newest, name, path, or last modified." (p.30)
 *
 * **An artifact is what the graph does not draw.** Datasets, transforms,
 * object types and sources are nodes already, so listing them again would be
 * the graph a second time. What links to a node from off the graph here is
 * two things: a **Workshop module** whose document names a selected dataset
 * or object type (p.30's "Slate applications" are this platform's modules;
 * it has no Contour), and the **code repository** a selected transform is
 * authored in. The server finds both (`services/related_artifacts.py`); this
 * file filters, sorts and words them.
 *
 * **p.10's exclusions have nothing to exclude.** Nothing here is deleted into
 * a trash, and a module is saved when somebody saves it rather than
 * automatically, so there is no second list for "unless chosen otherwise" to
 * choose. `EXCLUSION_NOTE` says so where the list is drawn.
 */

/** One artifact as the server answers it. */
export interface RelatedArtifact {
  kind: "workshop_module" | "code_repository";
  id: string;
  name: string;
  /** Opens at `/r/<resource_id>`, the route every resource opens from. */
  resource_id: string;
  project_id: string;
  project_name: string;
  created_at: string;
  updated_at: string;
  /** The selected graph nodes (`kind:uuid`) this artifact links to. */
  nodes: string[];
}

export type ArtifactKind = RelatedArtifact["kind"];

/** p.30's "different item types", in the order the list draws them. */
export const KINDS: { kind: ArtifactKind; label: string }[] = [
  { kind: "workshop_module", label: "Workshop modules" },
  { kind: "code_repository", label: "Code repositories" },
];

/** p.30's five orders. */
export type ArtifactSort = "name" | "path" | "newest" | "oldest" | "modified";

export const SORTS: { sort: ArtifactSort; label: string }[] = [
  { sort: "name", label: "Name" },
  { sort: "path", label: "Path" },
  { sort: "newest", label: "Newest" },
  { sort: "oldest", label: "Oldest" },
  { sort: "modified", label: "Last modified" },
];

export interface ArtifactEntry {
  key: string;
  kind: ArtifactKind;
  label: string;
  /** Another project's name, or null for the graph's own. */
  project: string | null;
  href: string;
  /** p.30's node icons: the selected nodes it links to, each to zoom to. */
  nodes: { id: string; label: string }[];
}

/** The kinds a node can be asked about. A source links to nothing off the
 * graph, so it is not sent. */
const ASKABLE = new Set(["dataset", "object_type", "model"]);

/** The selection's node ids worth asking the server about, in order. */
export function askedFor(selected: readonly string[]): string[] {
  return selected.filter((id) => ASKABLE.has(id.slice(0, id.indexOf(":"))));
}

/** A resource's path: its project, then its name - what p.30 sorts "path" by. */
function pathOf(artifact: RelatedArtifact): string {
  return `${artifact.project_name}/${artifact.name}`;
}

const ORDER: Record<ArtifactSort, (a: RelatedArtifact, b: RelatedArtifact) => number> = {
  name: (a, b) => a.name.localeCompare(b.name),
  path: (a, b) => pathOf(a).localeCompare(pathOf(b)),
  newest: (a, b) => b.created_at.localeCompare(a.created_at),
  oldest: (a, b) => a.created_at.localeCompare(b.created_at),
  modified: (a, b) => b.updated_at.localeCompare(a.updated_at),
};

/**
 * The entries to draw: `hidden` kinds left out, in `sort`'s order with the
 * name breaking ties so the list does not reshuffle between reads.
 *
 * `names` maps a node id to the name the graph draws it with, so an entry
 * says *which* of several selected nodes it links to; `currentProject` is the
 * graph's project id, whose name goes unsaid.
 */
export function artifactEntries(
  artifacts: readonly RelatedArtifact[],
  {
    names, currentProject, sort, hidden,
  }: {
    names: ReadonlyMap<string, string>;
    currentProject: string;
    sort: ArtifactSort;
    hidden: ReadonlySet<ArtifactKind>;
  },
): ArtifactEntry[] {
  return artifacts
    .filter((a) => !hidden.has(a.kind))
    .sort((a, b) => ORDER[sort](a, b) || a.name.localeCompare(b.name))
    .map((a) => ({
      key: `${a.kind}:${a.id}`,
      kind: a.kind,
      label: a.name,
      // Another project's artifact is worth saying: the reader is looking at
      // this project's graph, and a module elsewhere is a place they may not
      // expect a change here to reach.
      project: a.project_id === currentProject ? null : a.project_name,
      href: `/r/${a.resource_id}`,
      nodes: a.nodes.map((id) => ({ id, label: names.get(id) ?? id })),
    }));
}

/** How many of each kind, for the filter's chips. */
export function kindCounts(artifacts: readonly RelatedArtifact[]): Record<ArtifactKind, number> {
  const counts: Record<ArtifactKind, number> = { workshop_module: 0, code_repository: 0 };
  for (const a of artifacts) counts[a.kind] += 1;
  return counts;
}

/** p.10's exclusion clause, answered where the list is. */
export const EXCLUSION_NOTE =
  "Nothing here is deleted into a trash or saved automatically, so no artifact is left out.";

/** What an empty list says, which depends on why it is empty. */
export function emptyNote(asked: number, found: number): string {
  if (asked === 0) return "Select a dataset, object type or transform to see what links to it.";
  if (found === 0) return "Nothing off the graph links to the selection.";
  return "Every item type is filtered out.";
}
