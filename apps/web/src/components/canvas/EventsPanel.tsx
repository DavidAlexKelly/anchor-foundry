"use client";

/** The events panel (roadmap phase 2, item 1.6; the events are item 1.3).
 *
 * The event system has existed since §76 and until now could only be authored
 * by writing the document — every event in this repo's demo module was put
 * there by a script. A widget library and a variable graph are not an
 * application builder if the thing that connects them is unreachable.
 *
 * **It offers only what the server accepts.** Trigger widgets come from the
 * layout, triggers from what that widget can do, targets from the declared
 * variables minus the derived ones, pages from the pages that exist. That is
 * the same principle §77 arrived at the hard way: a rule that tolerates a
 * missing piece needs a construction that cannot omit it. Every refusal in
 * `services/workshop_events.py` is a shape this panel cannot build.
 *
 * **Effect order is editable and visible**, because it is semantic: effects
 * run in configured order and setting a variable copies immediately, so two
 * effects in the other order produce a different result. A list you could not
 * reorder would hide the one thing about an event that is not obvious.
 *
 * **Nothing here validates.** The server does, and this panel's job is to
 * make the invalid unbuildable rather than to re-implement the rules — a
 * second copy of them is a second thing to keep in step (`STATUS.md`, the
 * mirrored-file rough edge).
 */

import { useState } from "react";
import type { WorkshopEffect, WorkshopEvent, WorkshopVariable } from "@/lib/types";
import { newEventId } from "@/lib/workshop-module";

/** Mirrors `TRIGGERS` in the service, with the widgets each one belongs to.
 *
 * Per-widget rather than one list, because "row selected" on a button is not
 * a trigger anybody can fire — offering it would be offering an event that
 * never runs, which is the failure the server's refusals exist to prevent one
 * step later. */
const TRIGGERS: {
  on: string;
  label: string;
  widgets: string[];
  /** A different wording for the same trigger on a particular widget. "Row
   * selected" on a map reads as a mistake; a second trigger name meaning the
   * same thing would be a second thing every document, every panel and every
   * refusal has to know about. One trigger, worded for where it fires. */
  labels?: Record<string, string>;
}[] = [
  { on: "click", label: "Clicked", widgets: ["CanvasButton", "CanvasTabs"] },
  {
    on: "row_select",
    label: "Row selected",
    widgets: ["CanvasObjectTable", "CanvasMap"],
    labels: { CanvasMap: "Pin selected" },
  },
  {
    on: "change",
    label: "Changed",
    widgets: ["CanvasParameterControl", "CanvasFilterList"],
  },
];

/** Mirrors `EFFECTS`. The two the server refuses with a reason are absent:
 * offering them would be offering a choice that fails on save. */
const EFFECTS: { type: string; label: string; hint: string }[] = [
  { type: "set_variable", label: "Set a variable", hint: "" },
  { type: "navigate", label: "Go to a page or overlay", hint: "" },
  { type: "close_overlay", label: "Close the overlay", hint: "returns to the page underneath" },
  { type: "open_url", label: "Open a link", hint: "" },
];

/** Widget names that can fire something, for the caller reading the tree.
 * Derived from TRIGGERS so the two cannot disagree - a widget listed here but
 * with no trigger would show up as an option that offers nothing. */
export const TRIGGER_WIDGETS: string[] = [...new Set(TRIGGERS.flatMap((t) => t.widgets))];

export interface TriggerCandidate {
  id: string;
  label: string;
  widget: string;
}

export interface PageCandidate {
  id: string;
  label: string;
}

function triggersFor(widget: string): { on: string; label: string }[] {
  return TRIGGERS.filter((t) => t.widgets.includes(widget)).map((t) => ({
    on: t.on,
    label: t.labels?.[widget] ?? t.label,
  }));
}

export function EventsPanel({
  events,
  variables,
  triggerNodes,
  pages,
  onChange,
  readOnly,
}: {
  events: Record<string, WorkshopEvent>;
  variables: Record<string, WorkshopVariable>;
  /** Widgets in the layout that can fire something, read from the Craft tree
   * by the caller — this panel does not reach into the editor. */
  triggerNodes: TriggerCandidate[];
  /** Pages and overlays, which is what `navigate` accepts. */
  pages: PageCandidate[];
  onChange: (next: Record<string, WorkshopEvent>) => void;
  readOnly: boolean;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const writable = Object.values(variables).filter((v) => !v.derivation);

  function update(id: string, next: WorkshopEvent) {
    onChange({ ...events, [id]: next });
  }

  function addEvent() {
    const node = triggerNodes[0];
    if (!node) return;
    const on = triggersFor(node.widget)[0]?.on ?? "click";
    const id = newEventId();
    onChange({ ...events, [id]: { id, trigger: { node: node.id, on }, effects: [] } });
    setOpenId(id);
  }

  function removeEvent(id: string) {
    const next = { ...events };
    delete next[id];
    onChange(next);
    if (openId === id) setOpenId(null);
  }

  function setEffect(event: WorkshopEvent, index: number, effect: WorkshopEffect) {
    const effects = [...(event.effects ?? [])];
    effects[index] = effect;
    update(event.id, { ...event, effects });
  }

  function moveEffect(event: WorkshopEvent, index: number, by: number) {
    const effects = [...(event.effects ?? [])];
    const target = index + by;
    if (target < 0 || target >= effects.length) return;
    [effects[index], effects[target]] = [effects[target]!, effects[index]!];
    update(event.id, { ...event, effects });
  }

  const ids = Object.keys(events).sort();

  if (triggerNodes.length === 0) {
    return (
      <p className="canvas-widget-empty">
        Nothing in this app can be triggered yet — add a Button, an Object table or a
        Filter, then wire it here.
      </p>
    );
  }

  return (
    <div className="canvas-events-panel">
      {ids.length === 0 && (
        <p className="canvas-widget-empty">
          No events yet. An event is a trigger and an ordered list of effects.
        </p>
      )}
      {ids.map((id) => {
        const event = events[id]!;
        const node = triggerNodes.find((n) => n.id === event.trigger?.node);
        const open = openId === id;
        const effects = event.effects ?? [];
        return (
          <div key={id} className={`canvas-event${open ? " on" : ""}`}>
            <button type="button" className="canvas-event-head" onClick={() => setOpenId(open ? null : id)}>
              <strong>{node?.label ?? event.trigger?.node ?? "?"}</strong>
              <span>
                {triggersFor(node?.widget ?? "").find((t) => t.on === event.trigger?.on)?.label ??
                  event.trigger?.on}
                {" · "}
                {effects.length} {effects.length === 1 ? "effect" : "effects"}
              </span>
            </button>
            {open && (
              <div className="canvas-event-body">
                <label className="field">
                  <span className="field-label">When</span>
                  <select
                    disabled={readOnly}
                    value={event.trigger?.node ?? ""}
                    onChange={(e) => {
                      const picked = triggerNodes.find((n) => n.id === e.target.value);
                      if (!picked) return;
                      // The trigger has to be one this widget can fire: a row
                      // selection on a button is an event that never runs.
                      const still = triggersFor(picked.widget).some(
                        (t) => t.on === event.trigger?.on,
                      );
                      update(id, {
                        ...event,
                        trigger: {
                          node: picked.id,
                          on: still
                            ? event.trigger.on
                            : triggersFor(picked.widget)[0]?.on ?? "click",
                        },
                      });
                    }}
                  >
                    {triggerNodes.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Is</span>
                  <select
                    disabled={readOnly}
                    value={event.trigger?.on ?? ""}
                    onChange={(e) =>
                      update(id, { ...event, trigger: { ...event.trigger, on: e.target.value } })
                    }
                  >
                    {triggersFor(node?.widget ?? "").map((t) => (
                      <option key={t.on} value={t.on}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </label>

                <p className="field-label">
                  Then, in order
                  {effects.length > 1 && <span className="field-hint"> — order matters</span>}
                </p>
                {effects.map((effect, index) => (
                  <EffectEditor
                    key={index}
                    effect={effect}
                    index={index}
                    count={effects.length}
                    variables={writable}
                    pages={pages}
                    readOnly={readOnly}
                    onChange={(next) => setEffect(event, index, next)}
                    onMove={(by) => moveEffect(event, index, by)}
                    onRemove={() =>
                      update(id, {
                        ...event,
                        effects: effects.filter((_, i) => i !== index),
                      })
                    }
                  />
                ))}
                {!readOnly && (
                  <div className="row-actions">
                    <button
                      type="button"
                      className="btn quiet"
                      onClick={() =>
                        update(id, {
                          ...event,
                          effects: [...effects, { type: "set_variable", config: {} }],
                        })
                      }
                    >
                      Add an effect
                    </button>
                    <button type="button" className="btn danger" onClick={() => removeEvent(id)}>
                      Delete event
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
      {!readOnly && (
        <button type="button" className="btn" onClick={addEvent}>
          New event
        </button>
      )}
    </div>
  );
}

function EffectEditor({
  effect,
  index,
  count,
  variables,
  pages,
  readOnly,
  onChange,
  onMove,
  onRemove,
}: {
  effect: WorkshopEffect;
  index: number;
  count: number;
  variables: WorkshopVariable[];
  pages: PageCandidate[];
  readOnly: boolean;
  onChange: (next: WorkshopEffect) => void;
  onMove: (by: number) => void;
  onRemove: () => void;
}) {
  const config = effect.config ?? {};
  const setConfig = (patch: Record<string, unknown>) =>
    onChange({ ...effect, config: { ...config, ...patch } });

  return (
    <div className="canvas-effect">
      <div className="canvas-effect-head">
        <span className="canvas-effect-step">{index + 1}</span>
        <select
          disabled={readOnly}
          value={effect.type}
          // A fresh config on a type change: a `page` left over from a
          // navigate would ride along in a set_variable and be saved as debris
          // nobody put there.
          onChange={(e) => onChange({ type: e.target.value, config: {} })}
        >
          {EFFECTS.map((e) => (
            <option key={e.type} value={e.type}>
              {e.label}
            </option>
          ))}
        </select>
        {!readOnly && (
          <div className="row-actions">
            <button
              type="button"
              className="btn quiet"
              aria-label="Move earlier"
              disabled={index === 0}
              onClick={() => onMove(-1)}
            >
              ↑
            </button>
            <button
              type="button"
              className="btn quiet"
              aria-label="Move later"
              disabled={index === count - 1}
              onClick={() => onMove(1)}
            >
              ↓
            </button>
            <button type="button" className="btn quiet" aria-label="Remove" onClick={onRemove}>
              ×
            </button>
          </div>
        )}
      </div>

      {effect.type === "set_variable" && (
        <>
          <label className="field">
            <span className="field-label">Variable</span>
            <select
              disabled={readOnly}
              value={String(config.variable ?? "")}
              onChange={(e) => setConfig({ variable: e.target.value || undefined })}
            >
              <option value="">Pick a variable</option>
              {variables.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label || v.id}
                </option>
              ))}
            </select>
            {/* Derived variables are absent rather than disabled: they are
                computed from their inputs, and the server refuses a write. */}
            <span className="field-hint">Derived variables are not settable</span>
          </label>
          <label className="field">
            <span className="field-label">To</span>
            <select
              disabled={readOnly}
              value={config.from === "object" ? "object" : "value"}
              onChange={(e) =>
                onChange({
                  type: effect.type,
                  config:
                    e.target.value === "object"
                      ? { variable: config.variable, from: "object" }
                      : { variable: config.variable, value: "" },
                })
              }
            >
              <option value="value">A value</option>
              <option value="object">The object that was clicked</option>
            </select>
          </label>
          {config.from !== "object" && (
            <label className="field">
              <span className="field-label">Value</span>
              <input
                disabled={readOnly}
                value={String(config.value ?? "")}
                onChange={(e) => setConfig({ value: e.target.value })}
              />
              <span className="field-hint">
                {"{{name}}"} reads from what was clicked
              </span>
            </label>
          )}
        </>
      )}

      {effect.type === "navigate" && (
        <label className="field">
          <span className="field-label">Go to</span>
          <select
            disabled={readOnly}
            value={String(config.page ?? "")}
            onChange={(e) => setConfig({ page: e.target.value || undefined })}
          >
            <option value="">Pick a page or overlay</option>
            {pages.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
      )}

      {effect.type === "open_url" && (
        <label className="field">
          <span className="field-label">Link</span>
          <input
            disabled={readOnly}
            value={String(config.url ?? "")}
            placeholder="https://"
            onChange={(e) => setConfig({ url: e.target.value })}
          />
          <span className="field-hint">http, https, mailto or a path</span>
        </label>
      )}

      {effect.type === "close_overlay" && (
        <p className="field-hint">Returns to the page underneath. Nothing to configure.</p>
      )}
    </div>
  );
}
