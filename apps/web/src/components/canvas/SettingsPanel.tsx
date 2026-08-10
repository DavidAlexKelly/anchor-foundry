"use client";

import { useEditor, useNode } from "@craftjs/core";
import { useState } from "react";

/** The selected widget's configuration, in Foundry's three tabs (p.65–68).
 *
 * Previously one flat list of whatever the widget's own `related.settings`
 * offered. Foundry splits it three ways, and the split is not cosmetic — it
 * says what kind of statement each control is:
 *
 * - **Widget setup** — "the input and output variables of a widget … as well
 *   as any additional configuration and display options" (p.65). This is the
 *   per-widget panel we already had, unchanged.
 * - **Metadata** — rename, and the raw JSON (p.67–68).
 * - **Display** — sizing only: Auto (max), Absolute, Flex (p.68).
 *
 * The head above the tabs — move up, move down, delete — stays outside them.
 * It acts on the widget's place in the document rather than on its
 * configuration, and burying a delete button inside a tab is a good way to
 * make it unfindable.
 */

type Tab = "setup" | "metadata" | "display";

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
  const [tab, setTab] = useState<Tab>("setup");

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

      <div className="canvas-settings-tabs" role="tablist">
        {(
          [
            ["setup", "Widget setup"],
            ["metadata", "Metadata"],
            ["display", "Display"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`canvas-settings-tab${tab === key ? " is-active" : ""}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="canvas-settings-body">
        {tab === "setup" &&
          (selected.settings ? (
            <selected.settings />
          ) : (
            <p className="canvas-widget-empty">No settings for this widget.</p>
          ))}
        {tab === "metadata" && <MetadataTab id={selected.id} />}
        {tab === "display" && <DisplayTab id={selected.id} />}
      </div>
    </div>
  );
}

/** Rename, and the raw JSON (p.67–68).
 *
 * > "The Raw Widget Configuration displays how the current widget's setup is
 * > stored in JSON and offers advanced module builders the option to quickly
 * > view, edit, or copy this configuration in its raw format."
 *
 * **This is the cheapest high-value item in the parity spec** (`workshop.md`
 * §2) and the reason is worth restating: we already persist `format: 2`
 * documents, so every widget option Foundry has and we have not built a form
 * for is *survivable* rather than blocking. Someone can set it here.
 */
function MetadataTab({ id }: { id: string }) {
  const { actions, props, name } = useEditor((state) => ({
    props: state.nodes[id]?.data.props ?? {},
    name: (state.nodes[id]?.data.custom as { displayName?: string } | undefined)?.displayName ?? "",
  }));
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const current = JSON.stringify(props, null, 2);
  const text = draft ?? current;

  function apply() {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      // Reported, never swallowed. A raw editor that silently discarded a
      // malformed edit would lose work with no way to tell it had.
      setError(e instanceof Error ? e.message : "That is not valid JSON.");
      return;
    }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      setError("A widget's configuration is an object of prop names to values.");
      return;
    }
    setError(null);
    actions.setProp(id, (p: Record<string, unknown>) => {
      // Replace rather than merge: what is on screen *is* the configuration,
      // so a prop deleted in the editor has to actually go. Merging would make
      // deletion impossible and the editor would be lying about what it shows.
      for (const key of Object.keys(p)) delete p[key];
      Object.assign(p, parsed as Record<string, unknown>);
    });
    setDraft(null);
  }

  return (
    <>
      <label className="field">
        <span className="field-label">Widget name</span>
        <input
          type="text"
          value={name}
          data-testid="widget-name"
          placeholder="Its default name"
          onChange={(e) =>
            actions.setCustom(id, (custom: { displayName?: string }) => {
              // Empty means "no override", not "named empty string" - otherwise
              // clearing the box leaves a widget with no name at all in the
              // Layout panel.
              if (e.target.value.trim()) custom.displayName = e.target.value;
              else delete custom.displayName;
            })
          }
        />
        {/* p.68. The second half does not apply to us yet and saying so is
            better than implying it does: we do not generate variable names
            from widget names. */}
        <span className="field-hint">
          Changes how it is referenced in the Layout panel.
        </span>
      </label>

      <label className="field">
        <span className="field-label">Raw widget configuration</span>
        <textarea
          className="canvas-raw-json"
          value={text}
          spellCheck={false}
          rows={12}
          data-testid="widget-raw-json"
          onChange={(e) => setDraft(e.target.value)}
        />
      </label>
      {error && (
        <p className="canvas-raw-json-error" role="alert">
          {error}
        </p>
      )}
      <div className="row-actions">
        <button type="button" className="btn" onClick={apply} disabled={draft === null}>
          Apply
        </button>
        <button
          type="button"
          className="btn quiet"
          onClick={() => {
            setDraft(null);
            setError(null);
          }}
          disabled={draft === null}
        >
          Revert
        </button>
      </div>
    </>
  );
}

/** Sizing, and only sizing (p.68).
 *
 * > "The Display tab enables configuration of the size of the current widget
 * > and allows module builders to switch between Auto (max), Absolute, and
 * > Flex sizing."
 *
 * **Height, deliberately.** Foundry's own description is height-first and it
 * says why: Auto (max) "is not available for setting the width of widgets in a
 * column layout". Per-widget *width* in this app is already a solved problem
 * with a different mechanism — a section distributes width to its children by
 * weight, adjustable by dragging the handle between them. Adding a second,
 * per-widget width control would put two numbers in charge of one dimension
 * and no rule for which wins, so it is not built and this says so rather than
 * leaving somebody to find out.
 */
function DisplayTab({ id }: { id: string }) {
  const { actions, display } = useEditor((state) => ({
    display:
      ((state.nodes[id]?.data.custom as { display?: DisplayConfig } | undefined)?.display ??
        { mode: "auto" }) as DisplayConfig,
  }));

  const set = (next: DisplayConfig) =>
    actions.setCustom(id, (custom: { display?: DisplayConfig }) => {
      // "auto" with no maximum is the default, so it is stored as *absent*
      // rather than as a value. A document that records every default is a
      // document whose diffs are mostly noise.
      if (next.mode === "auto" && !next.max) delete custom.display;
      else custom.display = next;
    });

  return (
    <>
      <label className="field">
        <span className="field-label">Sizing</span>
        <select
          value={display.mode}
          data-testid="display-mode"
          onChange={(e) => set({ ...display, mode: e.target.value as DisplayMode })}
        >
          <option value="auto">Auto (max)</option>
          <option value="absolute">Absolute</option>
          <option value="flex">Flex</option>
        </select>
      </label>

      {display.mode === "auto" && (
        <label className="field">
          <span className="field-label">Maximum height (px)</span>
          <input
            type="number"
            min={0}
            value={display.max ?? ""}
            data-testid="display-max"
            placeholder="No maximum"
            onChange={(e) =>
              set({ mode: "auto", max: e.target.value ? Number(e.target.value) : undefined })
            }
          />
          <span className="field-hint">
            Grows with its contents, then scrolls. Blank means no limit.
          </span>
        </label>
      )}

      {display.mode === "absolute" && (
        <label className="field">
          <span className="field-label">Height (px)</span>
          <input
            type="number"
            min={0}
            value={display.height ?? ""}
            data-testid="display-height"
            onChange={(e) =>
              set({ mode: "absolute", height: e.target.value ? Number(e.target.value) : undefined })
            }
          />
        </label>
      )}

      {display.mode === "flex" && (
        <label className="field">
          <span className="field-label">Ratio</span>
          <input
            type="number"
            min={0}
            step={0.5}
            value={display.grow ?? 1}
            data-testid="display-grow"
            onChange={(e) => set({ mode: "flex", grow: Number(e.target.value) })}
          />
          <span className="field-hint">
            Its share of the height, relative to other widgets in the same rows
            section. Nothing to share in a column, so it has no effect there.
          </span>
        </label>
      )}
    </>
  );
}

export type DisplayMode = "auto" | "absolute" | "flex";

export interface DisplayConfig {
  mode: DisplayMode;
  /** `auto` only: the max height it grows to before scrolling. */
  max?: number;
  /** `absolute` only. */
  height?: number;
  /** `flex` only. */
  grow?: number;
}

/** The style a display config resolves to, kept beside the editor that writes
 * it so the two cannot describe different things.
 *
 * Returns `null` for the default, which is what lets the node wrapper render
 * nothing at all rather than an inert `<div>` around every widget in the
 * module — an extra element in a flex chain is not free.
 */
export function displayStyle(display: DisplayConfig | undefined): React.CSSProperties | null {
  if (!display) return null;
  if (display.mode === "absolute" && display.height) {
    return { height: display.height, overflow: "auto", minHeight: 0 };
  }
  if (display.mode === "flex") {
    return { flexGrow: display.grow ?? 1, flexBasis: 0, overflow: "auto", minHeight: 0 };
  }
  if (display.mode === "auto" && display.max) {
    return { maxHeight: display.max, overflow: "auto" };
  }
  return null;
}

/** Wraps every Craft node, so sizing is applied in one place instead of in
 * each of the twenty-odd widgets.
 *
 * Passed to `<Editor onRender>`, which is Craft's supported hook for exactly
 * this. **It returns `render` untouched when there is no sizing to apply**,
 * which is the common case — so a module that configures none is rendered
 * exactly as it was before this existed, with no extra elements in any flex
 * chain to change how anything lays out.
 */
export function CanvasNode({ render }: { render: React.ReactElement }) {
  const { display } = useNode((node) => ({
    display: (node.data.custom as { display?: DisplayConfig } | undefined)?.display,
  }));
  const style = displayStyle(display);
  if (!style) return render;
  return (
    <div className="canvas-sized" data-sizing={display?.mode} style={style}>
      {render}
    </div>
  );
}
