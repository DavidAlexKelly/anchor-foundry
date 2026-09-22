/**
 * p.11's command palette (§428; `code-repositories` p.11).
 *
 * > "To expose keyboard shortcuts via the command palette, use the F1 key in
 * > Windows or Fn+F1 on macOS."
 *
 * **Not Monaco's palette, and that is the whole reason this exists.** The
 * editor is a real Monaco instance, so F1 inside it already opens Monaco's
 * own palette — of Monaco's own commands: fold, go to line, change all
 * occurrences. p.11's sentence sits under "the core functionalities available
 * in your Code Repository", which is the *application's* vocabulary: switch
 * branch, open a file, get to the Checks tab. Monaco knows none of those, and
 * a palette that answered "branch" with nothing would be worse than no
 * palette at all.
 *
 * So this palette is over the application's commands, and it opens from
 * anywhere on the page rather than only where Monaco has focus — which is the
 * other half of the same point: a reader who has just clicked the file tree
 * should not have to click back into the editor to reach a keyboard shortcut.
 *
 * **No per-command keystroke column**, though p.11 calls the palette a way to
 * expose shortcuts. This page has exactly one binding — F1, the palette
 * itself — so a column would be empty on every row, and an empty column
 * teaches nobody (§223). What p.11's sentence asks for is carried by the
 * palette's footer naming the keys that *do* work: F1 to open it, the arrows
 * to move, Enter to run, Escape to leave.
 *
 * ---
 *
 * **Pure, and in `lib/` because vitest cannot parse `.tsx`.** What a palette
 * *does* is a component; which commands a query matches, and in what order,
 * is arithmetic — and it is the part that is wrong in every palette that
 * feels bad to use.
 */

export interface Command {
  /** Stable, and the key a test addresses. */
  id: string;
  /** What the palette shows. */
  label: string;
  /** The group it sits under — "Go to", "Branch", "Open". Shown beside the
   *  label, and carrying most of the row's meaning: "Files" and "z1.md" are
   *  a tab and a file, and only the group says which. It is matched on too,
   *  so "go files" and "open z1" both work. */
  group: string;
  /** Why a disabled command cannot run — "already here", "viewing a commit".
   *  Shown only when `enabled` is false, because that is the only time a
   *  reader is asking. */
  note?: string;
  /** Extra words a query may match that the label does not contain — "remove"
   *  finding "Delete file". Never shown; matching on invisible text is how a
   *  palette answers the word somebody actually thought of. */
  hints?: string[];
  /** False when the command cannot run right now. **Kept and disabled rather
   *  than removed**: a palette whose list changes shape as the page does is
   *  one nobody learns, and "Commit — nothing to commit" tells a reader why
   *  where an absent row tells them nothing (§214). */
  enabled?: boolean;
  run: () => void;
}

/** Whether every character of `query` appears in `text`, in order.
 *
 * **Subsequence rather than substring**, which is what makes "opf" find "Open
 * file": a palette people type three letters into has to match the way they
 * abbreviate. Case-insensitive, because nobody holds shift for a palette.
 */
export function subsequence(text: string, query: string): boolean {
  const haystack = text.toLowerCase();
  const needle = query.toLowerCase();
  let at = 0;
  for (const ch of needle) {
    at = haystack.indexOf(ch, at);
    if (at === -1) return false;
    at += 1;
  }
  return true;
}

/** How well one command answers a query. Lower is better; `null` is no match.
 *
 * The order is the one a reader expects and would not be able to name:
 *
 *   0. the label starts with the query — "com" should put "Commit" first;
 *   1. the label contains it — "mit" finds "Commit" without preferring it;
 *   2. the group or label matches as a subsequence — "opf" finds "Open file";
 *   3. only a hint matches — "remove" finds "Delete file", but after anything
 *      whose visible text matched, because a row that matched on words the
 *      reader cannot see looks like a mistake when it comes first.
 */
export function rank(command: Command, query: string): number | null {
  // **No early return for an empty query**, though one was written here. A
  // query of nothing trims to nothing, and every label starts with nothing,
  // so the prefix branch below already answers 0 for all of them - the guard
  // was a second way of saying the same thing, and a mutation sweep could not
  // make it matter (§223).
  const q = query.trim().toLowerCase();
  const label = command.label.toLowerCase();
  if (label.startsWith(q)) return 0;
  if (label.includes(q)) return 1;
  if (subsequence(`${command.group} ${command.label}`, q)) return 2;
  if ((command.hints ?? []).some((hint) => hint.toLowerCase().includes(q))) return 3;
  return null;
}

/**
 * The commands a query matches, best first.
 *
 * **Ties keep the order they were given in**, which is the author's grouping —
 * a palette that re-sorted equal matches alphabetically would shuffle its
 * whole list on every keystroke that changed nothing.
 *
 * **Disabled commands are matched and kept**, for the reason `enabled` exists:
 * a reader who types "commit" and sees nothing learns that the palette is
 * broken, where one who sees a greyed row learns that there is nothing to
 * commit.
 */
export function matching(
  commands: readonly Command[], query: string,
): Command[] {
  return commands
    .map((command, index) => ({ command, index, score: rank(command, query) }))
    .filter((hit): hit is { command: Command; index: number; score: number } =>
      hit.score !== null)
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map((hit) => hit.command);
}

/**
 * Where the highlight goes when the list changes under it.
 *
 * **By id, not by index.** A palette that kept "row 3" as the reader typed
 * would move the highlight to whatever command happened to land there, and
 * Enter would run something nobody was looking at — which is the one bug a
 * palette must not have. If the highlighted command is still in the list it
 * stays highlighted; otherwise the first row is, because there is always a
 * first row to run.
 */
export function keepHighlight(
  matches: readonly Command[], highlighted: string | null,
): string | null {
  if (matches.length === 0) return null;
  if (highlighted !== null && matches.some((c) => c.id === highlighted)) {
    return highlighted;
  }
  return matches[0]!.id;
}

/** The next highlighted id after an arrow key.
 *
 * **Wraps**, because a list of six commands is short enough that reaching the
 * end and stopping reads as the key not working. */
export function step(
  matches: readonly Command[], highlighted: string | null, by: 1 | -1,
): string | null {
  if (matches.length === 0) return null;
  const at = matches.findIndex((c) => c.id === highlighted);
  const next = (at === -1 ? (by === 1 ? 0 : matches.length - 1) : at + by);
  return matches[((next % matches.length) + matches.length) % matches.length]!.id;
}

/**
 * Whether a key event should open the palette.
 *
 * **F1, which is what p.11 names** — "the F1 key in Windows or Fn+F1 on
 * macOS". Those are the same event: `Fn` is a hardware modifier that produces
 * F1, so the browser sees `key === "F1"` either way and one binding covers
 * both. Said here because the two spellings look like two cases.
 *
 * **Not while a modifier is held**, so a browser or OS shortcut built on F1
 * keeps working — and not when the event has already been handled, which is
 * what `defaultPrevented` means. Monaco binds F1 to its own palette and calls
 * `preventDefault`; this listener is on the window and sees the event after
 * it, so the editor keeps its palette and the page keeps this one, and
 * neither opens two.
 */
export function opensPalette(event: {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  defaultPrevented?: boolean;
}): boolean {
  if (event.defaultPrevented) return false;
  if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return false;
  return event.key === "F1";
}

/** What the palette says when a query matches nothing.
 *
 * **It names the query.** "No command matches ‘comit’" is a typo somebody
 * can see; "No results" is a palette that might be broken. */
export function emptyNote(query: string): string {
  return `No command matches “${query.trim()}”`;
}
