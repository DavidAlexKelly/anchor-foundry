/** `object-views` p.37-41's panel Object Views, and Workshop p.263's panel
 * behaviours (§694).
 *
 * > "There are two types of configured panel Object Views you can build to
 * > display one or multiple objects of an object type: object instance panels
 * > display individual objects, while object set panels display multiple
 * > objects as an object set." (p.41)
 *
 * > "The default object instance panel view shows a single Property List
 * > widget that displays prominent properties of a single instance of the
 * > object type." (p.41)
 *
 * > "The default object set panel provides a tabbed layout with two
 * > interfaces to explore object collections: The Charts tab displays up to
 * > five XY Charts that visualize object aggregations grouped by property
 * > values. The List tab shows an Object List widget displaying up to three
 * > properties per object, including the object's title, prominent
 * > properties, and media when present." (p.41)
 */

interface Property {
  id?: string;
  api_name: string;
  data_type: string;
  visibility?: string;
}

/** p.41's "up to five". */
export const PANEL_CHARTS = 5;
/** p.41's "up to three properties per object". */
export const PANEL_LIST_PROPERTIES = 3;

/** The properties a set panel's Charts tab groups by: "grouped by property
 * values", so categories - text and yes/no - and not the title, which is
 * one value per object and so a bar per object. Prominent first, hidden
 * never. */
export function panelChartProperties<P extends Property>(
  properties: readonly P[], titleId: string | null | undefined,
  keys: readonly string[] = [],
): P[] {
  const candidates = properties.filter((p) => p.visibility !== "hidden" && p.id !== titleId
    && !keys.includes(p.api_name) && (p.data_type === "string" || p.data_type === "boolean"));
  const prominent = candidates.filter((p) => p.visibility === "prominent");
  const rest = candidates.filter((p) => p.visibility !== "prominent");
  return [...prominent, ...rest].slice(0, PANEL_CHARTS);
}

/** The properties that hold each object's own key, as a type's key column
 * mapped as a property does: in every row given, its value is the row's
 * primary key. Grouped by, it is a bar per object, which is the title's
 * reason for not being charted. None from no rows, since nothing says so. */
export function keyProperties(
  rows: readonly { primary_key: string; properties: Record<string, unknown> }[],
  properties: readonly { api_name: string }[],
): string[] {
  if (rows.length === 0) return [];
  return properties.map((p) => p.api_name).filter((name) =>
    rows.every((row) => String(row.properties[name] ?? "") === row.primary_key));
}

/** What the List tab draws for each object, besides its title: its media
 * when it has some, then its prominent properties, to p.41's three in all
 * with the title counted. */
export function panelListProperties<P extends Property>(
  properties: readonly P[], titleId: string | null | undefined,
): P[] {
  const shown = properties.filter((p) => p.visibility !== "hidden" && p.id !== titleId);
  const media = shown.filter((p) => p.data_type === "attachment");
  const prominent = shown.filter((p) => p.visibility === "prominent" && p.data_type !== "attachment");
  return [...media, ...prominent].slice(0, PANEL_LIST_PROPERTIES - 1);
}

/** Workshop p.263's Panel behavior. */
export const PANEL_BEHAVIORS = {
  instance: "Object instance",
  adaptive: "Adaptive",
  set: "Object set",
} as const;
export type PanelBehavior = keyof typeof PANEL_BEHAVIORS;

export function panelBehaviorOf(raw: unknown): PanelBehavior {
  return raw === "adaptive" || raw === "set" ? raw : "instance";
}

/** > "Object instance: Always displays the first object of the input object
 * > set as a single object view, regardless of the object count. Adaptive:
 * > … When the object set contains exactly one object, it displays the object
 * > instance view. When the object set contains zero or multiple objects, it
 * > displays the object set view. Object set: Always displays the object set
 * > view, regardless of the object count." (p.263) */
export function panelShows(behavior: PanelBehavior, total: number): "instance" | "set" {
  if (behavior === "instance") return "instance";
  if (behavior === "set") return "set";
  return total === 1 ? "instance" : "set";
}

/** Workshop p.261's Form factor. */
export const FORM_FACTORS = { full: "Full", panel: "Panel" } as const;
export type FormFactor = keyof typeof FORM_FACTORS;

export function formFactorOf(raw: unknown): FormFactor {
  return raw === "panel" ? "panel" : "full";
}

/** The three views a type may configure (§744; `object-views` p.35, p.41-42):
 * the full view, p.41's object instance panel and its object set panel. The
 * editor's form factor, and the server's `object_view_form_factor`. */
export const VIEW_FORMS = {
  full: "Full",
  panel: "Panel · object instance",
  panel_set: "Panel · object set",
} as const;
export type ViewForm = keyof typeof VIEW_FORMS;

export function viewFormOf(raw: unknown): ViewForm {
  return typeof raw === "string" && Object.hasOwn(VIEW_FORMS, raw) ? raw as ViewForm : "full";
}

/** What a view of this form receives: one object, or the set (p.41). */
export function subjectKindOf(form: ViewForm): "single_object" | "object_set" {
  return form === "panel_set" ? "object_set" : "single_object";
}
