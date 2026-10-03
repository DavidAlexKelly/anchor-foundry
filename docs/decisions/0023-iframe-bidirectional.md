# 0023 — The Iframe's Bidirectional mode: a message protocol of this platform's own

**Status:** decided and built (§756).
**Parity items:** `docs/parity/workshop.md` §10 (*Iframe*: "○: p.552–553's **Bidirectional** mode").
**Source:** `docs/pal/foundry_workshop.pdf` p.545, p.552-553, cited `(p.N)`.
**Follows:** §455 (the Iframe widget), §462 (an event fired from one of a widget's items), and decision 0002 (variables and events).

---

## What the document says

> "The configuration bidirectional option allows you to embed a custom-built application and enable bidirectional communication with Workshop using defined configuration fields. This enables the embedded application to act as if it were any other Workshop widget, with the ability to read from and write to Workshop variables, as well as execute Workshop events." (p.552)

> "The communication between your custom application and Workshop is done using the npm package @osdk/workshop-iframe-custom-widget … useWorkshopContext which takes in the definition of the variables and events that your application wants to receive from Workshop, and returns a context object that has an interface to read from Workshop variable values, write to Workshop variable values, and execute Workshop events." (p.552)

> "The widget's configuration panel will display a loading state while waiting to receive the definition of variables and events required by the embedded application. After receiving the definition of required variables and events, the widget's configuration panel will display variable pickers and event selectors for each variable and event requested … The value of the set Workshop variable will be sent to the custom application each time the value or loading state of the variable changes. The set events will determine what events can be executed from within the custom application." (p.553)

**Who defines what.** The framed application states what it needs: these fields, these events. The builder binds each field to a variable of the module and wires each event. After that the two talk through `postMessage`. Foundry's half of that conversation is an npm package whose wire format the document does not give, so this platform defines its own. The npm package is not a dependency of anything here.

## 1. The messages

Every message is a JSON object with a `type` beginning `anchor-widget//` and `version: 1`.

| Direction | `type` | Body |
|---|---|---|
| frame → module | `anchor-widget//definition` | `fields: [{id, label?, type, access?}]`, `events: [{id, label?}]` |
| module → frame | `anchor-widget//request-definition` | none; sent when the frame loads, so a definition sent before the module listened is sent again |
| module → frame | `anchor-widget//values` | `values: {fieldId: {value, loading}}`, for bound fields only |
| frame → module | `anchor-widget//set-value` | `fieldId`, `value` |
| frame → module | `anchor-widget//execute-event` | `eventId` |

* **A field's `type`** is a variable kind that has a plain JSON value: `string`, `number`, `boolean`, `date`, `timestamp`. An object set or an object is refused. p.552 sends the application to the Ontology SDK for ontology data, and this platform has none.
* **`access`** is `read`, `write` or `read_write` (the default). A `read` field cannot be written; a `write` field is sent no value.
* **`values` goes out whenever a bound value or its loading state changes**, as p.553 says, and once in full after each definition, so a reloaded frame catches up.
* Ids match `[A-Za-z][A-Za-z0-9_-]{0,63}`; at most 50 fields and 50 events. A definition outside that is ignored, as is a message that is not one of these.

## 2. Who may talk

`postMessage` crosses origins by design, so the widget checks both ends:

* **A message is read only from this frame's own window** (`event.source`), and only from the origin of the URL it framed. Another frame on the page, or a page this frame navigated to on another site, is ignored.
* **A message is sent only to that origin**, never `"*"`. A frame that has navigated elsewhere is sent nothing.

A path on this platform frames this platform's own origin, so the module's origin is the one it checks.

## 3. Writes and events, in run mode only

* `set-value` writes the bound variable, as a Text Input writes its own. It is refused (ignored, with a console warning for the application's author) when: the field is unbound or `read`; the variable is **derived**, since a derived value is a function of its inputs (decision 0002) and a write would be overwritten; or the value is not of the field's type.
* `execute-event` runs the module events wired to that item of the widget: `trigger: {node, on: "click", item: eventId}`, the same shape §462 gave a Menu button's items and §613 a table's right-click menu. The server checks the item against the definition saved on the widget, so an event wired to something the application no longer requests is refused on save.
* In the builder the frame is inert, as §455 left it. It still loads and still sends its definition, which is how p.553's configuration panel learns what to offer. Nothing it writes or fires is acted on there.

## 4. The definition is saved with the module

The panel stores the last definition it received on the widget (`frameDefinition`), beside the builder's bindings (`frameBindings`: field id → variable id) and the mode. So a module opens with its bindings intact even before the application answers. A viewer's frame that sends a different definition at run time is read against the saved one: a field the saved definition lacks is unbound, so it is neither sent nor written.

`frameBindings` is a mapping prop like an embed's interface (`MAPPING_REFERENCE_PROPS`). So a bound variable counts as used, cannot be deleted from under the widget, and is computed when the widget is on screen.

## 5. Not built

* The npm package's own wire format: it is not in the document, and an application written against it talks to Foundry. One written against §1 talks to this platform.
* Object and object-set fields, which need an ontology SDK on the far side (§1).
