/**
 * The platform's named icons (§705, decision 0019).
 *
 * > "Icon: Select the default icon to customize the icon and color of the
 * > object type; this icon and color will be displayed in user applications
 * > when a user views an object of this type." (`object-link-types` p.15)
 *
 * Until §705 every icon here was one or two typed characters, because "this
 * platform has no icon set" - and `object_types.icon` has defaulted to
 * `"cube"`, a name from Foundry's set, since db 0003, drawn as the type's
 * initial because nothing could draw a cube.
 *
 * **Drawn here rather than installed**: the web app's dependencies are React,
 * Next, Craft, Monaco and fonts, and an icon package of thousands to draw
 * fifty is the bloat this platform exists to leave out. Each is a few strokes
 * on a 16-unit grid, in `currentColor`, so it takes the ink of whatever it
 * sits in - white on a type's coloured mark, the text colour elsewhere.
 *
 * **Named as Foundry names them** (`cube`, `person`, `map-marker`,
 * `warning-sign` …), because the names are what is stored: an ontology
 * exported from Foundry, or a type created here before §705, already holds
 * them, and a different vocabulary would leave those drawn as initials.
 *
 * A typed glyph still works wherever it did. A value is a name only when it
 * is one of these; anything else is drawn as the characters it is.
 */

export interface IconDef {
  /** What the picker and a screen reader call it. */
  label: string;
  /** Stroked path data on a 16 × 16 grid. */
  paths: readonly string[];
}

const CIRCLE = "M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13Z";

export const ICONS = {
  cube: { label: "Cube", paths: ["M8 1.5 14 4.75v6.5L8 14.5 2 11.25v-6.5Z", "M2 4.75 8 8l6-3.25", "M8 8v6.5"] },
  person: {
    label: "Person",
    paths: ["M8 7.5a2.75 2.75 0 1 0 0-5.5 2.75 2.75 0 0 0 0 5.5Z", "M2.5 14.5c0-3 2.5-5 5.5-5s5.5 2 5.5 5"],
  },
  people: {
    label: "People",
    paths: [
      "M6 7a2.25 2.25 0 1 0 0-4.5A2.25 2.25 0 0 0 6 7Z", "M1.5 13.5c0-2.5 2-4.5 4.5-4.5s4.5 2 4.5 4.5",
      "M11 7a2 2 0 1 0 0-4", "M12 9.2c1.6.5 2.5 2 2.5 4.3",
    ],
  },
  office: {
    label: "Office",
    paths: ["M2.5 14.5v-12h7v12", "M9.5 6.5h4v8", "M1.5 14.5h13", "M4.5 5h2", "M4.5 8h2", "M4.5 11h2"],
  },
  shop: { label: "Shop", paths: ["M2.5 7v7.5h11V7", "M1.5 6.5l1.5-5h10l1.5 5Z", "M6.5 14.5v-4h3v4"] },
  home: { label: "Home", paths: ["M1.5 7.5 8 2l6.5 5.5", "M3.5 6v8.5h9V6", "M6.5 14.5v-4h3v4"] },
  document: { label: "Document", paths: ["M3.5 1.5h6l3 3v10h-9Z", "M9.5 1.5v3h3", "M5.5 8h5", "M5.5 10.5h5"] },
  "folder-close": { label: "Folder", paths: ["M1.5 3h4.5l1.5 1.5h7v9h-13Z"] },
  clipboard: { label: "Clipboard", paths: ["M4.5 2.5h-2v12h11v-12h-2", "M5.5 1.5h5v2h-5Z"] },
  briefcase: { label: "Briefcase", paths: ["M1.5 4.5h13v9h-13Z", "M5.5 4.5v-2h5v2", "M1.5 8.5h13"] },
  database: {
    label: "Database",
    paths: [
      "M2.5 3.5c0-1.1 2.5-2 5.5-2s5.5.9 5.5 2-2.5 2-5.5 2-5.5-.9-5.5-2Z",
      "M2.5 3.5v9c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2v-9", "M2.5 8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2",
    ],
  },
  "th-list": { label: "Table", paths: ["M1.5 2.5h13v11h-13Z", "M1.5 6h13", "M1.5 9.75h13", "M6 2.5v11"] },
  list: { label: "List", paths: ["M5 3.5h9.5", "M5 8h9.5", "M5 12.5h9.5", "M1.5 3.5h1", "M1.5 8h1", "M1.5 12.5h1"] },
  layers: { label: "Layers", paths: ["M8 1.5 14.5 5 8 8.5 1.5 5Z", "M1.5 8 8 11.5 14.5 8", "M1.5 11 8 14.5 14.5 11"] },
  application: { label: "Application", paths: ["M1.5 2.5h13v11h-13Z", "M1.5 5.5h13"] },
  "map-marker": {
    label: "Map marker",
    paths: ["M8 14.5s-4.5-4.6-4.5-8a4.5 4.5 0 0 1 9 0c0 3.4-4.5 8-4.5 8Z", "M8 8a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z"],
  },
  map: { label: "Map", paths: ["M1.5 3.5 5.5 2l5 1.5 4-1.5v10.5l-4 1.5-5-1.5-4 1.5Z", "M5.5 2v10.5", "M10.5 3.5V14"] },
  globe: {
    label: "Globe",
    paths: [CIRCLE, "M1.5 8h13", "M8 1.5C6 3.5 5.2 5.5 5.2 8S6 12.5 8 14.5", "M8 1.5c2 2 2.8 4 2.8 6.5S10 12.5 8 14.5"],
  },
  airplane: {
    label: "Airplane",
    paths: [
      "M8 1.5c.8 0 1.2.8 1.2 1.8V6l5.3 3v1.5L9.2 9v3l1.8 1.3v1.2L8 13.8l-3 .7v-1.2L6.8 12V9l-5.3 1.5V9l5.3-3V3.3C6.8 2.3 7.2 1.5 8 1.5Z",
    ],
  },
  truck: {
    label: "Truck",
    paths: [
      "M1.5 3.5h8v8h-8Z", "M9.5 6h3l2 2.5v3h-5",
      "M4.5 14a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z", "M11.5 14a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z",
    ],
  },
  calendar: { label: "Calendar", paths: ["M2 3.5h12v11H2Z", "M2 6.5h12", "M5 1.5v3", "M11 1.5v3"] },
  time: { label: "Time", paths: [CIRCLE, "M8 4.5V8l2.5 1.5"] },
  tag: { label: "Tag", paths: ["M1.5 1.5h6l7 7-6 6-7-7Z", "M5 5h.01"] },
  star: { label: "Star", paths: ["M8 1.5l1.9 4 4.4.5-3.3 3 .9 4.4L8 11.2l-3.9 2.2.9-4.4-3.3-3 4.4-.5Z"] },
  flag: { label: "Flag", paths: ["M3 14.5v-13", "M3 2h9l-2 3 2 3H3"] },
  bookmark: { label: "Bookmark", paths: ["M3.5 1.5h9v13L8 11l-4.5 3.5Z"] },
  heart: {
    label: "Heart",
    paths: ["M8 14S1.5 10 1.5 5.5A3.5 3.5 0 0 1 8 3.6a3.5 3.5 0 0 1 6.5 1.9C14.5 10 8 14 8 14Z"],
  },
  flash: { label: "Flash", paths: ["M9 1.5 3 9h4.5L7 14.5 13 7H8.5Z"] },
  lightbulb: {
    label: "Lightbulb",
    paths: ["M5.5 11.5h5", "M6 14.5h4", "M5.5 11.5C4 10.3 3 8.8 3 7a5 5 0 0 1 10 0c0 1.8-1 3.3-2.5 4.5"],
  },
  cloud: { label: "Cloud", paths: ["M4.5 12.5H12a3 3 0 0 0 .3-6 4.5 4.5 0 0 0-8.7.8 2.6 2.6 0 0 0 .9 5.2Z"] },
  shield: { label: "Shield", paths: ["M8 1.5 13.5 3.5v4c0 3.5-2.4 5.8-5.5 7-3.1-1.2-5.5-3.5-5.5-7v-4Z"] },
  lock: { label: "Lock", paths: ["M3 7.5h10v7H3Z", "M5 7.5V5a3 3 0 0 1 6 0v2.5"] },
  unlock: { label: "Unlock", paths: ["M3 7.5h10v7H3Z", "M5 7.5V5a3 3 0 0 1 5.8-1"] },
  key: {
    label: "Key",
    paths: ["M5 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z", "M8.5 7.5h6", "M12.5 7.5V10", "M14.5 7.5v2"],
  },
  "eye-open": {
    label: "Eye",
    paths: ["M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5Z", "M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"],
  },
  envelope: { label: "Envelope", paths: ["M1.5 3.5h13v9h-13Z", "M1.5 3.5 8 9l6.5-5.5"] },
  phone: {
    label: "Phone",
    paths: [
      "M3 1.5h3l1 3.5-2 1.2a8 8 0 0 0 4.8 4.8L11 9l3.5 1v3a1.5 1.5 0 0 1-1.5 1.5A11.5 11.5 0 0 1 1.5 3 1.5 1.5 0 0 1 3 1.5Z",
    ],
  },
  comment: { label: "Comment", paths: ["M1.5 2.5h13v9H7l-3.5 3v-3h-2Z"] },
  notifications: { label: "Notifications", paths: ["M4 11.5V7a4 4 0 0 1 8 0v4.5l1.5 1.5h-11Z", "M6.5 14.5h3"] },
  inbox: { label: "Inbox", paths: ["M1.5 9.5l2-6.5h9l2 6.5v4h-13Z", "M1.5 9.5h4l1 2h3l1-2h4"] },
  link: {
    label: "Link",
    paths: ["M6.5 9.5l3-3", "M7 4.5l1.3-1.3a2.8 2.8 0 0 1 4 4L11 8.5", "M9 11.5l-1.3 1.3a2.8 2.8 0 0 1-4-4L5 7.5"],
  },
  graph: {
    label: "Graph",
    paths: [
      "M3.5 5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z", "M12.5 6a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z",
      "M8 14a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z", "M5 3.7l6 .6", "M4.2 4.9l3.1 6.2", "M11.8 5.9l-3.1 5.3",
    ],
  },
  "timeline-line-chart": { label: "Line chart", paths: ["M1.5 1.5v13h13", "M3.5 11l3-4 3 2 4.5-5.5"] },
  "timeline-bar-chart": { label: "Bar chart", paths: ["M1.5 14.5h13", "M3.5 14.5v-5", "M6.5 14.5v-9", "M9.5 14.5v-7", "M12.5 14.5v-11"] },
  "pie-chart": { label: "Pie chart", paths: [CIRCLE, "M8 1.5V8h6.5"] },
  dashboard: { label: "Dashboard", paths: ["M1.5 11.5a6.5 6.5 0 0 1 13 0", "M8 11.5l3-3.5", "M1.5 14h13"] },
  dollar: { label: "Dollar", paths: ["M8 1v14", "M11.5 4h-5a2 2 0 0 0 0 4h3a2 2 0 0 1 0 4h-5"] },
  cog: {
    label: "Cog",
    paths: [
      "M8 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
      "M8 1.5v2", "M8 12.5v2", "M1.5 8h2", "M12.5 8h2",
      "M3.4 3.4l1.4 1.4", "M11.2 11.2l1.4 1.4", "M3.4 12.6l1.4-1.4", "M11.2 4.8l1.4-1.4",
    ],
  },
  search: { label: "Search", paths: ["M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z", "M10.5 10.5l4 4"] },
  filter: { label: "Filter", paths: ["M1.5 2.5h13L9.5 8.5v5l-3 1.5v-6.5Z"] },
  edit: { label: "Edit", paths: ["M10.5 2.5l3 3-8 8-3.5.5.5-3.5Z", "M9 4l3 3"] },
  trash: {
    label: "Trash",
    paths: ["M2 4h12", "M6 4V2h4v2", "M3.5 4l1 10.5h7l1-10.5", "M6.5 7v5", "M9.5 7v5"],
  },
  download: { label: "Download", paths: ["M8 1.5v9", "M4.5 7 8 10.5 11.5 7", "M2 14.5h12"] },
  upload: { label: "Upload", paths: ["M8 10.5v-9", "M4.5 5 8 1.5 11.5 5", "M2 14.5h12"] },
  refresh: { label: "Refresh", paths: ["M13.5 2.5V6H10", "M13.3 6A5.5 5.5 0 1 0 13.5 10"] },
  plus: { label: "Plus", paths: ["M8 2.5v11", "M2.5 8h11"] },
  minus: { label: "Minus", paths: ["M2.5 8h11"] },
  tick: { label: "Tick", paths: ["M2 8.5l4 4L14 4"] },
  "tick-circle": { label: "Tick circle", paths: [CIRCLE, "M5 8.2l2 2L11 6"] },
  cross: { label: "Cross", paths: ["M3 3l10 10", "M13 3 3 13"] },
  "ban-circle": { label: "Banned", paths: [CIRCLE, "M3.4 3.4l9.2 9.2"] },
  "warning-sign": { label: "Warning", paths: ["M8 1.5 15 14H1Z", "M8 6v4", "M8 12v.01"] },
  error: { label: "Error", paths: [CIRCLE, "M5.5 5.5l5 5", "M10.5 5.5l-5 5"] },
  "info-sign": { label: "Info", paths: [CIRCLE, "M8 7v4.5", "M8 4.75v.01"] },
  medical: { label: "Medical", paths: ["M6 1.5h4V6h4.5v4H10v4.5H6V10H1.5V6H6Z"] },
} as const satisfies Record<string, IconDef>;

export type IconName = keyof typeof ICONS;

export const ICON_NAMES = Object.keys(ICONS) as IconName[];

/** The icon a stored value names, or null when it names none - a typed
 * glyph, a blank, or a name from Foundry's set that is not one of these. */
export function iconNamed(value: unknown): IconDef | null {
  if (typeof value !== "string") return null;
  const name = value.trim();
  return Object.hasOwn(ICONS, name) ? ICONS[name as IconName] : null;
}
