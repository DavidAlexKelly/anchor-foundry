import { describe, expect, it } from "vitest";

import {
  ALIGNMENTS, DEFAULT_ALIGNMENT, URL_SCHEMES,
  alignmentOf, blockAlignment, columnAlignment,
  parse, parseInline, safeHref, sourceOf, textOf,
  type Block, type Inline,
} from "./markdown";

/** p.314–319's Markdown widget. */

/** The text of a tree, ignoring which marks produced it. Used where a test is
 * about *structure* rather than about the characters. */
function textOfInline(nodes: Inline[]): string {
  return nodes.map((n) => {
    if (n.kind === "text" || n.kind === "code") return n.text;
    if (n.kind === "image") return n.alt;
    if (n.kind === "break") return "\n";
    return textOfInline(n.children);
  }).join("");
}

function only(source: string): Block {
  const blocks = parse(source);
  expect(blocks, source).toHaveLength(1);
  return blocks[0]!;
}

describe("p.318's syntax table", () => {
  /** **p.318 is a specification and is used as one.** Each row is the example
   * that page gives, beside the block kind it has to produce. A syntax that
   * silently stopped working would otherwise be found by an author. */
  const EXAMPLES: [string, string, string][] = [
    ["Main Header", "# Main header", "heading"],
    ["Subheader", "### sub header", "heading"],
    ["Italics", "I *think* this", "paragraph"],
    ["Bold", "**sentence** is", "paragraph"],
    ["Strikethrough", "~pretty good~", "paragraph"],
    ["Highlight", "==great==", "paragraph"],
    ["Inline Code", "`share`", "paragraph"],
    ["Blockquote", "> This is a blockquote", "quote"],
    ["Unordered List", "- Item 1\n- Item 2", "list"],
    ["Ordered List", "1. First item\n2. Second item", "list"],
    ["Horizontal Rule", "---", "rule"],
    ["Link", "[title](https://palantir.com)", "paragraph"],
    ["Image", "![alt text](https://mydomain.palantir.com/image.png)", "paragraph"],
    ["Task List", "- [ ] Task 1\n- [x] Task 2", "list"],
  ];

  it.each(EXAMPLES)("parses p.318's %s", (_name, source, kind) => {
    expect(only(source).kind).toBe(kind);
  });

  it("parses p.318's code block", () => {
    expect(only("```\n example code \n```")).toEqual({
      kind: "code", text: " example code ", lang: "",
    });
  });

  it("parses p.318's table", () => {
    const block = only("| Header 1 | Header 2 |\n|----------|----------|\n"
      + "| Row 1    | Data 1   |\n| Row 2    | Data 2   |");
    expect(block.kind).toBe("table");
    if (block.kind !== "table") return;
    expect(block.head.map(textOfInline)).toEqual(["Header 1", "Header 2"]);
    expect(block.rows.map((r) => r.map(textOfInline)))
      .toEqual([["Row 1", "Data 1"], ["Row 2", "Data 2"]]);
  });
});

describe("headings", () => {
  it("reads p.317's levels 1 to 6", () => {
    // "Markdown supports subheaders ranging from level 1 to level 6."
    for (let level = 1; level <= 6; level += 1) {
      const block = only(`${"#".repeat(level)} Heading`);
      expect(block.kind).toBe("heading");
      if (block.kind === "heading") expect(block.level).toBe(level);
    }
  });

  it("does not read a seventh level as a heading", () => {
    expect(only("####### Not a heading").kind).toBe("paragraph");
  });

  it("needs a space after the hashes", () => {
    // `#hashtag` is a word somebody wrote, not a heading.
    expect(only("#hashtag").kind).toBe("paragraph");
  });
});

describe("inline marks", () => {
  it("prefers the longer delimiter", () => {
    // **Order is load-bearing**: `**` before `*`, or every bold run parses as
    // two italics with an empty middle.
    const nodes = parseInline("**bold**");
    expect(nodes).toHaveLength(1);
    expect(nodes[0]!.kind).toBe("strong");
  });

  it("reads each of p.318's marks", () => {
    expect(parseInline("*a*")[0]!.kind).toBe("em");
    expect(parseInline("_a_")[0]!.kind).toBe("em");
    expect(parseInline("**a**")[0]!.kind).toBe("strong");
    expect(parseInline("__a__")[0]!.kind).toBe("strong");
    expect(parseInline("~a~")[0]!.kind).toBe("del");
    expect(parseInline("~~a~~")[0]!.kind).toBe("del");
    expect(parseInline("==a==")[0]!.kind).toBe("mark");
  });

  it("nests marks", () => {
    const nodes = parseInline("**bold with *italic* inside**");
    expect(nodes[0]!.kind).toBe("strong");
    if (nodes[0]!.kind !== "strong") return;
    expect(nodes[0]!.children.some((c) => c.kind === "em")).toBe(true);
  });

  it("leaves an unclosed delimiter as text", () => {
    // **Somebody typing `2 * 3 * 4` has not asked for italics** — but they have
    // typed something with two asterisks, so this is the case that decides
    // whether a parser is trusted with arithmetic. One closer, so it *is* an
    // italic; the point of the test below is the unclosed one.
    expect(textOfInline(parseInline("2 * 3"))).toBe("2 * 3");
    expect(parseInline("2 * 3").every((n) => n.kind === "text")).toBe(true);
    expect(textOfInline(parseInline("**unclosed"))).toBe("**unclosed");
  });

  it("treats an empty delimiter pair as text", () => {
    expect(textOfInline(parseInline("****"))).toBe("****");
  });

  it("suppresses marks inside a code span", () => {
    // `` `a * b` `` is code containing an asterisk, not an italic.
    const nodes = parseInline("`a * b`");
    expect(nodes).toEqual([{ kind: "code", text: "a * b" }]);
  });

  it("leaves an unclosed backtick as text", () => {
    expect(textOfInline(parseInline("`unclosed"))).toBe("`unclosed");
  });

  it("honours a backslash escape", () => {
    // Without this there is no way to write a literal asterisk.
    const nodes = parseInline("\\*not italic\\*");
    expect(nodes.every((n) => n.kind === "text")).toBe(true);
    expect(textOfInline(nodes)).toBe("*not italic*");
  });

  it("joins adjacent text rather than fragmenting it", () => {
    // Otherwise the tree has a node per character and every consumer has to
    // reassemble it.
    expect(parseInline("plain words here")).toEqual([
      { kind: "text", text: "plain words here" },
    ]);
  });

  it("joins text across a node that was pushed and then refused", () => {
    // **The case above cannot fail**: a run with no syntax in it is buffered
    // and pushed once, so it is a single node whether or not anything merges.
    // The merge only does work when a push has already happened — here the
    // refused link is pushed as text, and the tail has to join it rather than
    // arrive as a second node.
    expect(parseInline("[x](javascript:y) tail")).toEqual([
      { kind: "text", text: "[x](javascript:y) tail" },
    ]);
  });
});

describe("safeHref", () => {
  /** **Every test of a mechanism here is written against an *allowed* scheme.**
   *
   * The first version of this block tested case folding and control-character
   * handling with `javascript:`, and all of it passed while proving nothing:
   * an allowlist refuses `javascript:` because it is not on the list, so a
   * test that mangles it and watches it be refused has confirmed the allowlist
   * and learnt nothing about the mangling. The mutation harness found all
   * three at once — deleting the mechanism each one named changed no result.
   *
   * **A defence can only be tested on an input the other defences would let
   * through.** So the case fold is tested on a URL that is otherwise fine, and
   * the control character is put inside a scheme that is otherwise allowed.
   */
  it("allows exactly the schemes the server allows", () => {
    // **The same list as `URL_SCHEMES` in `services/workshop_events.py`.**
    // `open_url` and a Markdown link are the same capability reached two ways.
    expect(URL_SCHEMES).toEqual(["http://", "https://", "mailto:", "/"]);
    expect(safeHref("https://palantir.com")).toBe("https://palantir.com");
    expect(safeHref("http://x.test")).toBe("http://x.test");
    expect(safeHref("mailto:a@b.test")).toBe("mailto:a@b.test");
    expect(safeHref("/home")).toBe("/home");
  });

  it("refuses a scheme a browser would execute", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<script>")).toBeNull();
    expect(safeHref("vbscript:x")).toBeNull();
  });

  it("matches the scheme regardless of case, and returns the URL unfolded", () => {
    // The mechanism under test, on an input the allowlist accepts either way.
    // Returned unfolded because `HTTPS://` is a URL and the case of somebody
    // else's path is not this function's to change.
    expect(safeHref("HTTPS://X.test/Path")).toBe("HTTPS://X.test/Path");
    expect(safeHref("MailTo:a@b.test")).toBe("MailTo:a@b.test");
  });

  it("refuses a control character inside an otherwise allowed URL", () => {
    // **The case that made the first implementation wrong rather than merely
    // untested.** It stripped control characters and re-checked, so this
    // string became `https://evil.test` and was allowed — an accepted URL
    // manufactured out of one nobody typed. Stripping is a denylist defence;
    // under an allowlist it can only ever *add* accepted strings.
    expect(safeHref("ht\ntps://evil.test")).toBeNull();
    expect(safeHref("mail\u0000to:a@b.test")).toBeNull();
    expect(safeHref("/ho\tme")).toBeNull();
  });

  it("trims whitespace at the ends, which is ordinary", () => {
    expect(safeHref("  https://x.test  ")).toBe("https://x.test");
    expect(safeHref("\n/home\n")).toBe("/home");
    // And trimming rescues nothing: the scheme still has to be on the list.
    expect(safeHref("  javascript:alert(1)")).toBeNull();
  });

  it("refuses anything that is not a string, or is empty", () => {
    expect(safeHref(null)).toBeNull();
    expect(safeHref(7)).toBeNull();
    expect(safeHref("")).toBeNull();
    expect(safeHref("   ")).toBeNull();
  });

  it("refuses an object that stringifies to an allowed URL", () => {
    // Not hypothetical: this is reached with whatever an author left in a
    // saved JSON document, and a `String(raw)` here would accept both of these.
    expect(safeHref({ toString: () => "https://x.test" })).toBeNull();
    expect(safeHref(["https://x.test"])).toBeNull();
  });

  it("refuses a bare word, which is a relative path this platform does not serve", () => {
    expect(safeHref("palantir.com")).toBeNull();
  });
});

describe("links and images", () => {
  it("makes a link of an allowed URL", () => {
    const nodes = parseInline("[title](https://palantir.com)");
    expect(nodes).toEqual([{
      kind: "link", href: "https://palantir.com",
      children: [{ kind: "text", text: "title" }],
    }]);
  });

  it("renders a refused URL as its own source text", () => {
    // **Not a dead link and not nothing**: an author who typed something this
    // platform will not follow should be able to see what was rejected.
    const nodes = parseInline("[click](javascript:alert(1))");
    expect(nodes.every((n) => n.kind === "text")).toBe(true);
    expect(textOfInline(nodes)).toContain("javascript:");
  });

  it("makes an image of an allowed URL and refuses others", () => {
    expect(parseInline("![alt](https://x.test/i.png)")).toEqual([
      { kind: "image", src: "https://x.test/i.png", alt: "alt" },
    ]);
    expect(parseInline("![alt](javascript:x)").every((n) => n.kind === "text")).toBe(true);
  });

  it("reads an image before a link", () => {
    // `![alt](src)` starts with the link syntax one character in.
    expect(parseInline("![a](https://x.test/i.png)")[0]!.kind).toBe("image");
  });

  it("parses marks inside a link's text", () => {
    const nodes = parseInline("[**bold**](https://x.test)");
    expect(nodes[0]!.kind).toBe("link");
    if (nodes[0]!.kind !== "link") return;
    expect(nodes[0]!.children[0]!.kind).toBe("strong");
  });
});

describe("blocks", () => {
  it("separates paragraphs on a blank line", () => {
    const blocks = parse("one\n\ntwo");
    expect(blocks).toHaveLength(2);
    expect(blocks.every((b) => b.kind === "paragraph")).toBe(true);
  });

  it("keeps a fenced block's content verbatim", () => {
    // Nothing inside a code fence is syntax - that is what a code fence is.
    const block = only("```\n# not a heading\n**not bold**\n```");
    expect(block).toEqual({
      kind: "code", text: "# not a heading\n**not bold**", lang: "",
    });
  });

  it("reads a fence's language", () => {
    const block = only("```python\nx = 1\n```");
    if (block.kind === "code") expect(block.lang).toBe("python");
  });

  it("closes an unterminated fence at the end of the source", () => {
    // Rather than dropping the rest of the document, which is what a parser
    // waiting for a closer would do.
    const block = only("```\nstill shown");
    if (block.kind === "code") expect(block.text).toBe("still shown");
  });

  it("reads a blockquote as blocks, not as text", () => {
    // p.314's "block styling" is a block, and a block that could only hold
    // text would not be one.
    const block = only("> # quoted heading\n> and a line");
    expect(block.kind).toBe("quote");
    if (block.kind !== "quote") return;
    expect(block.blocks[0]!.kind).toBe("heading");
  });

  it("tells the two list kinds apart", () => {
    const unordered = only("- a\n- b");
    const ordered = only("1. a\n2. b");
    if (unordered.kind === "list") expect(unordered.ordered).toBe(false);
    if (ordered.kind === "list") expect(ordered.ordered).toBe(true);
  });

  it("marks task items and leaves plain items unmarked", () => {
    // `undefined` and `false` are different answers: a checkbox nobody asked
    // for is as wrong as a missing one.
    const block = only("- [ ] todo\n- [x] done\n- plain");
    if (block.kind !== "list") return;
    expect(block.items.map((i) => i.done)).toEqual([false, true, undefined]);
    expect(block.items.map((i) => textOfInline(i.children)))
      .toEqual(["todo", "done", "plain"]);
  });

  it("accepts an upper-case tick", () => {
    const block = only("- [X] done");
    if (block.kind === "list") expect(block.items[0]!.done).toBe(true);
  });

  it("reads both of p.318's horizontal rules", () => {
    expect(only("---")).toEqual({ kind: "rule" });
    expect(only("***")).toEqual({ kind: "rule" });
  });

  it("does not read a list item as a rule", () => {
    expect(only("- item").kind).toBe("list");
  });

  it("needs three dashes, because two is how people type a dash", () => {
    expect(only("--").kind).toBe("paragraph");
    expect(only("**").kind).toBe("paragraph");
  });
});

describe("tables", () => {
  it("needs an alignment row, or the pipes are just text", () => {
    // Otherwise every sentence containing a pipe becomes a one-row table.
    expect(only("| a | b |").kind).toBe("paragraph");
  });

  it("reads p.317's per-column alignment", () => {
    const block = only("| l | c | r | n |\n| :--- | :---: | ---: | --- |\n| 1 | 2 | 3 | 4 |");
    if (block.kind !== "table") return;
    expect(block.align).toEqual(["left", "center", "right", null]);
  });

  it("leaves an unaligned column null rather than defaulting it", () => {
    // **p.317: explicit per-column alignment "takes precedence over the
    // widget-level text alignment setting"** — so a column that did not ask has
    // to stay unasked, or every table would override the widget's own setting.
    const block = only("| a |\n| --- |\n| 1 |");
    if (block.kind === "table") expect(block.align).toEqual([null]);
  });

  it("wants the alignment row to have a row's shape", () => {
    // The same leading-and-trailing pipes `TABLE_ROW` requires. Accepting a
    // bare `--- | ---` meant `cells` could be handed a line no pipe rule had
    // matched, which is the reachable-looking-but-unreachable fallback the
    // mutation harness turned up inside it.
    expect(only("| a | b |\n--- | ---\n| 1 | 2 |").kind).toBe("paragraph");
    expect(only("| a | b |\n| --- | --- |\n| 1 | 2 |").kind).toBe("table");
  });

  it("parses marks inside cells", () => {
    const block = only("| **bold** |\n| --- |\n| `code` |");
    if (block.kind !== "table") return;
    expect(block.head[0]![0]!.kind).toBe("strong");
    expect(block.rows[0]![0]![0]!.kind).toBe("code");
  });
});

describe("p.317's break on newlines", () => {
  it("begins a new line for each source newline by default", () => {
    const blocks = parse("one\ntwo");
    expect(blocks).toHaveLength(1);
    if (blocks[0]!.kind !== "paragraph") return;
    expect(blocks[0]!.children.some((c) => c.kind === "break")).toBe(true);
  });

  it("collapses them into spaces when disabled", () => {
    // p.317: "following standard Markdown rendering".
    const blocks = parse("one\ntwo", { breaks: false });
    if (blocks[0]!.kind !== "paragraph") return;
    expect(blocks[0]!.children.some((c) => c.kind === "break")).toBe(false);
    expect(textOfInline(blocks[0]!.children)).toBe("one two");
  });

  it("defaults to on, which p.317 states as the default for new widgets", () => {
    // Named rather than read from a constant (§203, §205).
    const blocks = parse("one\ntwo", {});
    if (blocks[0]!.kind === "paragraph") {
      expect(blocks[0]!.children.some((c) => c.kind === "break")).toBe(true);
    }
  });
});

describe("input", () => {
  it("is empty for anything that is not text", () => {
    expect(parse(null)).toEqual([]);
    expect(parse(undefined)).toEqual([]);
    expect(parse("")).toEqual([]);
  });

  it("normalises Windows line endings", () => {
    // A document pasted from elsewhere is a document, and a `\r` left on the
    // end of a line stops it matching any block rule — `$` does not match
    // before one, so the heading below silently becomes a paragraph.
    //
    // **Asserted on the kinds, not the count**: both outcomes produce two
    // blocks, so the count was a number the bug did not change (§204).
    expect(parse("# a\r\n\r\ntext").map((b) => b.kind))
      .toEqual(["heading", "paragraph"]);
  });

  it("emits no HTML, because it emits no strings of markup at all", () => {
    // **The whole safety argument in one assertion.** Raw HTML in the source is
    // text, because a tree of plain objects is all this produces — there is no
    // markup string anywhere in the path for it to be injected into.
    const blocks = parse("<script>alert(1)</script>");
    expect(blocks).toHaveLength(1);
    if (blocks[0]!.kind !== "paragraph") return;
    expect(blocks[0]!.children).toEqual([
      { kind: "text", text: "<script>alert(1)</script>" },
    ]);
  });
});

describe("widget settings", () => {
  it("has p.317's three alignments and defaults to left", () => {
    expect(Object.keys(ALIGNMENTS).sort()).toEqual(["center", "left", "right"]);
    expect(DEFAULT_ALIGNMENT).toBe("left");
    expect(alignmentOf("center")).toBe("center");
    expect(alignmentOf("diagonal")).toBe("left");
    expect(alignmentOf("constructor")).toBe("left");
    expect(alignmentOf(undefined)).toBe("left");
  });

  it("leaves a code block left-aligned whatever the widget says", () => {
    // p.317: "Code blocks remain left-aligned and full-width regardless of the
    // selected alignment." Centred code is unreadable, which is why the page
    // bothers to say so.
    const code = parse("```\nx = 1\n```")[0]!;
    const prose = parse("words")[0]!;
    expect(blockAlignment(code, "center")).toBe("left");
    expect(blockAlignment(code, "right")).toBe("left");
    expect(blockAlignment(prose, "center")).toBe("center");
    expect(blockAlignment(prose, "right")).toBe("right");
  });

  it("lets a column's own alignment beat the widget's", () => {
    // p.317: explicit per-column alignment "takes precedence over the
    // widget-level text alignment setting" — and a column that did not ask
    // keeps the widget's, which is what `null` is for.
    expect(columnAlignment("center", "right")).toBe("center");
    expect(columnAlignment("left", "right")).toBe("left");
    expect(columnAlignment(null, "right")).toBe("right");
    expect(columnAlignment(null, "left")).toBe("left");
  });

  it("has p.316's two input sources, defaulting to typed text", () => {
    expect(sourceOf("variable")).toBe("variable");
    expect(sourceOf("text")).toBe("text");
    expect(sourceOf(undefined)).toBe("text");
    expect(sourceOf("elsewhere")).toBe("text");
  });

  it("reads the text from whichever source is configured", () => {
    expect(textOf("text", "typed", "from variable")).toBe("typed");
    expect(textOf("variable", "typed", "from variable")).toBe("from variable");
  });

  it("is empty when the chosen source holds nothing", () => {
    // Which a variable does for the first few hundred milliseconds of every
    // module, because variables are computed on the server.
    expect(textOf("variable", "typed", undefined)).toBe("");
    expect(textOf("variable", "typed", null)).toBe("");
    expect(textOf("variable", "typed", 7)).toBe("");
  });
});
