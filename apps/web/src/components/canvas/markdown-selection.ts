/**
 * p.317's User text selection on the Markdown widget (§636).
 *
 * > "Output user selected raw text: Outputs the user selected text as a raw
 * > Markdown string. … Output user selected indices: Outputs the starting and
 * > ending indices of the user selected text as numeric variables." (p.317)
 *
 * The parse records where each text run came from (`ParseOptions.offsets`),
 * and the widget draws each run with its offset. A selection's two ends are
 * each a run's offset plus how far into the run they fall, and the raw text
 * is the source between them: what the reader selected, with whatever
 * Markdown sits inside it. The indices are p.321's: zero-based, the start
 * inclusive and the end exclusive.
 */

/** One end of a selection: the run's source offset and the offset into it. */
export interface SelectionEnd {
  at: number;
  offset: number;
}

/** The selection as source indices, start first however it was dragged, or
 * null for no selection (a click, or an end outside the text). */
export function selectionRange(
  a: SelectionEnd | null,
  b: SelectionEnd | null,
): { start: number; end: number } | null {
  if (!a || !b) return null;
  const x = a.at + a.offset;
  const y = b.at + b.offset;
  if (x === y) return null;
  return { start: Math.min(x, y), end: Math.max(x, y) };
}

/** The raw Markdown a selection covers. */
export function selectedSource(source: string, range: { start: number; end: number }): string {
  return source.slice(range.start, range.end);
}
