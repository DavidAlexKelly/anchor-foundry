import { describe, expect, it } from "vitest";

import { parse, type Block, type Inline } from "./markdown";
import { selectedSource, selectionRange } from "./markdown-selection";

/** p.317's user text selection (§636): offsets from the parse, and the range
 * a selection's two ends make. */

function runs(blocks: Block[]): { text: string; at: number | undefined; block?: true }[] {
  const out: { text: string; at: number | undefined; block?: true }[] = [];
  const inline = (nodes: Inline[]) => nodes.forEach((n) => {
    if (n.kind === "text" || n.kind === "code") out.push({ text: n.text, at: n.at });
    if ("children" in n) inline(n.children);
  });
  const block = (b: Block) => {
    if (b.kind === "heading" || b.kind === "paragraph") inline(b.children);
    if (b.kind === "quote") b.blocks.forEach(block);
    if (b.kind === "list") b.items.forEach((item) => inline(item.children));
    if (b.kind === "table") { b.head.forEach(inline); b.rows.forEach((r) => r.forEach(inline)); }
    if (b.kind === "code") out.push({ text: b.text, at: b.at, block: true });
  };
  blocks.forEach(block);
  return out;
}

const SOURCES = [
  "Newark has __*rarely*__ seen issues",
  "# Main header\n\n### sub header",
  "I *think* this **sentence** is ~pretty good~ and ==great== with `share`",
  "> quoted\n> across **two** lines",
  "- Item 1\n- Item **2**\n1. First\n2. Second",
  "- [ ] Task 1\n- [x] Task 2",
  "| Header 1 | Header 2 |\n|:--|--:|\n|  Row 1 | Data *1* |",
  "a \\*literal\\* star and [a link](https://example.com) here",
  "```\nexample code\nmore\n```",
  "line one\nline **two**\r\nline three",
  ':objectreference[Alert A1]{objectType="t" primaryKey="A1"} after',
];

describe("offsets from the parse", () => {
  it("names, for every run, the source it came from", () => {
    for (const source of SOURCES) {
      const text = source.replace(/\r\n?/g, "\n");
      for (const breaks of [true, false]) {
        for (const run of runs(parse(source, { offsets: true, breaks, references: true }))) {
          expect(run.at, `${JSON.stringify(source)} ${run.text}`).toBeTypeOf("number");
          // A newline in the source is a space in a paragraph without breaks;
          // a code block keeps its newlines either way.
          const joins = !breaks && !run.block;
          expect(text.slice(run.at!, run.at! + run.text.length).replace(/\n/g, joins ? " " : "\n"),
            JSON.stringify(source)).toBe(run.text);
        }
      }
    }
  });

  it("is only there when asked for", () => {
    for (const run of runs(parse("I *think* so\n\n```\ncode\n```"))) {
      expect(run.at).toBeUndefined();
    }
  });

  it("starts a heading's and a list item's text after their markers", () => {
    expect(runs(parse("## Title", { offsets: true }))).toEqual([{ text: "Title", at: 3 }]);
    expect(runs(parse("10. Tenth\n- [x] Done", { offsets: true }))).toEqual([
      { text: "Tenth", at: 4 }, { text: "Done", at: 16 }]);
    expect(runs(parse("- [x] Done", { offsets: true }))).toEqual([{ text: "Done", at: 6 }]);
  });

  it("splits a run where an escape skips a character", () => {
    const [p] = parse("a\\*b", { offsets: true });
    expect(p).toEqual({ kind: "paragraph", children: [
      { kind: "text", text: "a", at: 0 }, { kind: "text", text: "*b", at: 2 }] });
  });
});

describe("the selected range", () => {
  it("is start first whichever way it was dragged, and nothing for a click", () => {
    expect(selectionRange({ at: 10, offset: 3 }, { at: 2, offset: 1 }))
      .toEqual({ start: 3, end: 13 });
    expect(selectionRange({ at: 2, offset: 1 }, { at: 10, offset: 3 }))
      .toEqual({ start: 3, end: 13 });
    expect(selectionRange({ at: 4, offset: 0 }, { at: 2, offset: 2 })).toBeNull();
    expect(selectionRange(null, { at: 2, offset: 2 })).toBeNull();
    expect(selectionRange({ at: 2, offset: 2 }, null)).toBeNull();
  });

  it("covers the raw Markdown between the two ends", () => {
    const source = "I *think* this **sentence** is";
    // "think" to "sentence", as rendered: from inside the em to inside the strong.
    expect(selectedSource(source, { start: 3, end: 25 })).toBe("think* this **sentence");
  });
});
