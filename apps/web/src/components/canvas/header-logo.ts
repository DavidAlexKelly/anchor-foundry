/**
 * p.47–49's application logo *image*, and the collapsed-state image (§472).
 *
 * > "Enable an application logo by choosing an icon or uploading an image. …
 * > Image: Select an image from your Palantir resources or upload one from
 * > your computer. Customize the image height. Position the image: Choose
 * > left, center, or right for horizontal headers; choose top or bottom for
 * > vertical headers." (p.47)
 * >
 * > "Add a custom image for the collapsed state … To display a collapsed
 * > image, you must first set up a header image as outlined above. If you opt
 * > for an icon instead, the chosen icon will appear in the collapsed state."
 * > (p.48–49)
 */

export interface ImageRef {
  key: string;
  filename: string;
  content_type: string;
  size: number;
}

/** An uploaded image a header may show, or null. **Images only**: the
 * download route serves only its own allowlist inline, and a header asking
 * for a PDF would get a download link where a logo belongs. */
export function imageRefOf(raw: unknown): ImageRef | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Partial<ImageRef>;
  if (typeof r.key !== "string" || !r.key) return null;
  if (typeof r.content_type !== "string" || !r.content_type.startsWith("image/")) return null;
  return {
    key: r.key,
    filename: typeof r.filename === "string" ? r.filename : "",
    content_type: r.content_type,
    size: typeof r.size === "number" ? r.size : 0,
  };
}

export const HORIZONTAL_POSITIONS = ["left", "center", "right"] as const;
export const VERTICAL_POSITIONS = ["top", "bottom"] as const;

/** p.47's positions for this orientation, the first being where a logo goes
 * unless told otherwise - before the title, where the icon has always been. */
export function logoPositionsFor(orientation: unknown): readonly string[] {
  return orientation === "vertical" ? VERTICAL_POSITIONS : HORIZONTAL_POSITIONS;
}

/** A position valid for the orientation. A header switched from horizontal to
 * vertical keeps a `right` it can no longer use, and reads it as the default
 * rather than as nowhere. */
export function logoPositionOf(raw: unknown, orientation: unknown): string {
  const allowed = logoPositionsFor(orientation);
  return typeof raw === "string" && allowed.includes(raw) ? raw : allowed[0]!;
}

export const MIN_LOGO_HEIGHT = 12;
export const MAX_LOGO_HEIGHT = 120;
export const DEFAULT_LOGO_HEIGHT = 32;

/** p.47's "Customize the image height", in pixels, within a range a header
 * can hold. */
export function logoHeightOf(raw: unknown): number {
  const n = Math.round(Number(raw));
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_LOGO_HEIGHT;
  return Math.min(MAX_LOGO_HEIGHT, Math.max(MIN_LOGO_HEIGHT, n));
}

export type HeaderMark =
  | { kind: "image"; image: ImageRef }
  | { kind: "icon"; text: string }
  | null;

/**
 * What mark a header shows. An image wins over an icon, since uploading one
 * is the later and more deliberate choice. Collapsed, p.49's rules: the
 * collapsed image if there is one **and** a header image to go with it, else
 * the header image, else the icon.
 */
export function headerMark(opts: {
  icon: unknown;
  image: unknown;
  collapsedImage: unknown;
  collapsed: boolean;
}): HeaderMark {
  const image = imageRefOf(opts.image);
  const collapsedImage = imageRefOf(opts.collapsedImage);
  if (opts.collapsed && image && collapsedImage) return { kind: "image", image: collapsedImage };
  if (image) return { kind: "image", image };
  const text = String(opts.icon ?? "").trim().slice(0, 2);
  return text ? { kind: "icon", text } : null;
}
