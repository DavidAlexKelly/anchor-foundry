/** §509: the Details tab's Size (`dataset-preview` p.3). */
import { describe, expect, it } from "vitest";

import { currentBytes, sizeText } from "./dataset-size";

describe("sizeText", () => {
  it("says columns and bytes", () => {
    expect(sizeText(3, 2048)).toBe("3 columns · 2.0 KB in storage");
    expect(sizeText(1, 12)).toBe("1 column · 12 B in storage");
  });

  it("says the columns alone while the size is not known yet", () => {
    expect(sizeText(2, undefined)).toBe("2 columns");
  });

  it("says a missing file is not measured, not empty", () => {
    expect(sizeText(2, null)).toBe("2 columns · not measured: its file is not in storage");
    expect(sizeText(0, 0)).toBe("0 columns · 0 B in storage");
  });
});

describe("currentBytes", () => {
  const versions = [
    { version_number: 3, size_bytes: 300 },
    { version_number: 2, size_bytes: null },
    { version_number: 1 },
  ];

  it("finds the current version's size", () => {
    expect(currentBytes(versions, 3)).toBe(300);
  });

  it("tells a missing file from a missing row", () => {
    expect(currentBytes(versions, 2)).toBeNull();
    // A row the API sent without the field is a file it could not measure.
    expect(currentBytes(versions, 1)).toBeNull();
    expect(currentBytes(versions, 4)).toBeUndefined();
    expect(currentBytes(undefined, 3)).toBeUndefined();
  });
});
