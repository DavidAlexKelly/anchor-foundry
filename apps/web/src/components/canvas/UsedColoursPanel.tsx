"use client";

/** p.213's Used colors panel, the Unsaved half (§398).
 *
 * > "Used colors can be accessed by navigating to a module's Settings tab in
 * > edit mode… Unsaved colors represent custom colors used in layouts and
 * > widgets throughout the module that are not defined as saved colors. You
 * > can select the hex code of an unsaved color to copy it for use elsewhere,
 * > and you can also see the usage of these colors in layouts and widgets
 * > within the module." (p.213-214)
 *
 * Both halves now (§414). What counts as a used colour is `used-colours.ts`'s,
 * including p.213's one exclusion; what a saved colour *is* is
 * `saved-colours.ts`'s. This file draws them and answers one question neither
 * module can: what each node is *called*, which only the editor knows.
 *
 * **It reads the live document, not the saved one.** The panel exists to be
 * looked at while colours are being changed — a list that only caught up on
 * save would be telling an author about the module they had a minute ago,
 * which is the one moment a colour audit is useless.
 */

import { useEditor } from "@craftjs/core";
import { useState } from "react";

import { emptyReason, referenceUses, usageLabel, usedColours } from "./used-colours";
import { type SavedColour, added, paletteOf, updated } from "./saved-colours";

/** How long "Copied" stays up. Long enough to read, short enough that a second
 * copy of a different colour is not mistaken for the first one still showing.
 * Same two seconds as `CopyLinkButton`. */
const COPIED_MS = 2000;

export function UsedColoursPanel({
  palette: stored = [],
  onPaletteChange,
}: {
  /** p.214's Saved colors, as the module stores them. */
  palette?: unknown;
  /** Absent means a caller that has not been given the palette — the panel
   * then draws the Unsaved half alone rather than offering an Add button that
   * would write into nothing (§214). */
  onPaletteChange?: (next: SavedColour[]) => void;
}) {
  // One selector for both, because they are one walk of the same node map and
  // because Craft compares a selector's result deeply: the panel re-renders
  // when a colour changes and sits still through every other edit.
  const palette = paletteOf(stored);
  const { colours, labels, refs } = useEditor((state) => {
    const layout: Record<string, { props: unknown }> = {};
    const names: Record<string, string> = {};
    for (const [id, node] of Object.entries(state.nodes)) {
      // Craft's live node holds its props under `data`; the serialised map the
      // pure module reads holds them at the top. One shape conversion here
      // rather than a second walker that understands both (§292).
      layout[id] = { props: node.data?.props ?? {} };
      const renamed = (node.data?.custom as { displayName?: string } | undefined)
        ?.displayName;
      names[id] = renamed || node.data?.displayName || node.data?.name || "Widget";
    }
    // Parked widgets are walked too, and that is deliberate: a colour on a
    // widget under p.68's holding node is still a colour this module carries,
    // and the audit's job is to find every place a hex was typed. Decision
    // 0010 makes the same call for variables.
    return {
      colours: usedColours(layout), labels: names, refs: referenceUses(layout),
    };
  });
  const [copied, setCopied] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [openSaved, setOpenSaved] = useState<string | null>(null);
  const empty = emptyReason(colours);

  async function copy(hex: string) {
    try {
      await navigator.clipboard.writeText(hex);
      setCopied(hex);
      window.setTimeout(() => setCopied((c) => (c === hex ? null : c)), COPIED_MS);
    } catch {
      // The clipboard is absent outside a secure context and can refuse
      // inside one. The hex is on screen either way — it is six characters
      // and it is already selectable — so there is nothing to fall back to
      // and nothing to apologise for. What must not happen is the button
      // reporting a copy that did not occur (§214).
      setCopied(null);
    }
  }

  /** p.214's "Add colors to the Saved colors section". Seeded from a hex when
   * one is offered, which is what makes the button on an unsaved row useful:
   * the colour a builder is looking at is the one they want to name.
   *
   * **Adding does not rewrite the document.** p.214 says adding makes a colour
   * "selectable"; it does not say it claims every widget already holding that
   * hex. Rewriting them would be a silent edit to nodes the builder did not
   * select, and the one thing that cannot be undone by pressing the button
   * again. */
  function add(hex = "#16232f") {
    onPaletteChange?.(added(palette, hex));
  }

  function edit(id: string, change: Partial<Omit<SavedColour, "id">>) {
    onPaletteChange?.(updated(palette, id, change));
  }

  return (
    <div className="canvas-colours" data-testid="used-colours">
      {/* p.213: "The panel consists of two main sections: Saved colors and
          Unsaved colors", in p.213's order. Saved first because it is the one
          with something to press — the other is a report. */}
      <p className="field-label">Saved colours</p>
      {onPaletteChange && palette.length === 0 && (
        <p className="canvas-widget-empty" data-testid="saved-colours-empty">
          No saved colours. Add one to make it selectable on any background,
          and to change it everywhere at once.
        </p>
      )}
      {palette.length > 0 && (
        <ul className="canvas-colours-rows" data-testid="saved-colours-rows">
          {palette.map((colour) => {
            const uses = refs[colour.id] ?? [];
            return (
              <li key={colour.id} data-saved={colour.id}>
                <span className="canvas-colours-row">
                  <span
                    className="canvas-colours-swatch"
                    style={{ background: colour.light }}
                    data-testid={`saved-swatch-${colour.id}`}
                  />
                  <input
                    className="canvas-colours-name"
                    data-testid={`saved-name-${colour.id}`}
                    value={colour.name}
                    aria-label="Colour name"
                    readOnly={!onPaletteChange}
                    onChange={(e) => edit(colour.id, { name: e.target.value })}
                  />
                  <button
                    type="button"
                    className="btn quiet"
                    data-testid={`saved-uses-${colour.id}`}
                    aria-expanded={openSaved === colour.id}
                    onClick={() =>
                      setOpenSaved((o) => (o === colour.id ? null : colour.id))}
                  >
                    {/* The same sentence the unsaved rows use, from the same
                        function: two ways of saying "3 places" in one panel is
                        two things a reader has to learn. */}
                    {usageLabel({ hex: colour.light, uses })}
                  </button>
                </span>
                {/* p.214: "set separate colors for light and dark modes". Both
                    always shown rather than the dark one behind a toggle — a
                    pair where half is hidden is a pair people forget they
                    have, and a module that looks wrong in dark mode is found
                    by somebody else. */}
                <span className="canvas-colours-pair">
                  <label>
                    <span className="soft">Light</span>
                    <input
                      type="text"
                      data-testid={`saved-light-${colour.id}`}
                      value={colour.light}
                      readOnly={!onPaletteChange}
                      onChange={(e) => edit(colour.id, { light: e.target.value })}
                    />
                  </label>
                  <label>
                    <span className="soft">Dark</span>
                    <input
                      type="text"
                      data-testid={`saved-dark-${colour.id}`}
                      value={colour.dark}
                      readOnly={!onPaletteChange}
                      onChange={(e) => edit(colour.id, { dark: e.target.value })}
                    />
                  </label>
                </span>
                {openSaved === colour.id && (
                  <ul
                    className="canvas-colours-uses"
                    data-testid={`saved-use-list-${colour.id}`}
                  >
                    {uses.length === 0 ? (
                      <li className="soft">Nothing uses this colour yet.</li>
                    ) : uses.map((use) => (
                      <li key={`${use.node}.${use.prop}`}>
                        <span className="canvas-colours-use-node">
                          {labels[use.node] ?? use.node}
                        </span>
                        <span className="soft">{use.prop}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {onPaletteChange && (
        <button
          type="button"
          className="btn quiet"
          data-testid="saved-colours-add"
          onClick={() => add()}
        >
          Add a saved colour
        </button>
      )}

      <p className="field-label">Unsaved colours</p>
      {empty ? (
        <p className="canvas-widget-empty" data-testid="used-colours-empty">{empty}</p>
      ) : (
        <ul className="canvas-colours-rows" data-testid="used-colours-rows">
          {colours.map((colour) => (
            <li key={colour.hex}>
              <span className="canvas-colours-row">
                <span
                  className="canvas-colours-swatch"
                  style={{ background: colour.hex }}
                  data-testid={`colour-swatch-${colour.hex.slice(1)}`}
                />
                {/* p.214: "select the hex code of an unsaved color to copy
                    it". The hex *is* the button, rather than a hex with a
                    copy icon beside it — the sentence describes selecting the
                    code itself, and it is the only thing on the row worth
                    pressing. */}
                <button
                  type="button"
                  className="btn quiet canvas-colours-hex"
                  data-testid={`colour-hex-${colour.hex.slice(1)}`}
                  onClick={() => copy(colour.hex)}
                >
                  {copied === colour.hex ? "Copied" : colour.hex}
                </button>
                <button
                  type="button"
                  className="btn quiet"
                  data-testid={`colour-uses-${colour.hex.slice(1)}`}
                  aria-expanded={open === colour.hex}
                  onClick={() =>
                    setOpen((o) => (o === colour.hex ? null : colour.hex))}
                >
                  {usageLabel(colour)}
                </button>
                {/* p.214's "Add colors to the Saved colors section", from the
                    row a builder is already looking at. It adds the colour and
                    stops there: p.214 says adding makes a colour selectable,
                    not that it claims every widget already holding that hex,
                    and rewriting those would be a silent edit to nodes nobody
                    selected. The row stays where it is until somebody points a
                    widget at the saved colour. */}
                {onPaletteChange && (
                  <button
                    type="button"
                    className="btn quiet"
                    data-testid={`colour-save-${colour.hex.slice(1)}`}
                    onClick={() => add(colour.hex)}
                  >
                    Save
                  </button>
                )}
              </span>
              {/* p.214's "see the usage of these colors in layouts and
                  widgets". Behind the count rather than always open: a colour
                  used in eleven places would otherwise push every colour below
                  it off the panel, and the count alone answers the question
                  most often asked of this list. */}
              {open === colour.hex && (
                <ul
                  className="canvas-colours-uses"
                  data-testid={`colour-use-list-${colour.hex.slice(1)}`}
                >
                  {colour.uses.map((use) => (
                    <li key={`${use.node}.${use.prop}`}>
                      <span className="canvas-colours-use-node">
                        {labels[use.node] ?? use.node}
                      </span>
                      <span className="soft">{use.prop}</span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
