/**
 * p.20's personal editor preferences (§432; `code-repositories` p.20).
 *
 * > "In the Settings tab, code authors can configure their personal editor
 * > preferences and repository administrators can control the repository's
 * > behavior and policies."
 *
 * **p.20 draws a line and the tab has to draw it too.** Until now the Settings
 * tab held one setting and it was the administrative kind: `require_code_review`
 * is the project's, it is shared, and changing it changes how everybody's work
 * lands. A personal preference is the opposite in every way that matters — it
 * is mine, nobody else sees it, and it changes nothing about what runs. Two
 * settings of those two kinds under one heading is how somebody comes to think
 * their font size is a governance decision, or worse, the other way round.
 *
 * ---
 *
 * **Kept in this browser, and that is the scope rather than a compromise.**
 * These are about the machine you are typing on: a 13-inch laptop and a
 * 27-inch monitor want different font sizes, and a preference that followed
 * the account would be wrong on one of them the moment it was right on the
 * other. The screen says where they live, in the same words the drafts note
 * uses (§281), because a setting that silently fails to follow somebody to
 * another machine is worse than one that says it will not.
 *
 * **Every value is validated on the way in.** `localStorage` is a string
 * somebody can edit, an older version of this application can have written,
 * and a future one can have moved on from. A field that does not parse falls
 * back to its own default rather than taking the rest of the preferences with
 * it — losing four settings because one is unreadable is the failure mode a
 * blanket try/catch produces (§210).
 */

export interface EditorPreferences {
  /** Monaco's `fontSize`. */
  fontSize: number;
  /** Monaco's `minimap.enabled`. Off by default: this editor's files are a
   *  screen long and a minimap of forty lines is decoration. */
  minimap: boolean;
  /** Monaco's `wordWrap`. Off by default, because a SQL transform's lines are
   *  short and wrapping hides the shape of a long `CASE`. */
  wordWrap: boolean;
  /** Monaco's `tabSize`. */
  tabSize: number;
}

export const DEFAULTS: EditorPreferences = {
  // The value `code-editor.tsx` has had since it was written. **Defined here
  // now**, so the editor and this screen cannot disagree about what "default"
  // means (§292) — a Reset button that returned a font size the editor had
  // never used would be the more embarrassing of the two ways that goes wrong.
  fontSize: 12.5,
  minimap: false,
  wordWrap: false,
  tabSize: 2,
};

/** The sizes offered. A range rather than a free number: a text box lets
 *  somebody type 400 and lose the editor, and a preference you can break is
 *  not a preference. */
export const FONT_SIZES = [11, 12.5, 14, 16, 18] as const;
export const TAB_SIZES = [2, 4, 8] as const;

export const STORAGE_KEY = "anchor.editor.preferences";

function oneOf<T extends number>(
  value: unknown, allowed: readonly T[], fallback: T,
): T {
  return typeof value === "number" && (allowed as readonly number[]).includes(value)
    ? (value as T)
    : fallback;
}

/**
 * A stored boolean, or the default.
 *
 * **Exported so its contract can be checked.** `typeof value === "boolean"`
 * rather than `value === true` is a distinction between *false* and *unset*,
 * and neither preference here defaults to `true` — so through `read` the two
 * spellings behave identically and a mutation sweep proved it. The difference
 * appears the day a default flips, which is exactly when a stored `false`
 * being ignored would be hardest to find. Tested directly instead of waiting
 * for that day.
 */
export function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

/**
 * Preferences from whatever was stored, with every field answered.
 *
 * Takes the raw string rather than reading `localStorage` itself, so a test
 * can hand it the strings a browser cannot be persuaded to hold: a truncated
 * write, a value from a version that offered a font size this one does not,
 * somebody's idea of a joke.
 */
export function read(raw: string | null): EditorPreferences {
  let parsed: unknown = null;
  try {
    parsed = raw === null ? null : JSON.parse(raw);
  } catch {
    parsed = null;
  }
  // `?? {}` and nothing more: reading a property off a number or a string
  // yields `undefined` rather than throwing, so every field falls back on its
  // own anyway. The `typeof parsed === "object"` check that was here made no
  // input behave differently, which a sweep is how you find out (§223).
  const from = (parsed ?? {}) as Record<string, unknown>;
  return {
    fontSize: oneOf(from.fontSize, FONT_SIZES, DEFAULTS.fontSize),
    minimap: bool(from.minimap, DEFAULTS.minimap),
    wordWrap: bool(from.wordWrap, DEFAULTS.wordWrap),
    tabSize: oneOf(from.tabSize, TAB_SIZES, DEFAULTS.tabSize),
  };
}

/** What to store. Every field, always — a partial blob would make "unset" and
 *  "set to the default" the same thing, and the day a default changes those
 *  two want opposite answers (§210). */
export function write(preferences: EditorPreferences): string {
  return JSON.stringify(preferences);
}

/** Whether these are the defaults, which is what the Reset control asks. */
export function isDefault(preferences: EditorPreferences): boolean {
  return (
    preferences.fontSize === DEFAULTS.fontSize
    && preferences.minimap === DEFAULTS.minimap
    && preferences.wordWrap === DEFAULTS.wordWrap
    && preferences.tabSize === DEFAULTS.tabSize
  );
}

/**
 * The options the editor takes.
 *
 * **One writer of this mapping.** `code-editor.tsx` had these four values
 * written into its `options` literal; if this screen set them separately, the
 * two would drift the first time either changed — and the drift would be
 * invisible, because both would look right on their own.
 */
export function monacoOptions(preferences: EditorPreferences): {
  fontSize: number;
  minimap: { enabled: boolean };
  wordWrap: "on" | "off";
  tabSize: number;
} {
  return {
    fontSize: preferences.fontSize,
    minimap: { enabled: preferences.minimap },
    wordWrap: preferences.wordWrap ? "on" : "off",
    tabSize: preferences.tabSize,
  };
}

/** Where these live, in the words the drafts note uses — the same promise and
 *  the same limitation, so the two read as one policy rather than two. */
export const SCOPE_NOTE =
  "Kept in this browser. These follow the machine you are typing on rather "
  + "than your account, so another computer starts from the defaults.";
