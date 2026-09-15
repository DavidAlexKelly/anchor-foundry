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
