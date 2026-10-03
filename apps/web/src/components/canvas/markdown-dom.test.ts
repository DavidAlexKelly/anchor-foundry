/** p.466's rich view, edited in place (§789). */
import { describe, expect, it } from "vitest";

import { parse, type Block, type Inline } from "./markdown";
import { escapeText, markdownOf, type DomLike } from "./markdown-dom";

const text = (t: string): DomLike => ({ nodeType: 3, nodeName: "#text", textContent: t,
  childNodes: [] });

function el(name: string, kids: DomLike[] = [], attrs: Record<string, string> = {},
            extra: Partial<DomLike> = {}): DomLike {
  return {
    nodeType: 1, nodeName: name.toUpperCase(),
    get textContent() { return kids.map((k) => k.textContent ?? "").join(""); },
    childNodes: kids, getAttribute: (n: string) => attrs[n] ?? null, ...extra,
  };
}

/** The DOM `markdown-view.tsx` draws for these blocks. */
function inlineDom(nodes: Inline[]): DomLike[] {
  return nodes.map((n) => {
    switch (n.kind) {
      case "text": return text(n.text);
      case "code": return el("code", [text(n.text)]);
      case "strong": return el("strong", inlineDom(n.children));
      case "em": return el("em", inlineDom(n.children));
      case "del": return el("del", inlineDom(n.children));
      case "mark": return el("mark", inlineDom(n.children));
      case "break": return el("br");
      case "link": return el("a", inlineDom(n.children), { href: n.href });
      case "image": return el("img", [], { src: n.src, alt: n.alt });
      default: return text("");
    }
  });
}

function blockDom(b: Block): DomLike {
  switch (b.kind) {
    case "heading": return el(`h${b.level}`, inlineDom(b.children));
    case "paragraph": return el("p", inlineDom(b.children));
    case "code": return el("pre", [el("code", [text(b.text)])]);
    case "rule": return el("hr");
    case "quote": return el("blockquote", b.blocks.map(blockDom));
    case "list": return el(b.ordered ? "ol" : "ul", b.items.map((item) => el("li", [
      ...(item.done === undefined ? [] : [el("input", [], {}, { checked: item.done })]),
      ...inlineDom(item.children)])));
    case "table": return el("table", [
      el("thead", [el("tr", b.head.map((c) => el("th", inlineDom(c))))]),
      el("tbody", b.rows.map((r) => el("tr", r.map((c) => el("td", inlineDom(c))))))]);
  }
}

function roundTrip(source: string): string {
  return markdownOf(el("div", parse(source, { breaks: true }).map(blockDom)));
}

describe("what the rich view shows, written back", () => {
  it.each([
    "Plain words.",
    "**bold**, _italic_, ~~struck~~, ==marked== and `code`",
    "# One\n\n## Two\n\n###### Six",
    "line one\nline two",
    "- a\n- **b**\n\n1. one\n2. two",
    "- [x] done\n- [ ] not yet",
    "> quoted\n> still",
    "```\nconst a = 1;\n  indented\n```",
    "---",
    "[a link](https://example.com) and ![a picture](https://example.com/a.png)",
    "| A | B |\n| --- | --- |\n| 1 | **2** |",
    "Literal \\*stars\\*, \\_under\\_ and a \\[bracket\\]",
  ])("%s", (source) => {
    // The same document as the one rendered, whatever spelling it comes back in.
    expect(parse(roundTrip(source), { breaks: true })).toEqual(parse(source, { breaks: true }));
  });

  it("writes each element as the syntax markdown.ts reads", () => {
    expect(roundTrip("**b** _i_ ~~s~~ ==m== `c`")).toBe("**b** _i_ ~~s~~ ==m== `c`");
    expect(roundTrip("## H")).toBe("## H");
    expect(roundTrip("1. a\n2. b")).toBe("1. a\n2. b");
    expect(roundTrip("> q")).toBe("> q");
  });
});

describe("what a browser adds while editing", () => {
  it("reads its <div> lines as paragraphs, and an empty one as nothing", () => {
    expect(markdownOf(el("div", [text("first"), el("div", [text("second")]),
      el("div", [el("br")]), el("div", [text("third")])]))).toBe("first\n\nsecond\n\nthird");
  });

  it("reads <b>, <i> and <strike> as what they mean", () => {
    expect(markdownOf(el("div", [el("p", [el("b", [text("x")]), text(" "),
      el("i", [text("y")]), text(" "), el("strike", [text("z")])])]))).toBe("**x** _y_ ~~z~~");
  });

  it("moves a space at a marker's inside to its outside", () => {
    expect(markdownOf(el("div", [el("p", [text("a"), el("strong", [text(" b ")]),
      text("c")])]))).toBe("a **b** c");
    expect(markdownOf(el("div", [el("p", [el("em", [text("  ")])])]))).toBe("");
  });

  it("reads a non-breaking space as a space, and a line break as a new line", () => {
    expect(markdownOf(el("div", [el("p", [text("a\u00a0b"), el("br"), text("c"),
      el("br")])]))).toBe("a b\nc");
  });

  it("keeps a <div> holding blocks as those blocks", () => {
    expect(markdownOf(el("div", [el("div", [el("h2", [text("T")]), el("p", [text("x")])])])))
      .toBe("## T\n\nx");
  });
});

describe("text typed into the rich view stays text", () => {
  it("escapes what Markdown would read as syntax", () => {
    expect(escapeText("a*b_c`d[e]f\\g")).toBe("a\\*b\\_c\\`d\\[e\\]f\\\\g");
    expect(escapeText("a == b ~~ c = d ~ e")).toBe("a \\=\\= b \\~\\~ c = d ~ e");
  });

  it("escapes a line that would start a block", () => {
    for (const line of ["# not a heading", "> not a quote", "- not a list", "1. not a list",
                        "--- not a rule", "``` not a fence", "| not a table"]) {
      const written = markdownOf(el("div", [el("p", [text(line)])]));
      expect(parse(written, { breaks: true })).toEqual(
        [{ kind: "paragraph", children: [{ kind: "text", text: line }] }]);
    }
    expect(markdownOf(el("div", [el("p", [text("#hashtag")])]))).toBe("#hashtag");
  });

  it("leaves a link with no address as its text, and an image with none out", () => {
    expect(markdownOf(el("div", [el("p", [el("a", [text("x")]), el("img", [], { alt: "y" })])])))
      .toBe("x");
  });

  it("writes an empty table as nothing, and a table cell's pipe escaped", () => {
    expect(markdownOf(el("div", [el("table")]))).toBe("");
    expect(markdownOf(el("div", [el("table", [el("tr", [el("td", [text("a|b")])])])])))
      .toBe("| a\\|b |\n| --- |");
  });
});

describe("an element a browser leaves empty", () => {
  it("writes nothing for it: no empty code, heading or quote", () => {
    expect(markdownOf(el("div", [el("p", [text("a"), el("code"), text("b")])]))).toBe("ab");
    expect(markdownOf(el("div", [el("h2", [el("br")]), el("p", [text("x")])]))).toBe("x");
    expect(markdownOf(el("div", [el("blockquote", [el("p", [el("br")])]),
      el("p", [text("x")])]))).toBe("x");
  });

  it("marks a blank line inside a quote with the quote's own marker", () => {
    expect(markdownOf(el("div", [el("blockquote", [el("p", [text("a")]),
      el("p", [text("b")])])]))).toBe("> a\n>\n> b");
  });
});
