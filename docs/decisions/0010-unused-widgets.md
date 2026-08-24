# 0010 — Where a parked widget lives

**Status:** accepted, built in `STATUS.md` §197.
**Context:** `docs/parity/workshop.md` §1.3's last `○` — p.68's *Unused widgets* area, named
there as "a place in the document for nodes outside the layout tree, which is a format change
rather than a control".

> "After configuring a widget, you can copy it to reuse anywhere in the module… Use `Cmd+V`
> to paste the widget into the **Unused widgets area located at the bottom of the Layouts
> section in the left side panel**. Add the widget to your module by choosing **+ Add
> widget**, then find it in the Unused widgets tab of the widget selector modal." (p.68)

A widget that is *in the module* but *not on any page*. Every other node in this document is
reachable from `ROOT` by walking children, and the viewer renders exactly that walk — so
"in the module but not in the tree" is a state the format has never had to express.

---

## The two candidate homes

### A — a sibling key on the module document

```json
{ "format": 2, "layout": {…}, "unused": {…}, "variables": {…}, "events": {…} }
```

Parked subtrees live outside `layout` entirely. Appealing because it makes the invariant
loud: `layout` stays exactly "what gets rendered", and nothing in the render path needs to
learn about a node it must skip.

### B — a holding node inside the node map

A `CanvasUnused` node under `ROOT`, `isCanvas`, rendering nothing. Parked widgets are its
children. The node map keeps them; the render path skips them because the component draws
nothing; the Layout panel reads its children and lists them separately.

---

## Why B

**Because of one function.** `workshop_variables.usages()` decides whether a variable may be
deleted, and it works by iterating the node map:

```python
for node_id, node in layout.items():
```

Not by walking the tree. So a parked widget that lives *in the map* is counted as a usage
for free, and a parked widget that lives in a sibling key is not.

That difference is not cosmetic, and it is the whole decision. Under A, this sequence
silently breaks a module:

1. park a Filter List bound to `v_region`;
2. the Variables panel now reports `v_region` as **unused**, because the scan cannot see the
   parked widget;
3. an author tidies up and deletes it — and the server allows it, for the same reason;
4. the widget is added back later, bound to a variable that is gone.

Nothing reports an error at any step. This repo has now been caught three times by the same
shape — a list that had to be complete with nothing checking it against the thing it
described (§190's parity row, §191's `REFERENCE_PROPS`, §193's effect catalogue) — and A
creates a fourth instance deliberately, in the one place where the cost is a variable being
deleted out from under something that needed it.

A *could* be made correct by scanning both keys. That is exactly the fix that keeps not
getting made: two scans that must agree, where the second one is easy to forget in every
future feature that touches usages. B removes the possibility instead of guarding against it.

**Three smaller things also fall out of B**, none of which would have decided it alone:

- Craft's `getSerializedNodes` / `deserialize` round trip carries parked widgets with no
  special handling, because they are ordinary nodes with an ordinary parent.
- The existing paste machinery (§192's `clipboard.ts`) already moves subtrees between
  parents. Placing a parked widget is `paste` with a different target, not a new transform.
- Nothing that walks `ROOT`'s children for *pages* can mistake the holding node for one:
  `defaultPageNode` and `pageNodeFor` both filter on `resolvedName === "CanvasPage"`.

## What B costs, stated plainly

**The render path now contains a node that must draw nothing**, and "draws nothing" is a
property no test would notice the loss of unless one is written for it. A `CanvasUnused` that
started rendering its children would put parked widgets on the page for every reader, which
is the failure this decision is most likely to produce later. The guard is a browser test
that opens a module with a parked widget as a *reader* and asserts it is not on the page —
named here so the next person to touch that component knows why it exists.

**A second cost, smaller:** `usages()` now counts a parked widget, which means the Variables
panel says a variable is "used 1×" when nothing on screen uses it. That is the correct
answer to "may I delete this" and a confusing answer to "where is this". The Variables panel
therefore names the holding area when it lists that usage, rather than reporting a node id
the author cannot find on any page.

## What this does not decide

p.68's **widget selector modal** with its "Unused widgets tab" is a second surface for the
same list. The area at the bottom of the Layout panel is the one p.68 describes as the paste
target, and it is enough to make parked widgets reachable; the modal is a convenience on top
and is not built. Said here so that its absence reads as a decision rather than an oversight.
