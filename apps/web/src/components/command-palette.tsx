"use client";

/** The command palette (§428; `code-repositories` p.11).
 *
 * > "To expose keyboard shortcuts via the command palette, use the F1 key in
 * > Windows or Fn+F1 on macOS."
 *
 * The arithmetic — what a query matches, in what order, and where the
 * highlight goes when the list changes underneath it — is in
 * `lib/command-palette.ts`, because vitest cannot parse `.tsx` and that is
 * the part worth proving. What is left here is the part a browser has to
 * check: that F1 opens it, that the arrows move a highlight a reader can see,
 * that Enter runs the row they were looking at, and that Escape leaves
 * without running anything.
 *
 * **It owns its own open state and its own key listener.** The alternative —
 * a host that holds `open` and passes it down — puts the F1 binding in
 * whichever application happens to mount the palette, and the second
 * application to want one copies it slightly differently.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { Command } from "@/lib/command-palette";
import {
  emptyNote,
  keepHighlight,
  matching,
  opensPalette,
  step,
} from "@/lib/command-palette";

export function CommandPalette({ commands }: { commands: readonly Command[] }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!opensPalette(event)) return;
      // Firefox and Chrome both open help on F1; without this the palette
      // appears behind a browser window nobody asked for.
      event.preventDefault();
      setOpen(true);
      setQuery("");
      setHighlighted(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  const matches = useMemo(() => matching(commands, query), [commands, query]);

  // **Derived at render, not stored in an effect.** The highlight has to be
  // right in the same paint as the list it points into; a `useEffect` that
  // corrected it afterwards would show one frame where Enter runs the wrong
  // command, and one frame is all a fast typist needs.
  const current = keepHighlight(matches, highlighted);

  function close() {
    setOpen(false);
    setQuery("");
    setHighlighted(null);
  }

  function run(command: Command) {
    if (command.enabled === false) return;
    // Closed first: a command that navigates leaves a palette open over the
    // page it arrived at, and the reader has to dismiss a box to see what
    // they asked for.
    command.run();
    close();
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted(step(matches, current, event.key === "ArrowDown" ? 1 : -1));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const command = matches.find((c) => c.id === current);
      if (command) run(command);
    }
  }

  if (!open) {
    return (
      /* **A button as well as the key.** p.11 names F1, and a control that
         exists only behind a key nobody has been told about is one most
         readers never find (§214 read the other way round: a control that is
         absent is no better than one that looks broken). */
      <button
        type="button"
        className="btn quiet command-palette-open"
        data-testid="open-command-palette"
        onClick={() => {
          setOpen(true);
          setQuery("");
          setHighlighted(null);
        }}
      >
        Commands <kbd>F1</kbd>
      </button>
    );
  }

  return (
    <>
      <div className="command-palette-scrim" onClick={close} data-testid="palette-scrim" />
      <div
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Commands"
        data-testid="command-palette"
        onKeyDown={onKeyDown}
      >
        <input
          ref={input}
          type="text"
          className="command-palette-query"
          data-testid="command-query"
          aria-label="Command"
          /* `aria-activedescendant` rather than moving focus to the row: the
             arrows have to keep working while the caret stays in the box, or
             typing after an arrow key goes nowhere. */
          aria-activedescendant={current ? `command-${current}` : undefined}
          placeholder="Type a command…"
          autoComplete="off"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <ul className="command-palette-list" role="listbox" aria-label="Commands">
          {matches.map((command) => (
            <li key={command.id}>
              <button
                type="button"
                id={`command-${command.id}`}
                role="option"
                aria-selected={command.id === current}
                className={`command-row${command.id === current ? " on" : ""}`}
                data-testid="command-row"
                data-command={command.id}
                data-highlighted={command.id === current}
                disabled={command.enabled === false}
                /* **`onClick`, and it was `onMouseDown` first.** The reason
                   given for `mousedown` — that a click would blur the query
                   box and a blur handler would close the palette before the
                   click landed — was about a blur handler this palette does
                   not have. What `mousedown` costs is real: a row activated
                   by assistive technology fires `click` and nothing else, so
                   the palette would have been reachable by a mouse and by the
                   Enter key and by nothing in between. A mutation sweep found
                   the two indistinguishable, which is what sent somebody
                   looking for the difference that mattered (§223). */
                onClick={() => run(command)}
              >
                <span className="command-group">{command.group}</span>
                <span className="command-label">{command.label}</span>
                {command.enabled === false && command.note && (
                  <span className="command-note">{command.note}</span>
                )}
              </button>
            </li>
          ))}
          {matches.length === 0 && (
            <li className="command-empty" data-testid="command-empty">
              {emptyNote(query)}
            </li>
          )}
        </ul>
        {/* p.11's sentence is about *exposing* shortcuts, so the keys that
            work are written where somebody who pressed F1 can read them. */}
        <div className="command-palette-keys">
          <kbd>↑</kbd><kbd>↓</kbd> to move · <kbd>Enter</kbd> to run ·{" "}
          <kbd>Esc</kbd> to close · <kbd>F1</kbd> to open this again
        </div>
      </div>
    </>
  );
}
