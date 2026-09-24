import { describe, expect, it } from "vitest";

import {
  MAX_EXPORT_ROWS, collectRows, csvCell, csvOf, exportColumns, exportFileName, staticTypeOf,
  tsvOf,
  type ExportRow,
} from "./object-export";

const PROPS = [
  { api_name: "name", display_name: "Name" },
  { api_name: "region", display_name: "Region" },
  { api_name: "size", display_name: null },
];
const row = (key: string, properties: Record<string, unknown>): ExportRow =>
  ({ primary_key: key, properties });

describe("exportColumns", () => {
  it("is the key and then every property, in the type's order", () => {
    expect(exportColumns(PROPS).map((c) => c.header)).toEqual(["Key", "Name", "Region", "size"]);
    expect(exportColumns(PROPS, []).map((c) => c.apiName)).toEqual([null, "name", "region", "size"]);
  });

  it("is the chosen properties in the order they were chosen", () => {
    // p.489: "select the set of properties that should be included".
    expect(exportColumns(PROPS, ["region", "name"]).map((c) => c.header))
      .toEqual(["Key", "Region", "Name"]);
  });

  it("keeps a chosen property the type lacks, headed by its name", () => {
    // Dropping it would move every column after it under somebody's sheet.
    expect(exportColumns(PROPS, ["gone"]).map((c) => c.header)).toEqual(["Key", "gone"]);
  });
});

describe("csvCell", () => {
  it("writes plain values as they are", () => {
    expect(csvCell("north")).toBe("north");
    expect(csvCell(42)).toBe("42");
    expect(csvCell(true)).toBe("true");
  });

  it("writes nothing for no value, not the word null", () => {
    expect(csvCell(null)).toBe("");
    expect(csvCell(undefined)).toBe("");
  });

  it("quotes what would otherwise break the row", () => {
    expect(csvCell("a,b")).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell("two\nlines")).toBe('"two\nlines"');
    expect(csvCell("cr\rhere")).toBe('"cr\rhere"');
  });

  it("writes a structure as its JSON", () => {
    expect(csvCell({ a: 1 })).toBe('"{""a"":1}"');
    expect(csvCell([1, 2])).toBe('"[1,2]"');
  });

  it("writes text that starts like a formula as text", () => {
    for (const lead of ["=", "+", "-", "@", "\t"]) {
      expect(csvCell(`${lead}SUM(A1)`), JSON.stringify(lead)).toMatch(/^"?'/);
    }
    expect(csvCell("=HYPERLINK(1)")).toBe("'=HYPERLINK(1)");
  });

  it("leaves a negative number a number", () => {
    expect(csvCell(-5)).toBe("-5");
  });
});

describe("csvOf", () => {
  it("is a header row and one row per object, CRLF-terminated", () => {
    const columns = exportColumns(PROPS, ["name", "size"]);
    expect(csvOf(columns, [row("S1", { name: "Alpha, north", size: 3 }), row("S2", {})]))
      .toBe('Key,Name,size\r\nS1,"Alpha, north",3\r\nS2,,\r\n');
  });

  it("is only the header for an empty set", () => {
    expect(csvOf(exportColumns(PROPS, ["name"]), [])).toBe("Key,Name\r\n");
  });
});

describe("tsvOf", () => {
  it("is tab-separated, with no line inside a value", () => {
    const columns = exportColumns(PROPS, ["name"]);
    expect(tsvOf(columns, [row("S1", { name: "a\tb\r\nc" }), row("S2", { name: null })]))
      .toBe("Key\tName\nS1\ta b c\nS2\t");
  });
});

describe("exportFileName", () => {
  const now = new Date("2026-09-24T10:00:00Z");

  it("is the configured name, with one .csv", () => {
    expect(exportFileName("sites", "Site", now)).toBe("sites.csv");
    expect(exportFileName("sites.CSV", "Site", now)).toBe("sites.csv");
  });

  it("is the type and the day when none was configured", () => {
    expect(exportFileName("", "Site", now)).toBe("Site 2026-09-24.csv");
    expect(exportFileName(null, "", now)).toBe("objects 2026-09-24.csv");
  });

  it("keeps only characters a file system takes", () => {
    expect(exportFileName("a/b:c*?", "Site", now)).toBe("a_b_c_.csv");
    expect(exportFileName("///", "Site", now)).toBe("_.csv");
    expect(exportFileName("  ", "Site", now)).toBe("Site 2026-09-24.csv");
  });
});

describe("collectRows", () => {
  const served = (n: number) => {
    const asked: number[] = [];
    const all = Array.from({ length: n }, (_, i) => row(`K${i}`, {}));
    return {
      asked,
      fetchPage: async (offset: number, limit: number) => {
        asked.push(offset);
        return all.slice(offset, offset + limit);
      },
    };
  };

  it("reads every page", async () => {
    const { asked, fetchPage } = served(120);
    const got = await collectRows(fetchPage, 120);
    expect("rows" in got && got.rows.length).toBe(120);
    expect(asked).toEqual([0, 50, 100]);
  });

  it("refuses a set larger than it writes, and says how large", async () => {
    const { asked, fetchPage } = served(0);
    const got = await collectRows(fetchPage, MAX_EXPORT_ROWS + 1);
    expect("refused" in got && got.refused).toContain("10,001");
    expect(asked).toEqual([]);
    const most = await collectRows(served(0).fetchPage, MAX_EXPORT_ROWS);
    expect("rows" in most).toBe(true);
  });

  it("stops at a short page", async () => {
    const { asked, fetchPage } = served(60);
    const got = await collectRows(fetchPage, 500);
    expect("rows" in got && got.rows.length).toBe(60);
    expect(asked).toEqual([0, 50]);
  });
});

describe("staticTypeOf", () => {
  const vars = {
    v_base: { kind: "object_set", object_set: { object_type_id: "t1" } },
    v_narrow: { kind: "object_set", derivation: { transform: "narrow_set", inputs: ["v_base", "v_c"] } },
    v_filter: { kind: "object_set", derivation: { transform: "filter_set", inputs: ["v_narrow", "v_x"] } },
    v_far: { kind: "object_set", derivation: { transform: "traverse_set", inputs: ["v_base"] } },
    v_text: { kind: "string" },
    v_a: { kind: "object_set", derivation: { transform: "narrow_set", inputs: ["v_b"] } },
    v_b: { kind: "object_set", derivation: { transform: "narrow_set", inputs: ["v_a"] } },
    v_orphan: { kind: "object_set", derivation: { transform: "narrow_set", inputs: [] } },
  };

  it("reads a set's own type", () => {
    expect(staticTypeOf("v_base", vars)).toBe("t1");
  });

  it("follows narrowing and filtering back to it, however deep", () => {
    expect(staticTypeOf("v_narrow", vars)).toBe("t1");
    expect(staticTypeOf("v_filter", vars)).toBe("t1");
  });

  it("does not guess across a traversal, or for what is not a set", () => {
    expect(staticTypeOf("v_far", vars)).toBeNull();
    expect(staticTypeOf("v_text", vars)).toBeNull();
    expect(staticTypeOf("v_gone", vars)).toBeNull();
    expect(staticTypeOf("v_orphan", vars)).toBeNull();
  });

  it("stops on a cycle rather than looping", () => {
    expect(staticTypeOf("v_a", vars)).toBeNull();
  });
});
