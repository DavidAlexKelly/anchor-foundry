/**
 * An Excel workbook of one sheet, for p.489's Export event (`workshop` p.489;
 * §787).
 *
 * > "Export events take an object set variable as an input and trigger the
 * > export of the objects in the object set to either Excel or the user's
 * > clipboard." (p.489)
 *
 * An `.xlsx` file is a zip of XML parts (ECMA-376). This writes the smallest
 * set Excel opens: the content types, the package and workbook relations, the
 * workbook, and one worksheet whose text is inline strings - no shared string
 * table and no styles, which a workbook may leave out. The zip is **stored**,
 * not deflated: a reader must accept method 0, and it spares this file a
 * compressor.
 *
 * **A string is never a formula here.** An inline string cell is text by its
 * type, so `=HYPERLINK(...)` typed into a property is shown as typed - the
 * apostrophe CSV needs (`object-export.csvCell`) has nothing to do.
 *
 * Pure, so the bytes can be checked without a browser.
 */

export type XlsxCell = string | number | boolean | null | undefined;

const MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships";
const XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';

/** Text as XML character data. Control characters XML 1.0 cannot hold at all
 * are dropped; tab and line breaks stay. */
export function xmlText(value: string): string {
  return value
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]/g, "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** A column's letters: 0 is A, 25 Z, 26 AA. */
export function columnName(index: number): string {
  let name = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  }
  return name;
}

function cell(value: XlsxCell, ref: string): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number") {
    // Infinity and NaN have no cell; they are written as the text they are.
    if (Number.isFinite(value)) return `<c r="${ref}"><v>${value}</v></c>`;
    value = String(value);
  }
  if (typeof value === "boolean") return `<c r="${ref}" t="b"><v>${value ? 1 : 0}</v></c>`;
  const keep = /^\s|\s$/.test(value) ? ' xml:space="preserve"' : "";
  return `<c r="${ref}" t="inlineStr"><is><t${keep}>${xmlText(value)}</t></is></c>`;
}

/** The worksheet part: one row per array, the first being the header. */
export function sheetXml(rows: readonly (readonly XlsxCell[])[]): string {
  const body = rows.map((row, r) => `<row r="${r + 1}">${
    row.map((v, c) => cell(v, `${columnName(c)}${r + 1}`)).join("")}</row>`).join("");
  return `${XML_HEAD}<worksheet xmlns="${MAIN}"><sheetData>${body}</sheetData></worksheet>`;
}

/** A sheet's name as Excel takes one: at most 31 characters, none of
 * `[]:*?/\`, and not empty. */
export function sheetName(name: string): string {
  return name.replace(/[[\]:*?/\\]/g, " ").trim().slice(0, 31).trim() || "Sheet1";
}

/** The workbook's parts, by their path in the package. */
export function workbookParts(name: string, rows: readonly (readonly XlsxCell[])[]):
    [string, string][] {
  return [
    ["[Content_Types].xml", `${XML_HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      + '<Default Extension="xml" ContentType="application/xml"/>'
      + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      + '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
      + "</Types>"],
    ["_rels/.rels", `${XML_HEAD}<Relationships xmlns="${PKG_REL}">`
      + `<Relationship Id="rId1" Type="${REL}/officeDocument" Target="xl/workbook.xml"/>`
      + "</Relationships>"],
    ["xl/workbook.xml", `${XML_HEAD}<workbook xmlns="${MAIN}" xmlns:r="${REL}"><sheets>`
      + `<sheet name="${xmlText(sheetName(name))}" sheetId="1" r:id="rId1"/></sheets></workbook>`],
    ["xl/_rels/workbook.xml.rels", `${XML_HEAD}<Relationships xmlns="${PKG_REL}">`
      + `<Relationship Id="rId1" Type="${REL}/worksheet" Target="worksheets/sheet1.xml"/>`
      + "</Relationships>"],
    ["xl/worksheets/sheet1.xml", sheetXml(rows)],
  ];
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

/** The zip format's CRC-32 of some bytes. */
export function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const b of bytes) crc = CRC_TABLE[(crc ^ b) & 0xff]! ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** A zip of these files, stored rather than compressed. */
export function storedZip(files: readonly [string, Uint8Array][]): Uint8Array {
  const encoder = new TextEncoder();
  const chunks: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  for (const [path, data] of files) {
    const name = encoder.encode(path);
    const crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true); // version needed: 2.0
    local.setUint16(8, 0, true); // method: stored
    local.setUint16(12, 0x21, true); // 1980-01-01, a date every reader takes
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, name.length, true);
    const entry = new DataView(new ArrayBuffer(46));
    entry.setUint32(0, 0x02014b50, true);
    entry.setUint16(4, 20, true);
    entry.setUint16(6, 20, true);
    entry.setUint16(14, 0x21, true);
    entry.setUint32(16, crc, true);
    entry.setUint32(20, data.length, true);
    entry.setUint32(24, data.length, true);
    entry.setUint16(28, name.length, true);
    entry.setUint32(42, offset, true);
    chunks.push(new Uint8Array(local.buffer), name, data);
    central.push(new Uint8Array(entry.buffer), name);
    offset += 30 + name.length + data.length;
  }
  const size = central.reduce((n, c) => n + c.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, size, true);
  end.setUint32(16, offset, true);
  const all = [...chunks, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(all.reduce((n, c) => n + c.length, 0));
  let at = 0;
  for (const c of all) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}

/** The `.xlsx` file: a sheet named `name` holding `rows`, the first a header. */
export function xlsxOf(name: string, rows: readonly (readonly XlsxCell[])[]): Uint8Array {
  const encoder = new TextEncoder();
  return storedZip(workbookParts(name, rows).map(([path, xml]) => [path, encoder.encode(xml)]));
}

export const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
