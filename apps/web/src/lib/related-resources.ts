/**
 * What is related to the object type being looked at (§603; `ontology-manager`
 * p.30).
 *
 *     "Hovering over the Back home button will also bring up quick links to
 *      recently edited object types, link types, and action types, as well as
 *      all resources that are related to the one you are currently viewing."
 *
 * §317 built the first half in the search box. This is the second, and it
 * lives on the object type's own dialog rather than beside the search: the
 * search box is behind that dialog while it is open, so "the one you are
 * currently viewing" is never on screen at the same time as the box. The
 * dialog is where the question is asked.
 *
 * **Every entry goes somewhere or says why not.** A list of names that cannot
 * be followed is a second copy of facts the dialog already shows; the point of
 * p.30's links is the getting there.
 */
import type {
  ActionType,
  Implementation,
  LinkType,
  ObjectTypeGroupRef,
  ObjectTypeProperty,
} from "./types";

/** Where a related entry opens. Each is a dialog the ontology page already
 * has, so the destination is a kind and an id rather than a URL. */
export type RelatedDestination =
  | { open: "object_type"; id: string }
  | { open: "action_type"; id: string }
  | { open: "interface"; id: string }
  | { open: "shared_property"; id: string }
  | { open: "group"; id: string };

export interface RelatedEntry {
  /** Unique within its section, for a React key and a test id. */
  key: string;
  label: string;
  /** Why it is related, when the label alone does not say. */
  via: string | null;
  /** Null for the one entry that would reopen what is already open. */
  to: RelatedDestination | null;
}

export interface RelatedSection {
  title: string;
  entries: RelatedEntry[];
}

/**
 * The sections, in a fixed order, leaving out the empty ones.
 *
 * **A link type opens the object type at its other end**, not the link: a link
 * type has no dialog of its own on this page, and "what is at the other end of
 * this" is the question a link in this list answers. A link from the type to
 * itself (a manager on an employee) opens nothing, because the destination is
 * the dialog already open, and says so rather than being a button that
 * appears to do nothing.
 *
 * **Shared properties are listed once each** however many of the type's
 * properties use them, which the schema allows and which would otherwise read
 * as two shared properties with one name.
 */
export function relatedResources(
  type: { id: string; properties: readonly Pick<
    ObjectTypeProperty,
    "display_name" | "api_name" | "shared_property_id" | "shared_property_api_name"
  >[] },
  links: readonly LinkType[],
  actions: readonly Pick<ActionType, "id" | "api_name" | "display_name" | "object_type_id">[],
  interfaces: readonly Implementation[],
  groups: readonly ObjectTypeGroupRef[],
): RelatedSection[] {
  const linkEntries: RelatedEntry[] = links
    .filter((l) => l.from_object_type_id === type.id || l.to_object_type_id === type.id)
    .map((l) => {
      const self = l.from_object_type_id === type.id && l.to_object_type_id === type.id;
      const outgoing = l.from_object_type_id === type.id;
      const other = outgoing ? l.to_display_name : l.from_display_name;
      const otherId = outgoing ? l.to_object_type_id : l.from_object_type_id;
      return {
        key: l.id,
        label: l.display_name || l.api_name,
        via: self ? "to itself" : `${outgoing ? "to" : "from"} ${other}`,
        to: self ? null : { open: "object_type" as const, id: otherId },
      };
    });

  const actionEntries: RelatedEntry[] = actions
    .filter((a) => a.object_type_id === type.id)
    .map((a) => ({
      key: a.id,
      label: a.display_name || a.api_name,
      via: null,
      to: { open: "action_type" as const, id: a.id },
    }));

  const interfaceEntries: RelatedEntry[] = interfaces.map((i) => ({
    key: i.interface_id,
    label: i.display_name || i.api_name,
    via: null,
    to: { open: "interface" as const, id: i.interface_id },
  }));

  const shared = new Map<string, RelatedEntry>();
  for (const p of type.properties) {
    if (!p.shared_property_id) continue;
    const seen = shared.get(p.shared_property_id);
    const name = p.display_name || p.api_name;
    if (seen) {
      seen.via = `${seen.via}, ${name}`;
      continue;
    }
    shared.set(p.shared_property_id, {
      key: p.shared_property_id,
      label: p.shared_property_api_name ?? p.api_name,
      via: `as ${name}`,
      to: { open: "shared_property", id: p.shared_property_id },
    });
  }

  const groupEntries: RelatedEntry[] = groups.map((g) => ({
    key: g.id,
    label: g.display_name || g.api_name,
    via: null,
    to: { open: "group" as const, id: g.id },
  }));

  return [
    { title: "Link types", entries: linkEntries },
    { title: "Action types", entries: actionEntries },
    { title: "Interfaces", entries: interfaceEntries },
    { title: "Shared properties", entries: [...shared.values()] },
    { title: "Groups", entries: groupEntries },
  ].filter((s) => s.entries.length > 0);
}
