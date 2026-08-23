"use client";

import { useEditor } from "@craftjs/core";

import type { WorkshopEvent, WorkshopModule, WorkshopVariable } from "@/lib/types";
import { newEventId, newNodeId, newVariableId } from "@/lib/workshop-module";
import { clip, paste, pasteTarget, withoutSubtree } from "./clipboard";
import type { Clipping, PasteMode } from "./clipboard";

type StateSavingSettings = NonNullable<WorkshopModule["state_saving"]>;

/**
 * The Layout sidebar (roadmap phase 2, item 1.4).
 *
 * Foundry edits layout elements "from a Layout sidebar panel or by selecting
 * them in the module view". Both, not either: selecting in the view is the
 * fast path for a widget you can see, and the tree is the only way to reach
 * a node the view cannot offer you.
 *
 * **It is the answer to a structural problem, not a convenience.** A section
 * is filled by its children, and a page by its sections, so a container has
 * no pixels of its own to click - §78 had to give sections a builder label
 * just to make their settings reachable, and that trick does not generalise
 * to a container three levels down or to an empty one. A tree does: every
 * node in the document has exactly one row, whether or not it has any area.
 *
 * **The tree is read from the editor's own state, never duplicated.** Craft's
 * node map *is* the layout (decision 0002), so this panel holds no state of
 * its own and cannot disagree with what is being edited.
 */

/** Craft's node map, walked into rows. Depth is carried rather than nested so
 * that the whole thing is one flat list to render, and one keyboard sequence
 * to move through - a nested <ul> would read as a list of lists to a screen
 * reader for no gain, since the indent is the only nesting the eye needs. */
interface Row {
  id: string;
  depth: number;
  label: string;
  /** What distinguishes this node from its siblings — a page's title, a
   * section's direction. Without it a page of four sections is four
   * identical rows. */
  detail: string;
}

/** The prop worth showing beside a node's type, by node type. Widgets that
 * have nothing distinguishing (a chart is a chart) get their bound variable,
 * which is the thing an author is usually looking for. */
function detailOf(displayName: string, props: Record<string, unknown>): string {
  const first = (...keys: string[]): string => {
    for (const key of keys) {
      const value = props[key];
      if (typeof value === "string" && value.trim()) return value.trim();
    }
    return "";
  };
  if (displayName === "Section") {
    const direction = first("direction") || "columns";
    const weights = first("weights");
    return weights ? `${direction} · ${weights}` : direction;
  }
  return first("title", "label", "text", "name", "objectSetVariable", "datasetId").slice(0, 28);
}

export function LayoutPanel({
  routing,
  onRoutingChange,
  pageSelection = "",
  onPageSelectionChange,
  stringVariables = [],
  clipboard = null,
  onClipboardChange,
  variables = {},
  onVariablesChange,
  events = {},
  onEventsChange,
  stateSaving,
  onStateSavingChange,
}: {
  /** Whether this module writes its state to the URL (p.195). Here because
   * Foundry puts it in "the Pages section of the Settings panel" and the
   * layout tree is where our pages live — a routing switch on a panel that
   * never mentions pages would be a switch nobody finds. */
  routing?: boolean;
  onRoutingChange?: (next: boolean) => void;
  /** Variable-Based Page Selection (p.81): the id of the string variable whose
   * value is the page ID of the page showing, or "" for none. Here for
   * routing's reason and one more — it is the second setting on this panel
   * that decides which page a reader sees, and the two have to be read
   * together to be understood. */
  pageSelection?: string;
  onPageSelectionChange?: (next: string) => void;
  /** The module's string variables, which is all p.81 allows. */
  stringVariables?: { id: string; label: string }[];
  /** Cut / copy / paste (p.55). The whole document's variables and events,
   * not just the string ones: a clipping carries the definitions of whatever
   * the copied subtree references, and a paste can add to both.
   *
   * Here rather than on the widget settings panel because p.55 calls these
   * "the controls found for duplicating sections" (p.69), and because a
   * *paste* needs a target, which is a question about the layout tree rather
   * than about the selected widget. */
  clipboard?: Clipping | null;
  onClipboardChange?: (next: Clipping | null) => void;
  variables?: Record<string, WorkshopVariable>;
  onVariablesChange?: (next: Record<string, WorkshopVariable>) => void;
  events?: Record<string, WorkshopEvent>;
  onEventsChange?: (next: Record<string, WorkshopEvent>) => void;
  /** State saving (p.201's step 1, p.204's options). Beside routing because
   * Foundry puts both in the same Settings panel, and because they are the two
   * module-wide switches an author sets once. */
  stateSaving?: StateSavingSettings;
  onStateSavingChange?: (next: StateSavingSettings) => void;
} = {}) {
  const { rows, selectedId } = useEditor((state) => {
    const walk = (id: string, depth: number, out: Row[]): Row[] => {
      const node = state.nodes[id];
      if (!node) return out;
      // ROOT is the document itself; it has no settings anybody edits and a
      // row for it would only add an indent level to everything below.
      if (id !== "ROOT") {
        // A rename from the Metadata tab wins over the widget's type name.
        // p.68: renaming "will affect how the current widget is referenced
        // through Workshop, most notably as a component in the Layout panel",
        // which is this list - so a rename nothing here read would be a
        // control that visibly does nothing.
        const renamed = (node.data.custom as { displayName?: string } | undefined)?.displayName;
        out.push({
          id,
          depth,
          label: renamed || node.data.displayName || node.data.name,
          // The *detail* still keys off the type name: it says what kind of
          // thing this is ("Section, 2 columns"), and reading a custom name
          // there would make it say nothing at all once one was set.
          detail: detailOf(node.data.displayName || "", node.data.props ?? {}),
        });
      }
      for (const child of node.data.nodes ?? []) walk(child, id === "ROOT" ? 0 : depth + 1, out);
      return out;
    };
    return {
      rows: walk("ROOT", 0, []),
      selectedId: [...state.events.selected][0] ?? null,
    };
  });
  const { actions, query } = useEditor();

  // p.55's cut / copy / paste. **Both halves go through the serialised map**,
  // not through Craft's node-tree API: the layout *is* that map (decision
  // 0002), the transforms are in one tested pure module, and cut is then one
  // atomic edit rather than a copy followed by a separate delete that could
  // land without it.
  const clipboardEnabled = Boolean(onClipboardChange && onVariablesChange && onEventsChange);
  const labelOf = (id: string) =>
    rows.find((row) => row.id === id)?.label ?? "widget";

  const take = (andRemove: boolean) => {
    if (!selectedId) return;
    const layout = query.getSerializedNodes() as Record<string, unknown>;
    const clipping = clip(layout, variables, events, selectedId, labelOf(selectedId));
    if (!clipping) return;
    onClipboardChange?.(clipping);
    if (andRemove) actions.deserialize(withoutSubtree(layout, selectedId) as never);
  };

  const drop = (mode: PasteMode) => {
    if (!clipboard) return;
    const layout = query.getSerializedNodes() as Record<string, unknown>;
    const into = pasteTarget(layout, selectedId);
    if (!into) return;
    const next = paste(layout, variables, events, clipboard, {
      into, mode,
      mintNode: newNodeId, mintVariable: newVariableId, mintEvent: newEventId,
    });
    // Variables and events first: `deserialize` re-renders the tree, and a
    // widget that mounted before its new variable existed would read as
    // unbound for a frame and log a binding warning for a variable that is
    // about to arrive.
    onVariablesChange?.(next.variables);
    onEventsChange?.(next.events);
    actions.deserialize(next.layout as never);
  };

  const select = (id: string) => {
    actions.selectNode(id);
    // A tree row for a node scrolled out of view would select something the
    // author cannot see, which reads as nothing having happened.
    try {
      query.node(id).get().dom?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch {
      /* a node with no DOM yet - selecting it is still right */
    }
  };

  return (
    <div className="canvas-layout-tree">
      <p className="field-label">Layout</p>
      {rows.length === 0 && (
        <p className="canvas-widget-empty">Nothing here yet — drag a widget in.</p>
      )}
      {rows.map((row) => (
        <button
          key={row.id}
          type="button"
          className={`canvas-tree-row${row.id === selectedId ? " on" : ""}`}
          style={{ paddingLeft: 8 + row.depth * 12 }}
          aria-current={row.id === selectedId}
          onClick={() => select(row.id)}
        >
          <span className="canvas-tree-label">{row.label}</span>
          {row.detail && <span className="canvas-tree-detail">{row.detail}</span>}
        </button>
      ))}
      {clipboardEnabled && (
        <div className="canvas-clipboard">
          <div className="canvas-clipboard-row">
            <button
              type="button" className="btn" data-testid="clip-copy"
              disabled={!selectedId || selectedId === "ROOT"}
              onClick={() => take(false)}
            >
              Copy
            </button>
            <button
              type="button" className="btn" data-testid="clip-cut"
              disabled={!selectedId || selectedId === "ROOT"}
              onClick={() => take(true)}
            >
              Cut
            </button>
          </div>
          {/* p.55 offers two pastes rather than a paste and a setting, and the
              difference is worth two buttons: an author about to paste knows
              which one they mean, and would have to go and find a toggle
              otherwise. */}
          <div className="canvas-clipboard-row">
            <button
              type="button" className="btn" data-testid="clip-paste-same"
              disabled={!clipboard}
              onClick={() => drop("same")}
            >
              Paste
            </button>
            <button
              type="button" className="btn" data-testid="clip-paste-duplicate"
              disabled={!clipboard}
              onClick={() => drop("duplicate")}
            >
              Paste as a copy
            </button>
          </div>
          <p className="canvas-widget-empty" data-testid="clip-state">
            {clipboard
              ? `Holding ${clipboard.label}. "Paste" reuses its variables; `
                + `"Paste as a copy" makes new ones.`
              : "Select a widget or section, then Copy."}
          </p>
        </div>
      )}
      {onRoutingChange && (
        <label className="vars-toggle">
          <input
            type="checkbox"
            checked={!!routing}
            data-testid="routing-toggle"
            onChange={(e) => onRoutingChange(e.target.checked)}
          />
          Write state to the URL
        </label>
      )}
      {onPageSelectionChange && (
        <label className="field">
          <span className="field-label">Page from a variable</span>
          <select
            value={pageSelection}
            data-testid="page-selection"
            onChange={(e) => onPageSelectionChange(e.target.value)}
          >
            <option value="">Pages are chosen by events only</option>
            {stringVariables.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
          {/* p.81's gotcha, said here rather than left to be met as a bug:
              "the value of this variable will not be updated as a result of a
              Switch to Page event". Somebody who wires both and expects them
              to stay in step has no way to discover otherwise from the
              screen. */}
          <span className="field-hint">
            Its value is a page ID. A Switch-to-page event moves the reader
            without writing it back — use a Set variable value event too if
            you need them in step.
          </span>
          {/* A `<select>` whose value matches no option renders blank, which
              reads as "none" and is the opposite of the truth: the document
              still names a variable, and the server will refuse the next save
              for it. Named here so the refusal is not the first anyone hears
              of it. */}
          {pageSelection && !stringVariables.some((v) => v.id === pageSelection) && (
            <span className="field-hint">
              This names a variable that is gone, or one that is no longer a
              string. Pick another, or choose none.
            </span>
          )}
        </label>
      )}
      {onStateSavingChange && stateSaving && (
        <>
          <label className="vars-toggle">
            <input
              type="checkbox"
              checked={stateSaving.enabled}
              data-testid="state-saving-toggle"
              onChange={(e) =>
                onStateSavingChange({ ...stateSaving, enabled: e.target.checked })
              }
            />
            Let readers save named states
          </label>
          {stateSaving.enabled && (
            <>
              {/* p.204's "State display name" — so an application whose
                  readers say "inbox" can say "inbox". Wording only. */}
              <label className="field">
                <span className="field-label">Called a</span>
                <input
                  value={stateSaving.display_name ?? ""}
                  placeholder="module state"
                  data-testid="state-display-name"
                  onChange={(e) =>
                    onStateSavingChange({ ...stateSaving, display_name: e.target.value })
                  }
                />
              </label>
              <label className="field">
                <span className="field-label">Plural</span>
                <input
                  value={stateSaving.display_name_plural ?? ""}
                  placeholder="module states"
                  onChange={(e) =>
                    onStateSavingChange({
                      ...stateSaving, display_name_plural: e.target.value,
                    })
                  }
                />
              </label>
              <label className="vars-toggle">
                <input
                  type="checkbox"
                  checked={stateSaving.include_page ?? true}
                  onChange={(e) =>
                    onStateSavingChange({ ...stateSaving, include_page: e.target.checked })
                  }
                />
                {/* p.200: "optionally, the current page that a user is
                    viewing". */}
                Keep the page the reader was on
              </label>
              <p className="canvas-widget-empty">
                Variables are saved only where their Settings tab says so — and
                each needs an external ID, which is the key a state is stored
                under.
              </p>
            </>
          )}
        </>
      )}
      {onRoutingChange && routing && (
        <p className="canvas-widget-empty">
          {/* Two halves and both are needed, so the panel says so rather than
              leaving an author with a switch that appears to do nothing. */}
          Pages with an ID, and interface variables set to appear in the URL,
          are shared by the link.
        </p>
      )}
    </div>
  );
}
