# Ontology — parity specification

**Covers:** Ontology Manager, Object Explorer, Object Views, Action Types.

**Sources:** `foundry_ontology.pdf` (172 pp), `foundry_ontology-manager.pdf` (74 pp), `foundry_object-link-types.pdf` (274 pp), `foundry_action-types.pdf` (174 pp), `foundry_object-views.pdf` (140 pp). Citations name the file: `(object-link-types p.127)`.

**Today:** `apps/api/src/services/ontology.py`, `instances.py`, `object_sets.py`, `actions.py`; `components/applications/object-type-app.tsx`; Object Explorer at §58; OpenSearch instance store at §16.

> **Source gap.** Object Explorer has **no dedicated PDF** in `docs/pal/`. Section 3 below is reconstructed from the standard Object View documentation, the application reference (`getting-started` p.48), and scattered mentions. It is the least well-sourced section in this set, and the one most likely to need correction against the real product.

This is the foundation the rest of the parity work stands on. Workshop's object widgets, Object Views, and function-backed actions all resolve to what is here.

---

## 1. Object types and properties

### 1.1 Property base types (`object-link-types` p.127)

Ours: `string`, `integer`, `float`, `boolean`, `date`, `timestamp`, `geopoint`, `json`, `attachment`.

| Foundry base type | Status | Notes |
|---|---|---|
| String, Integer, Double/Float, Boolean, Date, Timestamp | ✅ | |
| **Geopoint** | ✅ | §20 |
| **Attachment** — files on objects, for use with functions | ◑ | we have the type; no file storage behind it |
| **Geoshape** | ○ | polygons and lines, not just points |
| **Time series** | ◑ | §148, §149 — the type, the `object_type_series` mapping (db 0047), the points read, and the chart on the standard Object View. §151 added **Workshop**'s time series set variables (`workshop.md` §3.2) and the Chart XY input that reads one. What is left is the other three widgets p.582 names — Map, Metric Card, Object Table — and p.583's time series *transforms*; geotemporal series is the same mechanism with a geopoint value column and is ○ |
| **Geotemporal series** | ○ | position over time; renders on a Map in standard Object Views |
| **Media reference** | ○ | points at an item in a media set: `mimeType` plus a reference triple of media-set / view / item RIDs (p.128). **Decision 0009 declines to add the type**: a shape promising a media set with none behind it is a contract nobody honours. Media that is already stored renders (§147); a media *set* waits for a consumer that needs a collection |
| **Struct** — schema-based properties with multiple fields | ○ | also needed for Workshop struct variables |
| **Vector** — for semantic search | ○ | out of scope unless semantic search is |
| Cipher text | — | out of scope (Cipher is out of scope) |
| **Arrays of any base type** except Vector and Time series | ○ | |

Ours has `json`, which Foundry does not — Foundry's equivalent is Struct, which is typed. **Recommendation:** keep `json` as an escape hatch, add Struct as the typed path, and do not let `json` become the way people model structured data.

### 1.2 Property configuration

| Feature | Status | Source |
|---|---|---|
| Display name, description, API name | ✅ | |
| **Visibility** — normal, prominent, hidden | ✅ | (`object-link-types` p.111); drives standard Object View layout (`object-views` p.10), Explorer columns, and the Linked objects rows (§145 — one shared rule, because the third surface is where a second copy of it leaked) |
| **Value formatting** | ◑ | §157 — p.94-101. Numeric (currency, unit, percentage, prefix/suffix, grouping, notation, and p.98's five digit options) and date/time (p.99's six styles, and p.100's timezone: a named zone or the reader's own). Applied in the browser, because p.100's "the application user's current timezone" is not something a server knows — and because formatting on the way out would make filters, actions and exports read `"$100K"` where they used to read `100000`. **What is missing is p.95's three lookup formatters** — Foundry ID, resource RID, artifact GID — each of which turns an ID into a name by *asking something*, so none is a transformation of the value in hand; and p.97's Fixed Values, which is a value-to-label map for the same reason |
| **Conditional formatting** | ◑ | §158 — p.102-109. An *ordered* list of rules per property, first match wins, with p.105's always-true fallback (refused unless it is last, because everything after it is unreachable). Standard rules across p.105 label C's comparisons — string with p.105 label D's four operators, numeric range and exact, boolean, is-null — reading either the property being painted or **another one** (label B), against a constant or another property's value (label E), invertible (label F). Colour, background and alignment. **It composes with value formatting rather than competing**: the rule compares the raw stored value and the formatter decides the text, which is what lets one property show "$100K" and be coloured by a 50000 threshold. Missing: p.105's **Math rule**, which runs arithmetic over properties and is an expression language rather than a comparison; p.107's **Copy rules** dialog; and Blueprint's named colours and intents, since there is no Blueprint here — colours are hex |
| **Required properties** | ✅ | §154 — p.116. The flag has existed since migration 0003 and meant nothing; now **actions refuse** a write that empties one and **sync reports** the rows that do not comply rather than refusing to index them, which is p.116's own split |
| **Edit-only properties** | ◑ | §160 — p.113-115. A property with no column in any backing dataset: written by an action straight to the instance, **preserved across syncs** rather than deleted by one, and refused as a mapping target (p.114's own flow is to untoggle first). A stored flag, not "absent from every mapping" — the two are the same state and different intentions, and telling them apart is what schema drift detection exists for. The exception to the write-back rule is deliberately narrow: a `modify_object` rule on the action's own subject. A **link** property still needs a column (a link is a join over stored data), and `create_object` still refuses one, because a creation's dataset row is how the object comes to exist and there is no instance yet to write the value to. Not built: p.113's permissioning of an edit-only property to one of the backing datasets |
| Mandatory control properties | ○ | p.121-126. **Declined for now, and the reason is structural rather than effort.** These are row-level access controls enforced by *markings*, *organizations* and **restricted views** — p.124 is explicit that "the mandatory controls are enforced by backing the object type with a restricted view which has a policy that requires users to satisfy the markings in the mapped column". This platform has organisations but neither markings nor restricted views, so the enforcement mechanism the whole feature rests on is absent. A flag that looks like access control and enforces nothing is the worst kind of gap — worse than an absent feature, because somebody will rely on it. Same reasoning as decision 0009 declined the media reference type |
| **Property reducers** | ○ | TOC §18 |
| **Derived properties** — calculated at runtime from other properties or links | ◑ | §161 declares one, §162 answers it, §163 draws one. A chain of up to three link types (p.147), an aggregation (p.145) and the property at the far end (p.146), built a hop at a time — each step offering only the links that exist from where the chain stands (p.145) — evaluated when an object is read and never stored (p.143). The chain is an object set rooted at the one object, so §155's traversal answers it. **Still ◑ for one reason, and it is a real one: four of p.145's nine aggregations are refused** — `sum`/`avg`/`min`/`max` on the untyped-index blocker (§52, §74, §83, §86; this is the fifth) and `approx_cardinality` because OpenSearch approximates where Postgres is exact. p.143's own first example, a department's average employee salary, is among them. Also single-object reads only: a derived *column* in a table needs the aggregation pushed into the index, which is the same blocked work |
| **Shared properties** — one definition used across object types | ◑ | §164 — p.178-191. One definition in a workspace, attached to a property on any number of object types, with `display_name`, `description`, `visibility` and `value_format` **resolved at read time** rather than copied at attach time — which is p.178's own reason to exist ("update … metadata in one place instead of on each object type") and the half a copy would silently break. The property keeps its own id and api_name (p.188), so `began_on` on Employee and `start_date` on Contractor can be the same shared property. p.181's base-type match is enforced; p.188's "direct edits … will be disabled" is a refusal on the wire, because a value accepted and discarded is somebody's edit vanishing with nothing to explain it; **attaching is exempt from it**, since choosing a shared property is choosing its metadata. p.185's delete **reverts rather than cascades** (`ON DELETE SET NULL`), and the property keeps its last inherited metadata. p.191's Usage names the object type *and* the property. Missing: **type classes** and **render hints**, absent rather than stubbed — nothing in this platform reads a type class, and reindex tuning is not something this instance store exposes; and the **Ontology Manager surface** (p.180's shared property page, p.187's dropdown, p.178's globe), built in §165: p.180's page, p.181's creation modal, p.187's dropdown offering only the shared properties whose base type matches, p.188's Detach and its two disabled controls, p.191's Usage, and p.178's globe. **The row is ◑ for the two absences above, not for the surface.** One deliberate divergence: a shared property **in use** cannot change its base type — Foundry lists it as editable and does not say what happens to the object types using it, and a silent cascading retype is the exact change `type_impact` exists to make somebody acknowledge |
| **Value types** — reusable constrained types, versioned | ◑ | §168 — p.222-234. A semantic wrapper around a base type carrying a **constraint**: p.222's own example, an `email` value type whose regex means every property using it is understood to hold an address. The constraint-sibling of shared properties (a shared property shares *metadata*, a value type shares a *rule*), attachable in both of p.227's places — an object type property and a shared property, with a property inheriting its shared property's when it has not chosen one. p.229's split is the schema: name/description are editable, **base type and constraint are immutable and a change appends a version**, and p.230's propagation is automatic because a property references the value type and the current version is the highest-numbered one. Constraints built: enum (with p.233's case-insensitive option), range (numbers, temporals, and a string's *length*), regex (with p.233's substring option), uuid. **Deliberate divergence on enforcement**: p.227 has a failing value make the object type "fail to index", which would take a whole type off every screen for one bad row — this platform reports on sync and refuses on action, which is p.116's own split as applied in §154. Missing: p.233's `rid` (Foundry-specific; our resource ids are UUIDs, so `uuid` is the same check under one name), array and struct constraints (neither base type exists, §1.1), Foundry's separate **Value Types Manager** and its cross-project import (p.232 — one ontology per workspace here), and **deprecation** (p.229), which is §1.3's Status row rather than a second flag. `api_name` is immutable here though Foundry allows renaming, for `object_types.api_name`'s reason. §169 built the **Ontology Manager surface**: p.224's create form with the constraint editor offering only the kinds the base type allows (p.233), a range that says whether it bounds a *value* or a string's *length*, p.227's dropdown on a property, p.229's constraint change as an explicit "Change rule" that appends a version beside the previous ones, and the usage list across both attachment points. A property inheriting its shared property's value type says so and shows `↑` rather than `•`, since the two are different states and only one is this property's own choice |
| Title property / primary key | ✅ | |

### 1.3 Object type configuration

| Feature | Status |
|---|---|
| Backing dataset mapping | ✅ |
| Icon and colour | ◑ |
| Groups / categories | ○ |
| **Interfaces** — shared property and link contracts across object types | ○ `[?]` | **Second source gap in this set, found in §168 and worth naming before anybody starts.** `docs/pal/` has *no Interfaces chapter*: `foundry_ontology.pdf` p.54 links back to "Interfaces / Metadata reference" and `foundry_functions.pdf` p.427 forward to "Interfaces / Overview", and neither page is in the export. What survives is the definition (`ontology` p.27: "an Ontology type that describes the shape of an object type and its capabilities… object type polymorphism"), the design guidance (p.41-53: interfaces for abstraction, multiple inheritance, workflows targeting an interface rather than a type), and the implementation rules a *property* has to satisfy (`object-link-types` p.138-141). That is enough to build from and not enough to build *to* — the create/edit/metadata reference is exactly the part that would decide the schema. Needs the missing pages, or an explicit decision to design it from the fragments and mark what was guessed |
| **Status** — promoted / active / experimental / deprecated / example | ◑ | §170 — p.253-259. All five of p.254's values on object types, properties and link types, defaulting to `experimental` (p.256). **The refusals are the feature**: an `active` or `promoted` resource cannot be deleted, and the message names the way through. p.256/p.258's propagation demotes a type's properties with it and **never promotes them** — p.258 makes that an option, not a consequence, so a half-built field is not declared production-ready by somebody finishing the type around it. p.257's table is implemented as a *cap* rather than a warning: a link type is stored at the lowest of its own declaration, its two object types and its join properties, so the invalid state p.257's troubleshooting section describes is unreachable rather than detected. p.254's deprecation note (why, by when, what replaces it) is refused on anything not deprecated and cleared when a resource stops being deprecated. §171 built the **Ontology Manager surface**: p.256's dropdown offering only what the kind allows (p.255 makes `promoted` object-types-only, so offering it elsewhere is offering a save that fails), p.253's badge in the listing — but *not* on `experimental`, which is the default and would therefore label every row of a new ontology, a Delete button disabled with the server's own sentence as its reason, p.254's note offered only where the server accepts it, and **a warning naming the properties a demotion is about to take with it**, on screen while the choice is still a choice, since p.256's propagation is otherwise invisible until it has already run. Missing: action type statuses (the column exists; nothing enforces one yet), p.255's requirement that only an Ontology Owner may apply `promoted` (there is no ontology-level role here), p.258's bulk edit, and a per-property status control — a property's status is carried through and propagated but is not yet individually editable on the type form |
| Indexing / reindexing state and errors surfaced per object type | ○ |

---

## 2. Link types (`object-link-types` p.192)

> "A link type is the schema definition of a relationship between two object types… A link type is **bidirectional**: it always has two sides, one for each of the two object types it relates. Each side of a link type can be traversed independently and has its own display name."

| Feature | Status | Notes |
|---|---|---|
| Cardinality one-to-one, one-to-many, many-to-many | ✅ | |
| Link traversal from an instance | ✅ | §18 |
| **Per-side display names** | ✅ | stored, resolved and rendered (`STATUS.md` §123); `side_name` comes back already resolved against the link's own name, so a caller never has to know which end it is on |
| **Self-links** — a link type between an object type and itself | ✅ | **§2 was wrong to call this absent.** `link_types_for_type` already returned a self-link twice, once per direction, deliberately. What was missing was two *names*, so the directions could be told apart — which is the row above |
| Independent traversal of each side | ◑ | |
| Link traversal inside an object set definition | ✅ | §155 — a set can be the far side of a link (`via`), in either direction, capped at three hops and 1000 join values. A hop compiles to an `in` filter, so it needed no new store capability; the primary key became filterable on both stores, which is what makes the second direction possible |

Per-side display names and self-links are both small and both currently impossible to express. They should go together.

---

## 3. Object Explorer

*Reconstructed — see the source gap note above.*

| Feature | Status | Notes |
|---|---|---|
| Workspace-wide object browsing | ✅ | §17 |
| Search across object types | ✅ | §63 |
| Filter by property | ✅ | |
| Link traversal | ✅ | §18 |
| Open an instance into its Object View | ✅ | §122, §144 — the generated view, or a configured module if the type has one |
| **Favourite an individual object** — star next to its title, added to the sidebar | ○ | `getting-started` p.34 |
| Direct object edit from the Explorer | ○ | `ontology-manager` p.32 lists it as a write source |
| Save and share a search | ○ | |

---

## 4. Object Views (`object-views`)

**The highest value per unit of work in the whole parity set**, and cheaper than it looks: configured Object Views are "fully customizable representations **built using Workshop**" (p.2). We have that engine.

### 4.1 Standard Object Views — generated, not configured

"When you create and configure an object type in your Ontology, Foundry automatically creates a standard Object View" (p.10). **Built — `STATUS.md` §122**, less the two renderings that need property types we do not have.

| Feature | Status | Notes |
|---|---|---|
| Auto-generated for every object type | ✅ | no configuration, no saved document, nothing to publish |
| **Prominent properties surfaced at the top** | ✅ | the payoff for property visibility (§1.2) |
| — geohash / geoshape / geotemporal → rendered on a Map | ✅ | ours is geopoint; one point is still a map |
| — everything else prominent → large card above a table of the rest | ✅ | |
| — media reference → dedicated media viewer | ◑ | §147 — an attachment holding an image, video or audio renders inline; the *media set* Foundry references is genuinely absent (decision 0009 declines to build one), so the property type stays ○ |
| — time series → interactive chart | ✅ | §149 — a prominent `time_series` property draws its line from the points in the dataset behind it (decision 0009); bucketed by day, because a card is not an analysis surface |
| Normal properties in a regular table; hidden properties not shown | ✅ | |
| **Linked objects component** — grouped by link type | ✅ | all four of p.11's capabilities. The groups are there (§18) and sit *inside* the view rather than beside it; a linked object's properties preview inline without navigating (§145), typed, prominent first, hidden absent; **§159** adds the other two — opening a subset in a new tab, which needed no new query because a link is a derived join (db 0027) and the subset is therefore a filter the Explorer already speaks, primary-key sentinel included; and the side panel, which holds one selected object beside the view and clears itself on a hop |

### 4.2 Configured Object Views

| Feature | Status | Notes |
|---|---|---|
| Built in Workshop, becomes the default view once created | ✅ | §144 — a published module is nominated in the Ontology Manager and stands in for the generated view. The object arrives in the module's `single_object` variable, which is the whole binding |
| **Users can always switch back to the standard view** | ✅ | §144 — a control on the view itself, and there is no setting that could express the opposite: nothing is stored that hides the generated view |
| **Full** form factor — comprehensive | ✅ | (p.3) |
| **Panel** form factor — for embedding in other applications, focused on critical data | ◑ | (p.4) — stored and separately addressable (db 0046), so the two never collide; nothing embeds one yet, which is the half that is missing |
| Version management for configured views | ✅ | the module's own — a view is a *pointer* at a module, so publishing, versions, revert and the changelog are all the ones §120 and §71 built |
| Branching object views | ○ | TOC §6 — out of scope, tracks Global Branching |
| Generate Object View URLs | ○ | TOC §20 |
| Comment on objects | ○ | TOC §21 |

**Build order.** Standard views first — they are generated, they need no builder UI, and they immediately make every object type navigable. Configured views second, reusing the Workshop runtime bound to a single object. The panel form factor last, since it exists to be embedded and there is nothing to embed it in yet.

**Configured views are built (§144), and the reason they were cheap is that they are a pointer.** `object_type_views` stores which module stands in for which type and which of its variables receives the object; everything a view needs beyond that — layout, variables, events, versions, publishing, changelog — is the module's, already built. Four refusals at save time keep a view from being configured that nobody could open: an unknown form factor, a module this workspace cannot see, an **unpublished** module (an object view is read by whoever can read the object), and a `subject_variable` that is not a `single_object` variable of that module.

---

## 5. Action types (`action-types`)

> "An action is a single transaction that changes the properties of one or more objects, based on a user-defined logic… An action type is the definition of a set of changes or edits to objects, property values, and links that a user can take at once. **It also includes the side effect behaviors that occur with action submission.**" (p.2)

Ours: **parameters and rules** (§127), run from a Workshop `run_action` effect. Migration 0044 split what used to be one list of property names into the inputs and what is done with them.

### 5.1 Core

| Feature | Status | Notes |
|---|---|---|
| Edit property values on one object | ✅ | |
| Edit **multiple objects in one transaction** | ✅ | §134–§141 — an action can change, create and delete several objects of several types, across as many datasets, in one transaction (decision 0008) |
| **Create and delete objects** | ✅ | §135, §138–§141 — create any type with a dataset in this project, delete or change the object the action ran on *or* one a parameter names, all in one transaction (decision 0008) |
| **Create and delete links** | ◑ | §136, §142 — a link here *is* the join property (migration 0027), so a link rule writes or clears it, from either end: the far side names the other object through a parameter and writes *its* join property. Many-to-many is refused with a sentence |
| **Parameters** — typed user inputs with their own form | ✅ | §127, §129, §130 — the model executes, is editable through the API, and the form renders one input per *visible* parameter (p.25) |
| Parameter default values | ✅ | §127, §129 — applied on execute (p.27) and settable through the definition endpoint |
| Filter the results of a parameter dropdown | ○ | TOC §8 |
| Parameter configuration overrides | ○ | TOC §10 |
| **Rules** — the logic mapping parameters to edits | ✅ | §127, §135–§143 — all five of p.75's simple rules execute against the subject or an object a parameter names, and the editor offers every shape |
| **Submission criteria** — conditions that must hold for submission | ◑ | §128–§131 — conditions over parameters and the current user, checked before the first write (p.49–56), editable in the Ontology Manager; no nesting (p.56's all / any / none) |
| **Validation** — e.g. only HR may perform this action | ◑ | §128 — this *is* submission criteria (p.140: "simple submission criteria can require a specific user ID or group ID"); a criterion can require a group |
| Configure sections in the action form | ○ | TOC §24 |
| Actions on interfaces / on structs | ○ | TOC §13–14 |

### 5.2 Side effects (TOC §18–23) — all ○

| Feature | Notes |
|---|---|
| **Notifications** | notify the old and new manager of a change |
| **Webhooks** | outbound call on submission |
| Trigger a schedule build | |

### 5.3 Operational

| Feature | Status | Notes |
|---|---|---|
| **Inline edits** | ○ | TOC §28 — required by Object Table inline editing |
| **Undo / revert an action** | ○ | TOC §32 |
| **Action log** | ◑ | we audit; Foundry surfaces it as an ontology feature and a Workshop widget (Action Log Timeline) |
| Action metrics | ○ | TOC §34 |
| Permissions, read and write authorizations | ✅ | RLS |
| Upload media / attachments through an action | ○ | TOC §25–26 |
| **Function-backed actions** `[fn]` | ○ | TOC §15–17, including batched execution |
| Writeback dataset — "the most up-to-date version of object data with user edits incorporated" | ○ | (p.3) |

The parameter-and-rules model is the big one. Ours conflates "what the user types" with "what gets written"; Foundry separates them, and everything else in this section — validation, submission criteria, defaults, dropdown filtering — hangs off that separation. **Do parameters and rules before any of the features that depend on them.**

**Decided in `docs/decisions/0007-action-parameters-and-rules.md` (§124); the model is built (§127).** Migration 0044 replaced the JSON column with `action_parameters` and `action_rules`, converting every existing action type into parameters named after the properties it wrote plus one `modify_object` rule each — which is what keeps every saved Workshop `run_action` working unchanged, and is tested by running the migration for real against a database seeded at 0043.

Executing an action is now two steps: bind the parameters (defaults, required, unknown names refused), then apply the rules. `hidden` and `default_value` are honoured; the other four rule kinds are storable and refused loudly rather than skipped.

**Submission criteria are built (§128).** Migration 0045 stores one condition per row with its own failure message (p.56); every row must pass (p.50), and the check runs before the run is even opened, so a refused action leaves no dataset version and no history. The operator names are Foundry's own (p.54–55), including "no value" for emptiness. A condition the executor cannot decide **fails** — p.52's warning about NOT conditions is that a check which passes for want of an attribute grants more access than intended.

**The definition is editable through the API (§129)** — `PUT /action-types/{id}/definition` replaces parameters, rules and criteria as one document, validated as a unit, and **refuses removing or renaming a parameter a Workshop module calls**, naming the module. That was decision 0007's last named acceptance test, and it is the reason a whole-document endpoint rather than per-row ones: the three lists constrain each other.

**The action form renders from parameters (§130)**: visible ones get a field, hidden ones are sent but not drawn (p.25), defaults and current values seed them (p.27), required blocks submission, and a refused submission shows the criterion's own failure message (p.56). It deliberately does *not* evaluate criteria itself to grey the button out in advance — that would be a second implementation of a rule governing writes, in another language, free to disagree with the first.

**The editor is in the Ontology Manager (§131, §137, §143)** — one dialog per action, saved as one document, with the server's refusals shown rather than re-implemented in the browser. It offers every rule kind that executes, and every shape each one can take.

**All five of p.75's simple rules execute (§135–§138)**, on decision 0008's boundary: stage every write, commit in one Postgres transaction, one dataset version per dataset per action, and the search index as a projection that is repaired rather than transacted.

**The lookup is built (§139).** A `create_object` rule can name any object type with a dataset mapped in this project; the row goes into *that* dataset, and both datasets commit together or not at all — which is the case decision 0008's `commit_versions` was written for and nothing had exercised until now.

**Naming a second object is built (§140, §141)** — a parameter of type `object` holds an instance, and a `delete_object` or `modify_object` rule can name one. A named modify is checked against *the type it changes* and written into *the source that instance came from*, because two instances of one type can come from two sources with different column mappings; changing an object and deleting the same one is refused at save time, and changing one and deleting another is not.

**Both ends of a link can be named (§142).** A link rule written from the side that holds no foreign key names the other object through a parameter and writes *its* join property with this object's `to_property` — as this action leaves it, so an action that changes the joined-on property and links on it in the same submit does not create a link that stops holding the moment it finishes. `delete_link` clears the same column.

**The dialog can say all of it (§143).** A rule picks which object it writes — this one, or one an `object` parameter names — and its property dropdown comes from *that* type; a create picks the type it creates; a link rule asks "which object to point at" or "which object to link" depending on which end this action's type is. Only `object`-typed parameters are offered where an instance is wanted, because a string one would carry a primary key and the executor looks instances up by id.

What is left of §5: many-to-many links stay refused — one foreign key cannot express one, and this platform has no join table to put the second half in. Nesting criteria (p.56's all / any / none) is a `config` shape and waits for something that asks for it.

---

## 6. Ontology Manager (`ontology-manager`)

| Feature | Status | Notes |
|---|---|---|
| Object type editor | ✅ | §57 |
| **Header search bar, `Cmd+K`** — across object types, properties, link types, action types, shared properties, interfaces, functions | ◑ | §146 — one query across the four kinds that exist here, with `Cmd+K` on the window. §167 added **shared properties**, the fifth of p.28's seven — the one that most needed it, since a shared property is what somebody looks for by name *before* creating a second one that means the same. It is the only kind with no object type to name (p.178), so its hit carries a **usage count** in place of an owner and opens the shared property itself. Interfaces and functions are ○ in §1.2/§1.3, so there is nothing of theirs to search |
| Search results highlight **which field matched**; arrow-key navigation with previews | ◑ | §146 — the matcher reports the field and the mark lands inside its value, because the browser re-deriving it would be a second matcher free to disagree. Arrow-key navigation and previews are ○ |
| Home page sections: Object types, Link types, Action Types, Shared Properties, Interfaces, Functions | ◑ | (p.29) |
| Filter by **visibility, development status, indexing issues** | ○ | (p.29) |
| **Red error messages in an issue column** for object types that failed to index | ○ | (p.29) — exactly the kind of thing that saves a support ticket |
| Back home, with hover quick-links to recently edited types and related resources | ○ | (p.30) |
| **Change management** — save changes, review and restore | ◑ | §85 gives us history; Foundry has an explicit review-and-restore flow (TOC §7–8). **A restore now restores the whole definition** (§166): the snapshot recorded six fields per property, so rolling back silently dropped `visibility`, `value_format`, `conditional_format`, `edit_only`, `derivation` and `shared_property_id` — five shipped features losing their configuration with no error, for five units, because a missing key has no general test. It has one test per field now. Two references can vanish between a version and its restore and are treated differently on purpose: a deleted **shared property** is dropped (p.185 already says its users revert to regular properties), a **derivation** whose links have gone is refused. Versions written before §166 still hold six keys and still lose the rest — that data was never captured |
| Export, edit, and import an ontology | ○ | TOC §9 |
| Ontology cleanup | ○ | TOC §10 |
| **Usage metrics** — reads, writes, interactions over 30 days, per object and link type | ○ | (p.32); note the counting rule — a bulk load or bulk edit counts as **one** |

---

## 7. Build order

1. ~~**Property visibility**~~ — **done (`STATUS.md` §121)**. Stored, editable, and honoured by the Object Explorer, which no longer draws a hidden property's column. Deliberately **a display hint and not a permission**: the value is still stored, still synced and still returned by the API, exactly as Foundry's "an indication to user applications" (p.111) describes. Making it look like access control would be worse than not having it, because somebody would use it as one.
2. **Standard Object Views.** Generated from the object type; no builder UI needed. Biggest visible gain in this file, and now unblocked — visibility is the input it was waiting for.
3. ~~**Link type per-side display names and self-links**~~ — **done (`STATUS.md` §123)**, less the one test named above. Self-links turned out to already work; only the naming was missing.
4. **Action parameters and rules.** The structural change everything in §5 depends on. **Designed — decision 0007 — and next to build.**
5. ~~**Time series and media reference property types.**~~ — decision 0009 made, and both built as far as this platform can honour them. Media needed no type at all, only a renderer (§147). Time series is the type, the `object_type_series` mapping and the points read (§148); what is left is the *chart* that draws them, which belongs with §4.1's standard Object View rather than with the storage.
6. ~~**Configured Object Views**, reusing the Workshop runtime~~ — **done (`STATUS.md` §144)**. A pointer at a published module plus the one variable that receives the object; the panel form factor is stored and separately addressable, and waits for something to embed it in.
7. **Struct property type**, then Workshop struct variables.
8. **Ontology Manager search** — done (`STATUS.md` §146), across the four kinds that exist. **Filters and the indexing-issue column** are still open: filtering wants a development status we do not have (§1.3), and the issue column wants indexing state the sync path does not record.
9. Shared properties, value types, interfaces, derived properties.
10. Side effects — notifications, then webhooks.

---

## 8. Acceptance tests

- **Property visibility** — a hidden property is absent from the standard Object View and from the Object Explorer's columns. Mutation: mark it normal, and both change. **Note on the original wording**: this said "the Object Table column picker", and there is no picker — the Workshop Object Table takes a typed `columns` string. The Explorer's derived columns are the equivalent surface and are what the test drives.
- **Standard Object Views** — an object type with a prominent time series property renders a chart, not a table cell; with a prominent geopoint, a map. Remove the prominent flag and it falls back to the table.
- **Linked objects** — an instance with two link types shows two groups; expanding one previews properties without navigation. **Met (§145)**, in `e2e/test_linked_object_preview.py`: the trail is the evidence nothing navigated, and the mutation that draws every declared property regardless of visibility is red.
- **Configured views** — creating one makes it the default; the standard view is still reachable. **Met (§144)**, in `e2e/test_configured_object_view.py`: the module renders in place of the generated view, the object reaches it through `object_property` on the subject variable (so a module that renders without the object goes red), and the switch works both ways.
- **Link sides** — a self-link between Employee and Employee renders both directions with distinct names.
- **Action parameters** — an action with a parameter whose submission criteria fail is **refused**, and the refusal names the criterion. Mutation: remove the criterion check, and the test goes red.
- **Action transactions** — an action editing two objects where the second edit fails leaves **neither** applied.
- **Undo** — reverting an action restores prior property values and re-creates deleted links.
- **Usage metrics** — a bulk load of 500 objects records **one** read, not 500.
