/**
 * p.466's rich text view, edited in place (§789): what a reader typed into
 * the rendered Markdown, written back as Markdown.
 *
 * > "Rich text and raw Markdown views: Toggle between a rich text view
 * > (formatted preview with inline editing) and a raw Markdown view (plain
 * > text with Markdown syntax)." (p.466)
 *
 * The rich view is the Markdown widget's own rendering (`markdown-view.tsx`)
 * made `contentEditable`. The browser edits that DOM - typing, Enter, its own
 * bold and lists - and this reads it back: each element the renderer draws
 * as the syntax `markdown.ts` reads it from, and the elements a browser adds
 * while editing (`<div>` for a new line, `<b>`, `<i>`, `<strike>`) as the
 * ones they mean. Text is escaped, so a `*` somebody types in the rich view
 * stays an asterisk rather than starting an italic.
 *
 * Pure over a small slice of the DOM (`DomLike`), so a test can hand it plain
 * objects; the widget hands it the live element.
 */

export interface DomLike {
  nodeType: number;
  nodeName: string;
  textContent: string | null;
  childNodes: ArrayLike<DomLike>;
  getAttribute?(name: string): string | null;
  /** An `<input type="checkbox">`'s tick: a task list item (p.318). */
  checked?: boolean;
}

const TEXT = 3;
const ELEMENT = 1;

const BLOCKS = new Set([
  "P", "DIV", "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "BLOCKQUOTE", "PRE", "HR",
  "TABLE",
]);

/** Plain text as Markdown that reads back as the same text. */
export function escapeText(text: string): string {
  return text
    .replace(/[\\`*_[\]]/g, "\\$&")
    .replace(/==/g, "\\=\\=")
    .replace(/~~/g, "\\~\\~");
}

/** A paragraph's first characters, escaped where they would start a block:
 * a heading, a quote, a list item, a rule, a fence or a table row. */
function guardLine(line: string): string {
  return /^(#{1,6}(\s|$)|>|[-+*](\s|$)|\d+\.(\s|$)|---|```|\|)/.test(line) ? `\\${line}` : line;
}

function children(node: DomLike): DomLike[] {
  return Array.from(node.childNodes);
}

function isBlock(node: DomLike): boolean {
  return node.nodeType === ELEMENT && BLOCKS.has(node.nodeName);
}

/** The Markdown of a run of inline nodes. */
export function inlineOf(nodes: readonly DomLike[]): string {
  return nodes.map(inlineNode).join("");
}

function wrapped(mark: string, node: DomLike): string {
  const inner = inlineOf(children(node));
  if (!inner.trim()) return inner;
  // A space just inside a marker stops it being one, so it moves outside.
  const lead = inner.match(/^\s*/)![0];
  const trail = inner.match(/\s*$/)![0];
  return `${lead}${mark}${inner.trim()}${mark}${trail}`;
}

function inlineNode(node: DomLike): string {
  if (node.nodeType === TEXT) return escapeText((node.textContent ?? "").replace(/\u00a0/g, " "));
  if (node.nodeType !== ELEMENT) return "";
  switch (node.nodeName) {
    case "STRONG": case "B": return wrapped("**", node);
    case "EM": case "I": return wrapped("_", node);
    case "DEL": case "S": case "STRIKE": return wrapped("~~", node);
    case "MARK": return wrapped("==", node);
    case "CODE": {
      const text = node.textContent ?? "";
      return text ? `\`${text}\`` : "";
    }
    case "BR": return "\n";
    case "A": {
      const href = node.getAttribute?.("href") ?? "";
      const text = inlineOf(children(node));
      return href ? `[${text}](${href})` : text;
    }
    case "IMG": {
      const src = node.getAttribute?.("src") ?? "";
      return src ? `![${escapeText(node.getAttribute?.("alt") ?? "")}](${src})` : "";
    }
    case "INPUT": return "";
    default: return inlineOf(children(node));
  }
}

/** A paragraph's lines, each guarded, without the blank lines a browser
 * leaves at its end. */
function paragraph(text: string): string {
  return text.replace(/\n+$/, "").split("\n").map(guardLine).join("\n");
}

/** One block element's Markdown, or "" for an empty one. */
function blockOf(node: DomLike): string {
  switch (node.nodeName) {
    case "H1": case "H2": case "H3": case "H4": case "H5": case "H6": {
      const text = inlineOf(children(node)).replace(/\n/g, " ").trim();
      return text ? `${"#".repeat(Number(node.nodeName[1]))} ${text}` : "";
    }
    case "UL": case "OL": {
      const items = children(node).filter((n) => n.nodeName === "LI");
      return items.map((item, i) => {
        const box = children(item).find((n) => n.nodeName === "INPUT");
        const task = box ? `[${box.checked ? "x" : " "}] ` : "";
        const text = inlineOf(children(item)).replace(/\n/g, " ").trim();
        return `${node.nodeName === "OL" ? `${i + 1}.` : "-"} ${task}${text}`;
      }).join("\n");
    }
    case "BLOCKQUOTE": {
      const inner = blocksOf(children(node));
      return inner ? inner.split("\n").map((l) => (l ? `> ${l}` : ">")).join("\n") : "";
    }
    case "PRE": return `\`\`\`\n${(node.textContent ?? "").replace(/\n$/, "")}\n\`\`\``;
    case "HR": return "---";
    case "TABLE": {
      const rows: DomLike[] = [];
      const collect = (n: DomLike) => {
        for (const c of children(n)) {
          if (c.nodeName === "TR") rows.push(c);
          else if (c.nodeType === ELEMENT) collect(c);
        }
      };
      collect(node);
      const lines = rows.map((r) => `| ${children(r)
        .filter((c) => c.nodeName === "TD" || c.nodeName === "TH")
        .map((c) => inlineOf(children(c)).replace(/\n/g, " ").replace(/\|/g, "\\|").trim())
        .join(" | ")} |`);
      if (lines.length === 0) return "";
      const width = (lines[0]!.match(/ \| /g)?.length ?? 0) + 1;
      return [lines[0], `|${" --- |".repeat(width)}`, ...lines.slice(1)].join("\n");
    }
    default: {
      // A paragraph, or a browser's line: a <div> may hold blocks of its own.
      return children(node).some(isBlock) ? blocksOf(children(node))
        : paragraph(inlineOf(children(node)));
    }
  }
}

/** The Markdown of a sequence of nodes: block elements one each, and runs of
 * inline nodes between them as paragraphs - the first line a browser leaves
 * as bare text before the `<div>`s it adds. */
export function blocksOf(nodes: readonly DomLike[]): string {
  const out: string[] = [];
  let run: DomLike[] = [];
  const flush = () => {
    const text = paragraph(inlineOf(run));
    if (text.trim()) out.push(text);
    run = [];
  };
  for (const node of nodes) {
    if (isBlock(node)) {
      flush();
      const text = blockOf(node);
      if (text.trim()) out.push(text);
    } else {
      run.push(node);
    }
  }
  flush();
  return out.join("\n\n");
}

/** The rich view's element, as the Markdown it now shows. */
export function markdownOf(root: DomLike): string {
  return blocksOf(children(root));
}
