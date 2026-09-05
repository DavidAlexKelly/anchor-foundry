/** Workshop routing: what the URL says about a running module (p.195–199).
 *
 * > "Workshop routing enables specific states or views of a module to be
 * > written to the URL, allowing users to easily share these views with others
 * > through link sharing." (p.195)
 *
 * **This is the outbound half only.** p.198 ends with a rule pointing the
 * other way — "If a query parameter key matches the external ID of a module
 * interface variable, the value of the query parameter will be used as the
 * variable's initial value, **regardless of URL inclusion behavior
 * configured**" — and that is `seedFromQuery` in `pure.ts`, which is not gated
 * on any of this. Two directions, two rules, deliberately not one setting that
 * would have to mean both: a link somebody types by hand should work against a
 * module whose author never turned routing on.
 *
 * Its own module rather than more of `pure.ts` because it needs the layout
 * walk, and because keeping the two directions in separate files is the
 * cheapest way to keep noticing that they are separate rules. Same boundary
 * though: no React, no DOM, nothing rendered.
 */
import { referencesOf } from "../../lib/workshop-module";

/** The query parameter carrying the current page (p.197).
 *
 * A fixed name rather than a configurable one. It shares a namespace with
 * every routed variable's external ID, and `EXTERNAL_ID_RE` allows `page`, so
 * a module with a variable called `page` has a collision — the page wins,
 * because it is written last, and this is the one reserved word.
 */
export const PAGE_PARAM = "page";

/** Kinds a value can travel in the URL as.
 *
 * Mirrors `ROUTABLE_KINDS` in `services/workshop_variables.py`, which is what
 * actually refuses a save; this copy only decides what the builder offers and
 * what gets written. It is the same list as `coerce`'s vocabulary in `pure.ts`
 * on purpose — a kind is routable exactly when the URL can be read back into
 * it. */
export const ROUTABLE_KINDS = ["string", "number", "boolean", "date", "timestamp"];

export type RoutingVariable = {
  id: string;
  kind: string;
  default?: unknown;
  external_id?: string | null;
  interface?: unknown;
  url_behavior?: string;
};

type LayoutNode = {
  type?: { resolvedName?: unknown };
  props?: Record<string, unknown>;
  nodes?: unknown;
  linkedNodes?: Record<string, unknown>;
};

const PAGE_NAME = "CanvasPage";

function resolvedName(node: LayoutNode | undefined): string | null {
  const name = node?.type?.resolvedName;
  return typeof name === "string" ? name : null;
}

/** Which variables are bound by widgets inside one page (p.198's "used in a
 * widget or layout that appears in the current view").
 *
 * **Descends the tree rather than scanning every node**, because that is what
 * "in the current view" means: a filter on page two is not on screen, and a
 * URL that carried its value would share a view the recipient does not get.
 * Linked nodes count — a widget inside a Tabs panel is still on this page —
 * and the page node's own props count too.
 *
 * A missing or unknown page id yields an empty set: nothing is on screen that
 * we can prove is on screen, and `when_visible` erring towards *out* of the
 * URL is the direction that cannot leak a value into a link.
 */
export function variablesOnPage(layout: unknown, pageNodeId: string | null): Set<string> {
  const found = new Set<string>();
  if (!layout || typeof layout !== "object" || !pageNodeId) return found;
  const nodes = layout as Record<string, LayoutNode>;
  if (!nodes[pageNodeId]) return found;

  const seen = new Set<string>();
  const walk = (nodeId: string) => {
    // A cycle cannot happen in a well-formed Craft.js tree, and this walk is
    // over a document that arrived from anywhere. An infinite loop here would
    // hang the viewer, which is a worse answer than a partial one.
    if (seen.has(nodeId)) return;
    seen.add(nodeId);
    const node = nodes[nodeId];
    if (!node) return;
    for (const { ref } of referencesOf(node.props)) found.add(ref);
    const children = Array.isArray(node.nodes) ? node.nodes : [];
    for (const child of children) if (typeof child === "string") walk(child);
    for (const child of Object.values(node.linkedNodes ?? {})) {
      if (typeof child === "string") walk(child);
    }
  };
  walk(pageNodeId);
  return found;
}

/** Whether a variable's value differs from where it started.
 *
 * p.198 says "the value is not the variable's default value" for both
 * inclusion behaviours, and the reason is the length of the link: a module
 * with twenty routed variables would otherwise put all twenty in the address
 * bar before anybody touched anything.
 *
 * Compared by JSON rather than by `===` so that a value which arrived through
 * a round trip still matches the default it equals. `undefined`, `null` and
 * `""` are one state here — "nothing chosen" — because a control that has been
 * cleared writes one and a variable that was never set holds another.
 */
function chosen(value: unknown, fallback: unknown): boolean {
  const empty = (v: unknown) => v === undefined || v === null || v === "";
  if (empty(value)) return false;
  if (empty(fallback)) return true;
  return JSON.stringify(value) !== JSON.stringify(fallback);
}

/** What the URL should say about this module right now (p.197–198).
 *
 * The whole rule in one place, returning parameters rather than writing them,
 * so the decision is testable without a router.
 *
 * **Routing off means an empty answer, not a partial one** (p.195: the whole
 * feature is behind one toggle). A module whose author has not enabled routing
 * must not put anything in the address bar, whatever its variables say — those
 * settings are configuration for a feature that is off.
 */
export function routingParams(input: {
  enabled: boolean;
  variables: Record<string, RoutingVariable>;
  values: Record<string, unknown>;
  /** The author-set ID of the current page, or null when it has none. p.197:
   * "For pages without a defined page ID, no page ID will be written to the
   * URL; users will be returned to the module's default page on page load." */
  pageId?: string | null;
  /** Variable ids bound by widgets on the current page — `variablesOnPage`. */
  visible?: Set<string>;
}): Record<string, string> {
  const out: Record<string, string> = {};
  if (!input.enabled) return out;

  const visible = input.visible ?? new Set<string>();
  for (const variable of Object.values(input.variables)) {
    const behavior = variable.url_behavior ?? "never";
    if (behavior !== "always" && behavior !== "when_visible") continue;
    // The same three conditions the server refuses a save for, applied again
    // rather than assumed: a document can arrive from anywhere, and a viewer
    // is the wrong person to find out that one did.
    if (!variable.external_id || !variable.interface) continue;
    if (!ROUTABLE_KINDS.includes(variable.kind)) continue;
    if (behavior === "when_visible" && !visible.has(variable.id)) continue;
    const value = input.values[variable.id];
    if (!chosen(value, variable.default)) continue;
    out[variable.external_id] = String(value);
  }

  if (input.pageId) out[PAGE_PARAM] = input.pageId;
  return out;
}

/** The author-set ID of one page node, or null when it has none.
 *
 * **Author-set, not the node id.** A Craft.js node id is generated and means
 * nothing to whoever writes or reads a link, and it changes when a page is
 * recreated — so a link built from one would expire for a reason nobody could
 * see. p.197's "pages without a defined page ID" is exactly this: a page
 * nobody has named has nothing to put in the URL.
 */
export function pageIdOf(layout: unknown, nodeId: string | null): string | null {
  if (!layout || typeof layout !== "object" || !nodeId) return null;
  const node = (layout as Record<string, LayoutNode>)[nodeId];
  const raw = node?.props?.pageId;
  return typeof raw === "string" && raw.trim() ? raw.trim() : null;
}

/** The page a module opens on when nothing names one.
 *
 * The **first** `CanvasPage` under ROOT, which is `CanvasPage`'s own rule for
 * which page shows before anybody navigates ("the layout decides which page is
 * first"). Read here rather than assumed so that the URL and the render agree
 * about what "the default page" means — two answers to that would put a page
 * ID in the address bar for a page the reader is not looking at.
 */
export function defaultPageNode(layout: unknown): string | null {
  if (!layout || typeof layout !== "object") return null;
  const nodes = layout as Record<string, LayoutNode>;
  const children = Array.isArray(nodes.ROOT?.nodes) ? nodes.ROOT.nodes : [];
  for (const child of children) {
    if (typeof child === "string" && resolvedName(nodes[child]) === PAGE_NAME) return child;
  }
  return null;
}

/** The page node one URL page ID names, or null for "the default page".
 *
 * Null covers three cases on purpose, and p.197 gives them all the same
 * answer — "users will be returned to the module's default page on page load":
 * no page ID in the link, a page ID nobody has assigned, and a page ID that
 * *was* assigned to a page since deleted. A link that outlived its page should
 * open the module, not an error.
 */
export function pageNodeFor(layout: unknown, pageId: string | null): string | null {
  if (!layout || typeof layout !== "object" || !pageId) return null;
  for (const [nodeId, node] of Object.entries(layout as Record<string, LayoutNode>)) {
    if (resolvedName(node) !== PAGE_NAME) continue;
    if (pageIdOf(layout, nodeId) === pageId) return nodeId;
  }
  return null;
}

/** p.165's **Open Workshop module**: the query that carries this module's
 * values into another module's interface.
 *
 * > "The Open Workshop module event can be used to avoid manually creating a
 * > URL… The selected module's interface will appear, allowing variable values
 * > to be passed from the current module to the chosen module's interface
 * > variables. When the event is called, the URL uses the current value to open
 * > the selected module." (p.165)
 *
 * **The URL it avoids is the one `queryFor` writes and `seedFromQuery` reads**,
 * so this builds the same shape rather than a second one: one parameter per
 * external ID, the value stringified the same way. p.165 spells the manual form
 * out immediately below that sentence (`?interfaceVariable=123`), which is what
 * makes "the same shape" a requirement rather than a convenience.
 *
 * A mapping whose variable holds nothing is **left out**. p.165 says the URL
 * uses "the current value", and a parameter carrying an empty string is not the
 * absence of a value — it would arrive at the target as a deliberate blank and
 * override the default the target declares, which is the one thing an unset
 * variable must not do.
 */
export function interfaceQuery(
  mapping: Record<string, string> | null | undefined,
  values: Record<string, unknown>,
): Record<string, string> {
  const out: Record<string, string> = {};
  if (!mapping || typeof mapping !== "object") return out;
  for (const [externalId, source] of Object.entries(mapping)) {
    if (!externalId || typeof source !== "string" || !source) continue;
    const value = values[source];
    // `chosen(value, undefined)` is "has a value at all" - the same emptiness
    // rule the URL writer uses, rather than a second opinion about what counts.
    if (!chosen(value, undefined)) continue;
    out[externalId] = String(value);
  }
  return out;
}
