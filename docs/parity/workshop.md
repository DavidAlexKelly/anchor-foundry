# Workshop — parity specification

**Scope:** core builder and the full widget library. Scenarios, Mobile and AIP widgets are out (see [`README.md`](README.md)).

**Source:** `docs/pal/foundry_workshop.pdf`, 718 pages. Citations are `(p.65)` unless another file is named.

**Today:** 16 content widgets and 5 layout primitives in `apps/web/src/components/canvas/`; server-side variable graph in `apps/api/src/services/workshop_variables.py`; builder at `app/(platform)/[workspace]/[project]/canvas/[appId]/page.tsx`.

The good news, before the long tables: the hard part is done. Typed variables with cycle refusal, ordered event effects, and a layout tree all exist, and the event semantics match Foundry's documented behaviour exactly — "the source variable value is copied to the target variable value immediately… downstream variables that depend on the target variable will not be up-to-date before the next configured event executes" (p.80). What follows is mostly breadth.

---

## 1. Layout

### 1.1 Header

| Feature | Status | Notes |
|---|---|---|
| Toggle header visibility | ✅ | |
| Title, used for browser tab name | ◑ | we set a title; it does not drive the document title (p.47) |
| Custom colour for title text | ○ | |
| Application logo — icon, with colour | ○ | (p.47) |
| Application logo — uploaded image, with height and position | ○ | position is left/center/right horizontal, top/bottom vertical (p.47) |
| Favourite-in-view-mode toggle | ○ | |
| Header background colour | ○ | |
| **Horizontal orientation** | ✅ | §80 |
| Header height (horizontal) | ○ | |
| **Vertical orientation** | ○ | displayed on the left (p.48) |
| Vertical width | ○ | |
| Vertical collapsibility, collapsed-by-default | ○ | (p.48) |
| Collapsed-state image | ○ | requires a header image first (p.49) |
| Collapsed behaviour: Button Group and Tabs show icons only, **all other widgets hidden** | ○ | (p.49) — a rule, not a style; needs a test |

### 1.2 Pages

| Feature | Status | Notes |
|---|---|---|
| Multiple pages, header persists between them | ✅ | |
| Add page from Layout panel | ✅ | |
| Layout template picker with hover preview | ○ | (p.52) |
| Switch page via Layout event | ✅ | |
| Variable-Based Page Selection | ○ | a string variable backs the current page; **note the documented gotcha** — a Switch-to-Page event does *not* update it (p.81) |

### 1.3 Sections — we have three of six layouts

| Layout | Status | Notes |
|---|---|---|
| Columns | ✅ | |
| Rows | ✅ | Foundry's has an **Enable scrolling** option (p.54) — ○ |
| Tabs | ✅ | |
| **Flow** | ○ | vertically scrolling container for widgets that exceed the viewport (p.54) |
| **Toolbar** | ○ | horizontal, "optimized for smaller widgets like Button Groups or Metric Cards" (p.54) |
| **Loop** | ○ | loop over an object set or array, rendering an embedded module per entry (p.54); depends on §4 |

| Section feature | Status | Notes |
|---|---|---|
| Conditional visibility on a variable | ◑ | we support it; Foundry also shows **layout-panel icons and tooltips** marking conditionally-visible sections so they can be found while hidden (p.55) |
| Collapsible sections, with Expand / Collapse / Toggle events | ○ | same gotcha as pages: a Boolean variable backing collapse state is not updated by these events (p.82) |
| Drop zones for drag payloads | ○ | cross-application interactivity (p.55) — see §11 |
| Cut / copy / paste sections and widgets | ○ | (p.55) |

### 1.4 Overlays

| Feature | Status | Notes |
|---|---|---|
| Drawers and modals | ✅ | |
| Open / Close events per overlay | ✅ | Foundry calls these **Layers** events (p.81) |

### 1.5 Style formatting (p.57–62)

Configurable at **page, section and widget level**. This is unglamorous and it is most of the distance between "a canvas" and "looks like Workshop" — it is what a builder reaches for in the first ten minutes, and none of it is hard.

| Feature | Status | Notes |
|---|---|---|
| Section header formatting: Block, Contained, Floating | ○ | (p.58) |
| Background colours: five preset shades **per theme**, Blueprint palette, transparent | ○ | (p.58) |
| Custom hex background, with module-level saved colours reusable on sections and pages | ○ | (p.59) |
| Widgets auto-switch light/dark **by background brightness** | ○ | (p.59–60) — a rule, not a style; needs a test. Pick a contrast threshold and assert a widget on a dark custom background renders its light variant |
| Border styles: Bordered, Outer drop shadow, Inner shadow, Borderless | ○ | (p.60) |
| Padding scale: None, Compact 16px, Regular 24/48, Large 40/62, Custom | ○ | (p.62) |
| Inner section style applied to all child sections | ○ | (p.62) |

The auto-switching rule is the only item here with behaviour worth testing; the rest are tokens and a settings panel. Doing the whole block together is cheaper than doing it piecemeal, because they share one style-resolution path from page → section → widget.

---

## 2. Widget configuration

Foundry's widget panel has **three** tabs (p.65–68). An earlier roadmap draft said Widget setup / Display / Actions; that was wrong, and events are configured on the widget's own controls instead (p.83).

| Tab | Contents | Status |
|---|---|---|
| **Widget setup** | input and output variables, plus widget-specific configuration | ◑ — we have the fields, flat, not organised as a tab with variables first |
| **Metadata** | rename widget; **view and edit raw widget JSON** | ○ |
| **Display** | sizing only: **Auto (max)**, **Absolute** (fixed px), **Flex** (ratio) | ○ |

Renaming matters more than it looks: the widget name "will affect how the current widget is referenced through Workshop, most notably as a component in the Layout panel, and also in default variable names" (p.68).

**The raw JSON editor is the cheapest high-value item in this file.** We already persist `format: 2` documents, so exposing and re-validating one is hours of work, and it makes every configuration we have not built a UI for survivable rather than blocking.

| Other | Status | Notes |
|---|---|---|
| Copy a widget with Cmd+C / Cmd+V into an **Unused widgets** area, re-addable from the widget selector | ○ | (p.68) |
| Widget selector modal with categories | ◑ | we have a palette; not a modal with Foundry's grouping |

---

## 3. Variables

Ours: 8 kinds (`string`, `number`, `boolean`, `date`, `timestamp`, `array`, `single_object`, `object_set`) and 9 transforms (`concat`, `if_else`, `cast`, `is_empty`, `is_not_empty`, `filter_set`, `narrow_set`, `object_property`, plus `object_set_aggregation` served by the store).

### 3.1 Definition types (p.73)

| Definition type | Status |
|---|---|
| Static | ✅ |
| Variable transformation | ✅ |
| Object set definition — object types, filters, link traversals | ◑ — filters and types yes; **link traversal in a set definition** ○ |
| Object set aggregation | ✅ via `/object-sets/aggregate` |
| Object property | ✅ |
| **Function** `[fn]` | ○ |

### 3.2 Variable types we do not have

| Type | Status | Notes |
|---|---|---|
| **Object set filter variables** | ○ | the output of every filtering widget; "captures the current filter state and can be applied to object set variables or reused in widget configurations" (p.444). Supports **default filters** and **filter value extraction**. This is the single most load-bearing missing variable type — most of the filtering widget category depends on it. |
| **Struct variables** | ○ | (p. §22 of TOC) |
| **Time series set variables** | ○ | consumed by Chart XY, Map, Metric Card, Object Table (Time series properties section) |
| Variable-backed layouts | ○ | a variable drives which page/tab/section state is active |

### 3.3 Variables panel (p.72)

| Feature | Status |
|---|---|
| List, add, select-to-configure | ✅ |
| Search by name or unique ID | ○ |
| **Variable lineage graph** | ○ |
| Filter by definition type or by enabled settings | ○ |
| **Partitions** — variables used by the selected widget; variables used on the active page | ○ |
| Duplicate variable | ○ |
| **New variable from current** (object sets) — new variable taking the current set as input | ○ |
| Refuse deletion of a variable in use | ✅ | §1.2a |

### 3.4 External IDs — one mechanism, three features

This is the most valuable structural item in the file.

> "The module interface is the set of variables that are able to be mapped to variables from a parent module when embedded, **and initialized from the URL**. You can think of the module interface as the API for a Workshop module." (p.163)

The mechanism is an **external ID** on a variable plus a module-interface toggle. State saving uses the same key: "variable values are stored within a saved state via their external ID" (p.202–203).

So one concept powers **embedding, URL deep-links, and state saving**. We built deep links separately (§99) and deferred embed mapping (§114) — one feature implemented half of, twice.

| Feature | Status |
|---|---|
| External ID on a variable | ○ |
| Module interface toggle, with display name and description | ○ |
| Interface variables mapped when embedding | ○ (deferred at §114) |
| Interface variables initialised from URL query parameters | ◑ — §99 does this with its own mechanism |
| State saving keyed on external ID | ○ |

**Refusals to build in:** mapping a variable not in the interface; a type mismatch between host and interface variable; a required interface variable left unmapped; renaming an external ID that saved states point at.

**The precedence rule, which is easy to get backwards:** "When an interface variable is mapped between a parent and an embedded child module, Workshop uses the **parent module's** variable definition and ignores the embedded module's own" (p.164).

### 3.5 Evaluation — when a variable actually computes

Two behaviours that are semantics rather than UI, which is why they are easy to skip and expensive to retrofit: both change what a correct implementation of §3 *is*, not what it looks like.

**Lazy loading.** "In both view and edit mode, Workshop variables will compute and recompute lazily only when displayed by a visible widget or layout. This means that variables used in non-visible pages, tabs, overlays, or non-visible pages of a looped layout will not be computed until they are shown. This behavior is the same for non-visible variables used in embedded modules." (p.75)

We evaluate the whole variable graph on load. For a module with a handful of variables that is invisible; for one with an overlay per row of a table it is the difference between usable and not. Note the second-order effect: the Performance Profiler (§9) only counts widgets and variables that affect the on-screen display precisely *because* of this rule, so profiling is meaningless without it.

**Recompute behaviour**, configurable per variable on Function, Object set aggregation, Object property, Variable transformation and Object set filter definitions (p.76):

| Behaviour | Meaning | Status |
|---|---|---|
| **Automatic** | recompute when any dependency changes — the default, and what we do unconditionally | ✅ |
| **Only when triggered by an event** | recompute solely on a `recompute {variable}` event | ○ |
| **On module load, and when triggered by an event** | recompute once at load, then only on the event | ○ |

Object set definitions do not offer the choice and always behave as Automatic; the documented escape hatch is to set the behaviour on an upstream variable or use a function-backed one (p.76).

The `recompute {variable}` event is the other half of this and is missing from §5. Two caveats worth carrying into the implementation: automatic variables "may recompute even when no upstream values have changed", for instance after an action submission or an auto-refresh (p.76) — so nothing may assume recompute means dependency-changed; and a Reset event restores the value configured in the variable *definition*, which under §3.4's precedence rule means the parent's definition, not the child's (p.85, p.128).

---

## 4. Embedded modules

| Feature | Status | Notes |
|---|---|---|
| Embed a module in a module | ✅ | §114 |
| Editor disabled inside an embed | ✅ | §114 |
| **Interface variable mapping** | ○ | explicitly deferred at §114; unblocked by §3.4 |
| Sibling-to-sibling communication through shared interface variables | ○ | (p.164) |
| Embedded module may modify interface variables through events | ○ | (p.164) |
| **Loop layouts** — one embedded module per object in a set | ○ | (p.54) |
| Open Workshop module event, passing values into the target's interface | ○ | (p.165) |
| In edit mode, opening a child from a reference carries the current interface values through, for debugging | ○ | (p.165) — small, and a genuinely thoughtful touch |

---

## 5. Events

Ours: 3 triggers (`click`, `row_select`, `change`) and 5 effects (`set_variable`, `navigate`, `close_overlay`, `open_url`, `run_action`). `export` is deliberately absent because the server refuses it (§76).

| Foundry event family | Status | Notes |
|---|---|---|
| **Layers** — Open / Close each overlay | ✅ | |
| **Layout** — Switch to page | ✅ | |
| **Layout** — Expand / Collapse / Toggle each collapsible section | ○ | needs collapsible sections (§1.3) |
| Set variable value | ✅ | |
| **Recompute {variable}** | ○ | the other half of §3.5 — without it, the two non-automatic recompute behaviours have no way to fire (p.85) |
| **Reset {variable} value** | ○ | static variables only; restores the value in the variable *definition*, which for a mapped interface variable means the parent's (p.85, p.128) |
| Run action | ✅ | |
| Open URL | ✅ | |
| **Switch to {tab}** | ○ | unlike page and section events, this one *does* write back to the variable behind Variable-Based Tab Selection (p.84) — an inconsistency to reproduce deliberately, not to tidy up |
| **Refresh data in module** | ○ | (p.91) |
| **Toggle light / dark mode** | ○ | (p.91) |
| **Export** | ○ | refused with reason at §76; Foundry treats export as a first-class `On click` target alongside actions, events and URLs (p.482) |
| Open Workshop module | ○ | §4 |
| Sequential execution, no waiting for downstream propagation | ✅ | matches p.80 exactly |

**Triggers.** Foundry fires events from "the Button Group, Object Table on row selection, String Dropdown on selection or deselection, and Tabs widgets" and more (p.80) — note *selection and deselection* as distinct triggers, which we do not distinguish.

---

## 6. Publishing, versioning, and change review

| Feature | Status | Notes |
|---|---|---|
| Saving does not move viewers; publishing does | ✅ | §88 |
| **Versions dialog** listing timestamp, editor, description | ○ | (p.191) |
| Publish this version | ◑ | possible, no dialog |
| View this version, **with a warning banner when non-published** | ○ | (p.191) |
| Revert to this version, with auto-generated description | ○ | (p.192) |
| Setting: **Automatically publish when saving** | ○ | (p.192) |
| Setting: **Always prompt for a version description** | ○ | (p.192) |
| **Changelog panel** — range or single-version diff | ○ | highlights "additions, deletions, changes, moves, and newly unused elements", with JSON diffs and a visual hierarchy (p.193) |
| `/dev/` vs `/latest/` in the URL — last saved vs last published | ○ | (p.166); one route, and save-versus-publish becomes checkable by a human |
| Module branching and rebasing, with conflict resolution in the Changelog panel | ○ | (p.193) — out of scope for now, but the Changelog panel is its prerequisite |

---

## 7. Routing and state saving

| Feature | Status | Notes |
|---|---|---|
| Enable routing toggle, in Pages settings | ○ | (p.195) |
| Module state written to the URL for sharing | ◑ | §99, by a different mechanism |
| Current **page ID** written to the URL; no ID means the default page on load | ○ | (p.197) |
| Per-variable URL behaviour: **In URL when used by visible widget or layout** | ○ | (p.198) — only when non-default *and* on screen |
| Per-variable URL behaviour: **Always in URL** (when non-default) | ○ | (p.198) |
| Per-variable URL behaviour: **Never in URL** | ○ | (p.198) |
| A query parameter matching an external ID seeds the variable **regardless** of the behaviour above | ○ | (p.198) — inbound and outbound are separate rules |
| Refuse routing on object set **filter** variables | ○ | (p.199) — documented limitation, so refuse rather than half-work |
| Object set variables in the URL limited to a single object by RID | ○ | (p.199) |
| Embedding does **not** inherit the child's routing config; pass through the interface instead | ○ | (p.199) — same precedence family as §3.4 |
| **State saving** — save, open, and share a named state | ○ | (p.200) |
| State saving preserves enabled variables **and optionally the current page** | ○ | (p.200) |
| Per-variable state-saving enablement via external ID | ○ | §3.4 |
| Configure allowed save locations and shortcuts | ○ | (p.202) |

---

## 8. Permissions

| Feature | Status | Notes |
|---|---|---|
| Viewer role to open, Editor role to edit | ✅ | (p. Permissions section) |
| Data, actions and functions permissioned **separately** from the module | ✅ | our RLS does this |
| **Check access panel** — inspect a named user's access to the module | ○ | genuinely useful; a support tool as much as a builder one |

---

## 9. Display and performance

| Feature | Status | Notes |
|---|---|---|
| **Value formatting** — fraction digits, min/max decimals, local to the module not the ontology | ○ | (Formatting section) |
| **Conditional formatting** | ◑ | ontology-level only, §83; Workshop-level ○ |
| **Derived properties** — runtime calculations per object type, defined at module level, including linked aggregations | ○ | (Derived properties section) |
| **Auto-refresh** — register object sets to watch; module refreshes when data changes anywhere in the platform | ○ | (Auto-refresh section); we have §refresh plumbing but not registration |
| **Performance Profiler** — reload in profiler mode, record network requests from initialisation | ○ | |
| **Widget display optimization** — control when widgets mount and unmount as users navigate | ○ | default is mount-on-visible, unmount-on-leave |
| **Usage metrics** — action submission counts and layout view counts, aggregate only, not per-user | ○ | |
| Translations — l10n/i18n of supported string types, served by browser locale | ○ | |
| Used colors | ○ | |
| Kiosk mode | ○ | read-only long-lived sessions; needs Control Panel allowlisting |
| Redact mode | ○ | visual obfuscation for screenshots — **explicitly not a security feature**; if built, carry that warning across |

---

## 10. The widget library

Foundry's inventory, compiled from the category Overview pages and the per-widget page headers. Some widgets appear in one and not the other; the union is the target.

Ours in the right-hand column. **We have 13 of ~52.**

### Filtering (p.444) — 13

| Foundry | Ours |
|---|---|
| Filter List — histograms, distribution charts, keyword search, single/multi-select, default criteria, user-addable filters | ◑ `CanvasFilterList` — no histograms or distribution charts |
| Object Dropdown — select one object | ○ |
| Object Selector — select many objects | ○ |
| **String Selector** | ◑ via generic `CanvasParameterControl` |
| **Checkbox** | ◑ via `CanvasParameterControl` |
| Date and Time Picker | ○ |
| **Date Input** — single date or range | ◑ via `CanvasParameterControl` |
| **Text Input** | ◑ via `CanvasParameterControl` |
| **Numeric Input** | ◑ via `CanvasParameterControl` |
| Exploration Filter Pills | ○ |
| Exploration Search Bar | ◑ `CanvasSearch` |
| Prominent Terms | ○ |
| User Select | ○ |

Our generic parameter control is a defensible design, but it is *our* design, and the ask was that Workshop feel like Workshop. **Decision needed:** split it into the four named widgets, or keep it and accept the divergence. This spec assumes splitting.

### Core display (p.220) — 7

| Foundry | Ours |
|---|---|
| Object Table | ◑ `CanvasObjectTable` — see below |
| Object List (cards) | ✅ `CanvasObjectCards` |
| **Object View** — renders Object Explorer's object view for one object | ○ — depends on `ontology.md` §Object Views |
| Property List | ○ |
| Links — link types and linked objects in expandable sections | ○ |
| Object Set Title | ○ |
| Header text — two rows optimised for a header | ○ |

**Object Table** is the most-configured widget in Foundry and our gap is wide (p.221–223): multiple object types in one table; time-series columns; **derived columns generated on-the-fly via a Function** `[fn]`; multi-column sort; column size and row height; conditional and numeric formatting from the ontology; single- and multi-select; **inline editing for cell-level writeback**; events on row selection ✅; custom row actions in the right-click menu; and a `hubble:icon` type class that renders an image property in place of the object-type icon.

### Visualization (p.276) — ~25

| Foundry | Ours |
|---|---|
| Chart XY — bar, line, scatter; multi-series; aggregation; segmentation; **function-backed layers** `[fn]`; axes, legends, numeric formatting; selection and downstream filtering | ◑ `CanvasChart` |
| Metric Card | ◑ `CanvasMetricCard` — Foundry's has an **Interactive metric** setting that fires commands/actions/events (p.480) |
| Pivot Table | ✅ `CanvasPivotTable` |
| Map | ◑ `CanvasMap` |
| Time Series Analysis | ◑ `CanvasTimeSeries` |
| Markdown — formatted text with object references | ◑ `CanvasText` |
| Pie Chart | ○ |
| Vega Chart — full Vega / Vega-Lite grammar | ○ |
| Waterfall Chart | ○ |
| Gantt Chart | ○ |
| Timeline | ○ |
| Status Tracker | ○ |
| Stepper — linear and non-linear | ○ |
| Free-form Analysis | ○ |
| Image Annotation | ○ |
| Media Preview — URL, RID, or base64; PNG/JPEG/PDF | ○ |
| PDF Viewer, with keyword search | ○ |
| Audio and Video Display | ○ |
| Video Display | ○ |
| Spreadsheet Display | ○ |
| Resource List | ○ |
| Linked Compass Resources | ○ |
| Data Freshness | ○ |
| Edit History | ○ |
| Action Log Timeline | ○ |

### Event-trigger and navigational (p.480) — 6

| Foundry | Ours |
|---|---|
| Button Group — inline, menu, and two-part buttons; on-click to action, events, URL or export; colour, icon, size, fill; conditional disabled and conditional visibility | ◑ `CanvasButton` |
| Tabs | ✅ `CanvasTabs` |
| **Inline Action** — inline action form or table on an ontology action type | ◑ `CanvasActionForm` |
| Comments | ○ |
| Media Uploader | ○ |
| Audio | ○ |

### Other

| Foundry | Ours |
|---|---|
| Embedded modules | ✅ `CanvasEmbeddedModule` |
| Observability Chart | ○ |
| — | `CanvasDatasetTable` — ours, no Foundry equivalent. Keep; a dataset-backed table is useful and Foundry's absence of one is a consequence of everything going through the ontology. |

### Build order for the library

1. **Text, Date, Numeric Input, String Selector, Checkbox** — split out of the parameter control; makes a filter bar feel complete
2. **Object set filter variables** (§3.2) — unblocks the rest of the filtering category
3. **Markdown** — trivially cheap, disproportionately useful
4. **Object Table depth** — sorting, sizing, formatting, inline edit, row actions
5. **Object View widget, Property List, Links, Object Set Title** — depend on ontology work
6. **Inline Action depth**, Object Dropdown, Object Selector
7. **Timeline, Stepper, Status Tracker, Pie, Waterfall** — the visual long tail
8. **Media Preview, PDF Viewer, Video, Image Annotation** — the media group; one storage decision serves all four
9. Everything else, on demand

---

## 11. Cross-application interactivity

| Feature | Status |
|---|---|
| Drag and drop between Workshop and other applications | ○ |
| App Pairing widget | ○ |
| Commands | ○ |
| Iframe embed of other platform applications | ○ |

Low priority — these are worth having only once there are several applications to interact *with*.

---

## 12. Acceptance tests

A widget is not done because it renders. Per the repo standard, each of these must be made to fail by removing the thing it tests.

- **Config tabs** — a widget's input variable is settable from Widget setup and the render changes without a save; the Metadata tab's raw JSON round-trips through save and reload; a Display sizing change alters computed height.
- **Section layouts** — a Flow section scrolls when its content exceeds it; a Toolbar section lays out horizontally; a Loop section over a 3-object set renders 3 embedded modules.
- **Vertical header collapse** — collapsed, a Tabs widget shows icons only and a Metric Card in the header is **not rendered**. Mutation: render it anyway, and the test goes red.
- **External IDs** — *one* test, three assertions: a host sets an embedded module's interface variable and the embedded row count changes; the same variable initialises from a URL query parameter; the same variable survives save-and-reload of a named state. **If any of the three needs its own mechanism, the design is wrong.**
- **Interface precedence** — a host and child both define the mapped variable with different defaults; the host's wins.
- **Interface refusals** — four saves, four refusals, each naming its reason.
- **Versions** — publishing version N while N+1 is saved leaves viewers on N; `/dev/` shows N+1; the non-published banner appears on N+1 and not on N.
- **Changelog** — moving a widget between sections produces a *move*, not a delete plus an add.
- **Object set filter variables** — a Filter List's output applied to a second object set narrows it; a default filter applies on load.
- **Object Table** — every documented configuration option has a test that drives it; inline edit writes back and an unpermitted edit is refused.
- **Auto-refresh** — an out-of-band ontology edit updates a rendered table without user interaction.
