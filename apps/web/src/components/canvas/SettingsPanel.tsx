"use client";

import { useEditor } from "@craftjs/core";

/** Renders the selected node's own `related.settings` component (registered
 * per-widget via `.craft.related.settings` in widgets.tsx) - the standard
 * Craft.js pattern for a props-editing sidebar that doesn't need to know
 * about every widget type itself.
 *
 * It also carries the widget's position (ROADMAP Canvas item 6). Craft.js
 * gives dragging a placed widget for free, but native HTML5 drag-and-drop is
 * the one canvas interaction that cannot be driven by automation (STATUS's
 * rough edges), *and* it is the one interaction a keyboard cannot do at all.
 * Two buttons are worth having for both reasons: they are testable, and they
 * are the only way to reorder an app without a mouse.
 */
export function SettingsPanel() {
  const { selected } = useEditor((state) => {
    const currentNodeId = [...state.events.selected][0];
    if (!currentNodeId || !state.nodes[currentNodeId]) return { selected: null };
    const node = state.nodes[currentNodeId];
    const parentId = node.data.parent;
    const siblings = parentId ? state.nodes[parentId]?.data.nodes ?? [] : [];
    const index = siblings.indexOf(currentNodeId);
    return {
      selected: {
        id: currentNodeId,
        displayName: node.data.displayName,
        settings: node.related?.settings,
        isDeletable: currentNodeId !== "ROOT",
        parentId,
        index,
        siblingCount: siblings.length,
      },
    };
  });
  const { actions } = useEditor();

  if (!selected) {
    return <p className="canvas-widget-empty">Select a widget to edit its settings.</p>;
  }

  const { parentId, index, siblingCount } = selected;
  const canMove = !!parentId && index >= 0 && siblingCount > 1;

  // Craft's `move` inserts at an index in the parent's *current* list, before
  // the node has been taken out of it - so moving down by one is index + 2,
  // not index + 1. Verified in a browser rather than assumed; the off-by-one
  // is silent (the widget stays put) if you get it wrong.
  const moveTo = (target: number) => {
    if (parentId) actions.move(selected.id, parentId, target);
  };

  return (
    <div>
      <div className="canvas-settings-head">
        <strong>{selected.displayName}</strong>
        <div className="row-actions">
          {canMove && (
            <>
              <button
                type="button"
                className="btn quiet"
                style={{ padding: "3px 9px", fontSize: 12 }}
                disabled={index === 0}
                aria-label="Move up"
                onClick={() => moveTo(index - 1)}
              >
                ↑
              </button>
              <button
                type="button"
                className="btn quiet"
                style={{ padding: "3px 9px", fontSize: 12 }}
                disabled={index === siblingCount - 1}
                aria-label="Move down"
                onClick={() => moveTo(index + 2)}
              >
                ↓
              </button>
            </>
          )}
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
      </div>
      {selected.settings ? <selected.settings /> : <p className="canvas-widget-empty">No settings for this widget.</p>}
    </div>
  );
}
