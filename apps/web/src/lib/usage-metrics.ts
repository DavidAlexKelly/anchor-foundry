/**
 * What a type's usage numbers say (§320; `ontology-manager` p.32-34).
 *
 *     "Reads… Writes… Interactions: The total number of reads and writes on
 *      objects of this type over the last 30 days. Active users: The number of
 *      unique user IDs that triggered the reads and writes recorded over the
 *      last 30 days." (p.32)
 *
 *     "A usage graph on the Overview tab: High-level summary of usage over the
 *      last 30 days, **enabling Ontology users to quickly understand the
 *      implications of making a breaking change to this resource**." (p.33)
 *
 * That last clause is the whole design brief, and it is why this file exists
 * rather than the numbers being formatted where they are drawn. The panel is
 * not a dashboard: it is read by somebody with their hand on a rename, and the
 * only thing it has to do is turn four integers into a sentence about whether
 * to go ahead.
 *
 * The server counts; this decides what the counts *mean*. Same division as
 * `object-type-issues.ts`.
 */
import type { ObjectTypeUsage, ObjectTypeUsageByApplication } from "./types";

/**
 * p.33's "No usage for the last 30 days".
 *
 * **A sentence, not an absent panel.** A screen that simply drew nothing would
 * be indistinguishable from one that failed to load — and p.33 attaches a
 * warning to exactly this state ("it's possible that internal tables may not
 * have been configured"), which means Foundry expects people to see it and
 * wonder. Ours can be definite: the number is zero because nobody used it.
 */
export function isUnused(usage: ObjectTypeUsage): boolean {
  return usage.interactions === 0;
}

export function emptyMessage(usage: ObjectTypeUsage): string {
  return `No usage in the last ${usage.window_days} days.`;
}

/**
 * The one-line summary, in the order p.33's reader needs it.
 *
 * **People first, then interactions.** p.32 lists reads, writes, interactions,
 * active users in that order, and that is the order they are *defined* in, not
 * the order they are useful in. Somebody deciding whether a rename is safe
 * needs to know how many people would notice before they need to know how
 * many times; thirty reads by one person and thirty by thirty people are the
 * same `reads` and a completely different answer.
 */
export function headline(usage: ObjectTypeUsage): string {
  if (isUnused(usage)) return emptyMessage(usage);
  return (
    `${count(usage.active_users, "person", "people")} and ` +
    `${count(usage.interactions, "interaction", "interactions")} ` +
    `in the last ${usage.window_days} days.`
  );
}

/**
 * Whether this type is used enough that a breaking change needs a plan.
 *
 * **Deliberately not a threshold on interactions.** A nightly job reading a
 * type ten thousand times is one caller to fix; two people using it by hand is
 * two conversations to have, and the second is the harder change. p.33 frames
 * the whole feature as understanding "the implications of making a breaking
 * change", so the question is how many *parties* are involved.
 */
export function hasAudience(usage: ObjectTypeUsage): boolean {
  return usage.active_users > 1;
}

/** Reads plus writes, said once, so a caller never re-derives it. */
export function share(row: ObjectTypeUsageByApplication): number {
  return row.interactions;
}

/**
 * What one application's row says.
 *
 * **Writes are named separately when there are any**, because they are the
 * half that makes a change dangerous: an application that only reads a type
 * breaks visibly at the next deploy, and one that writes it can be corrupting
 * data against a shape that has moved.
 */
export function applicationSummary(row: ObjectTypeUsageByApplication): string {
  if (row.writes === 0) {
    return `${count(row.reads, "read", "reads")}`;
  }
  return (
    `${count(row.reads, "read", "reads")}, ` +
    `${count(row.writes, "write", "writes")}`
  );
}

/**
 * How an application's name reads.
 *
 * The server stores whatever the caller said (`ontology-manager` p.33's "in
 * which Foundry applications"), and an application nobody has a label for is
 * shown **as it was recorded** rather than as "Unknown": a row labelled
 * `some_screen` is a screen somebody can go and look for, and a row labelled
 * "Unknown" is one nobody can.
 */
export const APPLICATION_LABELS: Record<string, string> = {
  explorer: "Object Explorer",
  object_view: "Object views",
  workshop: "Workshop",
  action: "Actions",
  api: "API",
};

export function applicationLabel(application: string): string {
  return APPLICATION_LABELS[application] ?? application;
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}
