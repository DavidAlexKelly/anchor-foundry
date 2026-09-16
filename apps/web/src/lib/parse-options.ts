/**
 * Reading an uploaded file again with different options
 * (§362; `dataset-preview` p.14, p.24-27).
 *
 * > "Here, users can also apply additional parsing options to drop jagged
 * >  rows, change encoding, or add additional columns like file path, byte
 * >  offset for row, import timestamp, or row number." (p.14)
 *
 * Pure, and in `lib/` rather than beside the panel, because vitest cannot
 * parse `.tsx`: a rule that lives in a component is a rule with no unit test.
 *
 * **The defaults are "what the upload already did", not "nothing".** p.24's
 * whole framing is that Foundry infers a sensible set and you correct it, so a
 * form that opened blank would be asking somebody to re-derive a parse that
 * already worked well enough to produce the table they are looking at.
 */

export type ParseOptions = {
  delimiter: string | null;
  quote: string | null;
  header: boolean;
  skip_lines: number;
  null_values: string[];
  drop_bad_rows: boolean;
  encoding: string;
  add_file_path: boolean;
  add_imported_at: boolean;
  add_row_number: boolean;
};

/** The character sets the server will decode from, in its order. */
export const ENCODINGS = [
  "utf-8",
  "utf-8-sig",
  "latin-1",
  "cp1252",
  "utf-16",
] as const;

export const DEFAULT_OPTIONS: ParseOptions = {
  delimiter: null,
  quote: null,
  header: true,
  skip_lines: 0,
  null_values: [],
  drop_bad_rows: false,
  encoding: "utf-8",
  add_file_path: false,
  add_imported_at: false,
  add_row_number: false,
};

/**
 * Why this dataset cannot be parsed again, or `""` when it can.
 *
 * The server refuses both of these too, and that refusal is the one that
 * counts; this exists so the panel is absent rather than present-and-failing,
 * which is the difference between a screen that does not offer something and
 * one that offers it and then apologises (§214).
 *
 * **Two different reasons, not one.** "Nothing uploaded this" is a permanent
 * property of a model output or a synced dataset, and the honest thing to say
 * is that it is rebuilt by whatever produces it. "Uploaded before the name was
 * recorded" is a gap in this platform's own history (db 0090) with a way out —
 * upload the file again — and saying so beats a single vague sentence that
 * fits neither.
 */
export function whyNotParseable(dataset: {
  origin: string;
  original_filename?: string | null;
}): string {
  if (dataset.origin !== "upload") {
    return `This dataset comes from a ${dataset.origin}, so there is no uploaded file to read again — it is rebuilt by whatever produces it.`;
  }
  if (!dataset.original_filename) {
    return "This dataset was uploaded before the original file was recorded, so it cannot be parsed again. Uploading the file again makes one that can be.";
  }
  return "";
}

/**
 * What these options change, as sentences, or `[]` when they change nothing.
 *
 * **Apply is the dangerous button here**, because a re-parse writes a version
 * and the difference between two parses of the same file can be invisible in a
 * hundred-row preview — a `nullValues` change retypes a column, and the rows
 * still look the same. So the panel says what it is about to do in words, from
 * the options rather than from the preview.
 *
 * Empty means the parse is the one that already ran, which is a legitimate
 * state (somebody undid their edits) and reads as "nothing to apply".
 */
export function describeOptions(options: ParseOptions): string[] {
  const said: string[] = [];
  if (options.delimiter) said.push(`fields split on "${options.delimiter}"`);
  if (options.quote) said.push(`fields quoted with "${options.quote}"`);
  if (!options.header) said.push("the first row is data, not column names");
  if (options.skip_lines > 0) {
    said.push(
      `the first ${options.skip_lines} ${options.skip_lines === 1 ? "line" : "lines"} skipped`,
    );
  }
  if (options.null_values.length > 0) {
    said.push(`${options.null_values.map((v) => `"${v}"`).join(", ")} read as empty`);
  }
  if (options.drop_bad_rows) said.push("rows that do not fit are dropped");
  if (options.encoding !== DEFAULT_OPTIONS.encoding) {
    said.push(`decoded as ${options.encoding}`);
  }
  if (options.add_file_path) said.push("a file path column added");
  if (options.add_imported_at) said.push("an import time column added");
  if (options.add_row_number) said.push("a row number column added");
  return said;
}

/**
 * The null markers as typed, one per line, turned into the list the server
 * takes — and back.
 *
 * A textarea rather than a tag input because the values are things like `NA`,
 * `\\N`, `-` and `NULL`, and a comma-separated box cannot express a marker
 * that *is* a comma. One per line can.
 *
 * Blank lines are dropped rather than sent: `nullstr` with an empty string in
 * it is a real instruction ("treat empty as null") and not what somebody
 * pressing Enter twice meant, so it has to be asked for deliberately if it is
 * ever offered at all.
 */
export function parseNullMarkers(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}
