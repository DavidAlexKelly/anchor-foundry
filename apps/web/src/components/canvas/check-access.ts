/** The Check access panel's reading of one answer (`workshop` p.92).
 *
 * > "You can use the Check access panel in the sidebar to easily check a
 * > user's access on a Workshop module. This will show if they meet the access
 * > requirement on the Workshop module, as well as additional data
 * > requirements to see object types, link types, action types, and
 * > functions." (p.92)
 *
 * The server decides; this turns its answer into the sentences a builder
 * reads. Kept out of the component so the wording of a refusal is testable —
 * the panel's whole value is in being read correctly under pressure, and
 * "cannot open" appearing where "can open but cannot act" belongs is the one
 * mistake that would send somebody to change the wrong setting.
 */

export type AccessStatus = "visible" | "unusable" | "hidden" | "unknown";

export type AccessResource = {
  kind: string;
  id: string;
  name: string | null;
  status: AccessStatus;
};

export type ModuleAccess = {
  user: { id: string; email: string; display_name: string; active: boolean };
  workspace_role: string | null;
  project_role: string | null;
  can_open: boolean;
  can_edit: boolean;
  resources: AccessResource[];
};

/** p.92's kinds, in p.92's order. Functions are the fourth and this platform
 * has none, which the panel says once rather than leaving a reader to wonder
 * whether the check ran. */
export const KINDS = [
  { kind: "object_type", label: "Object types" },
  { kind: "link_type", label: "Link types" },
  { kind: "action_type", label: "Action types" },
] as const;

/** What each state means, in the second person, because the builder is going
 * to paste one of these to the person it is about. */
export const STATUS_LABELS: Record<AccessStatus, string> = {
  visible: "Can use",
  unusable: "Can see, cannot run",
  hidden: "No access",
  unknown: "Not found",
};

/** Whether a state is a requirement met. `unusable` is not: the widget draws
 * and the button refuses, which is p.92's whole warning. */
export function met(status: AccessStatus): boolean {
  return status === "visible";
}

/** Every requirement this user does not meet.
 *
 * `unknown` is in here and it is not a complaint about the user — a reference
 * to something deleted is met by nobody, and leaving it out of the shortfall
 * would let a module with a dangling widget report itself entirely fine. */
export function shortfalls(resources: AccessResource[]): AccessResource[] {
  return resources.filter((r) => !met(r.status));
}

/** What to call a resource. The id is the fallback rather than the label,
 * because a uuid tells a reader nothing and only appears when nobody involved
 * could name the thing. */
export function label(resource: AccessResource): string {
  return resource.name ?? resource.id;
}

export function byKind(resources: AccessResource[]): AccessResource[] {
  const order = new Map(KINDS.map((k, i) => [k.kind as string, i]));
  return [...resources].sort((a, b) => {
    const ka = order.get(a.kind) ?? KINDS.length;
    const kb = order.get(b.kind) ?? KINDS.length;
    if (ka !== kb) return ka - kb;
    return label(a).localeCompare(label(b));
  });
}

/** p.92's first half, as a sentence.
 *
 * Three outcomes rather than two, because "can edit" and "can open" are
 * different answers to a builder deciding whether to share a link or grant a
 * role, and collapsing them would make the panel say "has access" about
 * somebody who cannot change a thing.
 */
export function moduleVerdict(access: ModuleAccess): string {
  // **Before the roles, because it outranks them.** A disabled account is
  // refused at authentication, so every role it still holds is a role it
  // cannot use. Reading those roles out as access would tell a builder that
  // somebody who cannot sign in can open the module.
  if (!access.user.active) return "This account is disabled";
  if (access.can_edit) return "Can open and edit this module";
  if (access.can_open) return "Can open this module, and not edit it";
  return "Cannot open this module";
}

/** Why the module half came out the way it did.
 *
 * Named roles, not a retelling of the rule: a builder who reads "no role on
 * this project, and the module is not published" knows both of the two things
 * they could change. "No access" tells them neither. */
export function moduleReason(access: ModuleAccess): string {
  // The roles are still worth naming for a disabled account: they are what it
  // would have on being re-enabled, which is the question a builder looking at
  // one is about to ask.
  const where = access.project_role
    ? `${access.project_role} on this project`
    : access.workspace_role
      ? `no role on this project, ${access.workspace_role} on the workspace`
      : "no role on this workspace";
  if (access.can_open && !access.project_role) {
    return `${where} — they reach it because it is published`;
  }
  return where;
}

/** The one line a builder acts on.
 *
 * A count of what is wrong, not a verdict on the person: "2 of 5 requirements
 * unmet" sends them to the list, and the list names which two.
 */
export function summary(access: ModuleAccess): string {
  const total = access.resources.length;
  const missing = shortfalls(access.resources).length;
  if (total === 0) return "This module needs no ontology access.";
  if (missing === 0) {
    return `Meets all ${total} data ${total === 1 ? "requirement" : "requirements"}.`;
  }
  return `${missing} of ${total} data requirements unmet.`;
}

/** p.92 names functions fourth and this platform has none. Said in the panel
 * rather than silently omitted: a missing row reads as a check that passed. */
export const NO_FUNCTIONS =
  "Functions are not checked: this platform has none.";
