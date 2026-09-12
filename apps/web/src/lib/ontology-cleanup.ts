/**
 * What a cleanup flag tells the reader (§325; `ontology-manager` p.68-74).
 *
 *     "The Ontology cleanup tool is a safe way to delete object types… The
 *      tool aims to help Ontology editors determine the safety of deleting an
 *      object type and provides a deprecation option which informs object type
 *      users of its future removal." (p.68)
 *
 *     "By default, the table is sorted by the highest priority among the flags
 *      that an object type triggers." (p.70)
 *
 * The server decides what is true; this decides what it means. Same division as
 * `action-metrics.ts` and `usage-metrics.ts`.
 *
 * **The flags are evidence, and the wording keeps them that way.** p.68 says
 * the tool "aims to help… determine the safety of deleting an object type" —
 * so nothing here says "safe to delete". Every line below says what is *true*
 * about the type and leaves the decision where p.71 puts it, on the three
 * buttons the editor presses.
 */
import type { CleanupCandidate } from "./types";

/** One flag's name and the sentence under it. */
export const FLAG_LABELS: Readonly<
  Record<string, { label: string; hint: string }>
> = {
  past_deprecation: {
    label: "Deprecation overdue",
    hint: "Deprecated, and the deadline somebody set has passed.",
  },
  unused: {
    label: "Nobody used it",
    hint: "No reads or writes in the last 30 days.",
  },
  no_source: {
    label: "No dataset",
    hint: "Nothing is mapped to it, so it has no data behind it.",
  },
  failing_source: {
    label: "Sync failing",
    hint: "A mapping is erroring, so its objects are going stale.",
  },
  stale_source: {
    label: "Not synced lately",
    hint: "No mapping has synced in the last 30 days.",
  },
  name_looks_temporary: {
    label: "Marked temporary",
    hint: "The name carries [test] or [deprecated].",
  },
  no_description: {
    label: "No description",
    hint: "Nobody wrote down what this type is for.",
  },
};

/**
 * A flag's name for the screen.
 *
 * **An unknown flag reads as itself rather than vanishing**, the same rule as
 * `action-metrics.ts`'s categories: p.73 says the list "is not exhaustive", so
 * one added on the server and not here would otherwise drop a row's only
 * explanation while leaving it in a list of deletion candidates.
 */
export function flagLabel(flag: string): string {
  const known = FLAG_LABELS[flag];
  if (known) return known.label;
  const words = flag.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : flag;
}

export function flagHint(flag: string): string {
  return FLAG_LABELS[flag]?.hint ?? "";
}

/**
 * The one line a row leads with.
 *
 * p.70 sorts by the worst flag, so the worst flag is what the row should say
 * first — a row whose headline was "No description" while it was really in the
 * list for an overdue deprecation would bury the reason it is there.
 *
 * The server sends `flags` already in priority order, so this takes the first
 * rather than re-ranking: a second ranking here is free to disagree with the
 * one that decided the row's position, and then the list's order and its
 * headlines would tell different stories (§146).
 */
export function headline(candidate: CleanupCandidate): string {
  const worst = candidate.flags[0];
  return worst ? flagLabel(worst) : "No flags";
}

/**
 * How many other things are wrong, for the row's second line.
 *
 * Counted rather than listed, because p.70's table is scanned: the worst flag
 * is the headline and "and 3 more" is enough to know whether opening the row
 * is worth it.
 */
export function alsoCount(candidate: CleanupCandidate): number {
  return Math.max(0, candidate.flags.length - 1);
}

export function alsoText(candidate: CleanupCandidate): string {
  const more = alsoCount(candidate);
  if (more === 0) return "";
  // There was a `more === 1 ? "and 1 more" : …` here and the sweep was right to
  // survive without it: the template produces "and 1 more" for one anyway, so
  // the branch could not change an answer. `snoozeText`'s plural *is* a real
  // branch — "Back tomorrow" is a different sentence from "Back in 1 days" —
  // which is why that one stayed and this one went (§213).
  return `and ${more} more`;
}

/**
 * Whether this type still has objects anybody touched.
 *
 * **The one number that argues against deleting**, and it is drawn even when
 * the type is flagged for other reasons: a type with no description and no
 * source that four hundred people still read is not a cleanup candidate, it is
 * a documentation problem.
 */
export function stillInUse(candidate: CleanupCandidate): boolean {
  return candidate.interactions > 0;
}

/**
 * What the queue says when it is empty.
 *
 * **"Nothing to clean up" rather than a blank table.** An empty list and a
 * list that failed to load look identical, and this is a screen somebody opens
 * expecting to find work — silence reads as the tool being broken.
 */
export const NOTHING_TO_DO =
  "Nothing here needs cleaning up. Every object type has a description, a "
  + "dataset behind it, and somebody using it.";

/**
 * How a snooze reads once it is set.
 *
 * The date, not "snoozed": p.71 makes the snooze "for a configurable amount of
 * time", so when it comes back is the whole fact, and a reader who snoozed
 * something twice wants to see which date won.
 */
export function snoozeText(until: string | null, now: Date = new Date()): string {
  if (!until) return "";
  const when = new Date(until);
  if (Number.isNaN(when.getTime())) return "";
  const days = Math.ceil((when.getTime() - now.getTime()) / 86_400_000);
  if (days <= 0) return "Back now";
  return days === 1 ? "Back tomorrow" : `Back in ${days} days`;
}

/**
 * The confirmation a delete asks for.
 *
 * **Names the type and says what goes with it.** p.71: "Delete object types
 * from the Ontology **and remove associated data from object storage**" — a
 * dialog that said only "Delete this object type?" would understate what the
 * button does, and this is the one action on p.71 that cannot be undone.
 */
export function deleteWarning(candidate: CleanupCandidate): string {
  const used = stillInUse(candidate)
    ? ` It has had ${candidate.interactions} interactions in the last 30 days.`
    : "";
  return (
    `Delete ${candidate.display_name} and remove its objects from storage? `
    + `This cannot be undone.${used}`
  );
}
