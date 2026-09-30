/** p.222's viewer-side Configure columns (§612). `workshop` pages. */
import { describe, expect, it } from "vitest";

import { moved, storageKey, storedChoice, toggled, viewerColumnsOf } from "./viewer-columns";

const offered = ["name", "region", "note"];

describe("what a viewer sees", () => {
  it("is the table as configured until the viewer chooses", () => {
    expect(viewerColumnsOf(offered, null)).toEqual(offered);
  });

  it("is the viewer's columns, in the viewer's order", () => {
    expect(viewerColumnsOf(offered, ["note", "name"])).toEqual(["note", "name"]);
  });

  it("drops a column no longer offered, and a choice left empty is none", () => {
    expect(viewerColumnsOf(offered, ["gone", "region"])).toEqual(["region"]);
    expect(viewerColumnsOf(offered, ["gone"])).toEqual(offered);
  });
});

describe("choosing", () => {
  it("removes a checked column and adds an unchecked one at the end", () => {
    expect(toggled(offered, null, "region")).toEqual(["name", "note"]);
    expect(toggled(offered, ["note"], "name")).toEqual(["note", "name"]);
  });

  it("keeps the last column rather than leaving a table of keys", () => {
    expect(toggled(offered, ["note"], "note")).toEqual(["note"]);
  });

  it("cannot add a column the table does not offer", () => {
    expect(toggled(offered, ["note"], "secret")).toEqual(["note"]);
  });

  it("moves a column a place up or down, and not past either end", () => {
    expect(moved(offered, null, "region", -1)).toEqual(["region", "name", "note"]);
    expect(moved(offered, null, "region", 1)).toEqual(["name", "note", "region"]);
    expect(moved(offered, null, "name", -1)).toEqual(offered);
    expect(moved(offered, null, "note", 1)).toEqual(offered);
    expect(moved(offered, null, "secret", 1)).toEqual(offered);
  });
});

describe("keeping the choice", () => {
  it("is per widget and per type", () => {
    expect(storageKey("tbl", "t1")).not.toEqual(storageKey("tbl", "t2"));
    expect(storageKey("tbl", "t1")).not.toEqual(storageKey("other", "t1"));
  });

  it("reads back only a list of names", () => {
    expect(storedChoice('["note","name"]')).toEqual(["note", "name"]);
    for (const raw of [null, "", "{", '"note"', "[]", '[1, null, ""]', "{\"a\":1}"]) {
      expect(storedChoice(raw)).toBeNull();
    }
  });
});
