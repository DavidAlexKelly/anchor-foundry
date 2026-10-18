/** The search at the top of a workspace's pages (§990): which workspace a
 * page is in, what a hit says, and the keys. */
import type { SearchHit } from "./types";

/** First path segments under the platform that are not a workspace. */
const NOT_A_WORKSPACE = new Set(["home", "org"]);

/** The workspace slug a page's path is in, or undefined. */
export function workspaceOf(pathname: string): string | undefined {
  const first = pathname.split("/").filter(Boolean)[0];
  return first && !NOT_A_WORKSPACE.has(first) ? first : undefined;
}

const KINDS: Record<string, string> = {
  connection: "Source",
  dataset: "Dataset",
  model: "Transform",
  object_type: "Object type",
  canvas_app: "Module",
  code_repo: "Repository",
};

export function kindLabel(kind: string): string {
  return KINDS[kind] ?? kind;
}

/** Where a hit lives, in words. */
export function whereText(hit: Pick<SearchHit, "project_name">): string {
  return hit.project_name ?? "the workspace";
}

/** Every resource opens by its id, whichever project it is in (§80). */
export function hitHref(hit: Pick<SearchHit, "id">): string {
  return `/r/${hit.id}`;
}

/** Whether a key press asks for the search: `/`, as on most sites, unless
 * somebody is typing somewhere already. */
export function focusesSearch(event: {
  key: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean;
  target?: { tagName?: string; isContentEditable?: boolean } | null;
}): boolean {
  if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return false;
  const tag = event.target?.tagName?.toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return false;
  return !event.target?.isContentEditable;
}

/** The highlight after an arrow, wrapping; -1 for none. */
export function step(current: number, count: number, by: 1 | -1): number {
  if (count === 0) return -1;
  if (current < 0) return by === 1 ? 0 : count - 1;
  return (current + by + count) % count;
}

/** The Object Explorer, asked the same words (§991): objects are found there,
 * by their properties, not here by a resource's name. */
export function objectsHref(workspaceSlug: string, query: string): string {
  return `/${workspaceSlug}/explore?q=${encodeURIComponent(query)}`;
}
