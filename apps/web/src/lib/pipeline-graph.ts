/**
 * Where a pipeline node opens (§351; `data-lineage` p.32).
 *
 * > "Click the Settings icon next to the object type to view its
 * > configuration in a new Ontology manager tab." (p.32)
 *
 * **One rule in one place, because there are three graphs.** The project
 * pipeline page, the dataset app's Lineage tab and the datasets page's lineage
 * dialog all draw `PipelineGraphView`, and each had its own `onOpen` written
 * out by hand — which is how `object_type` would have become a node three
 * places draw and two of them cannot open.
 *
 * Pure, and in `lib/` rather than beside the component, because vitest cannot
 * parse `.tsx`: a rule that lives in a component is a rule with no unit test.
 */

import type { PipelineNode } from "@/lib/types";

/** The project-relative section each kind of node belongs to. */
export function nodeSection(node: Pick<PipelineNode, "kind">): string {
  if (node.kind === "model") return "models";
  if (node.kind === "object_type") return "objects";
  return "datasets";
}

/**
 * The path to open this node at, under a workspace and project.
 *
 * Whether a caller *should* open a given kind is the caller's own decision —
 * the lineage dialog opened from the datasets list deliberately does nothing
 * for a dataset node, because the list it was opened over is right behind it.
 * This answers "where would it go", which is the half that must not differ
 * between the three graphs.
 */
export function nodePath(
  node: Pick<PipelineNode, "kind">, workspace: string, project: string,
): string {
  return `/${workspace}/${project}/${nodeSection(node)}`;
}

/**
 * What a node's out-of-date state reads as (§352; `data-lineage` p.51).
 *
 * > "Is there an upstream dataset that hasn't built and isn't up to date?"
 * > (p.51)
 *
 * **Two sentences rather than one badge**, because the two states send a
 * reader to different places: one names *this* dataset as the thing to
 * rebuild, and the other says the thing to rebuild is further up. A single
 * "out of date" would have somebody rebuilding the wrong one and watching it
 * come back stale.
 *
 * Returns `""` for a node that is current, which is most of them.
 */
export function outOfDateNote(
  node: Pick<PipelineNode, "out_of_date" | "out_of_date_reason">,
): string {
  if (!node.out_of_date) return "";
  if (node.out_of_date_reason === "upstream_is_out_of_date") {
    return "an upstream is out of date";
  }
  // Anything else out of date is the direct case. Not keyed on the exact
  // string: a reason this build has not heard of still means *something* is
  // stale, and saying so beats drawing nothing at all.
  return "its input is newer";
}
