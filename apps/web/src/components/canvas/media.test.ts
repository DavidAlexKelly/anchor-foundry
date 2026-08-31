import { describe, expect, it } from "vitest";

import {
  DEFAULT_SOURCE, INLINE_TYPES, KINDS, SOURCES,
  attachmentOf, kindOf, kindOfUrl, labelOf, resolveMedia, safeMediaUrl,
  sizeLabel, sourceOf,
} from "./media";

/** p.363-364's Media Preview. */

const href = (a: { key: string }) => `/api/attachments/download?key=${a.key}`;

describe("p.363's media sources", () => {
  it("has the two this platform can serve, defaulting to a media string", () => {
    expect(Object.keys(SOURCES).sort()).toEqual(["attachment", "string"]);
    expect(DEFAULT_SOURCE).toBe("string");
    expect(sourceOf(undefined)).toBe("string");
    expect(sourceOf("attachment")).toBe("attachment");
  });

  it("falls back for a source this platform does not have", () => {
    // p.363's third is a **media reference property**, which needs Foundry's
    // media sets. Falling back to a media string rather than drawing nothing
    // means a document naming it shows an empty preview and a settings panel
    // that can be fixed, not a widget that has vanished.
    expect(sourceOf("media_reference")).toBe("string");
    expect(sourceOf(7)).toBe("string");
  });
});

describe("what a content type draws as", () => {
  it("knows the four kinds p.363 names, plus not knowing", () => {
    expect([...KINDS]).toEqual(["image", "video", "audio", "document", "unknown"]);
  });

  it("reads an image, a video and an audio type", () => {
    expect(kindOf("image/png")).toBe("image");
    expect(kindOf("video/mp4")).toBe("video");
    expect(kindOf("audio/mpeg")).toBe("audio");
  });

  it("ignores the parameters a content type carries", () => {
    expect(kindOf("image/jpeg; charset=binary")).toBe("image");
    expect(kindOf("  IMAGE/PNG  ")).toBe("image");
  });

  it("does not know an SVG, and that is the behaviour", () => {
    // An SVG is an image by every naming convention and a **document that can
    // carry script** by what it is. Absent from the allowlist, so it is a link
    // on screen rather than an element with the app's origin behind it.
    expect(kindOf("image/svg+xml")).toBe("unknown");
  });

  it("does not know a PDF", () => {
    // p.363 says "document media", and this platform serves one as a
    // download: a PDF can run script, and inline from the app's own origin is
    // the stored-XSS shape the download route exists to describe. Widening
    // that is the PDF Viewer's decision to make deliberately.
    expect(kindOf("application/pdf")).toBe("unknown");
  });

  it("does not know a type nobody declared", () => {
    for (const value of ["", "   ", null, undefined, 7, "nonsense"]) {
      expect(kindOf(value)).toBe("unknown");
    }
  });
});

describe("what a media string may be", () => {
  it("takes http and https", () => {
    expect(safeMediaUrl("https://example.test/a.png")).toBe("https://example.test/a.png");
    expect(safeMediaUrl("http://example.test/a.png")).toBe("http://example.test/a.png");
  });

  it("takes a relative path", () => {
    // The attachment route is one, so refusing these would refuse the
    // platform's own links.
    expect(safeMediaUrl("/api/workspaces/w/attachments/download?key=k"))
      .toBe("/api/workspaces/w/attachments/download?key=k");
  });

  it("refuses a javascript: URL", () => {
    // **The refusal that matters most.** An app author sets this and every
    // viewer's browser follows it.
    expect(safeMediaUrl("javascript:alert(1)")).toBeNull();
    expect(safeMediaUrl("  JavaScript:alert(1)  ")).toBeNull();
  });

  it("takes a data URL for a media type it renders", () => {
    const png = "data:image/png;base64,iVBORw0KGgo=";
    expect(safeMediaUrl(png)).toBe(png);
  });

  it("refuses a data URL for anything else", () => {
    // `data:text/html` is a document with the app's own origin behind it,
    // which is the javascript: case by a longer route.
    expect(safeMediaUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeMediaUrl("data:image/svg+xml,<svg onload=alert(1)>")).toBeNull();
    expect(safeMediaUrl("data:application/pdf;base64,JVBERi0=")).toBeNull();
  });

  it("refuses every other scheme rather than listing the bad ones", () => {
    // A list of *bad* schemes is a list somebody has to keep complete.
    for (const bad of ["file:///etc/passwd", "blob:https://x/y", "about:blank",
                       "vbscript:msgbox", "ftp://x/y"]) {
      expect(safeMediaUrl(bad)).toBeNull();
    }
  });

  it("refuses a protocol-relative URL", () => {
    // `//evil.test/x` has no scheme and is still a different origin.
    expect(safeMediaUrl("//evil.test/x.png")).toBeNull();
  });

  it("refuses nothing at all", () => {
    for (const empty of ["", "   ", null, undefined, 7]) {
      expect(safeMediaUrl(empty)).toBeNull();
    }
  });
});

describe("what a media string looks like it is", () => {
  it("reads a data URL's own type", () => {
    expect(kindOfUrl("data:video/mp4;base64,AAAA")).toBe("video");
  });

  it("reads a plain URL's extension", () => {
    expect(kindOfUrl("https://example.test/a/b.PNG")).toBe("image");
    expect(kindOfUrl("https://example.test/clip.mp4")).toBe("video");
    expect(kindOfUrl("/local/song.flac")).toBe("audio");
  });

  it("ignores a query string and a fragment", () => {
    expect(kindOfUrl("https://example.test/a.png?v=2#top")).toBe("image");
  });

  it("does not know a URL with no extension", () => {
    // **Not "image".** A URL nobody can classify is a link, not a picture
    // nobody can see - and a guess here draws a broken image icon and calls it
    // a preview.
    // A path with no dot **anywhere in the string**, which is the case the
    // fallback is actually for: `https://example.test/media/1234` has a dot in
    // its host, so it reaches the extension lookup and misses there instead.
    expect(kindOfUrl("/media/1234")).toBe("unknown");
    expect(kindOfUrl("https://example.test/media/1234")).toBe("unknown");
    expect(kindOfUrl("https://example.test/a.pdf")).toBe("unknown");
  });
});

describe("an attachment property's value", () => {
  it("reads the shape db 0029 stores", () => {
    expect(attachmentOf({
      key: " ws/attachments/1/a.png ", filename: " a.png ",
      content_type: "image/png", size: 1234,
    })).toEqual({
      key: "ws/attachments/1/a.png", filename: "a.png",
      contentType: "image/png", size: 1234,
    });
  });

  it("is nothing without a key", () => {
    // The key is the only part that can fetch anything; a value without one is
    // a property nobody has uploaded to.
    expect(attachmentOf({ filename: "a.png", content_type: "image/png" })).toBeNull();
    expect(attachmentOf({ key: "   " })).toBeNull();
  });

  it("is nothing for anything that is not an object", () => {
    // Each of these falls out on the key check rather than on a guard of its
    // own - and `null`/`undefined` are the two that would *throw* on the way
    // there, which is what the `?? {}` is for.
    for (const bad of [null, undefined, "a.png", 7, ["a"], true]) {
      expect(attachmentOf(bad)).toBeNull();
    }
  });

  it("survives a value missing everything but its key", () => {
    expect(attachmentOf({ key: "k" })).toEqual({
      key: "k", filename: "", contentType: "", size: null,
    });
  });

  it("refuses a size that is not a number", () => {
    expect(attachmentOf({ key: "k", size: "1234" })?.size).toBeNull();
    expect(attachmentOf({ key: "k", size: Number.NaN })?.size).toBeNull();
  });
});

describe("what the thing is called", () => {
  it("is the author's label when there is one", () => {
    expect(labelOf(" Site photo ", null, "https://x.test/a.png")).toBe("Site photo");
  });

  it("is an attachment's filename when there is not", () => {
    expect(labelOf("", { key: "k", filename: "roof.png", contentType: "", size: null }, null))
      .toBe("roof.png");
  });

  it("is a URL's last segment", () => {
    expect(labelOf(null, null, "https://x.test/a/b/roof.png")).toBe("roof.png");
    expect(labelOf(null, null, "https://x.test/a/b/roof.png?v=2")).toBe("roof.png");
  });

  it("is never empty", () => {
    // **This widget's whole content is one file**, so an empty `alt` would
    // make it invisible to a screen reader rather than unobtrusive.
    expect(labelOf(null, null, null)).toBe("Media");
    expect(labelOf(null, null, "data:image/png;base64,AAAA")).toBe("Media");
    expect(labelOf(null, null, "https://x.test/")).toBe("Media");
  });
});

describe("a size in words", () => {
  it("counts bytes, then rounds up the units", () => {
    expect(sizeLabel(512)).toBe("512 B");
    expect(sizeLabel(2048)).toBe("2.0 KB");
    expect(sizeLabel(14 * 1024 * 1024)).toBe("14 MB");
    expect(sizeLabel(3 * 1024 * 1024 * 1024)).toBe("3.0 GB");
  });

  it("says nothing when nothing knows", () => {
    for (const bad of [null, undefined, "1234", -1, Number.NaN]) {
      expect(sizeLabel(bad)).toBe("");
    }
  });
});

describe("resolving what to draw", () => {
  const png = { key: "k", filename: "a.png", content_type: "image/png", size: 900 };

  it("draws an attachment through the download route", () => {
    const got = resolveMedia({
      source: "attachment", url: null, attachment: png, label: null,
      attachmentHref: href,
    });
    expect(got).toEqual({
      kind: "image", url: "/api/attachments/download?key=k", size: 900,
      label: "a.png", problem: null,
    });
  });

  it("draws a media string as itself", () => {
    const got = resolveMedia({
      source: "string", url: "https://x.test/clip.mp4", attachment: null,
      label: null, attachmentHref: href,
    });
    expect(got.kind).toBe("video");
    expect(got.url).toBe("https://x.test/clip.mp4");
    expect(got.size).toBeNull();
  });

  it("says which of the four things went wrong", () => {
    // **A sentence rather than a boolean**, because these are four different
    // things for an author to fix and one empty box for all of them says none
    // of it.
    expect(resolveMedia({
      source: "string", url: "", attachment: null, label: null, attachmentHref: href,
    }).problem).toBe("No media string set");

    expect(resolveMedia({
      source: "string", url: "javascript:alert(1)", attachment: null, label: null,
      attachmentHref: href,
    }).problem).toBe("That media string is not one this platform will follow");

    expect(resolveMedia({
      source: "attachment", url: null, attachment: null, label: null,
      attachmentHref: href,
    }).problem).toBe("No attachment on this object");
  });

  it("never hands out a url it refused", () => {
    // The one invariant that matters: a `problem` and a `url` together would
    // mean the widget drew something the rule above rejected.
    for (const bad of ["javascript:alert(1)", "data:text/html,x", "", "//evil.test/a.png"]) {
      const got = resolveMedia({
        source: "string", url: bad, attachment: null, label: null, attachmentHref: href,
      });
      expect(got.url).toBeNull();
      expect(got.problem).not.toBeNull();
    }
  });

  it("keeps the author's label whichever source it came from", () => {
    for (const source of ["string", "attachment"]) {
      expect(resolveMedia({
        source, url: "https://x.test/a.png", attachment: png, label: "Roof",
        attachmentHref: href,
      }).label).toBe("Roof");
    }
  });

  it("draws an attachment whose type is not renderable as a link", () => {
    const got = resolveMedia({
      source: "attachment", url: null, label: null, attachmentHref: href,
      attachment: { key: "k", filename: "report.pdf", content_type: "application/pdf" },
    });
    // A url and a label, so the viewer gets a link — and `unknown`, so nothing
    // tries to play it. No problem, because there is nothing wrong with it.
    expect(got.kind).toBe("unknown");
    expect(got.url).toBe("/api/attachments/download?key=k");
    expect(got.label).toBe("report.pdf");
    expect(got.problem).toBeNull();
  });
});

describe("the inline allowlist", () => {
  it("names only types the server also serves inline", async () => {
    // `INLINE_TYPES` exists twice: here, deciding what the browser draws, and
    // in `routes/objects.py`, deciding what the server serves inline. **The
    // server is the one that matters** - it ignores the uploader's claim - so
    // a browser copy that drifted wider would draw a player for bytes arriving
    // as a download.
    const { readFileSync } = await import("node:fs");
    const source = readFileSync(
      new URL("../../../../api/src/routes/objects.py", import.meta.url), "utf8",
    );
    const block = /INLINE_CONTENT_TYPES = frozenset\(\{([\s\S]*?)\}\)/.exec(source);
    expect(block, "INLINE_CONTENT_TYPES not found - has it been renamed?").toBeTruthy();
    const onServer = [...(block?.[1] ?? "").matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(onServer.length).toBeGreaterThanOrEqual(10);
    expect(onServer.sort()).toEqual(Object.keys(INLINE_TYPES).sort());
  });
});
