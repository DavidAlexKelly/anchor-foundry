/**
 * What each reviewer thinks of one file in a proposal
 * (§366; `code-repositories` p.55).
 *
 * > "To keep track of your progress while reviewing the changes in a pull
 * >  request, you can approve or reject each file individually." (p.55)
 *
 * Pure, and in `lib/` rather than beside the review surface, because vitest
 * cannot parse `.tsx`: a rule that lives in a component is a rule with no unit
 * test.
 */

export type FileMark = {
  reviewer_id: string;
  reviewer_email?: string | null;
  verdict?: string | null;
};

/** Four, where p.55 documents three. "Read and not sure yet" is where a
 *  reviewer spends most of a large diff, and it is what marking meant before
 *  verdicts existed — see db 0091. */
export type FileState = "unread" | "read" | "approved" | "rejected";

/**
 * My own mark, which is not the same question as "has anyone read this".
 *
 * **The distinction the surface got wrong before this existed**: the Unmark
 * button was drawn whenever *anybody* had read the file, so a second reviewer
 * arriving at a file their colleague had marked was offered "Unmark" for a
 * mark they had never made — and pressing it did nothing they could see,
 * because the delete is scoped to the caller.
 */
export function myMark(marks: FileMark[], myId: string | undefined): FileMark | undefined {
  // No `if (!myId) return undefined` guard: `find` already carries it, because
  // no mark's `reviewer_id` can equal `undefined`. It was written, and then
  // the sweep could not kill it — two ways of saying one thing, and the
  // shorter one is the one that is true (§213).
  return marks.find((m) => m.reviewer_id === myId);
}

/** Where I have got to with this file. */
export function fileState(marks: FileMark[], myId: string | undefined): FileState {
  const mine = myMark(marks, myId);
  if (!mine) return "unread";
  if (mine.verdict === "approved" || mine.verdict === "rejected") return mine.verdict;
  return "read";
}

/**
 * What everybody else has said, in one line — or "" when there is nothing.
 *
 * **Mine is left out on purpose.** The controls beside this line already show
 * my own state, and repeating it there turns a summary of what other people
 * think into a sentence a reader has to subtract themselves from.
 *
 * Verdicts are named and bare marks are counted, because "Ada rejected this"
 * is the thing that changes what somebody does next, and "two others have read
 * it" is context.
 */
export function othersSay(marks: FileMark[], myId: string | undefined): string {
  const others = marks.filter((m) => m.reviewer_id !== myId);
  if (others.length === 0) return "";
  const said = others
    .filter((m) => m.verdict)
    .map((m) => `${m.reviewer_email ?? "someone"} ${m.verdict}`);
  const silent = others.length - said.length;
  if (silent > 0) {
    said.push(`${silent} ${silent === 1 ? "other has" : "others have"} read it`);
  }
  return said.join(", ");
}

/**
 * What pressing a control should send.
 *
 * **Pressing the state you are already in clears it**, which is the only way
 * to get back to unread without a fourth button — and getting back to unread
 * matters, because a verdict you did not mean to give is worse than none.
 */
export function markRequest(
  current: FileState,
  pressed: Exclude<FileState, "unread">,
): { read: boolean; verdict?: "approved" | "rejected" } {
  if (current === pressed) return { read: false };
  if (pressed === "read") return { read: true };
  return { read: true, verdict: pressed };
}
