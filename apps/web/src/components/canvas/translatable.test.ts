import { describe, expect, it } from "vitest";
import {
  bestLanguage, done, occurrences, say, sources, stale, tableFor, toTranslate,
  translated, type Table,
} from "./translatable";

function node(resolvedName: string, props: Record<string, unknown>) {
  return { type: { resolvedName }, props };
}

function table(pairs: Record<string, string>): Table {
  return Object.fromEntries(Object.entries(pairs).map(([k, v]) => [k, { text: v }]));
}

describe("what p.208 says can be translated", () => {
  it("finds the module header's title", () => {
    expect(occurrences({ h: node("CanvasHeader", { title: "Cases" }) }))
      .toEqual([{ text: "Cases", node: "h", prop: "title" }]);
  });

  it("finds a page title, which is what a tab is labelled with", () => {
    // p.208 lists "Tabs widget Label". Our Tabs widget has no props of its
    // own - it draws one button per page and labels it with that page's
    // title - so the page title *is* the tab label, and translating the
    // widget would mean translating nothing.
    expect(occurrences({ p: node("CanvasPage", { title: "Open" }) })[0]?.text).toBe("Open");
  });

  it("finds the static-text widgets p.208 names, and our Text widget", () => {
    const found = occurrences({
      s: node("CanvasSection", { title: "Filters" }),
      o: node("CanvasOverlay", { title: "Confirm" }),
      t: node("CanvasText", { text: "Pick one" }),
      m: node("CanvasMarkdown", { text: "## Notes" }),
      b: node("CanvasButton", { label: "Submit" }),
      c: node("CanvasMetricCard", { label: "Open cases" }),
      v: node("CanvasPivotTable", { title: "By region" }),
      f: node("CanvasFilterList", { title: "Narrow it down" }),
      st: node("CanvasObjectSetTitle", { titleOverride: "Selected" }),
    });
    expect(found.map((o) => o.text)).toEqual([
      "Filters", "Confirm", "Pick one", "## Notes", "Submit",
      "Open cases", "By region", "Narrow it down", "Selected",
    ]);
  });

  it("does not translate data, or anything a variable produces", () => {
    // The rule p.208's examples are examples *of*: static text an author
    // typed. A table's columns name ontology properties, a variable's id
    // names a variable, and translating either would mean a module quietly
    // renaming the platform's own data for one reader.
    expect(occurrences({
      tbl: node("CanvasObjectTable", { columns: "status,owner", objectTypeId: "case" }),
      mk: node("CanvasMarkdown", { source: "variable", textVariable: "v_notes" }),
      f: node("CanvasFilterList", { properties: "status,owner", objectSetVariable: "v_cases" }),
    }).map((o) => o.text)).toEqual([]);
  });

  it("ignores a widget type it has no entry for", () => {
    expect(occurrences({ m: node("CanvasMap", { title: "Where" }) })).toEqual([]);
  });

  it("ignores an empty or whitespace string", () => {
    expect(occurrences({
      a: node("CanvasText", { text: "" }),
      b: node("CanvasText", { text: "   " }),
      c: node("CanvasText", {}),
    })).toEqual([]);
  });

  it("reads a node whose type is a bare string", () => {
    // Saved documents hold both forms - `workshop_format._resolved_name` was
    // written from a fixture that only had one and was corrected by running
    // over a real database.
    expect(occurrences({ h: { type: "CanvasHeader", props: { title: "Cases" } } }))
      .toHaveLength(1);
  });

  it("survives a document that is not one", () => {
    expect(occurrences(undefined)).toEqual([]);
    expect(occurrences({ a: "not a node" })).toEqual([]);
  });
});

describe("a section's tabs", () => {
  it("offers each label separately, with its position", () => {
    // p.208 names "Section header Title(s) and Tabs". They live in one
    // comma-separated prop, and handing a translator `"Open,Closed,All"` as
    // one string would make the comma count part of their job.
    expect(occurrences({ s: node("CanvasSection", { tabs: "Open,Closed,All" }) }))
      .toEqual([
        { text: "Open", node: "s", prop: "tabs[0]" },
        { text: "Closed", node: "s", prop: "tabs[1]" },
        { text: "All", node: "s", prop: "tabs[2]" },
      ]);
  });

  it("skips an empty slot rather than offering a box that cannot be filled", () => {
    // `tabLabels` names the middle one "Tab 2" from its position. There is
    // no string in the document to translate, and a filled-in box would have
    // nowhere to go.
    expect(occurrences({ s: node("CanvasSection", { tabs: "Open,,All" }) }).map((o) => o.prop))
      .toEqual(["tabs[0]", "tabs[2]"]);
  });
});

describe("the distinct list a translator works down", () => {
  it("says a repeated string once", () => {
    expect(sources({
      a: node("CanvasButton", { label: "Save" }),
      b: node("CanvasButton", { label: "Save" }),
      c: node("CanvasButton", { label: "Cancel" }),
    })).toEqual(["Save", "Cancel"]);
  });

  it("keeps document order rather than sorting", () => {
    // p.209 has a builder working down "each translatable string detected
    // within the module". Sorting would scatter one page's strings through
    // the list and lose their place.
    expect(sources({
      a: node("CanvasText", { text: "Zebra" }),
      b: node("CanvasText", { text: "Apple" }),
    })).toEqual(["Zebra", "Apple"]);
  });
});

describe("what a reader is served", () => {
  it("replaces a translated string", () => {
    const out = translated(
      { h: node("CanvasHeader", { title: "Cases", sticky: true }) },
      table({ Cases: "Dossiers" }),
    );
    expect((out.h as { props: { title: string; sticky: boolean } }).props)
      .toEqual({ title: "Dossiers", sticky: true });
  });

  it("leaves a string the table has nothing for", () => {
    const out = translated({ h: node("CanvasHeader", { title: "Cases" }) }, table({ Other: "Autre" }));
    expect((out.h as { props: { title: string } }).props.title).toBe("Cases");
  });

  it("does not blank a string on an empty entry", () => {
    // A box a builder opened and did not fill. Serving it would empty the
    // widget, which reads as broken rather than as untranslated.
    expect(say("Cases", { Cases: { text: "" } })).toBe("Cases");
    expect(say("Cases", { Cases: { text: "   " } })).toBe("Cases");
  });

  it("serves an unreviewed translation", () => {
    // p.210's "Marked as complete" is a builder's bookkeeping. A translation
    // nobody got round to ticking is still better than the wrong language.
    expect(say("Cases", { Cases: { text: "Dossiers", reviewed: false } })).toBe("Dossiers");
  });

  it("translates each tab label without touching the rest of the prop", () => {
    const out = translated(
      { s: node("CanvasSection", { tabs: "Open,Closed", title: "Cases" }) },
      table({ Open: "Ouvert", Cases: "Dossiers" }),
    );
    expect((out.s as { props: { tabs: string; title: string } }).props)
      .toEqual({ tabs: "Ouvert,Closed", title: "Dossiers" });
  });

  it("does not translate a label inside a longer one", () => {
    // Built by splitting rather than by replacing text: `"Open"` appearing
    // inside `"Open cases"` is a different string and keeps its own answer.
    const out = translated(
      { s: node("CanvasSection", { tabs: "Open cases,Open" }) },
      table({ Open: "Ouvert" }),
    );
    expect((out.s as { props: { tabs: string } }).props.tabs).toBe("Open cases,Ouvert");
  });

  it("leaves the spacing of a tab list it did not translate", () => {
    // The untranslated half of a prop comes back byte for byte. Rebuilding
    // it from the trimmed parts would rewrite `"Open, Closed"` as
    // `"Open,Closed"` - a change to text this pass did not translate.
    const out = translated(
      { s: node("CanvasSection", { tabs: "Open, Closed" }) },
      table({ Nothing: "Rien" }),
    );
    expect((out.s as { props: { tabs: string } }).props.tabs).toBe("Open, Closed");
    const some = translated(
      { s: node("CanvasSection", { tabs: "Open, Closed" }) },
      table({ Open: "Ouvert" }),
    );
    expect((some.s as { props: { tabs: string } }).props.tabs).toBe("Ouvert, Closed");
  });

  it("hands back the same object when nothing changes", () => {
    // `<Frame data>` is serialised from this. A new object every render for a
    // module with no table would be churn for nothing.
    const layout = { h: node("CanvasHeader", { title: "Cases" }) };
    expect(translated(layout, undefined)).toBe(layout);
    expect(translated(layout, {})).toBe(layout);
    expect(translated(layout, table({ Nothing: "Rien" }))).toBe(layout);
    const spaced = { s: node("CanvasSection", { tabs: "Open, Closed" }) };
    expect(translated(spaced, table({ Nothing: "Rien" }))).toBe(spaced);
  });
});

describe("which language a reader gets", () => {
  it("takes an exact match first", () => {
    expect(bestLanguage(["fr", "pt-BR"], ["pt-BR"])).toBe("pt-BR");
  });

  it("falls back to the base language", () => {
    // A browser says `fr-CA`; a module is translated into `fr`. French is
    // much better than English for that reader.
    expect(bestLanguage(["fr", "de"], ["fr-CA"])).toBe("fr");
  });

  it("takes a regional table for a bare request", () => {
    // The other direction, and the one every browser's own negotiation
    // makes: `pt` asking, only `pt-BR` stored.
    expect(bestLanguage(["pt-BR"], ["pt"])).toBe("pt-BR");
  });

  it("works down the reader's list in order", () => {
    expect(bestLanguage(["de", "fr"], ["es", "fr", "de"])).toBe("fr");
  });

  it("is not case sensitive about tags", () => {
    expect(bestLanguage(["pt-br"], ["PT-BR"])).toBe("pt-br");
  });

  it("matches the exact tag case-insensitively before falling back", () => {
    // Two Portuguese tables and a reader asking for one of them by name. A
    // case-sensitive exact match misses, and the base-language fallback then
    // hands back whichever came first - the wrong country, quietly. The
    // single-table version of this check cannot see the difference, because
    // the fallback returns the right answer there by luck.
    expect(bestLanguage(["pt-PT", "pt-BR"], ["pt-br"])).toBe("pt-BR");
  });

  it("serves the document itself when the reader speaks its language", () => {
    // p.209's starting language. A table stored under it would be English
    // into English, and serving it would let a stale table override the
    // document.
    expect(bestLanguage(["en", "fr"], ["en-GB"], "en")).toBeNull();
    expect(bestLanguage(["en", "fr"], ["fr"], "en")).toBe("fr");
  });

  it("has nothing for a language the module was not translated into", () => {
    expect(bestLanguage(["fr"], ["ja"])).toBeNull();
    expect(bestLanguage([], ["fr"])).toBeNull();
    expect(bestLanguage(["fr"], [])).toBeNull();
    expect(bestLanguage(["fr"], ["", "  "])).toBeNull();
  });
});

describe("the on switch", () => {
  it("serves nothing while p.208's toggle is off", () => {
    // A half-entered table must reach nobody. The check is here rather than
    // at the call sites so no surface can forget to ask.
    expect(tableFor(
      { enabled: false, languages: { fr: { Cases: { text: "Dossiers" } } } },
      ["fr"],
    )).toBeUndefined();
  });

  it("serves the matching table when it is on", () => {
    expect(tableFor(
      { enabled: true, languages: { fr: { Cases: { text: "Dossiers" } } } },
      ["fr-CA"],
    )).toEqual({ Cases: { text: "Dossiers" } });
  });

  it("has nothing for a module that has never been translated", () => {
    expect(tableFor(undefined, ["fr"])).toBeUndefined();
    expect(tableFor({ enabled: true, languages: {} }, ["fr"])).toBeUndefined();
  });
});

describe("p.210's split", () => {
  const layout = {
    a: node("CanvasButton", { label: "Save" }),
    b: node("CanvasButton", { label: "Cancel" }),
  };

  it("puts an untranslated string in To translate", () => {
    expect(toTranslate(layout, table({ Save: "Enregistrer" }))).toEqual(["Cancel"]);
    expect(done(layout, table({ Save: "Enregistrer" }))).toEqual(["Save"]);
  });

  it("puts an edited string back in To translate, with nothing noticing the edit", () => {
    // p.210: "Any new or modified strings detected in the module… will appear
    // in the To translate section". Keying the table by source text is what
    // makes this free - the edited string is a key nothing has an entry for.
    const edited = { a: node("CanvasButton", { label: "Save all" }) };
    expect(toTranslate(edited, table({ Save: "Enregistrer" }))).toEqual(["Save all"]);
  });

  it("keeps an entry whose string has left the module, out of sight", () => {
    // Not deleted: an edit that is undone should not have cost its
    // translations. Not shown either - a translator has no use for it.
    const t = table({ Save: "Enregistrer", Gone: "Parti" });
    expect(stale(layout, t)).toEqual(["Gone"]);
    expect(toTranslate(layout, t)).toEqual(["Cancel"]);
    expect(done(layout, t)).toEqual(["Save"]);
  });
});
