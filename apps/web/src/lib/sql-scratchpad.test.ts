import { describe, expect, it } from "vitest";

import {
  canRun,
  emptyReason,
  oneLine,
  ranNote,
  sampleWarning,
  showRewritten,
  starLabel,
  tabLabel,
} from "./sql-scratchpad";
import type { ScratchpadQuery, ScratchpadResult } from "./types";

function query(over: Partial<ScratchpadQuery> = {}): ScratchpadQuery {
  return {
    id: "q-1",
    repo_id: "r-1",
    sql: "SELECT * FROM `orders`",
    favourite: false,
    run_count: 1,
    first_ran_at: "2026-01-01T00:00:00Z",
    last_ran_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function result(over: Partial<ScratchpadResult> = {}): ScratchpadResult {
  return {
    columns: [{ name: "id", data_type: "BIGINT" }],
    rows: [[1]],
    row_count: 1,
    truncated: false,
    sampled: false,
    inputs: [],
    ran: 'SELECT * FROM "orders"',
    ...over,
  };
}

describe("when Run can be pressed", () => {
  it("needs something to run", () => {
    expect(canRun("")).toBe(false);
    expect(canRun("   \n  ")).toBe(false);
  });

  it("does not guess whether the query parses", () => {
    // Whether it parses is the server's answer. Guessing here is how a panel
    // starts refusing queries the server would have accepted — and nothing in
    // this file reads the reference syntax, which `scratchpad.py` owns.
    expect(canRun("this is not SQL at all")).toBe(true);
    expect(canRun("SELECT * FROM `orders")).toBe(true);
  });
});

describe("the tabs", () => {
  it("names p.15's three", () => {
    expect(tabLabel("query", 0)).toBe("Query");
    expect(tabLabel("history", 0)).toBe("History");
    expect(tabLabel("favourites", 0)).toBe("Favourites");
  });

  it("carries the count, because that is the reason to open it", () => {
    expect(tabLabel("history", 4)).toBe("History (4)");
    expect(tabLabel("favourites", 2)).toBe("Favourites (2)");
  });

  it("does not put a zero on a tab", () => {
    // "History (0)" is a tab telling you not to click it in the least direct
    // way available.
    expect(tabLabel("history", 0)).not.toContain("0");
  });

  it("never counts the query tab, which is not a list", () => {
    expect(tabLabel("query", 9)).toBe("Query");
  });
});

describe("a query on one line", () => {
  it("collapses whitespace rather than taking the first line", () => {
    // A formatted query's first line is `SELECT`, and a list of rows all
    // reading "SELECT" defeats the list.
    expect(oneLine("SELECT\n  id,\n  total\nFROM `orders`")).toBe(
      "SELECT id, total FROM `orders`",
    );
  });

  it("trims the ends", () => {
    expect(oneLine("  SELECT 1  ")).toBe("SELECT 1");
  });

  it("shortens a long query and says it did", () => {
    const long = `SELECT ${"x".repeat(200)}`;
    const short = oneLine(long, 20);
    expect(short).toHaveLength(20);
    expect(short.endsWith("…")).toBe(true);
  });

  it("leaves one that fits alone", () => {
    expect(oneLine("SELECT 1", 20)).toBe("SELECT 1");
  });
});

describe("what a history row says", () => {
  it("says nothing about a query run once", () => {
    // "ran once" on every row is noise.
    expect(ranNote(query({ run_count: 1 }))).toBeNull();
  });

  it("counts the ones somebody kept coming back to", () => {
    expect(ranNote(query({ run_count: 7 }))).toBe("ran 7 times");
  });

  it("says what the star will do, not what it is", () => {
    expect(starLabel(query({ favourite: false }))).toBe("Add to favourites");
    expect(starLabel(query({ favourite: true }))).toBe("Remove from favourites");
  });
});

describe("the empty tabs", () => {
  it("says nothing on the query tab, which is never empty", () => {
    expect(emptyReason("query", 0)).toBeNull();
  });

  it("explains that history is what ran, not what was typed", () => {
    const said = emptyReason("history", 0);
    expect(said).toContain("once it has run");
  });

  it("tells an unstarred history from an empty one", () => {
    // The remedy differs and only one of them is something the reader can do
    // right now.
    expect(emptyReason("favourites", 5)).toContain("Star a query in History");
    expect(emptyReason("favourites", 0)).toContain("nothing has run yet");
  });

  it("does not tell somebody to star a query when there are none to star", () => {
    expect(emptyReason("favourites", 0)).not.toContain("Star a query in History");
  });
});

describe("the sample warning", () => {
  it("says nothing when the whole dataset was read", () => {
    expect(sampleWarning(result({ sampled: false }))).toBeNull();
  });

  it("names the datasets and how much of them was read", () => {
    const said = sampleWarning(
      result({
        sampled: true,
        inputs: [
          {
            alias: "orders",
            dataset: "orders",
            dataset_id: "d-1",
            rows_available: 1000000,
            rows_used: 1000,
            sampled: true,
          },
        ],
      }),
    );
    expect(said).toContain("orders");
    expect(said).toContain("1,000");
    expect(said).toContain("1,000,000");
  });

  it("says that a sampled answer is not the answer", () => {
    // The half that matters: a join or a group by over a sample gives an
    // answer that is wrong in a way nothing on screen would otherwise show.
    const said = sampleWarning(
      result({
        sampled: true,
        inputs: [
          {
            alias: "a", dataset: "a", dataset_id: "d",
            rows_available: 10, rows_used: 5, sampled: true,
          },
        ],
      }),
    );
    expect(said).toContain("not the answer");
  });

  it("names only the inputs that were sampled", () => {
    const said = sampleWarning(
      result({
        sampled: true,
        inputs: [
          {
            alias: "big", dataset: "big", dataset_id: "d1",
            rows_available: 10, rows_used: 5, sampled: true,
          },
          {
            alias: "small", dataset: "small", dataset_id: "d2",
            rows_available: 3, rows_used: 3, sampled: false,
          },
        ],
      }),
    );
    expect(said).toContain("big");
    expect(said).not.toContain("small");
  });
});

describe("showing what the engine was given", () => {
  it("shows it when the query was translated", () => {
    // Backticks are Foundry's engine and not ours, so an error from DuckDB is
    // about text the author never wrote.
    expect(
      showRewritten("SELECT * FROM `orders`", result({ ran: 'SELECT * FROM "orders"' })),
    ).toBe(true);
  });

  it("does not show a query twice when nothing was translated", () => {
    expect(showRewritten('SELECT * FROM "orders"', result({ ran: 'SELECT * FROM "orders"' })))
      .toBe(false);
  });

  it("ignores whitespace at the ends, which is not a translation", () => {
    expect(showRewritten("  SELECT 1  ", result({ ran: "SELECT 1" }))).toBe(false);
  });
});
