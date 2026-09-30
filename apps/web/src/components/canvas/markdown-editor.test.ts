import { describe, expect, it } from "vitest";

import { FORMATS, MAX_ROWS, MIN_ROWS, applyFormat, autoRows, type MarkdownFormat } from "./markdown-editor";
import { parse } from "./markdown";

/** `[text, start, end]` with the selection marked `[` `]` in one string. */
function sel(marked: string): [string, number, number] {
  const start = marked.indexOf("[");
  const end = marked.indexOf("]") - 1;
  return [marked.replace("[", "").replace("]", ""), start, end];
}

function press(marked: string, format: MarkdownFormat): string {
  const [text, start, end] = sel(marked);
  const out = applyFormat(text, start, end, format);
  return out.text.slice(0, out.start) + "[" + out.text.slice(out.start, out.end) + "]"
    + out.text.slice(out.end);
}

describe("wrapping the selection (§582)", () => {
  it("wraps it, and keeps it selected inside the marks", () => {
    expect(press("a [word] here", "bold")).toBe("a **[word]** here");
    expect(press("a [word] here", "italic")).toBe("a _[word]_ here");
    expect(press("a [word] here", "strikethrough")).toBe("a ~~[word]~~ here");
    expect(press("a [word] here", "code")).toBe("a `[word]` here");
  });

  it("takes the marks off when pressed again, from outside or inside", () => {
    expect(press("a **[word]** here", "bold")).toBe("a [word] here");
    expect(press("a [**word**] here", "bold")).toBe("a [word] here");
    expect(press("a _[word]_ here", "italic")).toBe("a [word] here");
  });

  it("puts the caret between new marks when nothing is selected", () => {
    expect(press("a []b", "bold")).toBe("a **[]**b");
  });

  it("does not read a lone mark as a wrapped selection", () => {
    expect(press("[*]", "italic")).toBe("_[*]_");
    expect(press("[**]", "bold")).toBe("**[**]**");
  });

  it("fences code that runs over several lines", () => {
    expect(press("[x = 1\ny = 2]", "code")).toBe("```\n[x = 1\ny = 2]\n```");
  });

  it("takes the selection in either order", () => {
    const out = applyFormat("a word", 6, 2, "bold");
    expect(out.text).toBe("a **word**");
  });
});

describe("prefixing the lines (§582)", () => {
  it("prefixes every line the selection touches, whole", () => {
    expect(press("one\nt[wo\nthr]ee\nfour", "bullets")).toBe("one\n[- two\n- three]\nfour");
    expect(press("[]title", "heading")).toBe("[# title]");
    expect(press("a\n[b]", "quote")).toBe("a\n[> b]");
  });

  it("numbers from one", () => {
    expect(press("[a\nb\nc]", "numbers")).toBe("[1. a\n2. b\n3. c]");
  });

  it("takes the prefix off when every line has it", () => {
    expect(press("[- a\n- b]", "bullets")).toBe("[a\nb]");
    expect(press("[1. a\n7. b]", "numbers")).toBe("[a\nb]");
    // One line without it: the prefix goes on the rest, not doubled.
    expect(press("[- a\nb]", "bullets")).toBe("[- a\n- b]");
    expect(press("[1. a\nb]", "numbers")).toBe("[1. a\n2. b]");
  });

  it("does not reach the line after a selection ending at a newline", () => {
    expect(press("[a\n]b", "bullets")).toBe("[- a]\nb");
  });
});

describe("a link (§582)", () => {
  it("wraps the selection and selects the address to type", () => {
    const out = applyFormat("see docs", 4, 8, "link");
    expect(out.text).toBe("see [docs](https://)");
    expect(out.text.slice(out.start, out.end)).toBe("https://");
    expect(applyFormat("", 0, 0, "link").text).toBe("[link](https://)");
  });
});

describe("what the toolbar writes is what the renderer reads (§582)", () => {
  const read = (format: MarkdownFormat) => {
    const out = applyFormat("word", 0, 4, format);
    return parse(out.text)[0]!;
  };

  it("inline formats become their inline kinds", () => {
    const inline = (format: MarkdownFormat) =>
      (read(format) as { children: { kind: string }[] }).children[0]!.kind;
    expect(inline("bold")).toBe("strong");
    expect(inline("italic")).toBe("em");
    expect(inline("strikethrough")).toBe("del");
    expect(inline("code")).toBe("code");
    expect(inline("link")).toBe("link");
  });

  it("line formats become their blocks", () => {
    expect(read("heading").kind).toBe("heading");
    expect(read("quote").kind).toBe("quote");
    expect(read("bullets")).toMatchObject({ kind: "list", ordered: false });
    expect(read("numbers")).toMatchObject({ kind: "list", ordered: true });
  });

  it("every format has a button", () => {
    expect([...FORMATS].sort()).toEqual(
      ["bold", "bullets", "code", "heading", "italic", "link", "numbers", "quote", "strikethrough"]);
  });
});

describe("p.466's auto-sizing (§582)", () => {
  it("grows with the lines, within bounds", () => {
    expect(autoRows("")).toBe(MIN_ROWS);
    expect(autoRows("a\nb\nc\nd")).toBe(5);
    expect(autoRows("x\n".repeat(100))).toBe(MAX_ROWS);
    expect(autoRows("a", 6)).toBe(6);
  });
});
