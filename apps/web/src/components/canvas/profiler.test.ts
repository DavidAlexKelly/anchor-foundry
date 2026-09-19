import { describe, expect, it } from "vitest";
import {
  breakdown, durationLabel, emptyReason, isSlow, keyName, type LoadEvent, merge,
  narrow, profilerHref, profilerOn, span, summary, timeline, totalMs,
  triggeringPages,
} from "./profiler";

function ev(over: Partial<LoadEvent> = {}): LoadEvent {
  return {
    id: "v1", kind: "variable", name: "One", ms: 10, at: 0, loads: 1,
    page: null, ...over,
  };
}

describe("the total", () => {
  it("is the wall clock, not the sum of the parts", () => {
    // **The one that matters.** Two variables resolving in one request and
    // three widgets querying in parallel took 40ms between them, not 150 —
    // and a total that added the rows would grow with concurrency, which is
    // exactly backwards from what a profiler is for.
    const parallel = [
      ev({ id: "a", at: 0, ms: 40 }),
      ev({ id: "b", at: 5, ms: 30 }),
      ev({ id: "c", at: 10, ms: 25 }),
    ];
    expect(totalMs(parallel)).toBe(40);
  });

  it("reaches to the end of the last thing that finished", () => {
    expect(totalMs([ev({ at: 0, ms: 10 }), ev({ id: "b", at: 100, ms: 5 })])).toBe(105);
  });

  it("is zero before anything has loaded", () => {
    expect(totalMs([])).toBe(0);
  });
});

describe("the breakdown", () => {
  it("puts the slowest first, because that is what a reader came for", () => {
    const rows = breakdown([
      ev({ id: "a", name: "Fast", ms: 5 }),
      ev({ id: "b", name: "Slow", ms: 900 }),
      ev({ id: "c", name: "Middling", ms: 50 }),
    ]);
    expect(rows.map((r) => r.name)).toEqual(["Slow", "Middling", "Fast"]);
  });

  it("breaks ties on name so the order does not reshuffle", () => {
    const rows = breakdown([
      ev({ id: "b", name: "Beta", ms: 10 }),
      ev({ id: "a", name: "Alpha", ms: 10 }),
    ]);
    expect(rows.map((r) => r.name)).toEqual(["Alpha", "Beta"]);
  });

  it("does not mutate what it was given", () => {
    const given = [ev({ id: "a", ms: 1 }), ev({ id: "b", ms: 9 })];
    breakdown(given);
    expect(given.map((r) => r.id)).toEqual(["a", "b"]);
  });
});

describe("the timeline", () => {
  it("is in the order things happened, which is a different question", () => {
    // p.178 lists the timeline separately from the breakdown because a module
    // whose three slowest loads ran in parallel and one whose three fastest
    // ran in series look identical in a breakdown.
    const rows = timeline([
      ev({ id: "c", name: "Third", at: 90 }),
      ev({ id: "a", name: "First", at: 0 }),
      ev({ id: "b", name: "Second", at: 40 }),
    ]);
    expect(rows.map((r) => r.name)).toEqual(["First", "Second", "Third"]);
  });

  it("places a bar where it happened and as wide as it took", () => {
    const bar = span(ev({ at: 50, ms: 25 }), 100);
    expect(bar.left).toBe(50);
    expect(bar.width).toBe(25);
  });

  it("gives an instant load a bar you can still see", () => {
    // Without a floor every fast row is invisible and the timeline reads as
    // having lost them.
    expect(span(ev({ at: 10, ms: 0 }), 1000).width).toBe(1);
  });

  it("never runs a bar off the end", () => {
    const bar = span(ev({ at: 90, ms: 500 }), 100);
    expect(bar.left + bar.width).toBeLessThanOrEqual(100);
  });

  it("keeps an instant load at the very end on the track", () => {
    // **The case that broke, and the ordinary one.** A variable resolving in
    // under a millisecond at the end of the run puts `at / total` at 100%, and
    // a bar with the 1% floor starting there is a bar nobody can see. The
    // first version computed `left` first and let the floor push the bar off
    // the end; a browser test found the row in the DOM, correct, and outside
    // the track.
    const bar = span(ev({ at: 5, ms: 0.2 }), 5);
    expect(bar.left).toBeLessThanOrEqual(99);
    expect(bar.left + bar.width).toBeLessThanOrEqual(100);
    expect(bar.width).toBeGreaterThan(0);
  });

  it("draws a full bar when nothing has established a scale yet", () => {
    expect(span(ev(), 0)).toEqual({ left: 0, width: 100 });
  });
});

describe("how a duration reads", () => {
  it("says <1ms rather than 0ms", () => {
    // `0ms` is a number somebody will try to explain; `<1ms` is information.
    expect(durationLabel(0.4)).toBe("<1ms");
  });

  it("rounds milliseconds and switches to seconds when it is worth it", () => {
    expect(durationLabel(42.6)).toBe("43ms");
    expect(durationLabel(1500)).toBe("1.5s");
  });
});

describe("the summary", () => {
  it("does not report a good result for a module that has not loaded", () => {
    // Profiler mode reloads the page to record from initialisation, so there
    // is always a moment with the banner up and no rows. `0ms` there is a
    // measurement of nothing wearing the clothes of a fast module.
    expect(summary([])).toBe("Nothing has loaded yet.");
  });

  it("counts the two kinds separately", () => {
    const text = summary([
      ev({ id: "v", kind: "variable", ms: 10, at: 0 }),
      ev({ id: "q", kind: "request", ms: 90, at: 10 }),
      ev({ id: "q2", kind: "request", ms: 5, at: 10 }),
    ]);
    expect(text).toContain("1 variable");
    expect(text).toContain("2 requests");
    expect(text).toContain("100ms");
  });

  it("does not name a kind that did not happen", () => {
    expect(summary([ev({ kind: "variable" })])).not.toContain("request");
  });

  it("does not pluralise one of a kind", () => {
    // Asserted as "does not say variables" rather than by matching a trailing
    // space: with only one kind present there is nothing after the word, so
    // the space the first version looked for exists only when a second kind
    // follows - a check that passed for the wrong reason whenever it passed.
    const text = summary([ev({ kind: "variable" })]);
    expect(text).toContain("1 variable");
    expect(text).not.toContain("variables");
  });
});

describe("what counts as slow", () => {
  it("is a threshold rather than a scale", () => {
    expect(isSlow(ev({ ms: 499 }))).toBe(false);
    expect(isSlow(ev({ ms: 500 }))).toBe(true);
  });
});

describe("profiler mode lives in the URL", () => {
  it("reads the flag off the address", () => {
    expect(profilerOn("?profiler=1")).toBe(true);
    expect(profilerOn("?profiler=0")).toBe(false);
    expect(profilerOn("")).toBe(false);
  });

  it("turns it on and off again", () => {
    expect(profilerHref("/r/abc", true)).toBe("/r/abc?profiler=1");
    expect(profilerHref("/r/abc?profiler=1", false)).toBe("/r/abc");
  });

  it("keeps every other parameter", () => {
    // **Not tidiness.** A module reached through a routed link (p.197) carries
    // its variable values in the address; dropping them on the way into the
    // profiler would profile a different module state than the one the reader
    // was looking at.
    const on = profilerHref("/r/abc?v_region=north&tab=files", true);
    expect(on).toContain("v_region=north");
    expect(on).toContain("tab=files");
    expect(profilerHref(on, false)).not.toContain("profiler");
    expect(profilerHref(on, false)).toContain("v_region=north");
  });

  it("does not leave a bare question mark behind", () => {
    expect(profilerHref("/r/abc?profiler=1", false)).not.toContain("?");
  });
});

describe("naming a request", () => {
  it("reads the head of the key and one identifier", () => {
    expect(keyName(["canvas-object-set", "abc123def456ghi"])).toBe("object set · abc123def456");
  });

  it("says the head alone when there is nothing to identify", () => {
    expect(keyName(["object-type"])).toBe("object type");
  });

  it("skips a non-string segment to find one that identifies", () => {
    expect(keyName(["canvas-rows", 25, "orders"])).toBe("rows · orders");
  });

  it("does not collapse two reads of different things into one row", () => {
    // A key rendered as its head alone would make the breakdown say "object
    // set" over a number that is really every object-set read on the page.
    expect(keyName(["canvas-object-set", "aaa"])).not.toBe(keyName(["canvas-object-set", "bbb"]));
  });
});

describe("a reload folds into its row", () => {
  it("counts rather than appending", () => {
    // A module where a filter moves ten times would otherwise be a hundred
    // rows with no way to see that ten of them are one thing.
    let rows = merge([], ev({ id: "v1", ms: 10, at: 0 }));
    rows = merge(rows, ev({ id: "v1", ms: 30, at: 500 }));
    expect(rows).toHaveLength(1);
    expect(rows[0]?.loads).toBe(2);
  });

  it("shows the most recent time, which is the one still actionable", () => {
    let rows = merge([], ev({ id: "v1", ms: 10, at: 0 }));
    rows = merge(rows, ev({ id: "v1", ms: 30, at: 500 }));
    expect(rows[0]?.ms).toBe(30);
  });

  it("keeps the first start, so the timeline does not slide right", () => {
    let rows = merge([], ev({ id: "v1", ms: 10, at: 0 }));
    rows = merge(rows, ev({ id: "v1", ms: 30, at: 500 }));
    expect(rows[0]?.at).toBe(0);
  });

  it("keeps a variable and a request of the same name apart", () => {
    let rows = merge([], ev({ id: "x", kind: "variable" }));
    rows = merge(rows, ev({ id: "x", kind: "request" }));
    expect(rows).toHaveLength(2);
  });

  it("does not mutate what it was given", () => {
    const given = [ev({ id: "v1" })];
    merge(given, ev({ id: "v1" }));
    expect(given[0]?.loads).toBe(1);
  });
});


// ---- p.178's interaction list (§395) ----------------------------------------
describe("which pages the filter offers", () => {
  it("offers only the ones that actually triggered something", () => {
    // **Derived from the events, not from the layout.** A module with twelve
    // pages that has only ever loaded on two offers two — a picker listing ten
    // choices that all yield an empty panel is a control that looks like it
    // works (§214).
    const pages = triggeringPages([
      ev({ id: "a", page: "p1" }),
      ev({ id: "b", page: "p2" }),
      ev({ id: "c", page: "p1" }),
    ]);
    expect(pages).toEqual(["p1", "p2"]);
  });

  it("keeps the order they first appeared in", () => {
    // So the entry a reader arrived through is first.
    expect(triggeringPages([ev({ id: "a", page: "z" }), ev({ id: "b", page: "a" })]))
      .toEqual(["z", "a"]);
  });

  it("ignores loads that belong to no page", () => {
    expect(triggeringPages([ev({ page: null })])).toEqual([]);
  });
});

describe("narrowing what is shown", () => {
  const ROWS = [
    ev({ id: "a", name: "Region filter", page: "p1" }),
    ev({ id: "b", name: "Order rows", page: "p1" }),
    ev({ id: "c", name: "Region total", page: "p2" }),
  ];

  it("shows everything when nothing is set", () => {
    expect(narrow(ROWS)).toHaveLength(3);
  });

  it("filters by the page that triggered the load", () => {
    expect(narrow(ROWS, { page: "p2" }).map((r) => r.id)).toEqual(["c"]);
  });

  it("searches the name, which is what a reader can see", () => {
    // p.178 says "by widget or variable name". Matching an id would let a
    // search succeed against a string nowhere on screen.
    expect(narrow(ROWS, { search: "region" }).map((r) => r.id)).toEqual(["a", "c"]);
  });

  it("does not miss on capitalisation or stray spaces", () => {
    // A reader copies a label out of a panel that title-cases; a search that
    // missed would read as the event not having been recorded.
    expect(narrow(ROWS, { search: "  ORDER " }).map((r) => r.id)).toEqual(["b"]);
  });

  it("applies both at once", () => {
    // One question, not two: "which of these am I looking at".
    expect(narrow(ROWS, { page: "p1", search: "region" }).map((r) => r.id)).toEqual(["a"]);
  });

  it("an empty search is not a filter", () => {
    expect(narrow(ROWS, { search: "   " })).toHaveLength(3);
  });
});

describe("what an empty panel says", () => {
  it("tells a starting module apart from a filtered one", () => {
    // **The distinction the whole function exists for.** One means the module
    // is still coming up; the other means the reader set a filter. Showing the
    // first for the second sends somebody to diagnose a module that is fine.
    expect(emptyReason([], [])).toBe("Nothing has loaded yet.");
    expect(emptyReason([ev()], [])).toBe("No load events match this filter.");
  });

  it("says nothing when there is something to draw", () => {
    expect(emptyReason([ev()], [ev()])).toBeNull();
  });
});
