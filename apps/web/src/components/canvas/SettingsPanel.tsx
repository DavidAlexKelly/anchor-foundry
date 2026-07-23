"use client";

import { useEditor } from "@craftjs/core";

/** Renders the selected node's own `related.settings` component (registered
 * per-widget via `.craft.related.settings` in widgets.tsx) — the standard
 * Craft.js pattern for a props-editing sidebar that doesn't need to know
 * about every widget type itself. */
export function SettingsPanel() {
  const { selected } = useEditor((state) => {
    const currentNodeId = [...state.events.selected][0];
    if (!currentNodeId || !state.nodes[currentNodeId]) return { selected: null };
    const node = state.nodes[currentNodeId];
    return {
      selected: {
        id: currentNodeId,
        displayName: node.data.displayName,
        settings: node.related?.settings,
        isDeletable: currentNodeId !== "ROOT",
      },
    };
  });
  const { actions } = useEditor();

  if (!selected) {
    return <p className="canvas-widget-empty">Select a widget to edit its settings.</p>;
  }

  return (
    <div>
      <div className="canvas-settings-head">
        <strong>{selected.displayName}</strong>
        {selected.isDeletable && (
          <button
            type="button"
            className="btn danger"
            style={{ padding: "3px 9px", fontSize: 12 }}
            onClick={() => actions.delete(selected.id)}
          >
            Delete
          </button>
        )}
      </div>
      {selected.settings ? <selected.settings /> : <p className="canvas-widget-empty">No settings for this widget.</p>}
    </div>
  );
}
