import { describe, expect, it } from "vitest";

import { frameRefusal, frameTitle, safeFrameUrl, youtubeEmbedUrl } from "./frame";

describe("safeFrameUrl", () => {
  it("allows an http or https URL", () => {
    expect(safeFrameUrl("https://example.test/app")).toBe("https://example.test/app");
    expect(safeFrameUrl("http://example.test/app")).toBe("http://example.test/app");
  });

  it("allows a path on this platform, which is p.547's case", () => {
    // "When embedding another Foundry application" — a relative path resolves
    // against this app's own origin.
    expect(safeFrameUrl("/acme/explore?embedded=true")).toBe("/acme/explore?embedded=true");
  });

  it("refuses every data: URL, including one media would allow", () => {
    // **The one difference from `safeMediaUrl`.** An image data URL is safe in
    // an <img>; in a frame it is a document served as this app.
    expect(safeFrameUrl("data:image/png;base64,iVBORw0KGgo=")).toBeNull();
    expect(safeFrameUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
  });

  it("refuses what the media rule refuses", () => {
    for (const bad of ["javascript:alert(1)", "//evil.test/x", "file:///etc/passwd",
      "about:blank", "", "   ", null, 42]) {
      expect(safeFrameUrl(bad)).toBeNull();
    }
  });
});

describe("frameRefusal", () => {
  it("says nothing for an allowed URL or an empty one", () => {
    // An empty frame is "not set yet", which the widget says differently.
    expect(frameRefusal("https://example.test")).toBeNull();
    expect(frameRefusal("")).toBeNull();
  });

  it("names the data: case", () => {
    expect(frameRefusal("data:text/html,x")).toContain("data:");
  });

  it("names the protocol-relative case with its fix", () => {
    expect(frameRefusal("//example.test")).toContain("https://");
  });

  it("names the scheme rule for everything else", () => {
    expect(frameRefusal("javascript:alert(1)")).toContain("http");
  });
});

describe("youtubeEmbedUrl", () => {
  it("converts p.547's own example", () => {
    expect(youtubeEmbedUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
      .toBe("https://www.youtube.com/embed/dQw4w9WgXcQ");
  });

  it("reads the video id wherever it sits in the query", () => {
    expect(youtubeEmbedUrl("https://www.youtube.com/watch?list=PL1&v=dQw4w9WgXcQ&t=30"))
      .toBe("https://www.youtube.com/embed/dQw4w9WgXcQ");
  });

  it("converts the share button's short form", () => {
    expect(youtubeEmbedUrl("https://youtu.be/dQw4w9WgXcQ"))
      .toBe("https://www.youtube.com/embed/dQw4w9WgXcQ");
  });

  it("offers nothing for an embed URL, so the offer goes once taken", () => {
    expect(youtubeEmbedUrl("https://www.youtube.com/embed/dQw4w9WgXcQ")).toBeNull();
  });

  it("offers nothing for any other URL", () => {
    expect(youtubeEmbedUrl("https://example.test/watch?v=dQw4w9WgXcQ")).toBeNull();
    expect(youtubeEmbedUrl("")).toBeNull();
  });
});

describe("frameTitle", () => {
  it("uses the author's title", () => {
    expect(frameTitle("Weather", "https://example.test")).toBe("Weather");
  });

  it("falls back to the host, which is a true statement about the content", () => {
    expect(frameTitle("  ", "https://example.test/a/b")).toBe("Embedded page from example.test");
  });

  it("does not claim a host for a path on this platform", () => {
    expect(frameTitle("", "/acme/explore")).toBe("Embedded page");
  });
});
