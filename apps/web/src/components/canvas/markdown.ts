/** p.314–319's Markdown widget: the syntax p.318 lists, parsed to a tree.
 *
 * > "Basic Markdown text formatting such as bold, italic, strikethrough, and
 * > highlighting… More advanced Markdown formatting such as headers, tables,
 * > block styling, code styling, and URLs" (p.314)
 *
 * > "Note that the highlight syntax `==text==` and tasklist are supported
 * > despite not being standard in typical Markdown implementations." (p.317)
 *
 * > "**Break on newlines**: … When enabled, which is the default for new
 * > widgets, a single newline in the source begins a new line in the rendered
 * > output. When disabled, single newlines are collapsed into spaces, following
 * > standard Markdown rendering." (p.317)
 *
 * ---
 *
 * **Hand-rolled, and safety is the reason rather than the absence of a
 * library.** Markdown's whole hazard is that it emits markup, and every
 * off-the-shelf renderer produces an HTML *string* — which then has to be
 * sanitised and injected with `dangerouslySetInnerHTML`, so the app is one
 * missed sanitiser configuration away from executing whatever an author typed.
 *
 * This parses to a **tree of plain objects** which the widget renders as React
 * elements. There is no HTML string anywhere in the path, so there is nothing
 * to inject into: raw HTML in the source is text, because text is all this
 * produces.
 *
 * The one place a URL survives into an attribute is a link or an image, and
 * `safeHref` governs it with **the same rule `services/workshop_events.py`
 * already applies to `open_url`** — an app author is not necessarily trusted by
 * everyone who opens the app, and a published app is opened by the whole
 * workspace. A refused URL renders as its own text rather than vanishing, so an
 * author can see what was rejected.
 *
 * p.318's list is *closed*, which is what makes a hand-rolled parser reasonable
 * rather than optimistic: fourteen syntaxes, enumerated, with a table of
 * examples that reads as a specification and is used as one by the test beside
 * this module.
 *
 * **p.319's inline `:objectreference[…]{…}` extension is parsed when asked
 * for** (§632, the `references` option): a widget with p.316's "Inline
 * reference" tag type on. Off, the same characters are text, as they are in
 * standard Markdown and in a README. **Not built here**: p.315's annotation
 * objects, named rather than approximated.
 */

// ---- the tree ---------------------------------------------------------------

export type Inline =
  /** `at`, when the parse was asked for offsets (§636): where in the source
   * the text's first character is. A text node's characters are consecutive
   * in the source, so `at + n` is its n-th. */
  | { kind: "text"; text: string; at?: number }
  | { kind: "code"; text: string; at?: number }
  | { kind: "strong"; children: Inline[] }
  | { kind: "em"; children: Inline[] }
  | { kind: "del"; children: Inline[] }
  | { kind: "mark"; children: Inline[] }
  | { kind: "break" }
  | { kind: "link"; href: string; children: Inline[] }
  | { kind: "image"; src: string; alt: string }
  /** p.319's anchor (§632): text standing for one object, by its type's
   * api_name and its primary key. */
  | {
      kind: "objectref"; objectType: string; primaryKey: string; children: Inline[];
      /** Its place among the anchors, in reading order, once numbered. */
      index?: number;
    };

export type Align = "left" | "center" | "right";

export interface ListItem {
  children: Inline[];
  /** p.318's task list: `undefined` for an ordinary item, so "not a task" and
   * "an unticked task" stay different things — a checkbox nobody asked for is
   * as wrong as a missing one. */
  done?: boolean;
}

export type Block =
  | { kind: "heading"; level: number; children: Inline[] }
  | { kind: "paragraph"; children: Inline[] }
  | { kind: "code"; text: string; lang: string; at?: number }
  | { kind: "quote"; blocks: Block[] }
  | { kind: "list"; ordered: boolean; items: ListItem[] }
  | { kind: "rule" }
  | { kind: "table"; head: Inline[][]; rows: Inline[][][]; align: (Align | null)[] };

// ---- URLs -------------------------------------------------------------------

/** Schemes a link or image may use.
 *
 * **The same list as `URL_SCHEMES` in `services/workshop_events.py`**, and
 * deliberately so: `open_url` and a Markdown link are the same capability
 * reached two ways, and a scheme refused by one and allowed by the other is a
 * hole with a rule written next to it. `javascript:` is the one that matters.
 */
export const URL_SCHEMES = ["http://", "https://", "mailto:", "/"];

/** A URL if it is one this platform will navigate to, `null` otherwise.
 *
 * **An embedded control character is a refusal, not something to strip out.**
 * This first stripped them and re-checked, which is the standard defence
 * against `java\nscript:alert(1)` — and which is a *denylist* measure that
 * does nothing here while quietly doing harm. An allowlist already refuses
 * `javascript:` for the ordinary reason that it is not on the list, broken up
 * or not; what stripping adds is the other direction, where `ht\ntps://evil`
 * becomes an accepted `https://evil` that nobody wrote.
 *
 * The mutation harness is what found it: **deleting the strip changed no
 * test**, because all three tests that named it were watching the allowlist do
 * the work and calling it the strip's.
 *
 * Whitespace at the ends is ordinary and is trimmed. A control character
 * anywhere inside is not, and refuses the URL.
 */
export function safeHref(raw: unknown): string | null {
  // Not `String(raw)`: props come off a saved JSON document, so this is reached
  // with whatever an author put there, and an object that *stringifies* to an
  // allowed URL is not an allowed URL.
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(trimmed)) return null;
  // Folded for the comparison and returned **unfolded**: `HTTPS://` is a URL,
  // and case is not this function's to change.
  const lower = trimmed.toLowerCase();
  return URL_SCHEMES.some((s) => lower.startsWith(s)) ? trimmed : null;
}

// ---- inline -----------------------------------------------------------------

/** The delimiters p.318 lists, longest first.
 *
 * Order is load-bearing: `**` has to be tried before `*` or every bold run
 * parses as two italics with an empty middle.
 */
const MARKS: { open: string; close: string; kind: "strong" | "em" | "del" | "mark" }[] = [
  { open: "**", close: "**", kind: "strong" },
  { open: "__", close: "__", kind: "strong" },
  // p.317: "the highlight syntax `==text==`… supported despite not being
  // standard in typical Markdown implementations".
  { open: "==", close: "==", kind: "mark" },
  { open: "~~", close: "~~", kind: "del" },
  // p.318's own example is a *single* tilde: `~pretty good~`.
  { open: "~", close: "~", kind: "del" },
  { open: "*", close: "*", kind: "em" },
  { open: "_", close: "_", kind: "em" },
];

/** Append text, joined to the text before it when that is one run - and,
 * with offsets, only when the two are consecutive in the source, so a text
 * node's offset always names every one of its characters (§636). */
function pushText(out: Inline[], text: string, at?: number): void {
  if (!text) return;
  const last = out[out.length - 1];
  if (last && last.kind === "text"
      && (at === undefined || (last.at !== undefined && last.at + last.text.length === at))) {
    last.text += text;
  } else {
    out.push(at === undefined ? { kind: "text", text } : { kind: "text", text, at });
  }
}

/** Parse one line's worth of inline syntax.
 *
 * A single left-to-right scan with no backtracking beyond "is there a closer" —
 * which is why an unclosed delimiter comes out as its own text rather than
 * swallowing the rest of the document. Somebody typing `2 * 3 * 4` has not
 * asked for italics, and a parser that gives it to them is a parser people
 * stop trusting with arithmetic.
 */
/** p.319's syntax: `:objectreference[$text]{objectType="…" primaryKey="…"}`. */
const OBJECT_REFERENCE = /^:objectreference\[([^\]]*)\]\{([^}]*)\}/;
const ATTRIBUTE = /(\w+)\s*=\s*"([^"]*)"/g;

/** The two attributes p.319 requires, or null when either is missing. */
export function referenceAttributes(
  raw: string,
): { objectType: string; primaryKey: string } | null {
  const found: Record<string, string> = {};
  for (const [, key, value] of raw.matchAll(ATTRIBUTE)) found[key!] = value!;
  const objectType = found.objectType?.trim();
  const primaryKey = found.primaryKey;
  return objectType && primaryKey !== undefined && primaryKey !== ""
    ? { objectType, primaryKey }
    : null;
}

export function parseInline(source: string, references = false, map?: readonly number[]): Inline[] {
  const out: Inline[] = [];
  let i = 0;
  // `map[n]` is where the n-th character of `source` is in the whole
  // document (§636), when offsets were asked for.
  const at = (n: number) => (map ? map[n] : undefined);
  const sub = (from: number, to: number) => (map ? map.slice(from, to) : undefined);
  let plain = "";
  let plainAt: number | undefined;
  const flush = () => { pushText(out, plain, plainAt); plain = ""; plainAt = undefined; };
  // A character of plain text, starting a new run where the source skips.
  const add = (ch: string, where: number | undefined) => {
    if (plain && where !== undefined && plainAt !== undefined && plainAt + plain.length !== where) {
      flush();
    }
    if (!plain) plainAt = where;
    plain += ch;
  };

  while (i < source.length) {
    const rest = source.slice(i);

    // Escapes first: `\*` is a literal asterisk, and without this there is no
    // way to write one.
    if (rest[0] === "\\" && rest.length > 1) {
      add(rest[1]!, at(i + 1));
      i += 2;
      continue;
    }

    // Code spans suppress everything inside them, so they are tried before any
    // emphasis - `` `a * b` `` is code containing an asterisk, not an italic.
    if (rest[0] === "`") {
      const end = rest.indexOf("`", 1);
      if (end > 0) {
        flush();
        const where = at(i + 1);
        out.push(where === undefined
          ? { kind: "code", text: rest.slice(1, end) }
          : { kind: "code", text: rest.slice(1, end), at: where });
        i += end + 1;
        continue;
      }
    }

    // p.319's anchor, before links: its text is in brackets too. Only when
    // the widget asked for references, and only with both attributes - an
    // anchor naming no object is its own source text, as a refused link is.
    const reference = references ? OBJECT_REFERENCE.exec(rest) : null;
    if (reference) {
      const named = referenceAttributes(reference[2] ?? "");
      flush();
      if (named) {
        const open = ":objectreference[".length;
        out.push({ kind: "objectref", ...named,
                   children: parseInline(reference[1] ?? "", references,
                     sub(i + open, i + open + (reference[1] ?? "").length)) });
      } else {
        pushText(out, reference[0], at(i));
      }
      i += reference[0].length;
      continue;
    }

    // Images before links: `![alt](src)` starts with the link syntax one
    // character in.
    const image = /^!\[([^\]]*)\]\(([^)\s]*)\)/.exec(rest);
    if (image) {
      const src = safeHref(image[2]);
      flush();
      if (src) out.push({ kind: "image", src, alt: image[1] ?? "" });
      else pushText(out, image[0], at(i));
      i += image[0].length;
      continue;
    }

    const link = /^\[([^\]]*)\]\(([^)\s]*)\)/.exec(rest);
    if (link) {
      const href = safeHref(link[2]);
      flush();
      // **A refused URL renders as its own source text**, not as a link with a
      // dead href and not as nothing: an author who typed something this
      // platform will not follow should be able to see what was rejected.
      if (href) {
        out.push({ kind: "link", href, children: parseInline(link[1] ?? "", references,
          sub(i + 1, i + 1 + (link[1] ?? "").length)) });
      } else {
        pushText(out, link[0], at(i));
      }
      i += link[0].length;
      continue;
    }

    const mark = MARKS.find((m) => rest.startsWith(m.open));
    if (mark) {
      const end = rest.indexOf(mark.close, mark.open.length);
      // A closer, and something between it and the opener: `**` on its own is
      // two asterisks.
      if (end > mark.open.length) {
        flush();
        out.push({
          kind: mark.kind,
          children: parseInline(rest.slice(mark.open.length, end), references,
            sub(i + mark.open.length, i + end)),
        } as Inline);
        i += end + mark.close.length;
        continue;
      }
    }

    add(rest[0]!, at(i));
    i += 1;
  }
  flush();
  return out;
}

// ---- blocks -----------------------------------------------------------------

const HEADING = /^(#{1,6})\s+(.*)$/;
const RULE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/;
const UNORDERED = /^\s*[-*+]\s+(.*)$/;
const ORDERED = /^\s*\d+[.)]\s+(.*)$/;
const TASK = /^\[([ xX])\]\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const FENCE = /^\s*```\s*(\S*)\s*$/;
const TABLE_ROW = /^\s*\|(.*)\|\s*$/;
// The same pipe shape `TABLE_ROW` requires. Allowing the alignment row to
// drop its leading pipe made `cells` reachable with a line no pipe rule had
// matched, which is how the dead fallback above came to be written.
const TABLE_RULE = /^\s*\|[\s:|-]+\|\s*$/;

function alignOf(spec: string): Align | null {
  const t = spec.trim();
  if (!/^:?-+:?$/.test(t)) return null;
  const left = t.startsWith(":");
  const right = t.endsWith(":");
  if (left && right) return "center";
  if (right) return "right";
  if (left) return "left";
  // **`null`, not "left".** p.317 says explicit per-column alignment "takes
  // precedence over the widget-level text alignment setting" - so a column
  // that did not ask has to stay unasked, or the widget's own setting would be
  // overridden by every table that failed to mention it.
  return null;
}

export interface ParseOptions {
  /** p.317's "Break on newlines", **default on** — which is a divergence from
   * standard Markdown that p.317 states and chooses. */
  breaks?: boolean;
  /** p.316's "Inline reference" tag type (§632): parse p.319's anchors. */
  references?: boolean;
  /** Record where each text run came from in the source (§636), for p.317's
   * user text selection. Offsets count the source with its line endings made
   * `\n`, which is the text the widget renders. */
  offsets?: boolean;
}

/** A line, and where each of its characters is in the source. */
interface Line {
  text: string;
  map: number[] | undefined;
}

const range = (from: number, length: number) =>
  Array.from({ length }, (_, n) => from + n);

/** p.318's syntax, as blocks. */
export function parse(source: unknown, options: ParseOptions = {}): Block[] {
  const text = String(source ?? "").replace(/\r\n?/g, "\n");
  let at = 0;
  const lines: Line[] = text.split("\n").map((line) => {
    const out = { text: line, map: options.offsets ? range(at, line.length) : undefined };
    at += line.length + 1;
    return out;
  });
  return parseLines(lines, options);
}

function parseLines(lines: Line[], options: ParseOptions): Block[] {
  const breaks = options.breaks !== false;
  const refs = options.references === true;
  // The tail of a line from `from` on, with its map.
  const tail = (line: Line, from: number): Line => ({
    text: line.text.slice(from),
    map: line.map?.slice(from),
  });
  const inline = (l: Line) => parseInline(l.text, refs, l.map);
  const blocks: Block[] = [];
  let i = 0;

  const paragraph: Line[] = [];
  const endParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push({ kind: "paragraph", children: joined(paragraph, breaks, refs) });
    paragraph.length = 0;
  };

  while (i < lines.length) {
    const line = lines[i]!;

    if (!line.text.trim()) { endParagraph(); i += 1; continue; }

    const fence = FENCE.exec(line.text);
    if (fence) {
      endParagraph();
      const body: Line[] = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i]!.text)) { body.push(lines[i]!); i += 1; }
      i += 1;  // the closing fence, or the end of the source
      const code: Block = { kind: "code", text: body.map((l) => l.text).join("\n"),
        lang: fence[1] ?? "" };
      // A code block's lines are consecutive in the source, so its first
      // character's offset names the rest.
      const first = body[0]?.map?.[0];
      blocks.push(first === undefined ? code : { ...code, at: first } as Block);
      continue;
    }

    // Before the rule check, because `---` under a table is its alignment row
    // and `- item` starts with a dash.
    if (RULE.test(line.text)) { endParagraph(); blocks.push({ kind: "rule" }); i += 1; continue; }

    const heading = HEADING.exec(line.text);
    if (heading) {
      endParagraph();
      blocks.push({
        kind: "heading",
        level: heading[1]!.length,
        // The captured text runs to the end of the line, so it starts where
        // the line's length less its own leaves off.
        children: inline(tail(line, line.text.length - heading[2]!.length)),
      });
      i += 1;
      continue;
    }

    if (QUOTE.test(line.text)) {
      endParagraph();
      const body: Line[] = [];
      while (i < lines.length && QUOTE.test(lines[i]!.text)) {
        const rest = QUOTE.exec(lines[i]!.text)![1]!;
        body.push(tail(lines[i]!, lines[i]!.text.length - rest.length));
        i += 1;
      }
      // Recursive, so a quote may hold a list or a heading - p.314's "block
      // styling" is a block, and a block that could only hold text would not be
      // one.
      blocks.push({ kind: "quote", blocks: parseLines(body, options) });
      continue;
    }

    // A table needs its alignment row on the *next* line; without it these are
    // just lines with pipes in them.
    if (TABLE_ROW.test(line.text) && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1]!.text)) {
      endParagraph();
      const head = cells(line).map(inline);
      const align = cells(lines[i + 1]!).map((c) => alignOf(c.text));
      i += 2;
      const rows: Inline[][][] = [];
      while (i < lines.length && TABLE_ROW.test(lines[i]!.text)) {
        rows.push(cells(lines[i]!).map(inline));
        i += 1;
      }
      blocks.push({ kind: "table", head, rows, align });
      continue;
    }

    if (UNORDERED.test(line.text) || ORDERED.test(line.text)) {
      endParagraph();
      // No `&& !UNORDERED.test(line)`: it was there, and it was dead. One
      // regex needs a digit where the other needs `-`, `*` or `+`, so no
      // line matches both and the guard could never decide anything (§202).
      const ordered = ORDERED.test(line.text);
      const items: ListItem[] = [];
      while (i < lines.length) {
        const current = lines[i]!;
        const m = ordered ? ORDERED.exec(current.text) : UNORDERED.exec(current.text);
        if (!m) break;
        const item = tail(current, current.text.length - m[1]!.length);
        const task = TASK.exec(item.text);
        items.push(task
          ? { children: inline(tail(item, item.text.length - task[2]!.length)),
              done: task[1]!.toLowerCase() === "x" }
          : { children: inline(item) });
        i += 1;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }

    paragraph.push(line);
    i += 1;
  }
  endParagraph();
  return blocks;
}

/** A table row's cells, each trimmed, with their maps. */
function cells(line: Line): Line[] {
  // Strips the outer pipes rather than re-matching `TABLE_ROW`: the match
  // has already happened at both call sites, so a `?? line` fallback was a
  // branch no input could reach and no test could kill.
  const text = line.text;
  let from = text.length - text.trimStart().length;
  let to = text.trimEnd().length;
  if (text[from] === "|") from += 1;
  if (to > from && text[to - 1] === "|") to -= 1;
  const out: Line[] = [];
  let start = from;
  for (let n = from; n <= to; n++) {
    if (n === to || text[n] === "|") {
      let a = start;
      let b = n;
      while (a < b && /\s/.test(text[a]!)) a += 1;
      while (b > a && /\s/.test(text[b - 1]!)) b -= 1;
      out.push({ text: text.slice(a, b), map: line.map?.slice(a, b) });
      start = n + 1;
    }
  }
  return out;
}

/** A paragraph's lines as inline text, p.317's "Break on newlines" deciding
 * whether a newline is a break or a space. Either way the character stands
 * where the source's newline did, so the map runs straight through. */
function joined(lines: Line[], breaks: boolean, references: boolean): Inline[] {
  if (!breaks) {
    const text = lines.map((l) => l.text).join(" ");
    // The space joining two lines stands for the newline after the first.
    const map = lines[0]!.map
      ? lines.flatMap((l, n) => (n === lines.length - 1
        ? l.map! : [...l.map!, l.map![l.map!.length - 1]! + 1]))
      : undefined;
    return parseInline(text, references, map);
  }
  const out: Inline[] = [];
  lines.forEach((line, index) => {
    if (index > 0) out.push({ kind: "break" });
    out.push(...parseInline(line.text, references, line.map));
  });
  return out;
}

// ---- widget-level settings --------------------------------------------------

export const ALIGNMENTS: Record<Align, string> = {
  left: "Left",
  center: "Center",
  right: "Right",
};

export const DEFAULT_ALIGNMENT: Align = "left";

export function alignmentOf(raw: unknown): Align {
  return typeof raw === "string" && Object.hasOwn(ALIGNMENTS, raw)
    ? (raw as Align)
    : DEFAULT_ALIGNMENT;
}

/** How one block is aligned, given the widget's setting.
 *
 * > "Code blocks remain left-aligned and full-width regardless of the selected
 * > alignment." (p.317)
 *
 * A function rather than a conditional inside the renderer, because it is a
 * rule p.317 *states* — and a rule stated in a document is one somebody will
 * eventually ask whether we follow.
 */
export function blockAlignment(block: Block, widget: Align): Align {
  return block.kind === "code" ? "left" : widget;
}

/** How one table column is aligned.
 *
 * > "Explicit per-column alignment defined in Markdown table syntax (for
 * > example, `| :---: |`) takes precedence over the widget-level text alignment
 * > setting." (p.317)
 *
 * This is the whole reason `alignOf` returns `null` for a column that did not
 * ask, rather than defaulting it to `"left"`: a default there would mean every
 * table silently overrode the widget's own setting, and the precedence p.317
 * describes would run backwards.
 */
export function columnAlignment(column: Align | null, widget: Align): Align {
  return column ?? widget;
}

/** p.316's "Input data: Text/Variable". */
export type Source = "text" | "variable";

export function sourceOf(raw: unknown): Source {
  return raw === "variable" ? "variable" : "text";
}

/** The Markdown to render, from whichever source is configured. */
export function textOf(source: unknown, text: unknown, fromVariable: unknown): string {
  const raw = sourceOf(source) === "variable" ? fromVariable : text;
  return typeof raw === "string" ? raw : "";
}
