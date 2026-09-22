"use client";

/**
 * p.20's personal editor preferences, on the screen (§432).
 *
 * The rules are in `lib/editor-preferences.ts`. What is here is the part that
 * touches a browser: reading and writing `localStorage`, and the controls.
 *
 * **One hook, so there is one reader.** The Settings tab writes these and the
 * editor reads them, and they are in different tabs of the same application —
 * two components each doing their own `JSON.parse(localStorage.getItem(...))`
 * would be two chances to disagree about what an unreadable value means.
 */

import { useCallback, useEffect, useState } from "react";
import type { EditorPreferences } from "@/lib/editor-preferences";
import {
  DEFAULTS,
  FONT_SIZES,
  SCOPE_NOTE,
  STORAGE_KEY,
  TAB_SIZES,
  isDefault,
  read,
  write,
} from "@/lib/editor-preferences";

/** The preferences in force, and a way to change them. */
export function useEditorPreferences(): [
  EditorPreferences,
  (next: EditorPreferences) => void,
] {
  // **Starts at the defaults and reads storage in an effect**, not during the
  // first render: this component renders on the server too, where there is no
  // `localStorage`, and a first paint that disagreed with the second is a
  // hydration mismatch React resolves by throwing the page away.
  const [preferences, setPreferences] = useState<EditorPreferences>(DEFAULTS);

  useEffect(() => {
    try {
      setPreferences(read(window.localStorage.getItem(STORAGE_KEY)));
    } catch {
      // Storage can be unavailable outright - a private window, a browser
      // configured to refuse it. The defaults are already in state, and an
      // editor that works is worth more than a preference that was never set.
    }
  }, []);

  const change = useCallback((next: EditorPreferences) => {
    setPreferences(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, write(next));
    } catch {
      // Same again: the change is in force for this session either way, which
      // is the honest half of what was asked for.
    }
  }, []);

  return [preferences, change];
}

export function EditorPreferencesSection() {
  const [preferences, change] = useEditorPreferences();

  return (
    <section className="repo-settings-personal" data-testid="editor-preferences">
      {/* p.20's own division: "code authors can configure their personal
          editor preferences and repository administrators can control the
          repository's behavior and policies". Two kinds of setting under one
          heading is how somebody comes to think their font size is a
          governance decision. */}
      <p className="field-label">Your editor</p>
      <p className="login-note" data-testid="editor-preferences-scope">
        {SCOPE_NOTE}
      </p>

      <div className="repo-settings-fields">
        <label>
          Font size
          <select
            data-testid="pref-font-size"
            value={String(preferences.fontSize)}
            onChange={(e) =>
              change({ ...preferences, fontSize: Number(e.target.value) })
            }
          >
            {FONT_SIZES.map((size) => (
              <option key={size} value={String(size)}>
                {size}
              </option>
            ))}
          </select>
        </label>

        <label>
          Tab size
          <select
            data-testid="pref-tab-size"
            value={String(preferences.tabSize)}
            onChange={(e) =>
              change({ ...preferences, tabSize: Number(e.target.value) })
            }
          >
            {TAB_SIZES.map((size) => (
              <option key={size} value={String(size)}>
                {size}
              </option>
            ))}
          </select>
        </label>

        <label className="repo-settings-check">
          <input
            type="checkbox"
            data-testid="pref-minimap"
            checked={preferences.minimap}
            onChange={(e) => change({ ...preferences, minimap: e.target.checked })}
          />
          <span>Minimap</span>
        </label>

        <label className="repo-settings-check">
          <input
            type="checkbox"
            data-testid="pref-word-wrap"
            checked={preferences.wordWrap}
            onChange={(e) => change({ ...preferences, wordWrap: e.target.checked })}
          />
          <span>Wrap long lines</span>
        </label>
      </div>

      <button
        type="button"
        className="btn quiet"
        data-testid="pref-reset"
        // Disabled rather than hidden: a Reset that came and went as somebody
        // changed things is a control nobody learns is there.
        disabled={isDefault(preferences)}
        onClick={() => change(DEFAULTS)}
      >
        Reset to defaults
      </button>
    </section>
  );
}
