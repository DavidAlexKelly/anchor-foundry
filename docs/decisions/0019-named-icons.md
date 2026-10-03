# 0019 — A named icon set, drawn here

**Status:** decided (§705), under the standing instruction to choose the next
step rather than stop for it; small and reversible
**Roadmap:** every parity row carrying "○ for the reason every icon setting
is", and `object-link-types` p.15's "Select the default icon"

---

## The question

Foundry's icon settings choose from a named set. Until §705 this platform had
none, and said so in a dozen places: an icon was one or two typed characters,
an emoji or an initial, and the rows that wanted an icon carried a ○ for it.
Meanwhile `object_types.icon` has defaulted to `"cube"` since db 0003, a name
from Foundry's set, drawn as the type's initial because nothing could draw a
cube.

## Decision

**A small set of named icons, drawn in this repository** (`apps/web/src/lib/
icons.ts`), with Foundry's names.

- **Drawn, not installed.** The web app depends on React, Next, Craft, Monaco
  and its fonts. An icon package of thousands, to draw sixty-five, is the bloat
  this platform exists to leave out, and Blueprint's own set is Palantir's
  design system, which the style work already declined as a dependency
  (`workshop.md`, background colours).
- **Foundry's names** (`cube`, `person`, `map-marker`, `warning-sign` …),
  because names are what is stored. Types created here before §705 hold
  `cube`, and an ontology exported from Foundry holds Foundry's names. Each
  name in the set draws, and a name outside it still falls back to the
  initial, as before.
- **Strokes on a 16-unit grid in `currentColor`**, so an icon takes the ink of
  what it sits in, white on a type's coloured mark and the text colour
  elsewhere. A test holds every path inside the grid.
- **A typed glyph still works** wherever it did. A value is a name only when it
  is one of the set's. Nothing stored changes meaning except a name that now
  draws as its icon.

## What it closes, and in what order

§705 builds the set and the place p.15 names, an object type's icon: the
editor's picker, and the mark wherever a type is drawn (Explorer, object view,
panels, the Object Set Title's Show icon). Each widget icon setting that
carries the ○ then becomes its own unit, reading the same set: Prominent Term, Markdown interactions, Stepper, the section
header and the Button. Each one keeps accepting the glyph it took before.

## What it does not do

It does not try to be Foundry's set. Sixty-five icons cover the nouns an
operational ontology is made of, and an icon Foundry has that this set lacks
falls back to the type's initial, with the editor saying so. Adding one is a
line of path data and the grid test.
