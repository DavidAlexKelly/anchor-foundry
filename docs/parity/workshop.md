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
| Title, used for browser tab name | ✅ | §126 — the header title is the tab, falling back to the resource name (p.47) |
| Custom colour for title text | ○ | belongs with §1.5's style block, not here |
| Application logo — icon, with colour | ○ | (p.47); needs an icon library — see the divergence below |
| Application logo — uploaded image, with height and position | ○ | (p.47); needs an image-upload decision, which attachments (§39) already has a shape for |
| Favourite-in-view-mode toggle | ○ | there is no favourites feature to toggle into |
| Header background colour | ○ | §1.5 |
| **Horizontal orientation** | ✅ | §80 |
| Header height (horizontal) | ✅ | |
| **Vertical orientation** | ✅ | displayed on the left (p.48) |
| Vertical width | ✅ | |
| Vertical collapsibility, collapsed-by-default | ✅ | (p.48) |
| Collapsed-state image | ○ | requires a header image first (p.49) |
| Collapsed behaviour: Button Group and Tabs show icons only, **all other widgets hidden** | ✅ | (p.49) — the rule, and the reason `e2e/test_vertical_header.py` exists |

**The collapse rule is the only part of a header that is behaviour rather than styling**, and it is implemented as one: the header reads its children's node types and renders only `CanvasButton` and `CanvasTabs` when collapsed. The mutation that renders everything anyway turns the test red.

**Divergence: there is no icon library.** Foundry offers an icon picker; a Button and a Page take a one-or-two-character `icon` instead — an emoji, an initial — and an unset one falls back to the label's first letter. The *behaviour* p.49 describes (drop the text, show a glyph) is faithful; the picker is not built. The label survives as the `aria-label` and `title`, so a collapsed header stays navigable by anything that is not eyes.

**The container becomes a row, decided in code rather than by `:has()`.** A vertical header needs its *parent* to lay out as a row, and a child cannot set that — so `CanvasContainer` reads its own children for a vertical header. A CSS `:has()` selector would have been shorter and is exactly the silent-failure shape this repo has already been caught by twice: an unsupported selector is nothing at all, and the symptom would be a header above the page rather than beside it.

### 1.2 Pages

| Feature | Status | Notes |
|---|---|---|
| Multiple pages, header persists between them | ✅ | |
| Add page from Layout panel | ✅ | |
| Layout template picker with hover preview | ✅ §195 | (p.52–53) — the strip sits at the bottom of a page in the builder and nowhere else; hovering an icon previews that layout; clicking applies it. **The preview is drawn from the template rather than shipped as a picture**, so it cannot disagree with what the button does. **Divergence: the icons are not Foundry's** — p.52 shows glyphs we cannot reproduce and does not name the templates behind them, so the six here are ours, chosen to span what a `CanvasSection` can actually express (a count of sections, each one's direction and weights). **The design question p.53 leaves open is what happens to widgets already on the page**: "the page layout will update" is a sentence about layout, and the picker is documented on a page created moments earlier, so the intended use is a starting point — but the control is always on screen. Applying a template therefore **never loses a widget**: sections are replaced, their contents carried into the new ones positionally, and anything past the new count lands in the last section rather than nowhere. p.52's "two vertically divided sections" default is read as two sections stacked, which is the arrangement a page expresses directly; the other reading ("a vertical divider", side by side) is defensible and is written down in `layout-template.ts` because the screenshot that would settle it is an image |
| Switch page via Layout event | ✅ | |
| Variable-Based Page Selection | ✅ §189 | (p.81) — a string variable holding a **page ID** backs the showing page, and **the gotcha is implemented rather than merely noted**: a Switch-to-Page event moves the reader without writing the variable, and the Layout panel says so beside the picker. The resolution rule is §185's, one row up and for the same reason (`components/canvas/page-selection.ts` is `collapse.ts` with a page id where the boolean was): *the most recent instruction wins* — an event overrides the variable and stays in force until the variable's own value changes. Two things have no analogue in the boolean case. **The value is the author-set page ID, not the layout node**, for p.197's reason: a Craft.js node id is generated, means nothing to whoever types the value, and changes when a page is recreated — so the link and the variable name the same page in the same words, and an event can still reach a page nobody has named. And **a string can name a page that is not there**, which a boolean cannot; p.197 already answers that for the URL ("returned to the module's default page") and the same answer is right here, because the alternative to falling back is a blank module with no way out. The server refuses a `page_selection` naming a variable that is absent or is not a string, and deliberately does **not** check the *value* against the pages: a kind can never work if it is wrong, while a value that matches nothing today might match tomorrow, and refusing it would make a valid module stop saving because somebody renamed a page. **Where the two settings on this panel interact**: with routing on as well, a deep link's page ID is the older instruction — the backing variable takes the page as soon as it resolves. That follows from *backing* meaning what it says, and it is only reachable by an author who opted into both |

### 1.3 Sections — all six layouts

| Layout | Status | Notes |
|---|---|---|
| Columns | ✅ | |
| Rows | ✅ | **Enable scrolling** (p.54) ✅ |
| Tabs | ✅ §190 | (p.54) — "adds tabs to the top of a section", one child per tab, a tab holding several widgets being a child that is itself a section (p.54's own "a layout, which itself may contain one or more sections"). **This row was ✅ on a substitution and is now ✅ on the thing**: it used to mean the Tabs *widget*, which switches pages, and `CanvasSection`'s comment called that "the same idea one level up". It is not — a module has exactly one set of pages, so two independent tab groups side by side could not be expressed at all, and p.84's Variable-Based Tab Selection had nothing to attach to. Tab names are a comma-separated list in the same idiom as `weights`; unnamed ones become "Tab 3" rather than the child widget's name (a tab bar reading "Section" over a section says nothing), and duplicates are numbered because a tab name is the address p.84's event and the backing variable both use |
| **Flow** | ✅ | vertically scrolling container for widgets that exceed the viewport (p.54) |
| **Toolbar** | ✅ | horizontal, "optimized for smaller widgets like Button Groups or Metric Cards" (p.54); its widgets keep their own width rather than sharing the row, which is what separates it from Columns |
| **Loop** | ◑ | over an **object set** ✅ (p.129–136); over an **array** ○ — see below |

**Loop layouts** were unblocked by §3.4 rather than built alongside it: p.135 says loop variable mapping "works the same way as the embedded module interface configuration". Done: the set to loop, the module to repeat, the child interface variable that receives each object, the other interface variables (shared across copies, per p.135), Limit and Paged paging (p.134), List and Grid display with max columns and min card width (p.134). Each copy gets its own variable scope and layout state, per p.129 — the assertion the feature rests on, since one shared scope renders the right number of cards all showing the same object.

| Loop feature | Status | Notes |
|---|---|---|
| Loop an object set | ✅ | |
| Loop an **array** | ○ | p.132–133. Our `array` kind has no element type, so "a variable typed to the array type" (p.134) cannot be expressed or checked. Needs a typed-array kind first; refused rather than half-built |
| Sort by property | ○ | decision 0006 — properties are stored untyped, so an ordered comparison means one thing on Postgres and another on OpenSearch. The set's own order is stable, which p.132 says Foundry also guarantees via a primary-key sort behind user sorts |
| Interface variable warning | ✅ | p.135's "unexpected behavior may occur" is carried into the settings panel rather than left to be discovered |

**One divergence worth naming.** p.134 says the child "must have a module interface object set variable" for an object-set loop, while p.135 describes mapping "objects from the object set". We use our `single_object` kind, which is the one that actually describes a single object, and the server refuses anything else. If Foundry genuinely hands over a one-object *set*, this is a difference in the type, not in the behaviour.

| Section feature | Status | Notes |
|---|---|---|
| Conditional visibility on a variable | ✅ §196 | (p.55) — the condition itself, and the **layout-panel icons and tooltips** that mark it. **p.55's second half is the requirement, not the decoration**: the indicator exists so a section can be found "even when they are currently hidden in the module view", so it is driven by the *document* — does this node carry a condition — and never by what the variable currently resolves to. An indicator that went out when the condition was false would vanish in exactly the case the sentence is about. The canvas's own "hidden unless <label>" marker *is* value-driven, deliberately: the two answer different questions, one "what is happening now" and the other "what is configured", and `e2e/test_condition_indicators.py` asserts they disagree in that direction. **Two conditions, not one**: p.55 names visibility, and p.82's collapse backing is the same question about a different bit of state, so a row carrying both says both. The tooltip **names the variable** — "conditionally visible" alone meets the letter of "easier to identify and manage" and none of its purpose, since the label is the only part an author can act on. The catalogue is checked against `REFERENCE_PROPS` rather than against a copy of itself (§191's rule): a condition prop that was not a reference prop would be one nothing counts as a usage, so the variable it names could be deleted and the marker would point at nothing |
| Collapsible sections, with Expand / Collapse / Toggle events | ✅ §185 | (p.55, p.82) — the three events, a header the section draws for itself, a `collapsedByDefault`, and p.82's "Boolean variable backing the collapse state". **The gotcha is implemented rather than merely noted**: none of the three writes that variable, and the settings panel says so beside the picker rather than leaving somebody to meet it as a bug. The server refuses an effect aimed at a section that is not collapsible — p.82 offers them "for each collapsible section", and a section that cannot collapse has no state for them to change, so saving one would save a button that does nothing. **The rule p.82 does not state**: a section can be told two things at once, and the reading here is that the most recent instruction wins — an event overrides the variable and stays in force until the variable's own value *changes*. The two simpler rules each break one of p.82's own sentences: "the variable always wins" makes Expand and Collapse do nothing on exactly the sections the page says they are for, and "the event always wins" makes the word *backing* false after the first click |
| Drop zones for drag payloads | ○ | cross-application interactivity (p.55) — see §11 |
| Cut / copy / paste sections and widgets | ✅ §192 | (p.55, p.68-69) — with **both paste modes**, which are the whole of the feature: "Paste with same input variable" reuses the copied thing's variables, "Paste with duplicate input variables" mints new ones matching them. Two buttons rather than a paste plus a setting, because an author about to paste already knows which they mean. The transform is one pure module over the serialised layout (`components/canvas/clipboard.ts`), handed back to Craft's `deserialize` — one code path for cut and paste alike, and testable without a browser, which matters because "the paste rewrote one reference too few" is invisible until somebody edits the copy and watches the original move. **What travels**: the subtree through both `nodes` and `linkedNodes` (a Page's children hang off the latter, so a walk that missed them would paste an empty page); every variable the subtree references; and every event *triggered from inside* it, with node ids remapped where the target came along and left alone where it did not — p.55 does not mention events, but a copied Button that has lost its on-click is a copy that silently does less than the thing it copied. **What does not**: a duplicated variable's derivation *inputs*. p.55's "input variables" are the widget's own, not the graph behind them, and duplicating the graph would clone the object set a filter narrows — the one thing an author duplicating a filter wants to keep shared. A duplicate also **drops the external ID** rather than copying it: it is what a URL and an embedding module address, and the server refuses two variables that share one, so carrying it would make the paste unsaveable. **Not built**: p.68's *Unused widgets* area, the holding pen a Cmd+V lands in when there is nowhere to put a widget yet. That is a place in the document for nodes outside the layout tree, which is a format change rather than a control, and is named here rather than half-built |

### 1.4 Overlays

| Feature | Status | Notes |
|---|---|---|
| Drawers and modals | ✅ | |
| Open / Close events per overlay | ✅ | Foundry calls these **Layers** events (p.81) |

### 1.5 Style formatting (p.57–62)

Configurable at **page, section and widget level**. This is unglamorous and it is most of the distance between "a canvas" and "looks like Workshop" — it is what a builder reaches for in the first ten minutes, and none of it is hard.

| Feature | Status | Notes |
|---|---|---|
| Section header formatting: Block, Contained, Floating | ○ | (p.58) — blocked on a feature we do not have: p.58 says these "can be added when the header is enabled on a section", and sections here have no header. That is its own row, not part of the style block |
| Background colours: five preset shades, Blueprint palette, transparent | ◑ §184 | (p.58) — five presets and transparent, offered at all three levels. **Not "per theme"**: p.58 offers a ladder for light *and* dark mode and this platform has one theme, so a dark ladder would be five swatches that look wrong on every page they appear on. Adding a dark theme is a platform-wide decision, not Workshop's. No Blueprint palette either — Blueprint is Palantir's own design system and is not a dependency here; a custom hex reaches the same colours |
| Custom hex background | ✅ §184 | (p.59) — on pages, sections and widgets. `#abc`, `abc` and `#aabbcc` all mean the same colour, because this value is typed by hand and a picker that ignored `abc` would look broken rather than strict. **Module-level saved colours are not built** — that is a module-scoped palette, which is a store rather than a control |
| Widgets auto-switch light/dark **by background brightness** | ✅ §184 | (p.59–60) — the one item here that is a rule. WCAG relative luminance, and the threshold is WCAG's own crossover (`√(1.05×0.05) − 0.05` ≈ 0.179) rather than a round half, which would put white text on a mid-grey that black text reads better on. Applied as **one `data-scheme` attribute** that redefines the ink and line tokens beneath it, so a widget written years before this feature inherits legible colours without knowing it exists — colouring widgets individually would mean touching every one, and the one missed would be invisible until somebody picked a dark background |
| Border styles: Bordered, Outer drop shadow, Inner shadow, Borderless | ✅ §184 | (p.60) — on sections and widgets, which is where p.60 says and nowhere else |
| Padding scale: None, Compact 16px, Regular 24/48, Large 40/62, Custom | ✅ §184 | (p.62) — on pages and sections, p.62's own levels. Regular and Large are **not square**, which is the detail a single-number-per-option shape quietly loses |
| Inner section style applied to all child sections | ○ | (p.62) — inheritance rather than a value, and p.62's list of the "pre-defined section styles" it offers does not survive extraction from the PDF, so there is nothing to be faithful to yet |

**§184 built the block as one pure module.** The values are p.62's own numbers and p.60's own four, which is exactly why they are tested rather than typed into three panels: a control using 20px where the page says 24 looks plausible and nothing else in the system objects. The per-level asymmetry is p.57–62's own — backgrounds everywhere (p.58), borders on "sections and widgets" (p.60), padding on "pages and sections" (p.62) — and offering all four at every level would have been less code and would have put a padding control on a widget with nothing to pad.

---

## 2. Widget configuration

Foundry's widget panel has **three** tabs (p.65–68). An earlier roadmap draft said Widget setup / Display / Actions; that was wrong, and events are configured on the widget's own controls instead (p.83).

| Tab | Contents | Status |
|---|---|---|
| **Widget setup** | input and output variables, plus widget-specific configuration | ✅ §178-§182 — the panel is **variables-first**: p.65's order (Inputs → Configuration → Outputs) as three labelled sections, and p.66's progressive disclosure, which is the only *behaviour* in the row — "revealed in more detail once the Object Set is populated", so configuration nothing can answer yet is replaced by a line naming the input it is waiting on. A widget with nothing to output draws no Outputs heading, since an empty one promises a control that does not exist. **Converted: Filter List (p.65-67's own worked example), Search, Time Series** (§178), then **Object table, Card list, Pivot table, Metric card** (§179), then **Parameter control, Dataset table, Action form** (§180), then **Embedded module, Loop, Button** (§181), then **Map and Chart** (§182) — **all fifteen**. The wrapper is per-panel opt-in and the conversion was deliberately spread over five units rather than done as one ~4,700-line refactor nobody could review. **The denominator was wrong until §181**: "eighteen" counted every settings panel, and six of them — Container, Text, Section, Header, Page and **Overlay** — have no variable-bound control at all, so there is nothing for p.65's three sections to separate and a lone "Configuration" heading over the only content would divide nothing. §181's three each earn the wrapper differently: the **Embedded module** is the widget whose disclosure p.127 states in its own words ("Once a child module is selected, the module interface for the child module will be shown in the widget configuration panel"), replacing a mapping that used to vanish by rendering `null`; the **Loop** is the first widget that needs `requires` in its original **all-of** form — a set to loop through *and* a module to repeat, where §179's choice would say "or" and tell somebody they were finished when they were half finished; the **Button** is p.65's "as well as any additional configuration and display options" read literally, with the variable that decides whether it is pressable as the input and label, icon and style as the display options. §182's two were the restructure the earlier units deferred: the **Map**'s `requires` is the first that is not a literal — it is computed from the `Points from` toggle, because a map pointed at a dataset must not sit waiting for an object type nobody is going to pick — and the **Chart** is where p.280's three "Data input" options land as one choice with a third arm. Reading them in order to restructure them turned up **four disabled controls that could never be enabled**: the Map's `Label property` and `Filter property` guarded on `objectTypeId`, which a map bound to an object set variable never has, while `Location property` beside them guarded correctly; and the Chart's `Category`, `Of column` and `Filter column` guarded on the dataset while being populated from the set's properties. All of them rendered greyed out with their options already loaded. §180's three are the widgets that are *not* populated by an object set, and each bends the shape a different way: the **Parameter control** has no input at all — it produces the value everything else reads, so the panel opens on Outputs and its configuration waits for nothing (a rule that made configuration wait for an input would leave it permanently unconfigurable); the **Dataset table** is p.66's disclosure with a dataset in the object set's place; the **Action form** has two dropdowns that look alike and are not — the action type is the input, while what the form edits is configuration, because leaving *that* unset is a real answer ("whatever the viewer picks") rather than an unfinished one. §179 also found the rule §178's three widgets did not need: an Object table is populated *either* by a bound object set *or* by an object type picked directly, so `requires` takes a **choice** as well as a requirement — waiting for both would wait for something nobody is meant to supply, and the configuration would never appear. The Pivot table is the widget that shows why there are three sections rather than two: its drill-down variable is p.65's "data that is then produced and output by the widget". The Metric card is the one where the order does real work — its label describes a number the widget cannot produce until a set is chosen, so asking for the label first asks somebody to name a thing they have not picked |
| **Metadata** | rename widget; **view and edit raw widget JSON** | ✅ |
| **Display** | sizing only: **Auto (max)**, **Absolute** (fixed px), **Flex** (ratio) | ✅ for height; **width is not per-widget here** — see below |

Renaming matters more than it looks: the widget name "will affect how the current widget is referenced through Workshop, most notably as a component in the Layout panel, and also in default variable names" (p.68). The Layout panel half is done. The second half does not apply to us — we do not generate variable names from widget names — and that is a divergence rather than a gap.

**The raw JSON editor was the cheapest high-value item in this file**, and it is done. It **replaces** rather than merges, so removing a prop in the editor removes it from the widget; every other assertion about it passes just as happily against a merging implementation, which is why there is a test that only deletion can satisfy.

**Sizing is height, deliberately.** Foundry's own description is height-first and says why: Auto (max) "is not available for setting the width of widgets in a column layout" (p.68). Per-widget *width* here is already solved by a different mechanism — a section distributes width to its children by weight, draggable between them (`§section-resize`). A second per-widget width control would put two numbers in charge of one dimension with no rule for which wins, so it is not built.

Applied through one `<Editor onRender>` wrapper rather than in each of the twenty-odd widgets, and the wrapper **returns the node untouched when no sizing is set** — so a module that configures none renders exactly as it did before, with no extra element in any flex chain.

| Other | Status | Notes |
|---|---|---|
| Copy a widget with Cmd+C / Cmd+V into an **Unused widgets** area, re-addable from the widget selector | ○ | (p.68) |
| Widget selector modal with categories | ◑ | we have a palette; not a modal with Foundry's grouping |

---

## 3. Variables

Ours: 9 kinds (`string`, `number`, `boolean`, `date`, `timestamp`, `array`, `single_object`, `object_set`, `time_series_set`; the first five are the ones routing can carry, §152) and 12 transforms (`concat`, `if_else`, `cast`, `is_empty`, `is_not_empty`, `filter_set`, `narrow_set`, `traverse_set`, `object_property`, `filter_value`, `object_series`, plus `object_set_aggregation` served by the store).

### 3.1 Definition types (p.73)

| Definition type | Status |
|---|---|
| Static | ✅ |
| Variable transformation | ✅ |
| Object set definition — object types, filters, link traversals | ✅ — server (§155: `via` follows a link in either direction) and builder (§156: a traversal is the `traverse_set` transform, drawn by picking a base set and one end of a link) |
| Object set aggregation | ✅ via `/object-sets/aggregate` |
| Object property | ✅ |
| **Function** `[fn]` | ○ |

### 3.2 Variable types we do not have

| Type | Status | Notes |
|---|---|---|
| **Object set filter variables** | ◑ | the output of every filtering widget; "captures the current filter state and can be applied to object set variables or reused in widget configurations" (p.444). Both halves of p.444 now work: **applied to object set variables** is `narrow_set`, and **reused in widget configurations** is `filter_value`, a transform that reads one property's chosen value back out of a filter's clauses (a property nobody filtered on is `None`, not an error; a multi-select is returned whole). **Default filters** need nothing new — an `array` variable's `default` is filter state that is applied on load, and `test_a_filter_can_start_with_a_default_applied` holds that. What is still missing is a dedicated `object_set_filter` variable *kind*: filter state travels as an `array` of clauses rather than as its own type, so the panel cannot tell a filter apart from any other list, and a widget cannot ask for "a filter" specifically. |
| **Struct variables** | ○ | (p. §22 of TOC) |
| **Time series set variables** | ◑ | "Stores a time series property of a single object, optionally allowing the application of time series transforms to it" (p.76). Built: the `time_series_set` kind, always derived by an `object_series` transform naming a `single_object` variable and a `time_series` property, with the bucket and summariser on the *variable* rather than on each widget — so two widgets reading one series agree about what a point means. It resolves to a **reference**, never to points (decision 0009), the same way an `object_set` variable holds a definition rather than rows. Consumed by **Chart XY** (p.280's third Data input, forced to a line per p.281). The other three consumers p.582 names — Map, Metric Card, Object Table — are ○, and so are the p.583–584 **time series transforms** (cumulative/periodic/rolling aggregates), which are a computation over points rather than a variable |
| Variable-backed layouts | ✅ | a variable drives which page/tab/section state is active. **All three**: sections (§185, p.82), pages (§189, p.81) and tabs (§190, p.54/p.84). One rule across them — *the latest instruction wins* — and one documented inconsistency, reproduced rather than tidied up: the page and section events leave their variable alone, the tab event writes it. The write-back does **not** remove the need for the shared arithmetic, which is the trap: the write takes a debounce and a round trip, so the event and the variable still disagree for a moment, and the difference is only that here they converge instead of staying apart |

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
| External ID on a variable | ✅ |
| Module interface toggle, with display name and description | ✅ |
| Interface variables mapped when embedding | ✅ — the §114 deferral is closed |
| Interface variables initialised from URL query parameters | ✅ — same external ID, same field |
| State saving keyed on external ID | ✅ §153 — the third consumer, and the one that makes the external ID a *storage key* rather than a stable label |

**Refusals:** mapping a variable not in the interface ✅; a type mismatch between host and interface variable ✅; a required interface variable left unmapped ✅; renaming an external ID that saved states point at ○ (needs state saving to exist first).

**Built as one mechanism, on purpose.** An external ID plus an interface toggle on the variable; a mapping keyed by external ID on the embed node; the same external ID read from the query string. `e2e/test_module_interface.py` asks one module about two of the three consumers deliberately — when state saving lands, its assertion belongs in that file against that fixture rather than in a new one.

**`required` is ours, not Foundry's.** No documented counterpart was found; it exists because the alternative to refusing an unmapped variable is an embedded module rendering against a default nobody chose. Opt-in, so no existing module becomes unsaveable.

**The precedence rule, which is easy to get backwards:** "When an interface variable is mapped between a parent and an embedded child module, Workshop uses the **parent module's** variable definition and ignores the embedded module's own" (p.164).

### 3.5 Evaluation — when a variable actually computes

Two behaviours that are semantics rather than UI, which is why they are easy to skip and expensive to retrofit: both change what a correct implementation of §3 *is*, not what it looks like.

**Lazy loading.** "In both view and edit mode, Workshop variables will compute and recompute lazily only when displayed by a visible widget or layout. This means that variables used in non-visible pages, tabs, overlays, or non-visible pages of a looped layout will not be computed until they are shown. This behavior is the same for non-visible variables used in embedded modules." (p.75)

We evaluate the whole variable graph on load. For a module with a handful of variables that is invisible; for one with an overlay per row of a table it is the difference between usable and not. Note the second-order effect: the Performance Profiler (§9) only counts widgets and variables that affect the on-screen display precisely *because* of this rule, so profiling is meaningless without it.

**Recompute behaviour**, configurable per variable on Function, Object set aggregation, Object property, Variable transformation and Object set filter definitions (p.76):

| Behaviour | Meaning | Status |
|---|---|---|
| **Automatic** | recompute when any dependency changes — the default, and what we do unconditionally | ✅ |
| **Only when triggered by an event** | recompute solely on a `recompute {variable}` event | ✅ |
| **On module load, and when triggered by an event** | recompute once at load, then only on the event | ✅ |

Object set definitions do not offer the choice and always behave as Automatic; the documented escape hatch is to set the behaviour on an upstream variable or use a function-backed one (p.76). Refused at save with that reason, as is a behaviour on a static variable — p.76 offers the setting on derived definitions only.

**Where the held value lives.** The server computes and has no memory between requests, so "do not recompute this time" can only come from the caller: the browser keeps what each holding variable last computed and sends it back, and the evaluator uses it *as the input to everything downstream* rather than merely displaying it. Freezing it in the browser instead would leave a variable showing one number while its dependants recomputed from a fresh copy — two answers to one question on one page.

The wire therefore carries **two** fields, not one. `held` is memory; `recompute` is the ask. Collapsing the ask into an absence from `held` looks equivalent and is not: for **Only when triggered by an event**, "nothing held" is already the state at load, so an event spelled that way produces a request identical to a fresh page and does nothing at all. **On module load** hides the bug, because its answer to a missing held value is "compute" either way.

The `recompute {variable}` event is the other half of this, in §5. Two caveats worth carrying into the implementation: automatic variables "may recompute even when no upstream values have changed", for instance after an action submission or an auto-refresh (p.76) — so nothing may assume recompute means dependency-changed; and a Reset event restores the value configured in the variable *definition*, which under §3.4's precedence rule means the parent's definition, not the child's (p.85, p.128).

---

## 4. Embedded modules

| Feature | Status | Notes |
|---|---|---|
| Embed a module in a module | ✅ | §114 |
| Editor disabled inside an embed | ✅ | §114 |
| **Interface variable mapping** | ✅ | the §114 deferral is closed; §3.4 |
| Sibling-to-sibling communication through shared interface variables | ◑ | works by construction — two embeds mapped to one host variable share it through the host — but **untested**, so it is a claim about the design rather than a demonstrated behaviour (p.164) |
| Embedded module may modify interface variables through events | ◑ | the write path exists and is two-way per p.127; a `set_variable` in the child on a mapped id routes to the host. Also untested (p.164) |
| **Loop layouts** — one embedded module per object in a set | ✅ | (p.54, p.129–136); §1.3 |
| Open Workshop module event, passing values into the target's interface | ○ | (p.165) |
| In edit mode, opening a child from a reference carries the current interface values through, for debugging | ○ | (p.165) — small, and a genuinely thoughtful touch |

---

## 5. Events

Ours: 3 triggers (`click`, `row_select`, `change`) and 5 effects (`set_variable`, `navigate`, `close_overlay`, `open_url`, `run_action`). `export` is deliberately absent because the server refuses it (§76).

| Foundry event family | Status | Notes |
|---|---|---|
| **Layers** — Open / Close each overlay | ✅ | |
| **Layout** — Switch to page | ✅ | |
| **Layout** — Expand / Collapse / Toggle each collapsible section | ✅ §185 | (p.82) — see §1.3's row for the gotcha and the resolution rule |
| Set variable value | ✅ | |
| **Recompute {variable}** | ✅ §194 | the other half of §3.5 — without it the two non-automatic recompute behaviours have no way to fire (p.85). p.85 offers it "for non-static variable types", and p.76 sharpens that: the behaviours it triggers are configurable on derived definitions only. So the server refuses it on a static variable (the complement of Reset, which is refused on a derived one — each event is meaningless on the other's half) and on a derived variable left on **Automatic**, which already recomputes when its inputs change, so an event aimed at one would be a click with no effect. **The ask travels as its own field on the resolve, not as a hole in `held`** — see §3.5 for why an absence cannot express it |
| **Reset {variable} value** | ✅ §193 | (p.85, p.128) — and it is a **deletion of the viewer's value, not a write of the default**, which is what makes p.128's precedence rule fall out instead of needing a case of its own. The server resolves an unbound static variable as `values.get(vid, default)`, so forgetting the local value *is* "back to the definition"; and it resolves a variable an embedding module has mapped as the host's value with the child's definition skipped entirely (p.127), so forgetting the local override there is "back to the parent's definition". One operation, right both ways. It deliberately **never forwards to the host**, unlike a Set: that would have a child's Reset button edit its parent's state, which p.128 does not say and which is a child reaching upward. p.85 offers Reset "for static variables", so the server refuses it on a derived variable and on an object set with its own definition — neither has a stored value to put back |
| Run action | ✅ | |
| Open URL | ✅ | |
| **Switch to {tab}** | ✅ §190, offerable §193 | (p.84) — and the inconsistency is reproduced rather than tidied up: unlike Switch-to-page and the three section events, this one **does** write the variable behind Variable-Based Tab Selection, and so does an ordinary click on the tab strip ("events that change the selected tab", which a click is the most ordinary way to be). The settings panel says so beside the picker, because an author who has met the other two will expect this one to match. **The write-back does not remove the need for the override the other two use**, which is the thing p.84 might mislead you out of building: the write takes a debounce and a round trip, and the tab has to move now — so for a few hundred milliseconds the event and the variable disagree exactly as they do one row up, and the same "latest instruction wins" arithmetic applies. The difference is only that here the two *converge*: the value comes back agreeing and the override retires. The server refuses a `switch_tab` naming a section that is not tabbed or a tab it does not have, and the refusal lists the tabs that *are* there, because the usual cause is a rename |
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
| **Versions dialog** listing timestamp, editor, description | ✅ | (p.191); the editor's *name*, not their id |
| Publish this version | ✅ | a named version, not "whatever is newest" |
| View this version, **with a warning banner when non-published** | ✅ | (p.191); read-only, and the banner is conditional exactly as documented |
| Revert to this version, with auto-generated description | ✅ | (p.192); a new version, not a rewind |
| Descriptions viewable, addable and **editable after the fact** | ✅ | (p.192) |
| Setting: **Automatically publish when saving** | ✅ | (p.192) |
| Display name / plural for a saved state (p.204) | ✅ | §153 — wording only, and it reaches the control a reader uses |
| Setting: **Always prompt for a version description** | ✅ | (p.192); a prompt, never a validation rule — the server accepts an empty description whatever the setting says |
| **Changelog panel** — range or single-version diff | ✅ | §132 — all five kinds ("additions, deletions, changes, moves, and newly unused elements"), single and range selection (p.193); §183 added the rest of p.193's sentence, the **JSON diff** ("inspect JSON diffs to see the exact modifications") and the **visual hierarchy** ("understand how changes relate to nested components"). The diff is leaf-by-leaf rather than line-by-line: a path and its two values is the modification itself, where a line diff of re-serialised JSON reports every line a key insertion shifted. The hierarchy is the layout tree **pruned to branches that contain a change** — the unpruned tree is the whole module, and a changelog that redraws the module buries the four things that moved, while a flat list loses the nesting the sentence asks for. Deleted nodes are grafted back at the position they held in the older version, since otherwise the one kind of change with no node left to hang off would be the one kind the hierarchy could not show |
| `/dev/` vs `/latest/` in the URL — last saved vs last published | ○ | (p.166); one route, and save-versus-publish becomes checkable by a human |
| Module branching and rebasing, with conflict resolution in the Changelog panel | ○ | (p.193) — out of scope for now. **Its prerequisite is now met**: p.193 says the rebasing UI "uses the Changelog panel to visualize changes and highlight conflicts", and as of §183 that panel is complete. What branching still needs is its own model — two heads of one module, and a rule for what a conflict *is* — not more of this panel |

**"View this version" is read-only, which is ours rather than Foundry's wording** and is the part worth stating: a historic document rendered in an *editable* canvas is one Save away from silently becoming the current one, and the person who did it would have thought they were only looking. Foundry's own answer to editing an old version is a documented dance — revert, duplicate the file, revert back (p.192) — which reads as the same caution.

---

## 7. Routing and state saving

| Feature | Status | Notes |
|---|---|---|
| Enable routing toggle, in Pages settings | ✅ | §152 — on the Layout panel, which is where our pages live; stored in the *document* beside the per-variable behaviours, so reverting a version restores both |
| Module state written to the URL for sharing | ✅ | §152. §99's `useUrlState` is the mechanism; what was missing was the module's own say in what goes there |
| Current **page ID** written to the URL; no ID means the default page on load | ✅ | §152 — author-set, not the Craft.js node id: a generated id changes when a page is recreated, so a link built from one would expire for a reason nobody could see. All three "no page" cases (absent, unnamed, since-deleted) open the default page |
| Per-variable URL behaviour: **In URL when used by visible widget or layout** | ✅ | §152 — the page walk decides "on screen", so a filter on page two is not in the link |
| Per-variable URL behaviour: **Always in URL** (when non-default) | ✅ | §152 |
| Per-variable URL behaviour: **Never in URL** | ✅ | §152 — and the default, so adding routing cannot make an existing module start publishing state |
| A query parameter matching an external ID seeds the variable **regardless** of the behaviour above | ✅ | §116 for the seeding, §152 for keeping it ungated — the two directions are separate rules in separate files, so a link typed by hand works against a module whose author never turned routing on |
| Refuse routing on object set **filter** variables | ◑ | §152 refuses the whole `array` kind, which is what filter clauses travel in — but that also refuses an ordinary multi-select, because a list needs repeated query parameters that `seedFromQuery` does not read. Wider than p.199 by exactly that much, and named here rather than left to be discovered |
| Object set variables in the URL limited to a single object by RID | ○ | (p.199) — §152 refuses `object_set` and `single_object` outright instead. Supporting them means a by-RID rehydration this platform does not have; writing a key with no lookup behind it would be a link that restores everything except the selection |
| Embedding does **not** inherit the child's routing config; pass through the interface instead | ✅ | §152, by construction: the routing sync is mounted by the viewer routes and reads *that* module's toggle, so an embedded child never writes to the URL at all |
| **State saving** — save, open, and share a named state | ✅ | §153 — db 0048. A state is stored **by external ID** (p.203), so it outlives the module being rebuilt around it; whoever can open the module can open its states, because a published module is read by people outside its project |
| State saving preserves enabled variables **and optionally the current page** | ✅ | §153 — the page is the author-set ID routing also writes, and turning the option off means *not stored* rather than merely not written |
| Per-variable state-saving enablement via external ID | ✅ | §153 — the third consumer of an external ID, as §3.4 predicted. Unlike routing it needs **no interface membership**: a state is read back by this module, by name, so a stable name is the whole requirement |
| Configure allowed save locations and shortcuts | ○ | (p.202, p.204) — **refused rather than pending.** These configure where in Compass a state file is written; a state here belongs to its module, which is the only location this platform has, and a setting with one possible value teaches nothing. Revisit only if projects ever gain a folder tree |

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
| **Value formatting** — fraction digits, min/max decimals, local to the module not the ontology | ○ | (Formatting section). The *ontology-level* one is built (§157, `ontology.md` §1.2) and this is the other one: Workshop's is per module, so two applications can show one property differently. Not free on top of §157 — the formatter type and `formatValue` are reusable, but a module-level override needs somewhere in the document to live and a rule for which wins |
| **Conditional formatting** | ◑ | ontology-level is built (§158, `ontology.md` §1.2) and applies here, because p.102 names Workshop as one of the surfaces the Ontology Manager's rules reach. Workshop-level rules — set on the module rather than the ontology — are ○, and share the open question with value formatting above: where in the document an override lives and which one wins. This row previously read ◑ citing §83, which was wrong; the correction is recorded in `ontology.md` §1.2 |
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
| Chart XY — bar, line, scatter; multi-series; aggregation; segmentation; **function-backed layers** `[fn]`; axes, legends, numeric formatting; selection and downstream filtering | ◑ `CanvasChart` — two of p.280's three Data inputs now: an object set and a **time series set** (§151, drawn as a line per p.281). Function aggregation is ○ with `[fn]`. There are still no *layers*: one input per chart, so multi-series and segmentation are ○ |
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
| Tabs | ✅ `CanvasTabs` — the *widget*, which moves between the module's pages (p.53: "navigate users between the pages of a module… triggered from within widgets such as the Button Group or Tabs"). Distinct from §1.3's Tabs **section** (§190), which tabs a section's own children; Foundry has both |
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
2. ~~**Object set filter variables** (§3.2) — unblocks the rest of the filtering category~~ — done as far as behaviour goes (§3.2); only the dedicated variable *kind* is outstanding, and no widget is waiting on it
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
- **Object set filter variables** ✅ — a Filter List's output applied to a second object set narrows it (`e2e/test_narrowing_widgets.py`); a default filter applies on load (`test_a_filter_can_start_with_a_default_applied`).
- **Object Table** — every documented configuration option has a test that drives it; inline edit writes back and an unpermitted edit is refused.
- **Auto-refresh** — an out-of-band ontology edit updates a rendered table without user interaction.
