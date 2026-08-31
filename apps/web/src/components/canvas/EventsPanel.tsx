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
    widgets: [
      "CanvasObjectTable", "CanvasObjectCards", "CanvasMap", "CanvasTimeline",
    ],
    labels: {
      CanvasMap: "Pin selected", CanvasObjectCards: "Card selected",
      // p.349's "On active timeline event selection". **The same trigger, not
      // a second one** - the comment on `labels` above argues exactly this: a
      // second trigger name meaning "an object was selected" would be a second
      // thing every document, panel and refusal has to know about.
      CanvasTimeline: "Event selected",
    },
  },
  {
    on: "change",
    label: "Changed",
    // **`CanvasNumericInput` was missing here and the widget fired `change`
    // anyway** — §202 built the firing and not the offer, so an author could
    // not wire the event that the widget was already announcing. Exactly
    // §194's shape from the other side: there, an offer nothing fired; here, a
    // firing nothing could offer. Both are invisible from inside one half.
    widgets: [
      "CanvasParameterControl", "CanvasFilterList",
      "CanvasNumericInput", "CanvasTextInput", "CanvasStringSelector",
      "CanvasDateTimePicker",
    ],
  },
  {
    // p.465's "Event on enter". Separate from `Changed` because that fires per
    // keystroke and this fires once, when the entry is finished - which is the
    // whole reason p.465 offers it.
    on: "submit",
    label: "Submitted",
    widgets: ["CanvasTextInput"],
  },
];

/** Mirrors `EFFECTS`. The one the server still refuses with a reason
 * (`export`) is absent: offering it would be offering a choice that fails on
 * save. */
const EFFECTS: { type: string; label: string; hint: string }[] = [
  { type: "set_variable", label: "Set a variable", hint: "" },
  { type: "navigate", label: "Go to a page or overlay", hint: "" },
  { type: "close_overlay", label: "Close the overlay", hint: "returns to the page underneath" },
  { type: "open_url", label: "Open a link", hint: "" },
  { type: "run_action", label: "Run an action", hint: "writes to the object it acts on" },
  // p.82's three. Foundry groups them with `navigate` under "Layout events" -
  // they change "the on-screen display within a Workshop module".
  { type: "expand_section", label: "Expand a section", hint: "" },
  { type: "collapse_section", label: "Collapse a section", hint: "" },
  {
    type: "toggle_section",
    label: "Toggle a section",
    hint: "expands it if collapsed, collapses it if expanded",
  },
  // p.84's, and the one Layout event that *writes* its variable.
  {
    type: "switch_tab",
    label: "Switch to a tab",
    hint: "also updates the section's tab variable, unlike the four above",
  },
  // p.85's, offered "for static variables".
  {
    type: "reset_variable",
    label: "Reset a variable",
    hint: "back to the value in its definition",
  },
  // p.85's other one, offered "for non-static variable types" - the
  // complement of the row above.
  {
    type: "recompute",
    label: "Recompute a variable",
    hint: "for a derived variable that does not recompute automatically",
  },
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

/** An action this workspace has, and what it lets an event write. The
 * properties come from the action type rather than from a text box: the server
 * refuses a write to a property the action does not make editable, and a form
 * that let you type one would be teaching that rule by rejection. */
export interface ActionCandidate {
  id: string;
  label: string;
  editable: string[];
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
  tabSections,
  sections,
  actions = [],
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
  /** The module's **Tabs** sections and what each one's tabs are called
   * (p.54, p.84). Separate from `sections` below because the two lists answer
   * different questions - which sections can collapse, which have tabs - and a
   * section can be both. */
  tabSections?: { id: string; label: string; tabs: string[] }[];
  /** The module's **collapsible** sections, which is what p.82's three
   * effects accept - and only those, because the server refuses the rest. */
  sections?: PageCandidate[];
  /** The workspace's action types, which is what `run_action` accepts. */
  actions?: ActionCandidate[];
  onChange: (next: Record<string, WorkshopEvent>) => void;
  readOnly: boolean;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const writable = Object.values(variables).filter((v) => !v.derivation);
  // Subjects are *read*, so a derived one is fine here where it is not for a
  // set_variable: "the object this other variable computed" is a reasonable
  // thing to act on.
  const objects = Object.values(variables).filter((v) => v.kind === "single_object");
  // p.85's Recompute, narrowed the way `writable` narrows Set: derived, and
  // not on Automatic - a variable on Automatic already recomputes when its
  // inputs change (p.76), so an event aimed at one is a click with no effect
  // and the server refuses it.
  const recomputable = Object.values(variables).filter(
    (v) => v.derivation && (v.recompute ?? "automatic") !== "automatic",
  );

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
                    recomputable={recomputable}
                    objects={objects}
                    pages={pages}
                    tabSections={tabSections ?? []}
                    sections={sections ?? []}
                    actions={actions}
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
  recomputable,
  objects,
  pages,
  tabSections,
  sections,
  actions,
  readOnly,
  onChange,
  onMove,
  onRemove,
}: {
  effect: WorkshopEffect;
  index: number;
  count: number;
  variables: WorkshopVariable[];
  /** p.85's Recompute list: derived and not on Automatic. Separate from
   * `variables` because that one is narrowed for Set, which wants the exact
   * complement — static variables only. */
  recomputable: WorkshopVariable[];
  objects: WorkshopVariable[];
  pages: PageCandidate[];
  tabSections: { id: string; label: string; tabs: string[] }[];
  sections: PageCandidate[];
  actions: ActionCandidate[];
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

      {effect.type === "run_action" && (
        <RunActionEditor
          config={config}
          objects={objects}
          actions={actions}
          readOnly={readOnly}
          onChange={(next) => onChange({ type: effect.type, config: next })}
        />
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

      {(effect.type === "expand_section"
        || effect.type === "collapse_section"
        || effect.type === "toggle_section") && (
        <label className="field">
          <span className="field-label">Section</span>
          <select
            disabled={readOnly}
            data-testid="effect-section"
            value={String(config.section ?? "")}
            onChange={(e) => setConfig({ section: e.target.value || undefined })}
          >
            <option value="">Pick a collapsible section</option>
            {sections.map((s: PageCandidate) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          {sections.length === 0 && (
            <span className="field-hint">
              No collapsible sections yet — turn on Collapsible in a section&apos;s
              settings first
            </span>
          )}
        </label>
      )}

      {effect.type === "switch_tab" && (
        <>
          <label className="field">
            <span className="field-label">Section</span>
            <select
              disabled={readOnly}
              data-testid="effect-tab-section"
              value={String(config.section ?? "")}
              // The tab is cleared with the section, not carried across: tab
              // names are per section, so a name kept from the old one would
              // be refused on save and would look like a bug in the picker.
              onChange={(e) =>
                onChange({
                  type: effect.type,
                  config: { section: e.target.value || undefined },
                })}
            >
              <option value="">Pick a Tabs section</option>
              {tabSections.map((t) => (
                <option key={t.id} value={t.id}>{t.label}</option>
              ))}
            </select>
            {tabSections.length === 0 && (
              <span className="field-hint">
                No Tabs sections yet &mdash; set a section&apos;s layout to Tabs first
              </span>
            )}
          </label>
          <label className="field">
            <span className="field-label">Tab</span>
            <select
              disabled={readOnly}
              data-testid="effect-tab"
              value={String(config.tab ?? "")}
              onChange={(e) => setConfig({ tab: e.target.value || undefined })}
            >
              <option value="">Pick a tab</option>
              {(tabSections.find((t) => t.id === config.section)?.tabs ?? []).map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </label>
        </>
      )}

      {effect.type === "recompute" && (
        <label className="field">
          <span className="field-label">Variable</span>
          <select
            disabled={readOnly}
            data-testid="effect-recompute-variable"
            value={String(config.variable ?? "")}
            onChange={(e) => setConfig({ variable: e.target.value || undefined })}
          >
            <option value="">Pick a variable</option>
            {recomputable.map((v) => (
              <option key={v.id} value={v.id}>{v.label || v.id}</option>
            ))}
          </select>
          {/* The list is already narrowed to the ones this can act on, so the
              hint says what is missing rather than what is wrong. */}
          <span className="field-hint">
            {recomputable.length === 0
              ? "No variables are set to recompute on an event — set one's "
                + "recompute behaviour in the Variables panel first"
              : "Only derived variables not on Automatic recompute"}
          </span>
        </label>
      )}

      {effect.type === "reset_variable" && (
        <label className="field">
          <span className="field-label">Variable</span>
          <select
            disabled={readOnly}
            data-testid="effect-reset-variable"
            value={String(config.variable ?? "")}
            onChange={(e) => setConfig({ variable: e.target.value || undefined })}
          >
            <option value="">Pick a variable</option>
            {variables.map((v) => (
              <option key={v.id} value={v.id}>{v.label || v.id}</option>
            ))}
          </select>
          {/* p.85 offers Reset "for static variables", and `variables` is
              already the settable list for `set_variable` - the same filter,
              for the same reason: a derived variable has no stored value to
              put back. */}
          <span className="field-hint">
            Back to the value in its definition &mdash; or, for a variable an
            embedding module has mapped, back to the parent&apos;s.
          </span>
        </label>
      )}

      {effect.type === "close_overlay" && (
        <p className="field-hint">Returns to the page underneath. Nothing to configure.</p>
      )}
    </div>
  );
}


/** Configuring a `run_action`.
 *
 * Three things, and the third is the one worth care: **which action**, **which
 * variable holds the object it acts on**, and **what it writes**. The write
 * fields are one per editable property of the chosen action rather than a
 * free-form map, because the server refuses a property the action does not
 * make editable — and a text box that let you type one would be teaching that
 * rule by rejection, after the save.
 *
 * Changing the action clears the values with it. Property names carried over
 * from a different action would be refused on save with a message about a
 * property nobody typed.
 */
function RunActionEditor({
  config,
  objects,
  actions,
  readOnly,
  onChange,
}: {
  config: Record<string, unknown>;
  objects: WorkshopVariable[];
  actions: ActionCandidate[];
  readOnly: boolean;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const chosen = actions.find((a) => a.id === String(config.action ?? ""));
  const values = (config.values ?? {}) as Record<string, string>;

  return (
    <>
      <label className="field">
        <span className="field-label">Action</span>
        <select
          disabled={readOnly}
          value={String(config.action ?? "")}
          onChange={(e) =>
            onChange({ ...config, action: e.target.value || undefined, values: {} })
          }
        >
          <option value="">Pick an action</option>
          {actions.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
        </select>
        {actions.length === 0 && (
          <span className="field-hint">
            This workspace has no actions yet — define one on an object type first
          </span>
        )}
      </label>
      <label className="field">
        <span className="field-label">On the object in</span>
        <select
          disabled={readOnly}
          value={String(config.subject ?? "")}
          onChange={(e) => onChange({ ...config, subject: e.target.value || undefined })}
        >
          <option value="">Pick a variable</option>
          {objects.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label || v.id}
            </option>
          ))}
        </select>
        {/* Only object-holding variables are offered. A text variable holding
            a primary key looks equivalent and is not: the action runs against
            an instance id. */}
        <span className="field-hint">
          {objects.length === 0
            ? "Declare a variable that holds an object, and set it from a row click"
            : "Set by a row click, usually in an earlier effect of this same event"}
        </span>
      </label>
      {chosen && chosen.editable.length === 0 && (
        <p className="canvas-widget-empty">
          {chosen.label} makes no properties editable, so there is nothing for this
          effect to write.
        </p>
      )}
      {chosen?.editable.map((prop) => (
        <label className="field" key={prop}>
          <span className="field-label">{prop}</span>
          <input
            disabled={readOnly}
            value={values[prop] ?? ""}
            placeholder="leave blank not to write it"
            onChange={(e) => {
              const next = { ...values };
              if (e.target.value === "") delete next[prop];
              else next[prop] = e.target.value;
              onChange({ ...config, values: next });
            }}
          />
          <span className="field-hint">{"{{value}}"} reads from what was clicked or chosen</span>
        </label>
      ))}
    </>
  );
}
