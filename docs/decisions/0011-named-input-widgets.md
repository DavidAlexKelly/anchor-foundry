# 0011 — Splitting the generic parameter control into Foundry's named input widgets

**Status:** accepted; Numeric Input built in `STATUS.md` §202, Text Input in §203, String
Selector in §204. Date and Time Picker outstanding.
**Context:** `docs/parity/workshop.md` §10's filtering table, and the note under it that had
been sitting there unanswered:

> "Our generic parameter control is a defensible design, but it is *our* design, and the ask
> was that Workshop feel like Workshop. **Decision needed:** split it into the four named
> widgets, or keep it and accept the divergence. This spec assumes splitting."

Five rows of that table are `◑ via generic CanvasParameterControl` — String Selector,
Checkbox, Date Input, Text Input, Numeric Input. One widget with a `control` prop stands in
for all of them.

---

## The case for keeping one control

It is genuinely less code, and the five widgets share most of their shape: a label, an output
variable, a value the viewer edits. A `control` prop switching between a `<select>` and an
`<input type="search">` is not a hack; it is the same widget in two costumes.

And it is already in saved documents. Every module built on this platform so far declares
`CanvasParameterControl` nodes, and a split has to say what happens to them.

## The case for splitting, which wins

**The costumes are not the same widget.** Reading p.459–468 rather than the category
overview, the five diverge in configuration, not just appearance:

| Widget | Configuration Foundry gives it |
|---|---|
| **String Selector** (p.459–461) | static or dynamic options, single/multiple, dropdown / radio buttons / checkboxes, layout (vertical, horizontal, grid with a column count), per-mode placeholders, "allow creating new options", "disable clearing" |
| **Text Input** (p.465–466) | placeholder, format = single line / text area / Markdown, event-on-enter, initial height, a whole rich-text mode |
| **Numeric Input** (p.468) | show grouping, reset-to-default, unit prefix, unit suffix as text/icon/**percent** — and the percent case changes what the output variable holds |
| **Date and Time Picker** (p.463–464) | date format, time format, time precision to ms/s/min, timezone user-editable, default timezone static/variable/local |

Those are not four sets of styling options. A `control` prop would have to grow a union of
roughly twenty props of which each mode reads a quarter — and a settings panel showing a
"time precision" field beside a "show grouping" field is a panel nobody can read.

**The percent rule settles it on its own.** p.468: "If the percent sign is selected, the
output variable of the widget will be the user-entered value divided by 100." That is not a
display option. It changes the relationship between what the viewer types and what the
variable holds, for one suffix value, on one of the five. A shared control would carry that
rule permanently and apply it never.

**And the ask is parity.** An author who knows Workshop looks for "Numeric Input" in the
widget list. Finding "Filter" and being told to set its `control` prop is the divergence this
whole exercise exists to remove.

---

## What happens to `CanvasParameterControl`

**It stays, and it stays in the palette until every one of the five exists.**

It cannot be removed while saved documents contain it: the Craft resolver maps a node's
`resolvedName` to a component, and a document naming a component the resolver does not have
does not render — it throws, and the module is lost rather than degraded. Deleting the
component would break every module already built, including ones this platform's own browser
suite seeds.

It also cannot be *silently converted*. A conversion needs to know which of the five a given
node meant, and `control: "select"` maps to String Selector while `control: "text"` maps to
Text Input — which looks decidable until you notice that a `select` fed by a dataset column
is doing what no named widget does (p.461's options are static or from a string array
variable, never from a dataset query). A converter would have to either drop that capability
or invent a sixth widget to hold it.

So: the named widgets are added beside it. The generic control keeps working, keeps its
dataset-backed options, and is the answer for the case Foundry has no widget for. When all
five named widgets exist, its palette entry goes and the component stays — the same shape as
`legacy_name` on a variable: the old thing is not deleted, it is stopped from being the thing
anybody reaches for next.

**No migration, and that is the decision, not an omission.** The alternative — rewriting
saved documents on load — was rejected in decision 0002 for format conversion too, and for
the same reason: a document that changes when you open it is a document whose history stops
meaning anything.

---

## Build order within the split

1. **Numeric Input** (§202) — the smallest surface with the most behaviour, and the percent
   rule makes it the one that proves the split was necessary rather than cosmetic.
2. **Text Input** (§203) — single line and text area. Markdown deferred to the Markdown row,
   which is its own build-order item and its own editor; p.466 describes a formatting toolbar
   and a raw/rich toggle, which is not a format flag. This one also added the `submit` trigger
   to the server's vocabulary, for p.465's "Event on enter".
3. **String Selector** (§204) — subsumes p.444's *Checkbox* row, which p.461 shows is a
   *display mode of a multiple selection* rather than a widget of its own. p.461's selection
   axis turned out to be the second setting in this family that changes what the output
   variable *holds* (after §202's percent suffix), which is the clearest evidence yet that the
   split was necessary. "Allow creating new options" is deferred: it changes the option list
   at runtime and raises where user-created options live, which is a different question from
   choosing among options.
4. **Date and Time Picker** — subsumes *Date Input*; needs timezone handling that nothing
   else in this platform has yet.

Each lands with its own settings panel and its own parity row. The palette entry for the
generic control goes when 4 is done.
