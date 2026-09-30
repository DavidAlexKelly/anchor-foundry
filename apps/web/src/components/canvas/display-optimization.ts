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
 * **All six of p.182's options are offered.** Four are decided inside the
 * widget: mount **Default** and **Delay until on-screen**, unmount **Default**
 * and **when off-screen**. The last two are "is this element in the viewport",
 * which `useOnScreen` already asks for §224's auto-selection rule.
 *
 * **Eagerly mount** and **Never unmount** (§609) are about a widget whose page
 * is not showing, and §407 left them out because `CanvasPage` returned `null`
 * for such a page: no widget left to keep mounted, none to mount early. So an
 * inactive page that holds one now renders *hidden* rather than nothing, and
 * tells what is inside it that it is off-layout (`OffLayout` in
 * `SettingsPanel.tsx`). Every node there renders nothing, exactly as before,
 * unless `keptOffLayout` says it stays: an eager widget always, a never-unmount
 * widget once it has been mounted, and a container with one of those inside
 * it, so the widget has somewhere to be. A page with none of them still
 * returns `null`, so a module that configures nothing is untouched.
 *
 * **Tabs and collapsed sections are unchanged.** They already keep every
 * widget mounted (see above), which is Never unmount for all of them.
 *
 * Pure, for `components/canvas/pure.ts`'s reason: what shows when is exactly
 * the kind of rule a browser test can only confirm rendered *something*.
 */

/** p.182's mount options. */
export const MOUNTS: Record<string, string> = {
  default: "When its layout renders",
  on_screen: "Delay until on-screen",
  eager: "Eagerly mount",
};

/** p.182's unmount options. */
export const UNMOUNTS: Record<string, string> = {
  default: "When its layout closes",
  off_screen: "Unmount when off-screen",
  never: "Never unmount",
};

export const DEFAULT_MOUNT = "default";
export const DEFAULT_UNMOUNT = "default";

/** What the panel says under the two settings: p.181's own caution, and this
 * platform's one difference. Exported so the panel and its test read the
 * same words. */
export const DISPLAY_NOTE = "Eagerly mount and Never unmount keep a widget "
  + "across page switches, at the cost of memory while its page is closed. "
  + "Tabs and collapsed sections already keep their widgets mounted.";

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

/**
 * Whether a widget stays mounted while its page is closed (§609; p.182).
 *
 * > "Eagerly mount: The widget mounts as soon as the module loads, even if it
 * > is not yet visible. The widget remains mounted for the rest of the
 * > session." / "Never unmount: Once mounted, the widget remains mounted for
 * > the rest of the session."
 *
 * `mounted` is "has this widget been mounted while its page was showing",
 * which is the whole of Never unmount's "once mounted": a never-unmount
 * widget on a page nobody has opened is not mounted early - that is what the
 * *mount* setting is for, and the two are independent.
 */
export function keptOffLayout(
  { mount, unmount, mounted }: { mount: string; unmount: string; mounted: boolean },
): boolean {
  return mount === "eager" || (unmount === "never" && mounted);
}

/** Whether a node's own settings could keep it mounted off-layout, which is
 *  what a closed page and the containers in it ask of what they hold. */
export function mayKeep(display: { mount?: unknown; unmount?: unknown } | undefined): boolean {
  return mountOf(display?.mount) === "eager" || unmountOf(display?.unmount) === "never";
}
