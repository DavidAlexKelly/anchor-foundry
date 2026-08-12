/**
 * Which stored files this platform can *show* rather than hand over
 * (decision 0009, part 2; Foundry `object-views` p.10–11's "media reference →
 * dedicated media viewer").
 *
 * **There is no media reference type, and that is the decision.** Foundry's
 * media reference points into a media set, which we do not have; a type shaped
 * like one with nothing behind it would be a contract nobody honours. What was
 * actually missing was the renderer — an attachment holding a PNG drew a
 * download link, so the viewer row was blocked on display, not on storage.
 *
 * Pure because it is a rule, and the boundary `canvas/pure.ts` draws says a
 * rule gets a test that can make it fail.
 */

export type MediaKind = "image" | "video" | "audio" | "file";

/** The top-level media type, lowercased, with any `;` parameters dropped.
 *
 * `image/png; charset=binary` and `IMAGE/PNG` are the same thing, and a
 * renderer that compared the raw header would draw a download link for one and
 * a picture for the other.
 */
function topLevel(contentType: string): string {
  return contentType.split(";")[0]!.trim().toLowerCase();
}

/**
 * How a stored file should be presented.
 *
 * **Driven by the content type the upload recorded, not by the filename.** An
 * extension is a claim by whoever named the file; the content type is what the
 * platform stored, and it is the thing the browser will act on when the bytes
 * arrive. A file named `.png` that is really a PDF should not get an `<img>`
 * that fails to load.
 *
 * Anything unrecognised is `file`, which is the behaviour everything had
 * before this existed — so a type this does not know is a download link rather
 * than a broken player.
 */
export function mediaKind(contentType: string | null | undefined): MediaKind {
  if (!contentType) return "file";
  const type = topLevel(contentType);
  if (type.startsWith("image/")) {
    // SVG is an image the browser will happily execute script inside. It is
    // served from the attachment route, which is same-origin, so an inline
    // `<img>` is the one image case where "show it" carries a cost the others
    // do not - and a download link loses nothing that matters here.
    return type === "image/svg+xml" ? "file" : "image";
  }
  if (type.startsWith("video/")) return "video";
  if (type.startsWith("audio/")) return "audio";
  return "file";
}
