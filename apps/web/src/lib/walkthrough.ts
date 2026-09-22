/**
 * p.11's in-app walkthrough (§431; `code-repositories` p.11).
 *
 * > "In the Code tab, you can click the [?] button to start a step-by-step
 * > walkthrough that guides you through the core functionalities available in
 * > your Code Repository. The in-app help is currently only available in the
 * > Code view."
 *
 * **The last sentence is a limitation, not a design, and is not copied.**
 * "Currently only available" is Foundry noting where the feature has reached,
 * and the core functionalities it promises to guide you through are spread
 * across this application's seven tabs rather than gathered into one Code
 * view. A walkthrough that stopped at the Files tab would cover the editor and
 * none of the things somebody actually needs explaining — what publishing
 * does, where a review happens — so the button is in the bar on every tab and
 * the walk moves between them.
 *
 * ---
 *
 * **A step about something this project does not have is dropped, not shown.**
 * The gate note only exists in a project that requires review, so a walk
 * through an ungated one must not describe it. A tour that pointed at an empty
 * rectangle and explained what would be there is worse than one that is
 * shorter — it teaches the reader that the help does not know the page.
 *
 * **The condition is named by the step and answered by the caller, not read
 * out of the document.** Asking "is this element on the screen" was written
 * first and cannot work: a step about the Publish tab is never in the document
 * while you are on Files, so every step the walk exists to take you to would
 * be dropped before it could. The application knows what it has without
 * rendering it.
 *
 * That has a consequence the counter has to respect, and it is the bug this
 * module exists to make impossible: **"Step 3 of 7" is counted over the steps
 * that survived**, never over the list as written.
 */

/** Which tab a step needs. Kept as a string rather than importing `Tab` from
 *  `repository-commands.ts`, because this module is about *any* guided walk
 *  and the repository's steps are the caller's list. */
export interface Step {
  id: string;
  /** The tab this step lives on, if it lives on one. The walk switches to it
   *  on arrival — a step that described a control on a tab you are not
   *  looking at would be a sentence about nothing. */
  tab?: string;
  title: string;
  body: string;
  /** The `data-tour` value of the element this step is about. */
  anchor: string;
  /** A named condition this step needs, answered by the caller. Absent means
   *  the step is always shown. */
  needs?: string;
}

/**
 * The steps whose conditions hold.
 *
 * `holds` is asked per condition rather than given as a set, so the caller can
 * answer from whatever it already knows — a react-query result, a count — and
 * so a test can answer from a literal.
 */
export function stepsFor(
  steps: readonly Step[], holds: (need: string) => boolean,
): Step[] {
  return steps.filter((step) => step.needs === undefined || holds(step.needs));
}

/**
 * Where the next arrow goes.
 *
 * **Clamped, not wrapping** — the opposite of the command palette's arrows,
 * and for the opposite reason: a list of commands is a circle you scan, and a
 * walkthrough is a thing with an end. Wrapping from the last step to the first
 * would make "Next" restart a tour somebody has just finished, which is the
 * one thing a tour must not do.
 */
export function move(steps: readonly Step[], index: number, by: number): number {
  // **No guard for an empty walk**, though one was written. The clamp already
  // answers it: `Math.min(-1, …)` is at most -1 and `Math.max(0, …)` lifts it
  // back to 0, which is the same 0 the guard returned. A mutation sweep could
  // not tell the two apart, because there is nothing to tell apart (§223).
  return Math.max(0, Math.min(steps.length - 1, index + by));
}

/** The step to show, or `null` when there is nothing to show at all. */
export function at(steps: readonly Step[], index: number): Step | null {
  return steps[index] ?? null;
}

export function isLast(steps: readonly Step[], index: number): boolean {
  // `steps.length > 0 &&` was here and did nothing: on an empty walk the
  // comparison is `index === -1`, and `move` never produces a negative index.
  // The same sweep, the same answer (§223).
  return index === steps.length - 1;
}

/** "Step 3 of 7", over the steps that survived rather than over the list as
 *  written. A counter that promised nine and delivered seven would be the
 *  walkthrough's own first inaccuracy. */
export function progressLabel(steps: readonly Step[], index: number): string {
  return `Step ${Math.min(index + 1, steps.length)} of ${steps.length}`;
}

/** The word on the button that moves forward. */
export function nextLabel(steps: readonly Step[], index: number): string {
  return isLast(steps, index) ? "Done" : "Next";
}

export interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface Viewport {
  width: number;
  height: number;
}

/** How far the card sits from the thing it is describing. */
export const CARD_GAP = 12;
/** The margin the card keeps from the edge of the window. */
export const CARD_MARGIN = 12;

/**
 * Where to put the card for a highlighted element.
 *
 * **Below when there is room, above when there is not**, and never off the
 * side: a tour card that hangs past the right edge of the window is the tour
 * pointing somewhere the reader cannot look. Both of those are one line each
 * and both are wrong in most of the tours anybody has used.
 *
 * Returned in viewport coordinates, for a `position: fixed` card — the page
 * behind can scroll, and a card placed in document coordinates would drift off
 * the element it belongs to.
 */
export function placeCard(
  anchor: Rect, card: { width: number; height: number }, view: Viewport,
): { top: number; left: number } {
  const below = anchor.top + anchor.height + CARD_GAP;
  const fitsBelow = below + card.height + CARD_MARGIN <= view.height;
  const top = fitsBelow
    ? below
    : Math.max(CARD_MARGIN, anchor.top - CARD_GAP - card.height);
  // Left-aligned with the element, then pulled back inside the window. Pulled
  // rather than centred, because an element at the left edge and an element in
  // the middle should both have their card start where the eye already is.
  const left = Math.max(
    CARD_MARGIN,
    Math.min(anchor.left, view.width - card.width - CARD_MARGIN),
  );
  return { top, left };
}

/**
 * Where to put the card when there is nothing to point at.
 *
 * An anchor can be missing for a reason nobody predicted — a panel that failed
 * to load, a control behind a flag. **The words are still shown**, in the
 * middle of the window and without an outline: a walkthrough that went blank
 * would be the help itself breaking, which is the worst moment for it to.
 */
export function centred(
  card: { width: number; height: number }, view: Viewport,
): { top: number; left: number } {
  return {
    top: Math.max(CARD_MARGIN, (view.height - card.height) / 2),
    left: Math.max(CARD_MARGIN, (view.width - card.width) / 2),
  };
}
