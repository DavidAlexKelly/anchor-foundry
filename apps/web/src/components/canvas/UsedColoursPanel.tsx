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
 * What counts as a used colour is `used-colours.ts`'s, including p.213's one
 * exclusion. This file draws it and answers one question that module cannot:
 * what each node is *called*, which only the editor knows.
 *
 * **It reads the live document, not the saved one.** The panel exists to be
 * looked at while colours are being changed — a list that only caught up on
 * save would be telling an author about the module they had a minute ago,
 * which is the one moment a colour audit is useless.
 */

import { useEditor } from "@craftjs/core";
import { useState } from "react";

import { emptyReason, usageLabel, usedColours } from "./used-colours";

/** How long "Copied" stays up. Long enough to read, short enough that a second
 * copy of a different colour is not mistaken for the first one still showing.
 * Same two seconds as `CopyLinkButton`. */
const COPIED_MS = 2000;

export function UsedColoursPanel() {
  // One selector for both, because they are one walk of the same node map and
  // because Craft compares a selector's result deeply: the panel re-renders
  // when a colour changes and sits still through every other edit.
  const { colours, labels } = useEditor((state) => {
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
    return { colours: usedColours(layout), labels: names };
  });
  const [copied, setCopied] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
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

  return (
    <div className="canvas-colours" data-testid="used-colours">
      <p className="field-label">Used colours</p>
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
      {/* The half that is not built, named where somebody would look for it.
          p.213's Saved colors are a module-level palette widgets reference by
          name, so that "when you edit a saved color, the change propagates";
          an author who came here for that should find out here rather than
          from the absence of a section. */}
      <p className="canvas-widget-empty" data-testid="used-colours-note">
        These are colours typed into widgets. Named module colours that update
        everywhere at once aren&apos;t here yet.
      </p>
    </div>
  );
}
