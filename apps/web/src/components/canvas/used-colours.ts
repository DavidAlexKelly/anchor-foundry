/** p.213's Used colors panel: which colours a module actually uses (§398).
 *
 * > "Colors used within a Workshop application can be defined and saved on the
 * > module level using Workshop's used colors feature… The panel consists of
 * > two main sections: Saved colors and Unsaved colors." (p.213)
 *
 * > "Unsaved colors represent custom colors used in layouts and widgets
 * > throughout the module that are not defined as saved colors. You can select
 * > the hex code of an unsaved color to copy it for use elsewhere, and you can
 * > also see the usage of these colors in layouts and widgets within the
 * > module." (p.214)
 *
 * **This is the Unsaved half**, which is a *read* of a document this platform
 * already stores. Saved colors are a write and a much larger one — a named
 * module-level palette that widgets reference rather than copy, so that
 * "when you edit a saved color, the change propagates" — which turns every
 * colour prop in the canvas into a hex-or-reference and every reader into a
 * resolver. §391 sized the two and said to build this one first, because it
 * answers "where is this colour used" without changing how a single widget
 * stores anything. `workshop.md` §9 carries what the other half costs.
 *
 * **p.213's one exclusion maps onto something real here.** "Note that usage of
 * intent colors will not be displayed in the Used colors panel." Our intent
 * colours are `BACKGROUND_PRESETS` — `shade-2` is a name for a role, not a
 * value somebody chose — so a background set to a preset is not a used colour
 * and a background set to a hex is. That distinction is the whole reason the
 * panel is useful: it lists what an author typed, which is what an author
 * might want to tidy.
 */
import { isHex, normaliseHex } from "./style";
import { refIn } from "./saved-colours";
import type { LayoutNodes } from "../../lib/workshop-module";

/** Where one colour is used. */
export interface ColourUse {
  node: string;
  /** The prop that holds it, `steps[1].completedColour` for a nested one — the
   * index is what makes the answer usable, the same reason
   * `workshop_variables.references` reports one. */
  prop: string;
}

export interface UsedColour {
  /** Normalised: lowercase, six digits. `#FFF` and `#ffffff` are one colour,
   * or a module with four colours reports twelve. */
  hex: string;
  uses: ColourUse[];
}

/** Props whose value is a colour. Listed rather than pattern-matched on the
 * name: `colour` is a Pie segment's, `background` is a section's, and a rule
 * like "anything ending in Colour" would quietly start including the next prop
 * somebody names that way without deciding whether it belongs. */
const COLOUR_PROPS = ["background", "completedColour", "activeColour"] as const;
// `background` is every styled node's (`StyleProps`); `completedColour` and
// `activeColour` are the Stepper's p.313 pair, which are top-level props on
// the widget and not per-step — the first draft of this list had them nested
// under `steps`, where they would never have matched anything.

/** Nested colours: a prop holding a list of entries, each of which may carry
 * one. Same shape `NESTED_REFERENCE_PROPS` takes on the server.
 *
 * Two, and both were read off the widget that stores them rather than guessed
 * from the settings panel that edits them (§216). The Timeline's per-layer
 * colour (p.348) spells the field `colour`; the pie's per-segment override
 * (p.310) spells it `color`. The inconsistency is in the documents already —
 * changing it would be a migration, and a walker that only knew one spelling
 * would silently miss half the custom colours in the corpus. */
const NESTED_COLOUR_PROPS: Record<string, readonly string[]> = {
  layers: ["colour"],
  segments: ["color"],
};

function record(
  found: Map<string, ColourUse[]>,
  value: unknown,
  node: string,
  prop: string,
): void {
  if (typeof value !== "string" || value === "") return;
  // **p.213's exclusion is carried by the hex test below, not by a check of
  // its own.** "Note that usage of intent colors will not be displayed in the
  // Used colors panel" — and our intent colours are `BACKGROUND_PRESETS`,
  // whose keys are *names* (`shade-2`, `transparent`). None of them can pass
  // `isHex`, so an explicit `value in BACKGROUND_PRESETS` guard stood here
  // and no input could ever reach it. It is gone: a guard that cannot fire is
  // a claim nobody can check (§213), and leaving it would have suggested the
  // exclusion cost something to honour when in fact it falls out of what the
  // panel is for — an author can only copy a hex, so a hex is all it lists.
  if (!isHex(value)) return;
  const hex = normaliseHex(value);
  const uses = found.get(hex) ?? [];
  uses.push({ node, prop });
  found.set(hex, uses);
}

/**
 * Every custom colour in the document, with where it is used.
 *
 * Ordered by how widely a colour is used, then by hex so the list is stable
 * between renders. p.214's purpose is swapping a colour out, and the one used
 * in eleven places is the one worth looking at first.
 *
 * **A free-text CSS colour is not listed**, and that is a judgement rather than
 * an oversight. `resolveBackground` passes `red` and `var(--panel)` through
 * untouched because modules in the corpus hold them, but p.214 offers "the hex
 * code of an unsaved color to copy" — a row whose value cannot be copied as a
 * hex is a row that does not do what the panel says it does. They stay in the
 * document and out of this list, which is the honest treatment of a value the
 * feature has no answer for.
 */
export function usedColours(layout: unknown): UsedColour[] {
  const found = new Map<string, ColourUse[]>();
  eachColourValue(layout, (value, node, prop) => record(found, value, node, prop));
  return [...found.entries()]
    .map(([hex, uses]) => ({ hex, uses }))
    .sort((a, b) => (b.uses.length - a.uses.length) || a.hex.localeCompare(b.hex));
}

/** Every value sitting in a colour prop, wherever the prop sits.
 *
 * **Extracted when §414 needed the same walk for a different question.** Which
 * props hold a colour — and that two widgets spell theirs differently — is one
 * fact, and a second walk would be a second list to keep in step: a saved
 * colour would work on a section and not on a Timeline layer, and nobody would
 * report it because it reads as "that widget does not support it" (§292).
 */
export function eachColourValue(
  layout: unknown,
  visit: (value: unknown, node: string, prop: string) => void,
): void {
  if (!layout || typeof layout !== "object") return;
  for (const [nodeId, node] of Object.entries(layout as LayoutNodes)) {
    const props = (node as { props?: Record<string, unknown> } | undefined)?.props;
    if (!props || typeof props !== "object") continue;
    for (const prop of COLOUR_PROPS) visit(props[prop], nodeId, prop);
    for (const [listProp, inner] of Object.entries(NESTED_COLOUR_PROPS)) {
      const entries = props[listProp];
      if (!Array.isArray(entries)) continue;
      entries.forEach((entry, index) => {
        if (!entry || typeof entry !== "object") return;
        for (const key of inner) {
          visit(
            (entry as Record<string, unknown>)[key],
            nodeId,
            `${listProp}[${index}].${key}`,
          );
        }
      });
    }
  }
}

/** Where each saved colour is referenced, by id (p.214; §414).
 *
 * > "…and view where each color is used across layouts and widgets in your
 * > module." (p.214)
 *
 * The Saved half of the question `usedColours` answers for the Unsaved one,
 * over the same walk. Keyed by id rather than by name, because a rename must
 * not change the answer — which is the whole reason a reference names an id.
 */
export function referenceUses(layout: unknown): Record<string, ColourUse[]> {
  const found: Record<string, ColourUse[]> = {};
  eachColourValue(layout, (value, node, prop) => {
    const id = refIn(value);
    if (id === null) return;
    (found[id] ??= []).push({ node, prop });
  });
  return found;
}

/** How a colour's usage reads. p.214: "see the usage of these colors in layouts
 * and widgets within the module". */
export function usageLabel(colour: UsedColour): string {
  const places = new Set(colour.uses.map((u) => u.node)).size;
  return `${places} place${places === 1 ? "" : "s"}`;
}

/**
 * The sentence when a module has no custom colours.
 *
 * **Not "no colours".** A module using only presets is fully coloured and has
 * nothing to tidy, which is a good state rather than an empty one — and a
 * panel saying "no colours used" over a deliberately themed module would read
 * as a fault.
 */
export function emptyReason(colours: readonly UsedColour[]): string | null {
  return colours.length === 0
    ? "No custom colours. This module uses the standard shades only."
    : null;
}
