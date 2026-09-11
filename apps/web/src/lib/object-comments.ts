/**
 * What p.137's comments say (§322; `object-views` p.137).
 *
 *     "Object Explorer allows users to comment on an object, mention other
 *      users, and attach files and images. You can open the Comments Helper
 *      for any object using the **View comments** button in the header of any
 *      Object View." (p.137)
 *
 * The server stores the comment and decides who was mentioned; this decides
 * what the button says and how the text is cut up for rendering. Same division
 * as `object-type-issues.ts` and `usage-metrics.ts`.
 */
import type { ObjectComment, CommentMention } from "./types";

/**
 * What p.137's button says.
 *
 * **The count is on the button**, because a button that says nothing about
 * whether there is anything behind it is one people stop pressing — and the
 * question somebody has while looking at an object is "has anybody said
 * anything about this", which the label can answer without being opened.
 */
export function buttonLabel(count: number): string {
  if (count === 0) return "Comment";
  return count === 1 ? "1 comment" : `${count} comments`;
}

/** Whether the thread has anything in it, for a panel deciding what to draw. */
export function isEmpty(comments: readonly ObjectComment[]): boolean {
  return comments.length === 0;
}

/**
 * The empty state.
 *
 * p.137's framing is cooperative — "multiple users often work with a
 * particular object" — so an empty thread is an invitation rather than a
 * report. It also names the mention syntax, because a feature nobody can
 * discover is one nobody uses: there is no other place in the product that
 * would teach somebody to type `@`.
 */
export const EMPTY_THREAD =
  "No comments yet. Say something about this object — type @ to mention "
  + "somebody.";

/** One run of a comment's body: plain text, or a mention with its person. */
export type Segment =
  | { kind: "text"; text: string }
  | { kind: "mention"; text: string; userId: string };

/**
 * A comment's body, cut into runs at its mentions.
 *
 * **The spans come from the server and are not re-found here.** That is §146's
 * rule — a browser that re-derived them would be a second matcher, free to
 * disagree with the one that decided who was notified — and a disagreement
 * would show as a highlight on the wrong name, or on somebody who was never
 * told.
 *
 * Defensive about the spans all the same: they are read back out of `jsonb`,
 * and a mention whose range falls outside the body (or overlaps the one before
 * it) is dropped rather than allowed to slice the string into nonsense. That
 * cannot happen today — a comment is never edited — but the cost of being
 * wrong is a mangled comment, and the cost of the check is four comparisons.
 */
export function segments(comment: ObjectComment): Segment[] {
  const body = comment.body;
  const out: Segment[] = [];
  let at = 0;
  const ordered = [...(comment.mentions ?? [])].sort((a, b) => a.start - b.start);
  for (const mention of ordered) {
    if (!usable(mention, body, at)) continue;
    if (mention.start > at) {
      out.push({ kind: "text", text: body.slice(at, mention.start) });
    }
    out.push({
      kind: "mention",
      text: body.slice(mention.start, mention.end),
      userId: mention.user_id,
    });
    at = mention.end;
  }
  if (at < body.length) out.push({ kind: "text", text: body.slice(at) });
  return out;
}

function usable(mention: CommentMention, body: string, at: number): boolean {
  return (
    Number.isInteger(mention.start) &&
    Number.isInteger(mention.end) &&
    mention.start >= at &&
    mention.end > mention.start &&
    mention.end <= body.length
  );
}

/**
 * Who said it.
 *
 * **A departed author is named as gone, not as nobody.** The comment is still
 * in the thread — somebody leaving does not unsay what they said — and a blank
 * byline would read as a bug in the page rather than as a fact about the
 * person.
 */
export function authorLabel(comment: ObjectComment): string {
  return comment.author_name || comment.author_email || "Former member";
}
