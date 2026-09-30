/**
 * p.466's Markdown format for the Text Input (§582).
 *
 * > "Enable a rich text editing experience with a formatting toolbar. Users
 * > can compose and format text using Markdown syntax or the toolbar
 * > controls. The editor supports toggling between a rich text view and a raw
 * > Markdown view." (p.465)
 *
 * > "Formatting toolbar: Apply bold, italic, code, and other formatting using
 * > toolbar controls without needing to know Markdown syntax. Rich text and
 * > raw Markdown views: Toggle between a rich text view (formatted preview
 * > with inline editing) and a raw Markdown view (plain text with Markdown
 * > syntax). … Auto-sizing: Enable the editor to expand automatically based
 * > on content length." (p.466)
 *
 * **The toolbar writes Markdown into the text**, around the selection or at
 * the start of each line it touches, and pressing the same button again takes
 * it off. What it writes is what `markdown.ts` reads (§206), so the rich view -
 * the same renderer the Markdown widget draws with - shows exactly what the
 * toolbar did. Italic is written `_x_` rather than `*x*` so that it can never
 * be read as half of a bold's `**`.
 *
 * Pure: the widget holds the selection and hands it in.
 */

export const FORMATS = [
  "bold", "italic", "strikethrough", "code", "heading", "bullets", "numbers", "quote", "link",
] as const;
export type MarkdownFormat = (typeof FORMATS)[number];

export const FORMAT_LABELS: Record<MarkdownFormat, string> = {
  bold: "Bold",
  italic: "Italic",
  strikethrough: "Strikethrough",
  code: "Code",
  heading: "Heading",
  bullets: "Bulleted list",
  numbers: "Numbered list",
  quote: "Quote",
  link: "Link",
};

/** The text after an edit, and what should be selected in it. */
export interface Edit {
  text: string;
  start: number;
  end: number;
}

const WRAPS: Partial<Record<MarkdownFormat, string>> = {
  bold: "**",
  italic: "_",
  strikethrough: "~~",
  code: "`",
};

const PREFIXES: Partial<Record<MarkdownFormat, string>> = {
  heading: "# ",
  bullets: "- ",
  quote: "> ",
};

/** The selection wrapped in `marker`, or unwrapped when it already is: the
 * marker just outside the selection, or just inside it. */
function wrap(text: string, start: number, end: number, marker: string): Edit {
  const before = text.slice(0, start);
  const chosen = text.slice(start, end);
  const after = text.slice(end);
  if (before.endsWith(marker) && after.startsWith(marker)) {
    return {
      text: before.slice(0, -marker.length) + chosen + after.slice(marker.length),
      start: start - marker.length,
      end: end - marker.length,
    };
  }
  if (chosen.length >= 2 * marker.length && chosen.startsWith(marker) && chosen.endsWith(marker)) {
    const inner = chosen.slice(marker.length, chosen.length - marker.length);
    return { text: before + inner + after, start, end: start + inner.length };
  }
  return {
    text: before + marker + chosen + marker + after,
    start: start + marker.length,
    end: end + marker.length,
  };
}

/** The lines the selection touches, as offsets: from the start of the line
 * the selection starts on to the end of the line it ends on. */
function lineSpan(text: string, start: number, end: number): [number, number] {
  const from = text.lastIndexOf("\n", start - 1) + 1;
  const newline = text.indexOf("\n", Math.max(end, from));
  // A selection ending just after a newline has not touched the next line.
  const last = end > start && text[end - 1] === "\n" ? end - 1 : newline;
  return [from, last < 0 ? text.length : last];
}

const NUMBERED = /^\d+\. /;

/** A prefix on every line the selection touches, or off every one when all
 * already carry it. A numbered list counts from 1. */
function prefix(text: string, start: number, end: number, format: MarkdownFormat): Edit {
  const [from, to] = lineSpan(text, start, end);
  const lines = text.slice(from, to).split("\n");
  const marker = PREFIXES[format];
  const has = (line: string) => (marker ? line.startsWith(marker) : NUMBERED.test(line));
  const strip = (line: string) => (marker ? line.slice(marker.length) : line.replace(NUMBERED, ""));
  const next = lines.every(has)
    ? lines.map(strip)
    : lines.map((line, n) => (marker ?? `${n + 1}. `) + (has(line) ? strip(line) : line));
  const body = next.join("\n");
  return { text: text.slice(0, from) + body + text.slice(to), start: from, end: from + body.length };
}

/** A link around the selection, with its address selected to be typed. */
function link(text: string, start: number, end: number): Edit {
  const label = text.slice(start, end) || "link";
  const address = "https://";
  const written = `[${label}](${address})`;
  const at = start + label.length + 3;
  return {
    text: text.slice(0, start) + written + text.slice(end),
    start: at,
    end: at + address.length,
  };
}

/** One toolbar button pressed over the selection `start`..`end`. */
export function applyFormat(text: string, start: number, end: number, format: MarkdownFormat): Edit {
  const [a, b] = start <= end ? [start, end] : [end, start];
  if (format === "code" && text.slice(a, b).includes("\n")) {
    // Code over several lines is a fenced block, since a span stops at a line.
    const block = "```\n" + text.slice(a, b) + "\n```";
    return { text: text.slice(0, a) + block + text.slice(b), start: a + 4, end: a + 4 + (b - a) };
  }
  const marker = WRAPS[format];
  if (marker) return wrap(text, a, b, marker);
  if (format === "link") return link(text, a, b);
  return prefix(text, a, b, format);
}

/** p.466's Auto-sizing: as many rows as the text has lines, within bounds,
 * so the editor grows with what is written and stops before the page. */
export const MIN_ROWS = 3;
export const MAX_ROWS = 24;

export function autoRows(text: string, least: number = MIN_ROWS): number {
  const lines = text.split("\n").length;
  return Math.min(MAX_ROWS, Math.max(least, lines + 1));
}
