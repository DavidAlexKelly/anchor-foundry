/** Files uploaded into a dataset that already exists (§746; `dataset-preview`
 *  p.10).
 *
 *  > "If the filename and schema of the new file are identical to a previous
 *  > upload, you can update data in the existing dataset. If the filename is
 *  > different from previous uploads, you can append data to an existing
 *  > dataset." (p.10)
 *
 *  The filename decides between the two, so the page can say which before the
 *  press - the server decides on the name it will store, which is
 *  `safeFilename`'s, so that is the name compared here. The columns are the
 *  server's to check: reading the file is the upload.
 */

/** `datasets.safe_filename`, the name a file is stored under. */
export function safeFilename(name: string): string {
  const base = name.split("/").pop()!.split("\\").pop()!;
  const cleaned = base.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[._]+|[._]+$/g, "");
  return (cleaned || "upload").slice(0, 120);
}

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
}

export interface UploadIntent {
  mode: "update" | "append" | "refused";
  /** The name it will be stored under. */
  filename: string;
  text: string;
}

/** What uploading `picked` into a dataset holding `held` will do. */
export function uploadIntent(held: string[], picked: string): UploadIntent {
  const filename = safeFilename(picked);
  const [first] = held;
  if (first === undefined) {
    return { mode: "refused", filename, text: "This dataset holds no uploaded file to add to." };
  }
  const kind = extension(first);
  if (extension(filename) !== kind) {
    // The server's refusal, said before the press.
    return {
      mode: "refused",
      filename,
      text: `This dataset's files are ${kind} files, so ${filename} cannot join them.`,
    };
  }
  if (held.includes(filename)) {
    return {
      mode: "update",
      filename,
      text: `Replaces ${filename} with this file. Its columns must be the same as the one it replaces.`,
    };
  }
  const others = held.length === 1 ? first : `${held.length} files`;
  return {
    mode: "append",
    filename,
    text: `Adds ${filename} beside ${others}. Its columns must be the same as theirs.`,
  };
}

/** What happened, once it has. */
export function uploadedText(result: {
  mode: "update" | "append";
  filename: string;
  dataset: { row_count: number; current_version: number };
}): string {
  const verb = result.mode === "update" ? "Replaced" : "Added";
  const rows = result.dataset.row_count;
  return `${verb} ${result.filename}. The dataset is version ${result.dataset.current_version}, ${rows} ${rows === 1 ? "row" : "rows"}.`;
}
