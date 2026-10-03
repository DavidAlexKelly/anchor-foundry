/** p.489's Excel export, as bytes (§787). */
import { describe, expect, it } from "vitest";

import {
  columnName, crc32, sheetName, sheetXml, storedZip, xlsxOf, xmlText,
} from "./xlsx";

/** The files a stored zip holds, read from its central directory - so the
 * offsets and sizes it records are checked, not only the order it wrote. */
function unzip(bytes: Uint8Array): Map<string, string> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const end = bytes.length - 22;
  expect(view.getUint32(end, true)).toBe(0x06054b50);
  const count = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  const out = new Map<string, string>();
  const decoder = new TextDecoder();
  for (let i = 0; i < count; i++) {
    expect(view.getUint32(at, true)).toBe(0x02014b50);
    const crc = view.getUint32(at + 16, true);
    const size = view.getUint32(at + 24, true);
    const nameLength = view.getUint16(at + 28, true);
    const offset = view.getUint32(at + 42, true);
    const name = decoder.decode(bytes.subarray(at + 46, at + 46 + nameLength));
    expect(view.getUint32(offset, true)).toBe(0x04034b50);
    expect(view.getUint16(offset + 8, true)).toBe(0);
    expect(view.getUint32(offset + 14, true)).toBe(crc);
    const start = offset + 30 + view.getUint16(offset + 26, true);
    const data = bytes.subarray(start, start + size);
    expect(crc32(data)).toBe(crc);
    out.set(name, decoder.decode(data));
    at += 46 + nameLength;
  }
  return out;
}

describe("the zip", () => {
  it("is the zip format's CRC-32", () => {
    expect(crc32(new TextEncoder().encode("hello"))).toBe(0x3610a686);
    expect(crc32(new Uint8Array())).toBe(0);
  });

  it("holds each file where its directory says", () => {
    const enc = new TextEncoder();
    const files = unzip(storedZip([["a.txt", enc.encode("one")], ["b/c.xml", enc.encode("two")]]));
    expect([...files.entries()]).toEqual([["a.txt", "one"], ["b/c.xml", "two"]]);
  });
});

describe("the workbook", () => {
  it("has the parts Excel opens, with one sheet named for the type", () => {
    const parts = unzip(xlsxOf("Sites", [["Key"], ["S1"]]));
    expect([...parts.keys()]).toEqual([
      "[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
      "xl/worksheets/sheet1.xml"]);
    expect(parts.get("[Content_Types].xml")).toContain(
      'PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"');
    expect(parts.get("[Content_Types].xml")).toContain(
      'PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"');
    expect(parts.get("_rels/.rels")).toContain('Target="xl/workbook.xml"');
    expect(parts.get("xl/_rels/workbook.xml.rels")).toContain('Target="worksheets/sheet1.xml"');
    expect(parts.get("xl/workbook.xml")).toContain('<sheet name="Sites" sheetId="1" r:id="rId1"/>');
  });

  it("names a sheet as Excel allows", () => {
    expect(sheetName("Plan [draft]: a/b")).toBe("Plan  draft   a b");
    expect(sheetName("x".repeat(40))).toHaveLength(31);
    expect(sheetName(" ?* ")).toBe("Sheet1");
  });
});

describe("the sheet", () => {
  it("writes text as text, numbers and booleans as themselves, and nothing as no cell", () => {
    expect(sheetXml([["Key", "Count", "Open", "Note"], ["S1", 12.5, true, null]]))
      .toContain('<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Key</t></is></c>'
        + '<c r="B1" t="inlineStr"><is><t>Count</t></is></c>'
        + '<c r="C1" t="inlineStr"><is><t>Open</t></is></c>'
        + '<c r="D1" t="inlineStr"><is><t>Note</t></is></c></row>'
        + '<row r="2"><c r="A2" t="inlineStr"><is><t>S1</t></is></c><c r="B2"><v>12.5</v></c>'
        + '<c r="C2" t="b"><v>1</v></c></row></sheetData>');
    expect(sheetXml([[false, "", undefined]])).toContain(
      '<row r="1"><c r="A1" t="b"><v>0</v></c></row>');
  });

  it("keeps a formula as the text it was, and escapes what XML would read", () => {
    expect(sheetXml([['=HYPERLINK("x")', "a<b & c"]])).toContain(
      '<t>=HYPERLINK(&quot;x&quot;)</t></is></c><c r="B1" t="inlineStr"><is><t>a&lt;b &amp; c</t>');
  });

  it("keeps the spaces at a value's ends, and writes a number with no cell as text", () => {
    expect(sheetXml([[" x", Infinity]])).toContain(
      '<t xml:space="preserve"> x</t></is></c><c r="B1" t="inlineStr"><is><t>Infinity</t>');
  });

  it("escapes the one sequence character data may not hold", () => {
    expect(xmlText("a]]>b")).toBe("a]]&gt;b");
  });

  it("drops the characters XML cannot hold, and keeps tabs and line breaks", () => {
    expect(xmlText("a\u0001b\u000Bc\td\ne\u0000")).toBe("abc\td\ne");
  });

  it("names columns past Z", () => {
    expect([0, 25, 26, 27, 51, 52, 701, 702].map(columnName))
      .toEqual(["A", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA"]);
  });
});
