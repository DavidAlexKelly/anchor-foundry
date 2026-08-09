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
| **Visibility** — normal, prominent, hidden | ○ | drives standard Object View layout (`object-views` p.10) |
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
| **Per-side display names** | ○ | e.g. Employee → *Employer*, Company → *Employees*. We name the link once. |
| **Self-links** — a link type between an object type and itself | ○ | "Direct Report ↔ Manager can be defined between the Employee object type and itself" |
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

"When you create and configure an object type in your Ontology, Foundry automatically creates a standard Object View" (p.10). All ○ today.

| Feature | Notes |
|---|---|
| Auto-generated for every object type | no configuration required |
| **Prominent properties surfaced at the top**, with type-aware rendering | the payoff for property visibility (§1.2) |
| — media reference → dedicated media viewer | |
| — time series → interactive chart | |
| — geohash / geoshape / geotemporal → rendered on a Map | |
| — everything else prominent → large card format above a table of the rest | |
| Normal properties in a regular table; hidden properties not shown | |
| **Linked objects component** — grouped by link type; preview linked properties inline; open a subset in a new tab; preview a selected linked object in the side panel | (p.11) |

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

Ours: declarative edits to editable properties, run from a Workshop `run_action` effect.

### 5.1 Core

| Feature | Status | Notes |
|---|---|---|
| Edit property values on one object | ✅ | |
| Edit **multiple objects in one transaction** | ○ | |
| **Create and delete objects** | ○ | |
| **Create and delete links** | ○ | the Assign Employee example creates an Employee→Manager link |
| **Parameters** — typed user inputs with their own form | ◑ | we have editable properties, not a parameter model |
| Parameter default values | ○ | TOC §7 |
| Filter the results of a parameter dropdown | ○ | TOC §8 |
| Parameter configuration overrides | ○ | TOC §10 |
| **Rules** — the logic mapping parameters to edits | ○ | TOC §5 |
| **Submission criteria** — conditions that must hold for submission | ○ | TOC §12 |
| **Validation** — e.g. only HR may perform this action | ○ | |
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

1. **Property visibility** (normal / prominent / hidden). Small, and it is the input to standard Object Views.
2. **Standard Object Views.** Generated from the object type; no builder UI needed. Biggest visible gain in this file.
3. **Link type per-side display names and self-links.** Small, currently inexpressible.
4. **Action parameters and rules.** The structural change everything in §5 depends on.
5. **Time series and media reference property types.** Both unlock Workshop widgets; both need a storage decision first.
6. **Configured Object Views**, reusing the Workshop runtime.
7. **Struct property type**, then Workshop struct variables.
8. **Ontology Manager search, filters, and the indexing-issue column.**
9. Shared properties, value types, interfaces, derived properties.
10. Side effects — notifications, then webhooks.

---

## 8. Acceptance tests

- **Property visibility** — a hidden property is absent from the standard Object View and from the Object Table column picker. Mutation: mark it normal, and both change.
- **Standard Object Views** — an object type with a prominent time series property renders a chart, not a table cell; with a prominent geopoint, a map. Remove the prominent flag and it falls back to the table.
- **Linked objects** — an instance with two link types shows two groups; expanding one previews properties without navigation.
- **Configured views** — creating one makes it the default; the standard view is still reachable.
- **Link sides** — a self-link between Employee and Employee renders both directions with distinct names.
- **Action parameters** — an action with a parameter whose submission criteria fail is **refused**, and the refusal names the criterion. Mutation: remove the criterion check, and the test goes red.
- **Action transactions** — an action editing two objects where the second edit fails leaves **neither** applied.
- **Undo** — reverting an action restores prior property values and re-creates deleted links.
- **Usage metrics** — a bulk load of 500 objects records **one** read, not 500.
