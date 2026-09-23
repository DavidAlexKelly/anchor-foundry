/** The widget library, as data (§447).
 *
 * **Its own file because vitest cannot parse `.tsx`.** The list lived in
 * `widgets.tsx` beside the components it names, which is where it reads best
 * and where no test can reach it — so `widget-palette.test.ts` could not
 * check that every widget in it has a category, which is the one thing that
 * goes wrong silently when the library grows.
 *
 * The key is the resolver's, and `widgets.tsx` re-exports this so every
 * caller that has imported `PALETTE` from there since the builder was written
 * goes on working (§292).
 */

export interface PaletteEntry {
  key: string;
  label: string;
  /** One line, shown as the item's title. Searched as well as the label: the
   *  hints are where the word somebody actually thinks of lives. */
  hint: string;
}

export const PALETTE: PaletteEntry[] = [
  { key: "CanvasHeader", label: "Header", hint: "A toolbar above every page; one per module" },
  { key: "CanvasPage", label: "Page", hint: "A screen of the app; Tabs move between them" },
  { key: "CanvasSection", label: "Section", hint: "Columns, rows, a flow or a toolbar" },
  { key: "CanvasLoopSection", label: "Loop", hint: "One embedded module per object in a set" },
  { key: "CanvasOverlay", label: "Overlay", hint: "A modal or drawer over the page" },
  { key: "CanvasTabs", label: "Tabs", hint: "One button per page" },
  { key: "CanvasButton", label: "Button", hint: "Runs the events wired to its click" },
  { key: "CanvasContainer", label: "Container", hint: "A box to arrange other widgets in" },
  { key: "CanvasText", label: "Text", hint: "A heading or paragraph" },
  { key: "CanvasFilterList", label: "Filter list", hint: "Property filters over an object set, with counts" },
  { key: "CanvasFilterPills", label: "Filter pills", hint: "The filters on a set, shown as pills a viewer can remove" },
  { key: "CanvasUserSelect", label: "User select", hint: "Pick one or several people from the organisation" },
  { key: "CanvasProminentTerms", label: "Prominent terms", hint: "A curated list of values to filter by, each with its count" },
  { key: "CanvasNumericInput", label: "Numeric input", hint: "A number the viewer types, with units and grouping" },
  { key: "CanvasTextInput", label: "Text input", hint: "A line or a paragraph the viewer types" },
  { key: "CanvasStringSelector", label: "String selector", hint: "Pick one or many from a list of strings" },
  { key: "CanvasDateTimePicker", label: "Date and time", hint: "A single date and time, in a chosen timezone" },
  { key: "CanvasMarkdown", label: "Markdown", hint: "Formatted text, typed or read from a string variable" },
  { key: "CanvasObjectSetTitle", label: "Object set title", hint: "One object's title, or an object type and how many there are" },
  { key: "CanvasPropertyList", label: "Property list", hint: "The properties of one object, in a grid" },
  { key: "CanvasLinksWidget", label: "Links", hint: "One object's links, in expandable sections" },
  { key: "CanvasObjectViewWidget", label: "Object view", hint: "The whole object view for one object, embedded" },
  { key: "CanvasObjectDropdown", label: "Object dropdown", hint: "Pick one object from a searchable list" },
  { key: "CanvasObjectSelector", label: "Object selector", hint: "Pick several objects from a searchable list" },
  { key: "CanvasPieChart", label: "Pie chart", hint: "Objects grouped by a property, as proportional slices" },
  { key: "CanvasStepper", label: "Stepper", hint: "Progress through a multi-step workflow, in order or not" },
  { key: "CanvasTimeline", label: "Timeline", hint: "Objects from any number of sets, as events in time order" },
  { key: "CanvasMediaPreview", label: "Media preview", hint: "An image, video or audio file, from a URL or an attachment" },
  { key: "CanvasDatasetTable", label: "Dataset table", hint: "Preview rows from a dataset" },
  { key: "CanvasObjectTable", label: "Object table", hint: "Live rows from an ontology object type" },
  { key: "CanvasObjectCards", label: "Card list", hint: "The same objects as cards, one heading each" },
  { key: "CanvasSearch", label: "Search", hint: "Narrow an object set by a property prefix" },
  { key: "CanvasPivotTable", label: "Pivot table", hint: "Counts by two properties at once, over an object set" },
  { key: "CanvasTimeSeries", label: "Time series", hint: "When the objects in a set last changed" },
  { key: "CanvasEmbeddedModule", label: "Embedded module", hint: "Another Workshop module, shown inside this one" },
  { key: "CanvasChart", label: "Chart", hint: "Bar, line, pie or scatter over a dataset" },
  { key: "CanvasMap", label: "Map", hint: "Pins from a geopoint property or location columns" },
  { key: "CanvasMetricCard", label: "Metric card", hint: "One number over an object set" },
  { key: "CanvasActionForm", label: "Action form", hint: "Write back to an object instance" },
];
