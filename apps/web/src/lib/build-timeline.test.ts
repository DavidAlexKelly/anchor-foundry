import { describe, expect, it } from "vitest";

import {
  type TimelineNode, durationLabel, emptyReason, placeOf, timelineFor,
} from "./build-timeline";

function built(id: string, name: string, from: string, to: string): TimelineNode {
  return {
    id, name, kind: "dataset",
    build_started_at: from, build_finished_at: to,
  };
}

const A = built("dataset:a", "Alpha", "2026-01-01T10:00:00Z", "2026-01-01T10:00:30Z");
const B = built("dataset:b", "Beta", "2026-01-01T10:00:30Z", "2026-01-01T10:01:30Z");
const C = built("dataset:c", "Gamma", "2026-01-01T10:01:30Z", "2026-01-01T10:02:00Z");
const UPLOADED: TimelineNode = {
  id: "dataset:u", name: "Uploaded", kind: "dataset",
  build_started_at: null, build_finished_at: null,
};

describe("timelineFor", () => {
  it("gives each build its offset and its length", () => {
    const { bars, span } = timelineFor([A, B]);
    expect(span).toBe(90_000);
    expect(bars).toEqual([
      { id: "dataset:a", name: "Alpha", offset: 0, ms: 30_000 },
      { id: "dataset:b", name: "Beta", offset: 30_000, ms: 60_000 },
    ]);
  });

  it("orders by when a build started, not by the order asked about", () => {
    // A Gantt is read left to right and top to bottom at once. Sorting by
    // anything but start time loses the diagonal that shows the pipeline's
    // shape, which is the only thing this chart says that a table does not.
    expect(timelineFor([C, A, B]).bars.map((b) => b.name))
      .toEqual(["Alpha", "Beta", "Gamma"]);
  });

  it("orders by time even when that is not alphabetical order", () => {
    // **The case the test above cannot see.** Alpha, Beta and Gamma happen to
    // have been built in alphabetical order, so sorting by name passes it —
    // found by the sweep, which removed the start-time sort and broke nothing.
    // Here the names run backwards against the clock, so only one order is
    // right.
    const late = built("dataset:a", "Alpha", "2026-01-01T10:02:00Z", "2026-01-01T10:02:10Z");
    const early = built("dataset:z", "Zulu", "2026-01-01T10:00:00Z", "2026-01-01T10:00:10Z");
    expect(timelineFor([late, early]).bars.map((b) => b.name)).toEqual(["Zulu", "Alpha"]);
  });

  it("breaks a tie on name so renders do not reshuffle", () => {
    const first = built("dataset:z", "Zulu", "2026-01-01T10:00:00Z", "2026-01-01T10:00:10Z");
    const second = built("dataset:m", "Mike", "2026-01-01T10:00:00Z", "2026-01-01T10:00:10Z");
    expect(timelineFor([first, second]).bars.map((b) => b.name))
      .toEqual(["Mike", "Zulu"]);
  });

  it("measures the window from the first start to the last finish", () => {
    // Not the sum of the bars: builds overlap, and a span that added them
    // would grow with concurrency, which is backwards.
    const overlapping = [
      built("dataset:x", "X", "2026-01-01T10:00:00Z", "2026-01-01T10:01:00Z"),
      built("dataset:y", "Y", "2026-01-01T10:00:10Z", "2026-01-01T10:00:40Z"),
    ];
    expect(timelineFor(overlapping).span).toBe(60_000);
  });

  it("counts the nodes it cannot chart rather than dropping them", () => {
    // §226 and §214: three bars drawn for twelve selected datasets would read
    // as "three datasets selected" unless the chart says otherwise.
    const { bars, without } = timelineFor([A, UPLOADED, B, UPLOADED]);
    expect(bars).toHaveLength(2);
    expect(without).toBe(2);
  });

  it("refuses a build that finished before it started", () => {
    // Clocks move and rows can be edited. A negative bar would sit to the left
    // of the axis and an absolute value would invent a duration nobody
    // measured — so it counts as a node with no build.
    const backwards = built("dataset:b", "Backwards",
      "2026-01-01T10:01:00Z", "2026-01-01T10:00:00Z");
    const { bars, without } = timelineFor([backwards]);
    expect(bars).toEqual([]);
    expect(without).toBe(1);
  });

  it("charts a build that took no measurable time", () => {
    // Zero is a real duration, unlike a missing one.
    const instant = built("dataset:i", "Instant",
      "2026-01-01T10:00:00Z", "2026-01-01T10:00:00Z");
    const { bars, span, without } = timelineFor([instant]);
    expect(bars).toEqual([{ id: "dataset:i", name: "Instant", offset: 0, ms: 0 }]);
    expect(span).toBe(0);
    expect(without).toBe(0);
  });

  it("treats an unparseable timestamp as no build", () => {
    const junk: TimelineNode = {
      id: "dataset:j", name: "Junk", kind: "dataset",
      build_started_at: "not a date", build_finished_at: "2026-01-01T10:00:00Z",
    };
    expect(timelineFor([junk])).toEqual({ bars: [], span: 0, without: 1 });
  });

  it("answers nothing for nothing", () => {
    expect(timelineFor([])).toEqual({ bars: [], span: 0, without: 0 });
  });
});

describe("placeOf", () => {
  it("places a bar as a share of the window", () => {
    const { bars, span } = timelineFor([A, B]);
    expect(placeOf(bars[1]!, span)).toEqual({ left: (30 / 90) * 100, width: (60 / 90) * 100 });
  });

  it("draws one instantaneous build full width", () => {
    // A single zero-length build would otherwise divide by zero, and the chart
    // would be empty for a selection that definitely built something.
    expect(placeOf({ id: "i", name: "Instant", offset: 0, ms: 0 }, 0))
      .toEqual({ left: 0, width: 100 });
  });

  it("gives a very short build a sliver wide enough to see", () => {
    // A row with a real duration and no bar reads as a row with no duration.
    //
    // **Asserted as a floor, not as "more than nothing"** — the sweep removed
    // the floor and this passed, because one millisecond in ten minutes is
    // 0.000167% and that is indeed greater than zero. A width nobody can see
    // or click is the same as no bar, so the number that matters is the one
    // that keeps it drawable.
    const { width } = placeOf({ id: "s", name: "Short", offset: 0, ms: 1 }, 600_000);
    expect(width).toBeGreaterThanOrEqual(0.5);
  });
});

describe("durationLabel", () => {
  it("reads against a clock", () => {
    expect(durationLabel(400)).toBe("400 ms");
    expect(durationLabel(1500)).toBe("1.5 s");
    expect(durationLabel(42_000)).toBe("42 s");
    // Not "1.5m": minutes with a decimal point have to be converted before
    // they mean anything.
    expect(durationLabel(90_000)).toBe("1m 30s");
    expect(durationLabel(120_000)).toBe("2m");
  });
});

describe("emptyReason", () => {
  it("says nothing when there is a chart", () => {
    expect(emptyReason(timelineFor([A]))).toBeNull();
  });

  it("asks for a selection when nothing was asked about", () => {
    expect(emptyReason(timelineFor([]))).toContain("Select datasets");
  });

  it("explains an unbuilt dataset rather than calling it empty", () => {
    // A selection of uploads is an ordinary thing to have, and it has no
    // builds because nothing built it — a fact about where the data came from
    // rather than a fault.
    expect(emptyReason(timelineFor([UPLOADED]))).toContain("not built by a model");
    expect(emptyReason(timelineFor([UPLOADED, UPLOADED]))).toContain("None of these");
  });
});
