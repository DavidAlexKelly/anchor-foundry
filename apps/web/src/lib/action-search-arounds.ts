/** Where an object dropdown's objects come from, the parts a document decides
 * (§333; `action-types` p.34, p.36-37).
 *
 * > "A Search Around would create a new set by traversing a link on every
 * > object in the current set. For example, `Github Issue of Current Employee`
 * > would take the `Employees` in the current set and create a resulting set of
 * > `Github Issues` linked to those `Employees`." (p.37)
 *
 * ---
 *
 * **Nothing here walks anything.** A walk crosses links between objects, and
 * the objects live on the server; the form asks `parameter-choices` what the
 * walk reached and draws that. What is in this file is the editor's side — the
 * choices a panel can offer without guessing, and the sentence that says what a
 * walk does — plus the one thing the form needs, which is already covered by
 * `dropdown_watches` (§332) and so is not here either.
 *
 * **A viewer receives no walk at all** (p.40-41). §331 redacted the filters
 * because a static value is readable by anyone who can read the action type;
 * a walk names object types and link types, and "somebody is offering the
 * Documents linked to this Investigation" is the same combination p.40 is
 * about. So every function here is for the editor, and the running form uses
 * none of them.
 */

import type { ActionSearchAround, ActionSearchAroundHop } from "@platform/types";

export type SearchAround = ActionSearchAround;
export type Hop = ActionSearchAroundHop;

/** A link type as the editor's panel needs to read one. */
export interface LinkType {
  id: string;
  display_name: string;
  from_object_type_id: string;
  to_object_type_id: string;
  from_property?: string | null;
  to_property?: string | null;
}

/** Which object type this link reaches from `here`, or `null` when it does not
 * touch `here` at all.
 *
 * The browser's copy of `object_sets.far_end`, and the only rule duplicated
 * across the two languages in this unit. It is here because the panel has to
 * offer the links that *can* be followed next, and asking the server between
 * two clicks of a dialog would make an editor wait to find out that a link they
 * can see is not one they can pick. The server still decides — `check_source`
 * refuses a hop that does not join up — so this narrows what is offerable
 * rather than being a second authority on it.
 */
export function reaches(link: LinkType, here: string): string | null {
  if (link.from_object_type_id === here) return link.to_object_type_id;
  if (link.to_object_type_id === here) return link.from_object_type_id;
  return null;
}

/** Whether this link can be followed at all.
 *
 * db 0027 lets a link type be defined without a join. There is nothing to
 * follow, so the panel does not offer it — the alternative is a hop somebody
 * picks and the server refuses with a sentence about a column pair.
 */
export function traversable(link: LinkType): boolean {
  return !!(link.from_property && link.to_property);
}

/** Where the walk has arrived after these hops, starting from `startType`.
 *
 * `null` as soon as a hop does not join up, because everything after it is a
 * walk through a link that was not taken. A stored document cannot be in that
 * state — the server refused it — but one being edited is in it constantly:
 * changing the starting type is one click and invalidates every hop below.
 */
export function landsOn(
  source: SearchAround | null | undefined,
  links: LinkType[],
): string | null {
  if (!source?.start?.object_type_id) return null;
  let here = source.start.object_type_id;
  for (const hop of source.hops ?? []) {
    const link = (links ?? []).find((l) => l.id === hop.link_type_id);
    if (!link) return null;
    const next = reaches(link, here);
    if (next === null) return null;
    here = next;
  }
  return here;
}

/** The links a next hop could follow from wherever the walk has reached.
 *
 * Empty when the walk is already broken, rather than every link in the
 * workspace: offering a hop that cannot be added to *this* walk is §214's
 * control that looks like it works.
 */
export function nextHops(
  source: SearchAround | null | undefined,
  links: LinkType[],
): LinkType[] {
  const here = landsOn(source, links);
  if (here === null) return [];
  return (links ?? []).filter(
    (link) => traversable(link) && reaches(link, here) !== null);
}

/** Whether the walk as it stands would be accepted, given what the parameter
 * holds.
 *
 * The panel shows this rather than letting Save produce a 422 several fields
 * later. Not a second authority: the server makes the same check, in the same
 * words, and this exists so that nobody meets it by the obvious route.
 */
export function landsWhereItShould(
  source: SearchAround | null | undefined,
  links: LinkType[],
  objectTypeId: string | null | undefined,
): boolean {
  if (!source) return true;
  if (!objectTypeId) return false;
  return landsOn(source, links) === objectTypeId;
}

/** A blank walk, as "Start somewhere else" leaves it.
 *
 * Starting at the type the parameter already holds, with no hops — which is
 * p.36's default written out, and the one state that is both empty and
 * saveable. Starting somebody at a type the walk cannot land on would be a
 * panel that opens refusing to save (§214).
 */
export function blankSearchAround(objectTypeId: string): SearchAround {
  return { start: { kind: "object_type", object_type_id: objectTypeId }, hops: [] };
}

/** One line describing where a dropdown's objects come from.
 *
 * Reads as p.37 does — the far things of the near thing — so an editor checking
 * their own work sees the sentence rather than the shape.
 */
export function sourceSummary(
  source: SearchAround | null | undefined,
  links: LinkType[],
  typeNames: Record<string, string>,
  labels: Record<string, string>,
): string {
  if (!source?.start) return "Every object of this type";
  const named = (id: string | null) =>
    (id && typeNames?.[id]) || "an object type";
  const start = source.start.kind === "parameter"
    ? `the ${labels?.[source.start.parameter ?? ""]
      || source.start.parameter || "chosen object"} chosen above`
    : `every ${named(source.start.object_type_id)}`;
  const hops = (source.hops ?? []).map((hop) =>
    (links ?? []).find((l) => l.id === hop.link_type_id)?.display_name
    || "a link");
  if (hops.length === 0) return `Start from ${start}`;
  return `Start from ${start}, then follow ${hops.join(", then ")}`;
}

/** What to say when the walk does not end where the parameter holds.
 *
 * Names both ends, because "this is wrong" without them leaves somebody
 * comparing two dropdowns of type names by eye.
 */
export function landingNote(
  source: SearchAround | null | undefined,
  links: LinkType[],
  objectTypeId: string | null | undefined,
  typeNames: Record<string, string>,
): string | null {
  if (landsWhereItShould(source, links, objectTypeId)) return null;
  const here = landsOn(source, links);
  if (here === null) {
    return "This walk does not join up — one of its links does not touch the "
      + "type before it.";
  }
  const reached = typeNames?.[here] || "another type";
  const wanted = (objectTypeId && typeNames?.[objectTypeId]) || "this parameter";
  return `This walk reaches ${reached}, and ${wanted} is what the parameter `
    + "holds. Add or remove a link so it ends there.";
}

/** The parameters a walk may start from: the *object* ones, and not this one.
 *
 * p.36 says an ObjectReference parameter, so a string is not offered — starting
 * from one would treat whatever somebody typed as an object's key. Not this one
 * either, which would make the dropdown walk from the value it is offering. The
 * server refuses both; this is why nobody meets those refusals by the obvious
 * route.
 */
export function startableParameters(
  parameters: { api_name: string; data_type: string; object_type_id?: string | null }[],
  apiName: string,
): { api_name: string; object_type_id: string }[] {
  return (parameters ?? [])
    .filter((p) => p.api_name !== apiName
      && p.data_type === "object" && !!p.object_type_id)
    .map((p) => ({ api_name: p.api_name, object_type_id: p.object_type_id as string }));
}
