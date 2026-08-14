"use client";

import { useEditor } from "@craftjs/core";

import type { WorkshopModule } from "@/lib/types";

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
  stateSaving,
  onStateSavingChange,
}: {
  /** Whether this module writes its state to the URL (p.195). Here because
   * Foundry puts it in "the Pages section of the Settings panel" and the
   * layout tree is where our pages live — a routing switch on a panel that
   * never mentions pages would be a switch nobody finds. */
  routing?: boolean;
  onRoutingChange?: (next: boolean) => void;
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
