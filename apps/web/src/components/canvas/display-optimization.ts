/**
 * Widget display optimization (`foundry_workshop` p.180-182).
 *
 * > "Widget display optimization is a Workshop setting that controls when
 * > individual widgets mount and unmount as users navigate within a module."
 * > (p.180)
 *
 * > "Display optimization is controlled by two independent settings: a
 * > widget's mount behavior and its unmount behavior." (p.182)
 *
 * ---
 *
 * **What this platform already does, which is not what the parity row said.**
 * The row read "default is mount-on-visible, unmount-on-leave". Both halves
 * were wrong, and p.182 is explicit about the first:
 *
 * > "Default: The widget mounts when its containing layout (the page, section,
 * > or tab that holds it) first renders." — mount-on-visible is p.182's
 * > *"Delay until on-screen"*, which it calls "the historical behavior for
 * > some widget types".
 *
 * The second was wrong about this platform rather than about Foundry, and it
 * is wrong in two different directions at once:
 *
 * * a **page** switch unmounts — `CanvasPage` returns `null` in run mode — so
 *   pages already behave as p.182's Default;
 * * a **tab** switch does not. `CanvasSection` renders every tab and marks the
 *   inactive ones `hidden`, deliberately: *"a table in a tab nobody is looking
 *   at should not refetch every time somebody comes back to it"*. A collapsed
 *   section does the same. So tabs already behave as p.182's **Never
 *   unmount**, and Foundry treats a tab and a page alike.
 *
 * That divergence is recorded rather than removed. Making tabs unmount to
 * match p.182's Default would undo a decision with its own argument, and it
 * would be a behaviour change to every module in the corpus dressed up as a
 * settings feature.
 *
 * ---
 *
 * **So two of p.182's six options are offered and four are not**, and the two
 * that are offered are the two this platform can honour from inside a widget:
 *
 * * mount **Delay until on-screen**, and unmount **when off-screen** — both
 *   are "is this element in the viewport", which `useOnScreen` already asks
 *   for §224's auto-selection rule.
 * * mount **Default** and unmount **Default** are what happens now.
 *
 * **Eagerly mount** and **Never unmount** are *not offered*, and the reason is
 * structural rather than a shortcut: both are claims about a widget whose
 * layout is not rendered, and this code runs inside that layout. When
 * `CanvasPage` returns `null` there is no widget left to keep mounted and none
 * to mount early — honouring either would mean changing how pages render their
 * children, which is a different unit. §214: a control that looks like it
 * works is worse than one that is absent, so they are absent, with the panel
 * saying why.
 *
 * Pure, for `components/canvas/pure.ts`'s reason: what shows when is exactly
 * the kind of rule a browser test can only confirm rendered *something*.
 */

/** p.182's mount options, minus the one this platform cannot honour. */
export const MOUNTS: Record<string, string> = {
  default: "When its layout renders",
  on_screen: "Delay until on-screen",
};

/** p.182's unmount options, minus the one this platform cannot honour. */
export const UNMOUNTS: Record<string, string> = {
  default: "When its layout closes",
  off_screen: "Unmount when off-screen",
};

export const DEFAULT_MOUNT = "default";
export const DEFAULT_UNMOUNT = "default";

/** p.182's two options this platform does not offer, and the sentence saying
 * so. Exported so the panel and its test read the same words. */
export const UNSUPPORTED = "Eagerly mount and Never unmount are not offered: "
  + "both are about a widget whose layout is not on screen, and this setting "
  + "lives inside that layout. Tabs and collapsed sections already keep their "
  + "widgets mounted.";

function oneOf(raw: unknown, allowed: Record<string, string>, fallback: string): string {
  const value = String(raw ?? "");
  return value in allowed ? value : fallback;
}

/** §212: a layout document holds whatever was put there, including a setting
 * from a build that offered more of them than this one does. */
export function mountOf(raw: unknown): string {
  return oneOf(raw, MOUNTS, DEFAULT_MOUNT);
}

export function unmountOf(raw: unknown): string {
  return oneOf(raw, UNMOUNTS, DEFAULT_UNMOUNT);
}

/**
 * Whether this widget needs watching at all.
 *
 * **The common case is `false`, and that matters.** An observer per widget on
 * every module would be a cost paid by every app to serve the few p.181 says
 * this is for — "custom widgets that hold local state", "widgets with
 * expensive initial loads". A module that configures nothing gets exactly what
 * it got before this existed.
 */
export function watches(mount: string, unmount: string): boolean {
  return mount === "on_screen" || unmount === "off_screen";
}

/**
 * Whether the widget's body should be rendered this frame.
 *
 * `seen` is "has this ever been on screen", which is what separates the two
 * settings. **Delay-until-on-screen is a one-way door**: p.182 says the widget
 * "delays mounting until it is scrolled into view", not that it unmounts again
 * — that is what the *unmount* setting is for, and they are independent.
 *
 * `visible` is deliberately ignored when neither setting asks about it, so a
 * widget with only sizing configured is never at the mercy of an observer that
 * has not reported yet.
 */
export function shows(
  { mount, unmount, visible, seen }:
  { mount: string; unmount: string; visible: boolean; seen: boolean },
): boolean {
  if (unmount === "off_screen" && !visible) {
    // **Except before it has ever been seen, when the mount setting decides.**
    // Without this an off-screen-unmounting widget with the default mount
    // would never render at all in a runtime whose observer reports late:
    // nothing to intersect, so nothing to report, so nothing to render.
    if (mount === "on_screen" || seen) return false;
  }
  if (mount === "on_screen") return seen;
  return true;
}

/**
 * The height to hold open while the body is not rendered.
 *
 * **A collapsed placeholder is worse than no feature.** Unmounting a widget in
 * a long scrollable layout — the case p.181 names — removes its height, which
 * pulls everything below it upward and moves the viewport out from under the
 * reader; the widget then scrolls back into view and remounts, and the page
 * oscillates. Holding the last measured height keeps the scroll position
 * still, and keeps the element big enough for the observer to see it again.
 *
 * `null` before anything has been measured, which is the delay-until-on-screen
 * case: nothing has rendered, so there is no height to remember and a minimum
 * stands in.
 */
export const UNMEASURED_HEIGHT = 40;

export function placeholderHeight(measured: number | null): number {
  return measured && measured > 0 ? measured : UNMEASURED_HEIGHT;
}
