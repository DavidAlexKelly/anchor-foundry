/** The audit log page's wording and query (§988). */
import type { AuditEntry } from "./types";

/** One page: enough to read, few enough to send at once. */
export const AUDIT_PAGE = 50;

export interface AuditFilters {
  action: string;
  userId: string;
  resourceId: string;
  /** Days, as the date inputs give them: `YYYY-MM-DD`. */
  since: string;
  until: string;
}

export const NO_FILTERS: AuditFilters = { action: "", userId: "", resourceId: "", since: "", until: "" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** What a resource id that is not one says, before anything is asked. */
export function filterProblem(filters: AuditFilters): string {
  const id = filters.resourceId.trim();
  if (id && !UUID.test(id)) return "A resource is named by its id, which looks like 3f2a…-…";
  if (filters.since && filters.until && filters.until < filters.since) {
    return "The end of the span is before its start.";
  }
  return "";
}

/** The API's query for these filters and a page after `beforeId`. A day's
 * `until` is the whole day: up to the start of the next. */
export function auditQuery(filters: AuditFilters, beforeId?: number): string {
  const q = new URLSearchParams({ limit: String(AUDIT_PAGE) });
  if (filters.action.trim()) q.set("action", filters.action.trim());
  if (filters.userId) q.set("user_id", filters.userId);
  if (filters.resourceId.trim()) q.set("resource_id", filters.resourceId.trim());
  if (filters.since) q.set("since", `${filters.since}T00:00:00Z`);
  if (filters.until) {
    const next = new Date(`${filters.until}T00:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    q.set("until", next.toISOString());
  }
  if (beforeId !== undefined) q.set("before_id", String(beforeId));
  return q.toString();
}

/** The cursor for the page after this one; undefined when this was the last. */
export function nextCursor(page: readonly AuditEntry[]): number | undefined {
  const last = page[page.length - 1];
  return page.length === AUDIT_PAGE && last ? last.id : undefined;
}

/** Who did it: a person by name and address, or the platform itself. */
export function actorText(entry: Pick<AuditEntry, "actor_name" | "actor_email">): string {
  if (!entry.actor_email) return "the platform";
  return entry.actor_name && entry.actor_name !== entry.actor_email
    ? `${entry.actor_name} (${entry.actor_email})`
    : entry.actor_email;
}

/** Where from, as much as was recorded. */
export function originText(entry: Pick<AuditEntry, "ip_address" | "user_agent">): string {
  if (!entry.ip_address) return "not recorded";
  return entry.user_agent ? `${entry.ip_address} · ${entry.user_agent}` : entry.ip_address;
}
