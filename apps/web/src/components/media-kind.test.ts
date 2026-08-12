import { describe, expect, it } from "vitest";
import { mediaKind } from "./media-kind";

describe("mediaKind", () => {
  it("shows images, video and audio", () => {
    expect(mediaKind("image/png")).toBe("image");
    expect(mediaKind("image/jpeg")).toBe("image");
    expect(mediaKind("video/mp4")).toBe("video");
    expect(mediaKind("audio/mpeg")).toBe("audio");
  });

  it("ignores case and content-type parameters", () => {
    // `image/png; charset=binary` and `IMAGE/PNG` are the same thing; a
    // renderer comparing the raw header would draw a picture for one and a
    // download link for the other.
    expect(mediaKind("IMAGE/PNG")).toBe("image");
    expect(mediaKind("image/png; charset=binary")).toBe("image");
    expect(mediaKind("  video/webm  ")).toBe("video");
  });

  it("leaves SVG as a download", () => {
    // An image the browser will execute script inside, served same-origin
    // from the attachment route. A download link loses nothing that matters.
    expect(mediaKind("image/svg+xml")).toBe("file");
  });

  it("falls back to a download for anything else", () => {
    // The behaviour everything had before this existed, so a type this does
    // not know is a link rather than a broken player.
    expect(mediaKind("application/pdf")).toBe("file");
    expect(mediaKind("text/csv")).toBe("file");
    expect(mediaKind("application/octet-stream")).toBe("file");
  });

  it("falls back when there is no content type at all", () => {
    expect(mediaKind(null)).toBe("file");
    expect(mediaKind(undefined)).toBe("file");
    expect(mediaKind("")).toBe("file");
  });

  it("does not treat a lookalike prefix as media", () => {
    // "imagery/..." starts with "image" but is not "image/".
    expect(mediaKind("imagery/tiff")).toBe("file");
  });
});
