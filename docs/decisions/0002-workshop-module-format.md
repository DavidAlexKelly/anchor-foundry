# 0002 — What a Workshop module is, on disk

**Status:** decided
**Roadmap:** phase 2, item 1.1 (blocking for 1.2–1.5)
**Supersedes nothing.** Extends the Canvas work recorded in `STATUS.md` §36–§38, §43–§44.

---

## The question

Canvas stores an app as a Craft.js node tree and nothing else. Workshop apps are three things — a **layout**, a set of **variables**, and a set of **events** — and only the first is a tree. Before building variables (1.2), events (1.3) or layouts (1.4), we have to decide what the saved document *is*, because all three write to it.

## What exists today, precisely

A saved definition is a flat map of node id → Craft.js node. Here is a real one, trimmed:

```json
{
  "ROOT":   { "type": {"resolvedName": "CanvasContainer"}, "nodes": ["f1", "objmap"], "isCanvas": true },
  "f1":     { "type": {"resolvedName": "CanvasParameterControl"},
              "props": { "name": "region", "label": "Region", "column": "region", … } },
  "objmap": { "type": {"resolvedName": "CanvasMap"},
              "props": { "filterProperty": "region", "filterParameter": "region", … } }
}
```

Two things are worth staring at.

**A variable is declared as a side effect of placing a widget.** `f1` has a `name` prop of `"region"`. That is the only place the parameter `region` comes into existence. Delete the Filter and the parameter is gone; nothing else notices.

**A reference is a string that happens to match.** `objmap` binds to it with `filterParameter: "region"`. Nothing links the two. Rename the filter's `name` and the map keeps asking for a parameter no longer set — silently, and forever, because a missing parameter reads as "no filter" (`useCanvasParameter`, deliberately, so an app is not empty on first load). The failure is invisible: the map shows *more* rows than it should.

That is not a bug to fix in place. It is what an implicit, untyped, string-keyed namespace does, and it is exactly what Workshop's variables are not.

## Decision

**A module is one document with three top-level parts.**

```json
{
  "format": 2,
  "layout":    { "ROOT": { … Craft.js nodes … } },
  "variables": { "v_region": { "id": "v_region", "kind": "string", "label": "Region", … } },
  "events":    { "e_1": { "id": "e_1", "trigger": {…}, "effects": [ … ] } }
}
```

### 1. Craft.js stays, for the layout only

It works, the drag/selection model is not trivial, and §37's map-pan fix lives in that world. But node props stop being the system of record for anything except **layout and per-widget display options**. Data bindings become variable references.

The alternative — replacing Craft.js now — is a rewrite of the one part of Canvas that is not in question, in service of the two parts that are.

### 2. Variables are declared, not implied

A variable exists because the module declares it, with an id, a kind and a label. Widgets reference `"v_region"`, never `"region"`. Consequences, all of them the point:

- **Renaming is free.** The label changes; the id does not; every binding survives.
- **Deleting can be refused.** "Used by 2 widgets" is answerable by reading the document, so the builder can refuse rather than silently unbinding — which is what happens today.
- **Kinds can be checked.** An object-set variable cannot be dropped into a slot expecting a string. Today every parameter is `unknown`.

Ids are generated, opaque and stable (`v_` + a short random suffix). Not derived from the label, because a derived id is a rename waiting to break every reference — the exact failure being removed.

### 3. Variable *values* are never persisted

Already true of Canvas (`context.tsx`) and it stays true. The definition describes the variables; the values belong to one viewing of the app. A published app opens at its defaults for every viewer rather than at whatever the last person happened to select — a saved app is not a saved session.

This is the same rule as everywhere else in the platform: **a record of what something is must not change when live state does.**

### 4. Events are declarations too, in the same document

`trigger` (which widget, what happened) → ordered `effects`. They live beside the layout rather than inside a widget's props because an event routinely spans widgets: a button that sets a variable a table reads. Nesting that inside the button makes the table's behaviour depend on a node the table cannot see, which is the current design's problem restated.

Ordered and sequential, matching Foundry: effects run in configured order and do not wait for downstream recomputation, and setting a variable copies the value immediately so the next effect sees it. Matching that exactly matters — the alternative gives different results for the same configuration, which is invisible until someone's app misbehaves.

### 5. The document carries a `format` number

`format: 2` from the start. Version 1 is "a bare Craft.js map with no wrapper", which is recognisable without a marker: a v1 document has `ROOT` at the top level, a v2 one has `layout`. A reader that has to guess is a reader that will guess wrong on the first app whose top-level widget somebody named `layout`.

### 6. Conversion is one-shot, done in Python, and keeps the original

Three options were considered.

- **Lazy conversion on open** — convert in the builder when an old app loads. Rejected: apps nobody opens stay v1 forever, so every reader carries both formats indefinitely, and "indefinitely" is how long the second format's bugs live.
- **A Node script running the TypeScript renderer's own converter.** Attractive, because the builder is the only thing that understands Craft.js. Rejected on evidence: this repo has no TypeScript test runner, so the converter would be the one piece of format-critical logic with no automated test.
- **A Python converter, run once, tested with pytest.** Chosen. It fits how everything else here is tested (real Postgres, real assertions), and the conversion is a pure function over JSON — it does not need to know what a widget *renders*, only which props name a parameter.

**`services/canvas.py` still does not interpret definitions.** That property is intact and worth keeping: the request path stores and versions an opaque blob. `services/workshop_format.py` is a format tool, imported by the migration and by its tests, and by nothing that serves a request.

**The original is kept.** Conversion writes a new `canvas_app_versions` row rather than overwriting, so what an app *was* is still readable after the format changed underneath it. Same principle as §4 above, applied to the migration itself.

## What this does not decide

- **The widget-to-variable binding vocabulary per widget** — which props of which widget become which variable slots. That is 1.5's work, widget by widget; the converter here handles the bindings that exist today (`filterParameter`, `searchParameter`).
- **Object-set variables**, the hard and valuable ones (1.2). They need server-side evaluation against the instance store and are a schema question in their own right; this document only reserves the `kind`.
- **Whether `canvas_apps` becomes `workshop_modules`.** A rename belongs with the change that makes the thing different, not with the one that changes its file format (registry kind naming, `db/0032`).

## Proof

`apps/api/tests/test_workshop_format.py` converts real v1 definitions, including the one quoted above, and asserts:

- the layout survives byte-for-byte,
- each parameter-declaring widget produces exactly one variable,
- every string reference is rewritten to that variable's id,
- a reference to a parameter nothing declares is preserved as a **broken binding that the document records**, rather than dropped — the app is already wrong, and a converter that silently tidies it away destroys the evidence,
- converting twice is the same as converting once.
