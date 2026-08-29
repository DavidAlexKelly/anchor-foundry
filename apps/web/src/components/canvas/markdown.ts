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
 * **Not built here, and named rather than approximated**: p.319's inline
 * `:objectreference[…]{…}` extension and p.315's annotation objects. Both need
 * ontology plumbing and an output object set; a renderer that showed their
 * syntax as literal text would be worse than one that says it does not do them.
 */

// ---- the tree ---------------------------------------------------------------

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "strong"; children: Inline[] }
  | { kind: "em"; children: Inline[] }
  | { kind: "del"; children: Inline[] }
  | { kind: "mark"; children: Inline[] }
  | { kind: "break" }
  | { kind: "link"; href: string; children: Inline[] }
  | { kind: "image"; src: string; alt: string };

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
  | { kind: "code"; text: string; lang: string }
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

function pushText(out: Inline[], text: string): void {
  if (!text) return;
  const last = out[out.length - 1];
  if (last && last.kind === "text") last.text += text;
  else out.push({ kind: "text", text });
}

/** Parse one line's worth of inline syntax.
 *
 * A single left-to-right scan with no backtracking beyond "is there a closer" —
 * which is why an unclosed delimiter comes out as its own text rather than
 * swallowing the rest of the document. Somebody typing `2 * 3 * 4` has not
 * asked for italics, and a parser that gives it to them is a parser people
 * stop trusting with arithmetic.
 */
export function parseInline(source: string): Inline[] {
  const out: Inline[] = [];
  let i = 0;
  let plain = "";
  const flush = () => { pushText(out, plain); plain = ""; };

  while (i < source.length) {
    const rest = source.slice(i);

    // Escapes first: `\*` is a literal asterisk, and without this there is no
    // way to write one.
    if (rest[0] === "\\" && rest.length > 1) {
      plain += rest[1];
      i += 2;
      continue;
    }

    // Code spans suppress everything inside them, so they are tried before any
    // emphasis - `` `a * b` `` is code containing an asterisk, not an italic.
    if (rest[0] === "`") {
      const end = rest.indexOf("`", 1);
      if (end > 0) {
        flush();
        out.push({ kind: "code", text: rest.slice(1, end) });
        i += end + 1;
        continue;
      }
    }

    // Images before links: `![alt](src)` starts with the link syntax one
    // character in.
    const image = /^!\[([^\]]*)\]\(([^)\s]*)\)/.exec(rest);
    if (image) {
      const src = safeHref(image[2]);
      flush();
      if (src) out.push({ kind: "image", src, alt: image[1] ?? "" });
      else pushText(out, image[0]);
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
      if (href) out.push({ kind: "link", href, children: parseInline(link[1] ?? "") });
      else pushText(out, link[0]);
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
          children: parseInline(rest.slice(mark.open.length, end)),
        } as Inline);
        i += end + mark.close.length;
        continue;
      }
    }

    plain += rest[0];
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

function cells(line: string): string[] {
  // Strips the outer pipes rather than re-matching `TABLE_ROW`: the match
  // has already happened at both call sites, so a `?? line` fallback was a
  // branch no input could reach and no test could kill.
  return line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

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
}

/** p.318's syntax, as blocks. */
export function parse(source: unknown, options: ParseOptions = {}): Block[] {
  const breaks = options.breaks !== false;
  const lines = String(source ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  const paragraph: string[] = [];
  const endParagraph = () => {
    if (paragraph.length === 0) return;
    const joined = breaks ? paragraph.join("\n") : paragraph.join(" ");
    blocks.push({ kind: "paragraph", children: withBreaks(joined) });
    paragraph.length = 0;
  };

  while (i < lines.length) {
    const line = lines[i]!;

    if (!line.trim()) { endParagraph(); i += 1; continue; }

    const fence = FENCE.exec(line);
    if (fence) {
      endParagraph();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i]!)) { body.push(lines[i]!); i += 1; }
      i += 1;  // the closing fence, or the end of the source
      blocks.push({ kind: "code", text: body.join("\n"), lang: fence[1] ?? "" });
      continue;
    }

    // Before the rule check, because `---` under a table is its alignment row
    // and `- item` starts with a dash.
    if (RULE.test(line)) { endParagraph(); blocks.push({ kind: "rule" }); i += 1; continue; }

    const heading = HEADING.exec(line);
    if (heading) {
      endParagraph();
      blocks.push({
        kind: "heading",
        level: heading[1]!.length,
        children: parseInline(heading[2]!),
      });
      i += 1;
      continue;
    }

    if (QUOTE.test(line)) {
      endParagraph();
      const body: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i]!)) {
        body.push(QUOTE.exec(lines[i]!)![1]!);
        i += 1;
      }
      // Recursive, so a quote may hold a list or a heading - p.314's "block
      // styling" is a block, and a block that could only hold text would not be
      // one.
      blocks.push({ kind: "quote", blocks: parse(body.join("\n"), options) });
      continue;
    }

    // A table needs its alignment row on the *next* line; without it these are
    // just lines with pipes in them.
    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1]!)) {
      endParagraph();
      const head = cells(line).map(parseInline);
      const align = cells(lines[i + 1]!).map(alignOf);
      i += 2;
      const rows: Inline[][][] = [];
      while (i < lines.length && TABLE_ROW.test(lines[i]!)) {
        rows.push(cells(lines[i]!).map(parseInline));
        i += 1;
      }
      blocks.push({ kind: "table", head, rows, align });
      continue;
    }

    if (UNORDERED.test(line) || ORDERED.test(line)) {
      endParagraph();
      // No `&& !UNORDERED.test(line)`: it was there, and it was dead. One
      // regex needs a digit where the other needs `-`, `*` or `+`, so no
      // line matches both and the guard could never decide anything (§202).
      const ordered = ORDERED.test(line);
      const items: ListItem[] = [];
      while (i < lines.length) {
        const m = ordered ? ORDERED.exec(lines[i]!) : UNORDERED.exec(lines[i]!);
        if (!m) break;
        const text = m[1]!;
        const task = TASK.exec(text);
        items.push(task
          ? { children: parseInline(task[2]!), done: task[1]!.toLowerCase() === "x" }
          : { children: parseInline(text) });
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

/** Turn the newlines inside a paragraph into explicit breaks.
 *
 * p.317's "Break on newlines" is decided by the *caller* — this only sees the
 * text it was handed, joined with newlines when the option is on and with
 * spaces when it is off.
 */
function withBreaks(text: string): Inline[] {
  const parts = text.split("\n");
  const out: Inline[] = [];
  parts.forEach((part, index) => {
    if (index > 0) out.push({ kind: "break" });
    out.push(...parseInline(part));
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
