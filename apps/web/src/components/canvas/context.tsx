"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { CollapseOverride } from "./collapse";
import type { TabOverride } from "./tab-selection";

/** Environment a canvas widget renders in - never part of the saved
 * definition (Craft.js node props), since it's the same app rendered from
 * different routes (editor, workspace-wide published view) rather than
 * per-widget configuration. Widgets read it via context instead. */
export interface CanvasEnv {
  workspaceId: string;
  projectId: string;
  /** "edit": dragged around the builder canvas, data-bound widgets show a
   * live preview but forms/buttons are inert so a builder can't accidentally
   * submit real writes while arranging the page. "run": the real app, as an
   * end user sees it - forms and actions are live. */
  mode: "edit" | "run";
}

const CanvasContext = createContext<CanvasEnv | null>(null);

export const CanvasEnvProvider = CanvasContext.Provider;

export function useCanvasEnv(): CanvasEnv {
  const env = useContext(CanvasContext);
  if (!env) throw new Error("useCanvasEnv used outside a CanvasEnvProvider");
  return env;
}

/**
 * Shared parameter state (ROADMAP Canvas item 1) — the mechanism cross-widget
 * interactivity is built on: one widget sets a named value, any number of
 * others read it.
 *
 * A separate context from CanvasEnv, for a reason worth keeping: this one
 * changes on every interaction, while CanvasEnv changes only when the app
 * remounts or the edit/run mode flips. Merging them would make every widget
 * that only wants "which workspace am I in" re-render on every keystroke.
 *
 * **Values are runtime state, not part of the saved app.** A parameter's
 * name, label and options are Craft.js node props and are serialised with the
 * app; the value a viewer currently has selected is not, for exactly the
 * reason CanvasEnv isn't — it belongs to this render of the app, not to its
 * definition. So a published app opens at its defaults for every viewer
 * rather than at whatever the last person happened to choose.
 */
export interface CanvasParameters {
  values: Record<string, unknown>;
  set: (name: string, value: unknown) => void;
  /** Apply several at once. One event's effects are one render, and applying
   * them one at a time would let a widget re-fetch against a half-applied set
   * of writes. */
  setMany: (values: Record<string, unknown>) => void;
  /** p.85's Reset: forget the viewer's value so the definition's shows again.
   * A deletion rather than a write of the default — see the implementation for
   * why that is what makes p.128's precedence rule fall out. */
  reset: (names: readonly string[]) => void;
}

const ParameterContext = createContext<CanvasParameters | null>(null);

/**
 * Resolved variable values, computed by the server (roadmap 1.2).
 *
 * Two maps rather than one, and the distinction is the whole design:
 * `values` above is **what the viewer has set** - a dropdown selection, a row
 * click - and is written by widgets. This one is **what every variable
 * currently resolves to**, including derived ones, and is written only by the
 * server. A widget reading a derived variable reads this; a widget setting a
 * filter writes that.
 *
 * Merging them would let a widget write a derived variable, which is a value
 * that is a function of its inputs - so the same document could show two
 * different things depending on which write the reader believed.
 */
export interface CanvasVariables {
  /** The module's events, by id. Widgets look up their own triggers here
   * rather than holding them in props - an event routinely spans widgets, and
   * nesting it in the trigger's node would hide it from the widget it acts
   * on (decision 0002 §4). */
  events?: Record<string, import("./events").WorkshopEventDef>;
  /** What the module *declares*. Widget settings read this to offer a picker
   * of variables to bind to, which is the whole reason a binding is a choice
   * from a list rather than a name somebody types and hopes matches. */
  declared: Record<string, import("@/lib/types").WorkshopVariable>;
  resolved: Record<string, unknown>;
  /** True while the first resolve is in flight. A widget that rendered "0
   * results" during it would be reporting an answer it does not have. */
  pending: boolean;
}

const VariableContext = createContext<CanvasVariables>({
  declared: {},
  resolved: {},
  pending: false,
});

export const CanvasVariableProvider = VariableContext.Provider;

export function useCanvasVariables(): CanvasVariables {
  return useContext(VariableContext);
}

/** One variable's resolved value - a scalar for most kinds, an object-set
 * *definition* for `object_set`. Undefined while nothing has resolved it, which
 * a consumer reads as "not yet", never as "empty". */
export function useCanvasVariable(id: string | null | undefined): unknown {
  const { resolved } = useCanvasVariables();
  return id ? resolved[id] : undefined;
}

export function CanvasParameterProvider({
  children,
  seed,
  link,
}: {
  children: React.ReactNode;
  /** Starting values, applied once. Used to initialise interface variables from
   * URL query parameters (Foundry p.165, p.198) — a *starting* value, not a
   * binding, so the first widget interaction overwrites it and the URL does not
   * fight the viewer for control of the filter. */
  seed?: Record<string, unknown>;
  /** Set on an embedded module whose host has mapped variables into it.
   *
   * The two-way part of Foundry's interface, p.127: "Any change to a variable
   * value in either the child or parent module … will be reflected in all
   * modules where the variable is mapped." So a mapped name does not live here
   * at all — reads come from the host's values and writes go to the host's
   * setter, which makes one value with two views of it rather than two values
   * that have to be kept in step. */
  link?: {
    /** child variable id -> host variable id */
    bindings: Record<string, string>;
    values: Record<string, unknown>;
    set: (name: string, value: unknown) => void;
  };
}) {
  const [values, setValues] = useState<Record<string, unknown>>(seed ?? {});

  // **The seed usually arrives after the first render**, which is why this is
  // an effect and not just the initial state above. Seeding needs the module's
  // declared variables to know which external ID belongs to which variable, and
  // those come from a fetch — so at mount `seed` is `{}` and the real one lands
  // a beat later. Initial state alone silently did nothing, and the symptom was
  // a URL parameter that worked in no case at all.
  //
  // Applied *under* whatever is already set, so it stays a seed rather than a
  // binding: if a viewer has already touched a filter, their value wins and the
  // address bar does not take it back off them.
  const seeded = useRef<string | null>(null);
  const seedKey = JSON.stringify(seed ?? {});
  useEffect(() => {
    if (!seed || Object.keys(seed).length === 0) return;
    if (seeded.current === seedKey) return;
    seeded.current = seedKey;
    setValues((current) => ({ ...seed, ...current }));
  }, [seedKey, seed]);
  const set = useCallback(
    (name: string, value: unknown) => {
      const hostName = link?.bindings[name];
      if (hostName) {
        link.set(hostName, value);
        return;
      }
      setValues((current) => ({ ...current, [name]: value }));
    },
    [link],
  );
  const setMany = useCallback(
    (next: Record<string, unknown>) => {
      if (link) {
        for (const [name, value] of Object.entries(next)) {
          const hostName = link.bindings[name];
          if (hostName) link.set(hostName, value);
        }
      }
      setValues((current) => ({
        ...current,
        ...Object.fromEntries(
          Object.entries(next).filter(([name]) => !link?.bindings[name]),
        ),
      }));
    },
    [link],
  );

  /** p.85's Reset: forget what the viewer set, so the value falls back to the
   * one in the definition.
   *
   * **A deletion, not a write of the default**, and that is what makes p.128
   * fall out instead of needing a case of its own. The server resolves an
   * unbound static variable as `values.get(vid, variable.default)`, so removing
   * the local value *is* "back to the definition". And it resolves a variable
   * an embedding module has mapped as the host's value with the child's
   * definition skipped entirely (p.127) - so removing the local override there
   * is "back to the parent's definition", which is exactly what p.128 asks for.
   * One operation, right in both cases.
   *
   * **It never forwards to the host**, unlike `set`. A bound name's value is
   * overlaid from `link.values`, so deleting the local copy leaves the host's
   * showing - whereas forwarding would have a child's Reset button edit its
   * parent's state, which p.128 does not say and which is a child reaching
   * upward.
   */
  const reset = useCallback((names: readonly string[]) => {
    setValues((current) => {
      const next = { ...current };
      for (const name of names) delete next[name];
      return next;
    });
  }, []);

  // The host's value for every bound name, overlaid on our own. Overlaid rather
  // than merged into state so there is exactly one copy: a bound name that also
  // had a local value would drift the moment the host changed and nothing here
  // noticed.
  const linked = link
    ? Object.fromEntries(
        Object.entries(link.bindings).map(([childName, hostName]) => [
          childName,
          link.values[hostName],
        ]),
      )
    : null;
  const merged = useMemo(
    () => (linked ? { ...values, ...linked } : values),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [values, JSON.stringify(linked)],
  );

  const value = useMemo(
    () => ({ values: merged, set, setMany, reset }),
    [merged, set, setMany, reset],
  );
  return <ParameterContext.Provider value={value}>{children}</ParameterContext.Provider>;
}

export function useCanvasParameters(): CanvasParameters {
  const params = useContext(ParameterContext);
  if (!params) {
    throw new Error("useCanvasParameters used outside a CanvasParameterProvider");
  }
  return params;
}

/** One parameter's current value. `undefined` when nothing has set it, which
 * a consumer must read as "no filter" rather than "filter to nothing" — an
 * app whose table is empty until you touch a dropdown looks broken on first
 * load. */
export function useCanvasParameter(name: string | null | undefined): unknown {
  const { values } = useCanvasParameters();
  return name ? values[name] : undefined;
}

/**
 * Which page of a multi-page module is showing (roadmap 1.4).
 *
 * **Runtime state, never persisted** — the same rule variable values follow
 * (decision 0002 §3). A published app opens on its first page for every
 * viewer rather than on whatever page the last person happened to be looking
 * at; a saved app is not a saved session.
 *
 * `current` is null until something sets it, which a page reads as "show me if
 * I am the first one". That is a deliberate alternative to seeding it with the
 * first page's id at mount: the layout is what decides which page is first,
 * and duplicating that decision into state would make the two disagree the
 * moment somebody reorders the pages.
 */
export interface CanvasPageState {
  current: string | null;
  go: (nodeId: string) => void;
  /** The overlay covering the page, if any. Held apart from `current` because
   * an overlay does not replace the page - closing one returns you to what was
   * underneath, which a single "where am I" value cannot express. */
  overlay: string | null;
  openOverlay: (nodeId: string) => void;
  closeOverlay: () => void;
  /** What p.82's Expand/Collapse/Toggle events have said about each section,
   * by node id, and the backing-variable value each was said against.
   *
   * Here rather than inside the section, because an event routinely fires
   * from somewhere else: p.82's own worked example is a button that expands
   * an object view. A section holding its own state could not be told
   * anything by a widget it cannot see - which is decision 0002's argument
   * for events living beside the layout, one level down.
   */
  collapsed: Record<string, CollapseOverride>;
  setCollapsed: (nodeId: string, override: CollapseOverride) => void;
  /** Which tab each Tabs section is showing, by section node id, and the
   * backing variable value each was chosen against (p.54, p.84).
   *
   * Here rather than inside the section for `collapsed`'s reason - a
   * Switch-to-tab event fires from somewhere else in the module - and kept
   * *separate* from `collapsed` because a section can be both collapsible and
   * tabbed, and one map keyed by node id could then hold only one of the two
   * things that section is doing. */
  tabs: Record<string, TabOverride>;
  setTab: (nodeId: string, override: TabOverride) => void;
  /** p.91's "Module appearance": which scheme the module is showing.
   *
   * **Module-level runtime state**, beside the current page and the section
   * overrides, and for their reason: p.91's event fires from a button that
   * knows nothing about who is listening, so the answer cannot live inside a
   * widget. Never persisted (decision 0002 §3) - a published module opens
   * light for every viewer, because a saved app is not a saved session.
   *
   * The dark half is `[data-scheme="dark"]`, which p.59-60's per-section
   * brightness rule already defines: every widget reads `--ink`, `--line` and
   * `--panel`, so a module-wide scheme is the same attribute one level up
   * rather than a second set of colours. */
  scheme: "light" | "dark";
  toggleScheme: () => void;
  /** p.85's Recompute (p.76's behaviours). Forget what these variables last
   * computed and resolve again, so the server computes them fresh.
   *
   * Here rather than on the parameter context because a held value is not a
   * *parameter* - nobody set it, the server computed it - and mixing the two
   * would let a widget "set" a derived variable through the back door. */
  recompute: (names: readonly string[]) => void;
}

const PageContext = createContext<CanvasPageState>({
  current: null,
  go: () => {},
  overlay: null,
  openOverlay: () => {},
  closeOverlay: () => {},
  collapsed: {},
  setCollapsed: () => {},
  tabs: {},
  setTab: () => {},
  scheme: "light",
  toggleScheme: () => {},
  recompute: () => {},
});

export const CanvasPageProvider = PageContext.Provider;

export function useCanvasPage(): CanvasPageState {
  return useContext(PageContext);
}

/** Running an action from an event (roadmap 1.3, the `run_action` effect).
 *
 * Held here rather than built by each widget for the reason `useEventContext`
 * exists: the first widget to assemble a capability by hand forgot one, and a
 * missing capability makes an effect silently skip. It is also the only effect
 * that *writes* — the rest move the reader around — so it is the only one whose
 * outcome somebody has to be told about. `status` is that telling.
 *
 * The default is a no-op with a null status, so a widget rendered outside a
 * `VariableBridge` (a Craft.js preview, a test) does not throw; the effect is
 * skipped, which is the same rule every other capability follows.
 */
export interface CanvasActions {
  run: (
    config: { action: string; subject: string; values?: Record<string, string> },
    context: { object?: { id?: string } | null },
  ) => void;
  /** What the last run did. Kept as one value rather than a list: an app that
   * accumulated a log of every click would bury the one that failed. */
  status: { ok: boolean; message: string } | null;
  dismiss: () => void;
}

const ActionsContext = createContext<CanvasActions>({
  run: () => {},
  status: null,
  dismiss: () => {},
});

export const CanvasActionsProvider = ActionsContext.Provider;

export function useCanvasActions(): CanvasActions {
  return useContext(ActionsContext);
}


/** Whether the module header is collapsed (Foundry p.49).
 *
 * A context rather than a prop because the rule reaches past the header's own
 * children: a Tabs widget draws one button per *page*, and it has to know to
 * drop the labels. Defaults to false, so every widget outside a header - which
 * is most of them - reads the same value it would have read before this
 * existed.
 */
export const CanvasHeaderCollapsedContext = createContext(false);

export function useHeaderCollapsed(): boolean {
  return useContext(CanvasHeaderCollapsedContext);
}
