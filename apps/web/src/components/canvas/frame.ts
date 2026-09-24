/**
 * The Iframe widget's rules, with no React in them (`workshop` p.545–547; §455).
 *
 * > "The Iframe widget enables embedding of external, full-page applications
 * > within Workshop, providing builders with a way to add custom views to
 * > their modules." (p.545)
 *
 * Two things live here because both are decisions a test should be able to
 * ask about without a browser: which URLs a frame may point at, and p.547's
 * YouTube conversion.
 */

import { safeMediaUrl } from "./media";

/** A URL this platform will put in an `<iframe src>`, or `null`.
 *
 * **`safeMediaUrl`'s rule plus one refusal**, rather than a second copy of the
 * scheme logic (§292). Everything that rule refuses is refused here for the
 * same reasons — `javascript:`, protocol-relative, every scheme that is not
 * `http`/`https` — and a relative path is still allowed, because that is how
 * a module frames one of this platform's own pages (p.547's "embedding
 * another Foundry application").
 *
 * **The one addition is every `data:` URL.** Media allows a data URL whose
 * type it renders inline, because an `<img>` cannot run what it is given. A
 * frame renders a *document*, whatever the declared type, and a data-URL
 * document is served with this app's origin behind it — which is the
 * `javascript:` case by a longer route, and exactly the thing an author who
 * binds this to a string variable would be handing to whoever controls that
 * variable.
 */
export function safeFrameUrl(raw: unknown): string | null {
  const value = safeMediaUrl(raw);
  if (value === null) return null;
  return /^data:/i.test(value) ? null : value;
}

/** Why a non-empty URL was refused, in a sentence a builder can act on.
 *
 * A frame that draws nothing for a refused URL looks exactly like one whose
 * page failed to load, and the two have different fixes (§214). */
export function frameRefusal(raw: unknown): string | null {
  const value = typeof raw === "string" ? raw.trim() : "";
  if (!value || safeFrameUrl(value) !== null) return null;
  if (/^data:/i.test(value)) {
    return "A data: URL is a document served as this app, so it cannot be framed.";
  }
  if (value.startsWith("//")) {
    return "Start the URL with https:// — a protocol-relative URL is refused.";
  }
  return "Only http:// and https:// URLs, or a path on this platform, can be framed.";
}

const WATCH = /^https?:\/\/(?:www\.|m\.)?youtube\.com\/watch\?(?:[^#]*&)?v=([A-Za-z0-9_-]{6,})/i;
const SHORT = /^https?:\/\/youtu\.be\/([A-Za-z0-9_-]{6,})/i;

/** p.547's conversion: "When pasting a standard YouTube URL (for example,
 * `https://www.youtube.com/watch?v=VIDEO_ID`), Workshop will detect the URL
 * format and offer a one-click option to convert it to the proper embedded
 * format (`https://www.youtube.com/embed/VIDEO_ID`) required for display in an
 * iframe."
 *
 * `null` when the URL is not one of the two shapes that needs converting —
 * including one that is *already* an embed URL, so the offer disappears once
 * it has been taken rather than offering to convert a URL into itself.
 *
 * `youtu.be` is the share button's form and the one people actually paste,
 * so it is read too; p.547's example is the other one and does not claim to
 * be the only one.
 */
export function youtubeEmbedUrl(raw: unknown): string | null {
  const value = typeof raw === "string" ? raw.trim() : "";
  const match = WATCH.exec(value) ?? SHORT.exec(value);
  return match ? `https://www.youtube.com/embed/${match[1]}` : null;
}

/** What a frame is called, for a screen reader.
 *
 * An `<iframe>` with no `title` is announced as "frame" and nothing else, so
 * the widget always gives it one: the author's, or failing that the host it
 * points at, which is at least a true statement about what is inside. */
export function frameTitle(title: unknown, url: string): string {
  const said = typeof title === "string" ? title.trim() : "";
  if (said) return said;
  try {
    return new URL(url, "https://this.platform").host === "this.platform"
      ? "Embedded page"
      : `Embedded page from ${new URL(url).host}`;
  } catch {
    return "Embedded page";
  }
}
