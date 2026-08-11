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
| **Time series** | ○ | "stores a history of timestamped values"; consumed by Chart XY, Map, Metric Card, Object Table |
| **Geotemporal series** | ○ | position over time; renders on a Map in standard Object Views |
| **Media reference** | ○ | points at an item in a media set: `mimeType` plus a reference triple of media-set / view / item RIDs (p.128). Backing dataset needs a media reference column. |
| **Struct** — schema-based properties with multiple fields | ○ | also needed for Workshop struct variables |
| **Vector** — for semantic search | ○ | out of scope unless semantic search is |
| Cipher text | — | out of scope (Cipher is out of scope) |
| **Arrays of any base type** except Vector and Time series | ○ | |

Ours has `json`, which Foundry does not — Foundry's equivalent is Struct, which is typed. **Recommendation:** keep `json` as an escape hatch, add Struct as the typed path, and do not let `json` become the way people model structured data.

### 1.2 Property configuration

| Feature | Status | Source |
|---|---|---|
| Display name, description, API name | ✅ | |
| **Visibility** — normal, prominent, hidden | ✅ | (`object-link-types` p.111); drives standard Object View layout (`object-views` p.10) — **the view itself is still ○, see §4.1** |
| **Value formatting** | ○ | `object-link-types` TOC §11 |
| **Conditional formatting** | ✅ | §83 |
| **Required properties** | ○ | TOC §15 |
| **Edit-only properties** | ○ | TOC §14 |
| Mandatory control properties | ○ | TOC §16 |
| **Property reducers** | ○ | TOC §18 |
| **Derived properties** — calculated at runtime from other properties or links | ○ | TOC §19; also a Workshop feature |
| **Shared properties** — one definition used across object types | ○ | TOC §26–30 |
| **Value types** — reusable constrained types, versioned | ○ | TOC §36–39 |
| Title property / primary key | ✅ | |

### 1.3 Object type configuration

| Feature | Status |
|---|---|
| Backing dataset mapping | ✅ |
| Icon and colour | ◑ |
| Groups / categories | ○ |
| **Interfaces** — shared property and link contracts across object types | ○ |
| Status (development / experimental / active / deprecated) | ○ |
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
| Link traversal inside an object set definition | ○ | needed by Workshop §3.1 |

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
| Open an instance into its Object View | ○ | §4 |
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
| — media reference → dedicated media viewer | ○ | **blocked on the property type**, §1.1 — not on this view |
| — time series → interactive chart | ○ | same |
| Normal properties in a regular table; hidden properties not shown | ✅ | |
| **Linked objects component** — grouped by link type | ◑ | the groups are there (§18) and now sit *inside* the view rather than beside it (p.11). Inline property preview, open-a-subset-in-a-tab and the side-panel preview are ○ |

### 4.2 Configured Object Views

| Feature | Status | Notes |
|---|---|---|
| Built in Workshop, becomes the default view once created | ○ | (p.2) |
| **Users can always switch back to the standard view** | ○ | standard views "remain accessible even after a configured Object View is built" (p.2) |
| **Full** form factor — comprehensive | ○ | (p.3) |
| **Panel** form factor — for embedding in other applications, focused on critical data | ○ | (p.4) |
| Version management for configured views | ○ | TOC §4 |
| Branching object views | ○ | TOC §6 — out of scope, tracks Global Branching |
| Generate Object View URLs | ○ | TOC §20 |
| Comment on objects | ○ | TOC §21 |

**Build order.** Standard views first — they are generated, they need no builder UI, and they immediately make every object type navigable. Configured views second, reusing the Workshop runtime bound to a single object. The panel form factor last, since it exists to be embedded and there is nothing to embed it in yet.

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
| **Header search bar, `Cmd+K`** — across object types, properties, link types, action types, shared properties, interfaces, functions | ○ | (p.28) |
| Search results highlight **which field matched**; arrow-key navigation with previews | ○ | (p.28) |
| Home page sections: Object types, Link types, Action Types, Shared Properties, Interfaces, Functions | ◑ | (p.29) |
| Filter by **visibility, development status, indexing issues** | ○ | (p.29) |
| **Red error messages in an issue column** for object types that failed to index | ○ | (p.29) — exactly the kind of thing that saves a support ticket |
| Back home, with hover quick-links to recently edited types and related resources | ○ | (p.30) |
| **Change management** — save changes, review and restore | ◑ | §85 gives us history; Foundry has an explicit review-and-restore flow (TOC §7–8) |
| Export, edit, and import an ontology | ○ | TOC §9 |
| Ontology cleanup | ○ | TOC §10 |
| **Usage metrics** — reads, writes, interactions over 30 days, per object and link type | ○ | (p.32); note the counting rule — a bulk load or bulk edit counts as **one** |

---

## 7. Build order

1. ~~**Property visibility**~~ — **done (`STATUS.md` §121)**. Stored, editable, and honoured by the Object Explorer, which no longer draws a hidden property's column. Deliberately **a display hint and not a permission**: the value is still stored, still synced and still returned by the API, exactly as Foundry's "an indication to user applications" (p.111) describes. Making it look like access control would be worse than not having it, because somebody would use it as one.
2. **Standard Object Views.** Generated from the object type; no builder UI needed. Biggest visible gain in this file, and now unblocked — visibility is the input it was waiting for.
3. ~~**Link type per-side display names and self-links**~~ — **done (`STATUS.md` §123)**, less the one test named above. Self-links turned out to already work; only the naming was missing.
4. **Action parameters and rules.** The structural change everything in §5 depends on. **Designed — decision 0007 — and next to build.**
5. **Time series and media reference property types.** Both unlock Workshop widgets; both need a storage decision first.
6. **Configured Object Views**, reusing the Workshop runtime.
7. **Struct property type**, then Workshop struct variables.
8. **Ontology Manager search, filters, and the indexing-issue column.**
9. Shared properties, value types, interfaces, derived properties.
10. Side effects — notifications, then webhooks.

---

## 8. Acceptance tests

- **Property visibility** — a hidden property is absent from the standard Object View and from the Object Explorer's columns. Mutation: mark it normal, and both change. **Note on the original wording**: this said "the Object Table column picker", and there is no picker — the Workshop Object Table takes a typed `columns` string. The Explorer's derived columns are the equivalent surface and are what the test drives.
- **Standard Object Views** — an object type with a prominent time series property renders a chart, not a table cell; with a prominent geopoint, a map. Remove the prominent flag and it falls back to the table.
- **Linked objects** — an instance with two link types shows two groups; expanding one previews properties without navigation.
- **Configured views** — creating one makes it the default; the standard view is still reachable.
- **Link sides** — a self-link between Employee and Employee renders both directions with distinct names.
- **Action parameters** — an action with a parameter whose submission criteria fail is **refused**, and the refusal names the criterion. Mutation: remove the criterion check, and the test goes red.
- **Action transactions** — an action editing two objects where the second edit fails leaves **neither** applied.
- **Undo** — reverting an action restores prior property values and re-creates deleted links.
- **Usage metrics** — a bulk load of 500 objects records **one** read, not 500.
