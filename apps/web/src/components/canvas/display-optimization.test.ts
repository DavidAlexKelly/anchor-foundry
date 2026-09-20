import { describe, expect, it } from "vitest";

import {
  DEFAULT_MOUNT, DEFAULT_UNMOUNT, MOUNTS, UNMEASURED_HEIGHT, UNMOUNTS,
  mountOf, placeholderHeight, shows, unmountOf, watches,
} from "./display-optimization";

/** p.180-182's widget display optimization. */

describe("the options offered", () => {
  it("is p.182's list minus the two this platform cannot honour", () => {
    expect(Object.keys(MOUNTS)).toEqual(["default", "on_screen"]);
    expect(Object.keys(UNMOUNTS)).toEqual(["default", "off_screen"]);
    // **Not offered rather than offered and ignored** (§214). Both absentees
    // are claims about a widget whose layout is not rendered, and the setting
    // lives inside that layout.
    expect(Object.keys(MOUNTS)).not.toContain("eager");
    expect(Object.keys(UNMOUNTS)).not.toContain("never");
  });

  it("names them the way p.182 does", () => {
    expect(MOUNTS.on_screen).toBe("Delay until on-screen");
    expect(UNMOUNTS.off_screen).toBe("Unmount when off-screen");
  });
});

describe("reading a stored setting", () => {
  it("falls back for anything it does not offer", () => {
    // §212, and the specific case: a document written by a build that offered
    // p.182's other two. `eager` must read as the default rather than as
    // itself, or the panel would show a setting nothing implements.
    for (const raw of ["eager", "", null, undefined, 3, {}]) {
      expect(mountOf(raw)).toBe(DEFAULT_MOUNT);
    }
    for (const raw of ["never", "", null, undefined, [], true]) {
      expect(unmountOf(raw)).toBe(DEFAULT_UNMOUNT);
    }
  });

  it("keeps the two it does offer", () => {
    expect(mountOf("on_screen")).toBe("on_screen");
    expect(unmountOf("off_screen")).toBe("off_screen");
  });
});

describe("whether a widget is watched at all", () => {
  it("is false for a module that configured nothing", () => {
    // The common case, and the reason it matters: an observer per widget on
    // every module is a cost paid by every app to serve the few p.181 names.
    expect(watches("default", "default")).toBe(false);
  });

  it("is true as soon as either setting asks about the viewport", () => {
    expect(watches("on_screen", "default")).toBe(true);
    expect(watches("default", "off_screen")).toBe(true);
    expect(watches("on_screen", "off_screen")).toBe(true);
  });
});

describe("what shows this frame", () => {
  const at = (over: Partial<Parameters<typeof shows>[0]>) => shows({
    mount: "default", unmount: "default", visible: false, seen: false, ...over,
  });

  it("shows everything when neither setting was chosen", () => {
    // Deliberately regardless of `visible`: a widget with only sizing set is
    // never at the mercy of an observer that has not reported yet.
    expect(at({})).toBe(true);
    expect(at({ visible: true })).toBe(true);
  });

  it("delays until the widget has been on screen once", () => {
    expect(at({ mount: "on_screen" })).toBe(false);
    expect(at({ mount: "on_screen", visible: true, seen: true })).toBe(true);
  });

  it("does not undo the delay once it has mounted", () => {
    // **A one-way door.** p.182 says the widget "delays mounting until it is
    // scrolled into view", not that it unmounts again - that is the other
    // setting, and the two are independent.
    expect(at({ mount: "on_screen", visible: false, seen: true })).toBe(true);
  });

  it("unmounts when scrolled away, and only with that setting", () => {
    expect(at({ unmount: "off_screen", visible: true, seen: true })).toBe(true);
    expect(at({ unmount: "off_screen", visible: false, seen: true })).toBe(false);
    expect(at({ unmount: "default", visible: false, seen: true })).toBe(true);
  });

  it("still renders once before it has ever been seen", () => {
    // Without this an off-screen-unmounting widget with the *default* mount
    // never renders at all where the observer reports late: nothing to
    // intersect, so nothing to report, so nothing to render. The mount
    // setting decides the first frame; the unmount setting takes over after.
    expect(at({ unmount: "off_screen", visible: false, seen: false })).toBe(true);
    // Unless the mount setting asked for the delay, which is the one case
    // where not-yet-seen genuinely means not-yet-shown.
    expect(at({ mount: "on_screen", unmount: "off_screen" })).toBe(false);
  });
});

describe("the height held open while the body is gone", () => {
  it("is the last height the body actually had", () => {
    // A collapsed placeholder pulls everything below it upward, the widget
    // scrolls back into view, remounts, and the page oscillates.
    expect(placeholderHeight(320)).toBe(320);
  });

  it("is a minimum before anything has been measured", () => {
    // The delay-until-on-screen case: nothing has rendered, so there is no
    // height to remember - and zero would be an element the observer can
    // never see again.
    expect(placeholderHeight(null)).toBe(UNMEASURED_HEIGHT);
    expect(placeholderHeight(0)).toBe(UNMEASURED_HEIGHT);
    expect(UNMEASURED_HEIGHT).toBeGreaterThan(0);
  });
});
