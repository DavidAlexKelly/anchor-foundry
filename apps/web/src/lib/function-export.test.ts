/** A function-backed export (Workshop p.489-490; §775). */
import { describe, expect, it } from "vitest";

import {
  EXPORT_FILE_TYPES, exportContent, exportFileName, isBinary, isExportFileType, mimeOf,
} from "./function-export";

describe("p.489's file types", () => {
  it("are the seven, three of them binary", () => {
    expect(EXPORT_FILE_TYPES).toEqual(["csv", "txt", "json", "xml", "pdf", "docx", "xlsx"]);
    expect(EXPORT_FILE_TYPES.filter(isBinary)).toEqual(["pdf", "docx", "xlsx"]);
    expect(isExportFileType("csv")).toBe(true);
    expect(isExportFileType("exe")).toBe(false);
    expect(isExportFileType(3)).toBe(false);
  });

  it("each with the MIME type the download is given", () => {
    expect(mimeOf("csv")).toBe("text/csv");
    expect(mimeOf("txt")).toBe("text/plain");
    expect(mimeOf("json")).toBe("application/json");
    expect(mimeOf("xml")).toBe("application/xml");
    expect(mimeOf("pdf")).toBe("application/pdf");
    expect(mimeOf("docx")).toContain("wordprocessingml");
    expect(mimeOf("xlsx")).toContain("spreadsheetml");
  });
});

describe("the file's name", () => {
  it("is the one configured, with its extension", () => {
    expect(exportFileName("sites", "csv")).toBe("sites.csv");
    expect(exportFileName("sites.CSV", "csv")).toBe("sites.CSV");
    expect(exportFileName("sites.csv", "json")).toBe("sites.csv.json");
    expect(exportFileName("  ", "pdf")).toBe("export.pdf");
    expect(exportFileName(null, "txt")).toBe("export.txt");
  });
});

describe("the file's content (p.490)", () => {
  it("is the string itself for a text format", () => {
    expect(exportContent("a,b\n1,2", "csv")).toEqual({ content: "a,b\n1,2" });
    expect(exportContent("", "txt")).toEqual({ content: "" });
    // As written, its own spacing kept.
    expect(exportContent("  a\n", "txt")).toEqual({ content: "  a\n" });
  });

  it("is the bytes base64 encodes for a binary one", () => {
    const got = exportContent("JVBE Rg==\n", "pdf");
    expect("content" in got && Array.from(got.content as Uint8Array)).toEqual(
      [0x25, 0x50, 0x44, 0x46]);
  });

  it("refuses what is not a string, a MIME prefix, and what is not base64", () => {
    expect(exportContent(3, "csv")).toEqual({
      problem: "The function must return a string to export (Workshop p.490)." });
    expect(exportContent("data:application/pdf;base64,JVBERg==", "pdf")).toEqual({
      problem: 'Return the PDF bytes as base64 without a "data:" prefix (Workshop p.490).' });
    expect(exportContent("not base64!", "xlsx")).toEqual({
      problem: "A XLSX export is the file's bytes as base64, and this is not base64 "
        + "(Workshop p.490)." });
    expect(exportContent("abc", "docx")).toHaveProperty("problem");
    expect(exportContent("abc!", "docx")).toHaveProperty("problem");
  });
});
