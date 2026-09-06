/**
 * The inbox, browser side (Foundry `action-types` p.91; §257).
 *
 * §257 built the delivery. This is the small amount a screen has to decide for
 * itself, and it is two things — how the badge reads, and whether a link in a
 * notification may be followed at all.
 *
 * **The link is the interesting one, and it is a safety rule rather than a
 * display one.** p.91 lets a notification carry a link with a button, and
 * p.92's triple handlebars mean the URL is a *template* — so part of it comes
 * from a property value, which comes from a dataset, which comes from
 * somewhere. A notification is the one surface in this platform where somebody
 * else's data is rendered as a control the recipient is invited to click. An
 * `https://` or a `javascript:` reaching that button would make an action
 * type into a way to send phishing links to colleagues.
 *
 * `safeReturnPath` already encodes exactly the rule this needs — same-origin
 * paths only, and not the protocol-relative `//host` that the browser reads as
 * a host — so this reuses it rather than writing a second copy of a security
 * check (§213). The two are the same question asked about different strings.
 *
 * Relative times are `value-format`'s, for the same reason: p.94's "8 minutes
 * ago" is already implemented and a second renderer would eventually disagree
 * with the first about what "yesterday" means.
 */

import { safeReturnPath } from "./auth";

/** How many the badge will spell out before it gives up counting.
 *
 * Nine, so the badge is never wider than two characters — the number stops
 * being information long before that anyway: somebody with 47 unread
 * notifications and somebody with 9+ do the same thing next. */
export const BADGE_CAP = 9;

/** The badge, or null when there is nothing to say.
 *
 * **Null rather than "0".** A badge showing zero is a mark on every screen
 * that means "nothing has happened", which is the one message it does not need
 * to deliver.
 */
export function badgeLabel(unread: number): string | null {
  if (unread <= 0) return null;
  return unread > BADGE_CAP ? `${BADGE_CAP}+` : String(unread);
}

/** A notification's link, if it is one this app may send somebody to.
 *
 * Returns null for anything that is not a same-origin path — an absolute URL,
 * a protocol-relative `//host`, a `javascript:` — because part of the URL came
 * from a template that read a property value, and a property value came from
 * a dataset. The button is simply not drawn in that case: a link that quietly
 * went somewhere else would be worse than no link, and one that renders as
 * plain text invites somebody to copy it out.
 */
export function safeNotificationLink(url: string | null | undefined): string | null {
  return safeReturnPath(url ?? null);
}

/** Whether a notification is still new, from the row a listing holds. */
export function isUnread(notification: { read_at: string | null }): boolean {
  return notification.read_at === null;
}
