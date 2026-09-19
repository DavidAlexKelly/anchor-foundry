import { afterEach, describe, expect, it, vi } from "vitest";
import { readerLanguages, readerLayout } from "./reader-layout";

afterEach(() => {
  vi.unstubAllGlobals();
});

function browser(languages?: readonly string[], language?: string) {
  vi.stubGlobal("navigator", { languages, language });
}

const DEFINITION = {
  format: 2,
  layout: {
    h: { type: { resolvedName: "CanvasHeader" }, props: { title: "Case review" } },
  },
  variables: {},
  events: {},
  translations: {
    enabled: true,
    source_language: "en",
    languages: {
      fr: { "Case review": { text: "Examen des dossiers" } },
      de: { "Case review": { text: "Fallprüfung" } },
    },
  },
};

function titleOf(layout: Record<string, unknown>): string {
  return (layout.h as { props: { title: string } }).props.title;
}

describe("what the browser asked for", () => {
  it("takes the whole list, in order", () => {
    // `navigator.languages` rather than `navigator.language`: a reader who
    // lists Catalan then Spanish is telling us both, and a module translated
    // into Spanish but not Catalan should serve Spanish.
    browser(["ca", "es-ES", "en"]);
    expect(readerLanguages()).toEqual(["ca", "es-ES", "en"]);
  });

  it("falls back to the single language when the list is empty", () => {
    browser([], "fr-CA");
    expect(readerLanguages()).toEqual(["fr-CA"]);
  });

  it("has nothing when the browser says nothing", () => {
    browser([], "");
    expect(readerLanguages()).toEqual([]);
  });

  it("has nothing where there is no browser at all", () => {
    // Server rendering, and anywhere else the API is missing. Resolves to the
    // document as written, which is the right answer for a surface that does
    // not know who is looking.
    vi.stubGlobal("navigator", undefined);
    expect(readerLanguages()).toEqual([]);
  });

  it("hands back one array rather than a fresh one each call", () => {
    // Callers key work on this. A new `[]` every render would be churn for
    // every module that has no table, which is most of them.
    vi.stubGlobal("navigator", undefined);
    expect(readerLanguages()).toBe(readerLanguages());
  });
});

describe("the layout a reader is served", () => {
  it("is translated when the browser asks for a language the module has", () => {
    browser(["fr-CA"]);
    expect(titleOf(readerLayout(DEFINITION))).toBe("Examen des dossiers");
  });

  it("works down the reader's list rather than taking the first table", () => {
    // `de` is stored first in the document. A reader who wants French and
    // would accept German must get French.
    browser(["fr", "de"]);
    expect(titleOf(readerLayout(DEFINITION))).toBe("Examen des dossiers");
    browser(["de", "fr"]);
    expect(titleOf(readerLayout(DEFINITION))).toBe("Fallprüfung");
  });

  it("is the document as written for a language the module does not have", () => {
    browser(["ja"]);
    expect(titleOf(readerLayout(DEFINITION))).toBe("Case review");
  });

  it("is the document as written while p.208's switch is off", () => {
    browser(["fr"]);
    const off = { ...DEFINITION, translations: { ...DEFINITION.translations, enabled: false } };
    expect(titleOf(readerLayout(off))).toBe("Case review");
  });

  it("is the document as written for a module that has never been translated", () => {
    browser(["fr"]);
    const plain = { format: 2, layout: DEFINITION.layout, variables: {}, events: {} };
    expect(titleOf(readerLayout(plain))).toBe("Case review");
  });

  it("reads a v1 document, which has no wrapper to hold a table", () => {
    // Every module in the corpus predates this. A bare Craft node map has to
    // come back untouched rather than throwing on a missing `translations`.
    browser(["fr"]);
    expect(titleOf(readerLayout(DEFINITION.layout))).toBe("Case review");
  });
});
