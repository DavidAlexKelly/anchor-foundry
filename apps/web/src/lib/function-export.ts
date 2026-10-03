/**
 * A function-backed export (Workshop p.489-490; §775; decision 0018 option B).
 *
 * > "Function-backed exports take a Function and its inputs, and download the
 * > output into a specified file type. Supported file types are CSV, TXT,
 * > JSON, XML, PDF, DOCX, and XLSX." (p.489)
 *
 * > "The Function output must be a string … Text-based formats (CSV, TXT,
 * > JSON, XML): … a plain string representing the file content. Binary
 * > formats (PDF, DOCX, XLSX): … a base64-encoded string of the file bytes. …
 * > Do not include a MIME type prefix … or the export will fail to download.
 * > Workshop infers the MIME type from the file type selected" (p.490)
 *
 * A SQL function writes text with `string_agg` and bytes with `base64(...)`.
 */

export const EXPORT_FILE_TYPES = ["csv", "txt", "json", "xml", "pdf", "docx", "xlsx"] as const;
export type ExportFileType = (typeof EXPORT_FILE_TYPES)[number];

const MIME: Record<ExportFileType, string> = {
  csv: "text/csv",
  txt: "text/plain",
  json: "application/json",
  xml: "application/xml",
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

const BINARY: ReadonlySet<ExportFileType> = new Set(["pdf", "docx", "xlsx"]);

export function isExportFileType(value: unknown): value is ExportFileType {
  return (EXPORT_FILE_TYPES as readonly unknown[]).includes(value);
}

export function mimeOf(type: ExportFileType): string {
  return MIME[type];
}

export function isBinary(type: ExportFileType): boolean {
  return BINARY.has(type);
}

/** The file's name: the one configured, or "export", with the type's
 * extension added when it does not already end in it. */
export function exportFileName(name: string | null | undefined, type: ExportFileType): string {
  const base = (name ?? "").trim() || "export";
  return base.toLowerCase().endsWith(`.${type}`) ? base : `${base}.${type}`;
}

const BASE64_RE = /^[A-Za-z0-9+/]*={0,2}$/;

/** The file's bytes or text from the function's answer, or the reason it
 * cannot be one - p.490's two encodings, and its refusal of a MIME prefix. */
export function exportContent(
  answer: unknown,
  type: ExportFileType,
): { content: string | Uint8Array } | { problem: string } {
  if (typeof answer !== "string") {
    return { problem: "The function must return a string to export (Workshop p.490)." };
  }
  if (!isBinary(type)) return { content: answer };
  if (answer.startsWith("data:")) {
    return { problem: `Return the ${type.toUpperCase()} bytes as base64 without a "data:" `
      + "prefix (Workshop p.490)." };
  }
  const compact = answer.replace(/\s+/g, "");
  if (compact.length % 4 !== 0 || !BASE64_RE.test(compact)) {
    return { problem: `A ${type.toUpperCase()} export is the file's bytes as base64, and this `
      + "is not base64 (Workshop p.490)." };
  }
  const raw = atob(compact);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return { content: bytes };
}
