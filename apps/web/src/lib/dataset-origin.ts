/** How a dataset's current version was made (§506; `dataset-preview` p.3).
 *
 * > "About: Information including … any tools and input datasets used to
 * > create the data" (p.3)
 *
 * The API names the tool and the inputs (`services/dataset_provenance.py`);
 * this turns them into the words and links the Details tab shows.
 */

export type DatasetOrigin = {
  version_number: number;
  /** `produced_by_kind`: model, sync, action, action_batch, fork, rollback,
   *  upload, reparse, action_log or join_table. */
  kind: string;
  made_at: string;
  tool: { kind: string; name: string; resource_id: string | null } | null;
  inputs: { name: string; resource_id: string }[];
  note: string | null;
};

/** What a tool is called beside its name. */
export const TOOL_LABELS: Record<string, string> = {
  transform: "Transform",
  sync: "Sync",
  action: "Action",
  listener: "Listener",
};

/** What wrote the version, when no tool can be named: the producer is gone,
 * or the version was not written by a tool at all. */
export function kindText(kind: string): string {
  switch (kind) {
    case "model": return "A transform";
    case "sync": return "A sync";
    case "action": return "An action";
    case "listener": return "A listener";
    case "action_batch": return "A batch of actions";
    case "fork": return "A branch";
    case "rollback": return "A rollback";
    case "reparse": return "A re-parse";
    case "upload": return "An upload";
    // §554's log and §562's join table are made empty, by the platform.
    case "action_log": return "An action log";
    case "join_table": return "A generated join table";
    default: return kind;
  }
}

/** The "Made by" line: the tool by its label and name when there is one,
 * else what kind of thing wrote it. The note is shown beside it, softer. */
export function madeByText(origin: Pick<DatasetOrigin, "kind" | "tool">): string {
  return origin.tool
    ? `${TOOL_LABELS[origin.tool.kind] ?? origin.tool.kind} ${origin.tool.name}`
    : kindText(origin.kind);
}

/** Where a tool or an input opens. */
export function originHref(resourceId: string): string {
  return `/r/${resourceId}`;
}
