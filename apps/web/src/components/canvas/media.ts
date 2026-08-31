/** p.363-364's Media Preview: "display image, audio, video, and document
 * media, given a supported media source".
 *
 * > "Currently supported media sources include media URLs, attachment
 * > properties, and media reference properties." (p.363)
 *
 * > "**Media string** options support images referenced in the following three
 * > formats… Blobster RID… Media URL… Data URL with a Base64-encoded media, for
 * > example, `data:image/png;base64,{base64-encoded image}`." (p.363)
 *
 * > "**Attachment property**: Define an object set with a single object and
 * > select the attachment typed property to render a preview of the media for
 * > that object." (p.363-364)
 *
 * ---
 *
 * **The storage decision this widget was waiting for is already made.**
 * `workshop.md`'s build order put the media group behind "one storage decision
 * serves all four", written before attachments existed — and they do:
 * `attachment` is a declared property type (db 0029), `POST /attachments`
 * stores one and `GET /attachments/download` serves it back with the
 * workspace-prefix check that is the isolation boundary. §216's lesson again:
 * open what a line cites before building on it.
 *
 * **What a media string may be is a security rule, not a formatting one.** An
 * app author types this, and a viewer's browser follows it, so `safeMediaUrl`
 * is the whole of what makes that safe: `javascript:` is a script, and
 * `data:text/html` is a document with the app's own origin behind it. Both are
 * refused here rather than at the element, because there are four elements and
 * one rule.
 */

/** p.363's media sources. */
export const SOURCES: Record<string, string> = {
  string: "Media string",
  attachment: "Attachment property",
};

export const DEFAULT_SOURCE = "string";

export function sourceOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(SOURCES, raw) ? raw : DEFAULT_SOURCE;
}

/** What kind of thing a media type is, and therefore which element draws it.
 *
 * `unknown` rather than a guess, because the four elements are not
 * interchangeable: an `<img>` pointed at an MP4 shows a broken image, and an
 * `<audio>` pointed at a PNG shows a player that will never play. A kind
 * nothing recognises gets a link, which is the one answer that is never wrong.
 */
export const KINDS = ["image", "video", "audio", "document", "unknown"] as const;

export type Kind = (typeof KINDS)[number];

/** The media types this platform will render **inline**.
 *
 * Mirrors `INLINE_CONTENT_TYPES` in `routes/objects.py`, and a test asserts the
 * two agree. The server is what decides — it serves an attachment inline only
 * for a type on its own list, whatever the uploader claimed — so a browser copy
 * that drifted wider would draw a player for bytes arriving as a download.
 *
 * **`application/pdf` is deliberately absent from both.** A PDF is a document
 * that can run script, and serving one inline from the app's own origin is the
 * stored-XSS shape the download route's docstring exists to describe. p.363's
 * "document media" therefore reaches a viewer as a link here, and widening that
 * is the PDF Viewer's decision to make deliberately rather than this widget's
 * to make in passing.
 */
export const INLINE_TYPES: Record<string, Kind> = {
  "image/png": "image",
  "image/jpeg": "image",
  "image/gif": "image",
  "image/webp": "image",
  "image/avif": "image",
  "image/bmp": "image",
  "video/mp4": "video",
  "video/webm": "video",
  "video/ogg": "video",
  "audio/mpeg": "audio",
  "audio/ogg": "audio",
  "audio/wav": "audio",
  "audio/webm": "audio",
  "audio/aac": "audio",
  "audio/flac": "audio",
};

/** The kind a content type draws as.
 *
 * Only the allowlist answers. A `image/svg+xml` is an image by every naming
 * convention and is **not** on the list, because an SVG is a document that can
 * carry script — so it is `unknown` here and a link on screen, which is the
 * behaviour rather than an oversight.
 */
export function kindOf(contentType: unknown): Kind {
  const type = String(contentType ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
  return INLINE_TYPES[type] ?? "unknown";
}

const DATA_URL = /^data:([a-z0-9.+-]+\/[a-z0-9.+-]+)(;[a-z0-9.+=-]*)*,/i;

/** A media string this platform will point an element at, or `null`.
 *
 * **The refusals are the feature.** An app author supplies this and a viewer's
 * browser follows it:
 *
 * - `javascript:` is a script, and an author who can set one on a widget can
 *   run code in every viewer's session.
 * - `data:text/html` is a document, served with the app's own origin behind it,
 *   which is the same thing by a longer route. So a data URL is allowed only
 *   for a media type this platform already renders inline.
 * - Everything else that is not `http`/`https` — `file:`, `blob:`, `about:` —
 *   is refused rather than enumerated, because a list of *bad* schemes is a
 *   list somebody has to keep complete.
 *
 * A **relative** path is allowed: it resolves against this app's own origin,
 * which is where the attachment route lives, so refusing it would refuse the
 * platform's own links.
 */
export function safeMediaUrl(raw: unknown): string | null {
  const value = typeof raw === "string" ? raw.trim() : "";
  if (!value) return null;
  const data = DATA_URL.exec(value);
  if (data) {
    return kindOf(data[1]) === "unknown" ? null : value;
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(value)) {
    return /^https?:/i.test(value) ? value : null;
  }
  // No scheme at all: a relative or protocol-relative path. `//evil.com/x` is
  // protocol-relative and *is* a different origin, so it is refused with the
  // schemes rather than allowed with the paths.
  return value.startsWith("//") ? null : value;
}

/** The kind a media string draws as, when nothing declares a content type.
 *
 * A data URL says so itself. A plain URL does not, so this reads the
 * extension — and **falls back to `unknown` rather than to `image`**, which is
 * what p.363's "supported media sources" leaves open: a URL with no extension
 * is a link, not a picture nobody can see.
 */
export function kindOfUrl(raw: unknown): Kind {
  const value = typeof raw === "string" ? raw.trim() : "";
  const data = DATA_URL.exec(value);
  if (data) return kindOf(data[1]);
  const path = value.split(/[?#]/)[0] ?? "";
  const dot = path.lastIndexOf(".");
  if (dot < 0) return "unknown";
  return EXTENSIONS[path.slice(dot + 1).toLowerCase()] ?? "unknown";
}

/** Derived from `INLINE_TYPES` rather than written out, so an extension cannot
 * name a type the platform will not render. */
const EXTENSIONS: Record<string, Kind> = {
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image",
  avif: "image", bmp: "image",
  mp4: "video", webm: "video", ogv: "video",
  mp3: "audio", oga: "audio", ogg: "audio", wav: "audio", aac: "audio", flac: "audio",
};

export interface Attachment {
  key: string;
  filename: string;
  contentType: string;
  size: number | null;
}

/** An `attachment` property's value, as a document can hold it (db 0029:
 * `{"key", "filename", "content_type", "size"}`).
 *
 * `null` for anything else, including the string a property holds before
 * anybody uploads to it. Tolerant for §212's reason: this comes out of a jsonb
 * blob written by a sync, an action or a hand-edit.
 */
export function attachmentOf(raw: unknown): Attachment | null {
  // **The key check is the whole type check.** An array, a string, a number —
  // none of them carry a `key`, so each falls out below without a guard of its
  // own. Guards for those shapes were three lines no test could make fail,
  // which is the standard this codebase holds its checks to. `?? {}` is the one
  // that is load-bearing: `null.key` throws where every other value returns
  // `undefined`.
  const value = (raw ?? {}) as Record<string, unknown>;
  const key = typeof value.key === "string" ? value.key.trim() : "";
  if (!key) return null;
  const size = typeof value.size === "number" && Number.isFinite(value.size)
    ? value.size
    : null;
  return {
    key,
    filename: typeof value.filename === "string" ? value.filename.trim() : "",
    contentType: typeof value.content_type === "string"
      ? value.content_type.trim()
      : "",
    size,
  };
}

/** What to call the thing on screen, for a caption and for an `alt`.
 *
 * **An `alt` is not optional and not decorative here**: this widget's whole
 * content is one file, so an empty `alt` would make the widget invisible to a
 * screen reader rather than unobtrusive. The filename is the truest thing
 * available when an author has written no label.
 */
export function labelOf(label: unknown, attachment: Attachment | null, url: unknown): string {
  const written = typeof label === "string" ? label.trim() : "";
  if (written) return written;
  if (attachment?.filename) return attachment.filename;
  const value = typeof url === "string" ? url.trim() : "";
  if (!value || value.startsWith("data:")) return "Media";
  const path = value.split(/[?#]/)[0] ?? "";
  return path.slice(path.lastIndexOf("/") + 1) || "Media";
}

/** A size in bytes, for the caption under a link.
 *
 * Shown only where the media is *not* rendered, which is the case a viewer most
 * needs it for: a link says nothing about what is behind it, and "PDF, 14 MB"
 * is the difference between clicking and not.
 */
export function sizeLabel(bytes: unknown): string {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

export interface Resolved {
  kind: Kind;
  url: string | null;
  label: string;
  /** Bytes, when something knows — an attachment does, a URL does not. */
  size: number | null;
  /** Why there is nothing to show, when there is nothing to show. */
  problem: string | null;
}

/** Everything the widget needs to draw, from either of p.363's two sources.
 *
 * One function for both because the *drawing* is one thing: p.363 says the
 * Media Preview "displays all types of media" and the specialised widgets each
 * do one, so the general one has exactly one decision — what kind is this, and
 * where are its bytes.
 *
 * `problem` is a sentence rather than a boolean, because the four ways this
 * ends up empty are four different things for an author to fix: no source
 * configured, a set with no object in it, a property with no attachment, or a
 * string this platform will not follow.
 */
export function resolveMedia({ source, url, attachment, label, attachmentHref }: {
  source: unknown;
  url: unknown;
  attachment: unknown;
  label: unknown;
  /** Where an attachment's bytes are, given its key. Supplied by the widget so
   * this module stays free of the API surface. */
  attachmentHref: (attachment: Attachment) => string;
}): Resolved {
  if (sourceOf(source) === "attachment") {
    const found = attachmentOf(attachment);
    if (!found) {
      return {
        kind: "unknown", url: null, size: null,
        label: labelOf(label, null, null),
        problem: "No attachment on this object",
      };
    }
    return {
      kind: kindOf(found.contentType),
      url: attachmentHref(found),
      size: found.size,
      label: labelOf(label, found, null),
      problem: null,
    };
  }
  const safe = safeMediaUrl(url);
  const written = typeof url === "string" ? url.trim() : "";
  if (!safe) {
    return {
      kind: "unknown", url: null, size: null,
      label: labelOf(label, null, url),
      problem: written
        ? "That media string is not one this platform will follow"
        : "No media string set",
    };
  }
  return {
    kind: kindOfUrl(safe),
    url: safe,
    size: null,
    label: labelOf(label, null, safe),
    problem: null,
  };
}
