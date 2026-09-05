"use client";

/** Keeps resolved variable values in step with what the viewer has selected
 * (roadmap phase 2, item 1.2).
 *
 * The canonical Workshop interaction is a Filter List narrowing an object set
 * that a table and a chart both read. This is the wire between the two halves:
 * a filter widget writes a raw value into the parameter context, this posts
 * every raw value to the server, and the server returns what each variable
 * *resolves* to - derived scalars computed, object sets narrowed.
 *
 * **Why the server and not here.** The transformation semantics (`if_else`'s
 * truthiness, `cast`'s refusals, what an unset filter means) would otherwise
 * exist twice, and this repo already carries five mirrored files with a
 * standing note that a sixth should be a shared package instead. It also rides
 * along with a call the app is making anyway: the narrowed set has to reach the
 * server to be evaluated regardless.
 *
 * **Debounced**, because a text filter would otherwise cost a request per
 * keystroke. The debounce is the honest cost of the decision above, and it is
 * the reason `pending` exists rather than widgets rendering stale rows as if
 * they were current.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { actions as actionApi, ApiError, canvas as canvasApi } from "@/lib/api";
import {
  CanvasActionsProvider,
  CanvasPageProvider,
  CanvasVariableProvider,
  useCanvasParameters,
} from "./context";
import { invalidateCanvasReads } from "./refresh";
import type { CollapseOverride } from "./collapse";
import type { TabOverride } from "./tab-selection";
import { asPageId, pageState, type PageOverride } from "./page-selection";
import { heldFor, remember, request, requested, settled } from "./recompute";
import { defaultPageNode, pageNodeFor } from "./routing";
import { RoutingSync } from "./RoutingSync";
import { StateBar } from "./StateBar";

const DEBOUNCE_MS = 250;

export function VariableBridge({
  workspaceId,
  projectId,
  appId,
  declared,
  events,
  published = false,
  bound,
  routing = false,
  layout,
  pageSelection,
  stateSaving,
  children,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
  /** True on the workspace-wide published route. A published app is reached by
   * someone who may not be in its project at all, so the project-scoped
   * resolve would 404 for exactly the audience it was published to. */
  published?: boolean;
  /** The module's declared variables. Empty for a v1 document, which is also
   * how this knows to cost no requests. */
  declared: Record<string, import("@/lib/types").WorkshopVariable>;
  events?: Record<string, import("./events").WorkshopEventDef>;
  /** Variable ids a host module is backing, when this module is embedded. Sent
   * to the server so the child's own definition stands aside for the host's
   * value — Foundry's precedence rule (p.122, p.127). Not derivable from this
   * document: only the host knows what it mapped. */
  bound?: string[];
  /** Whether this module writes its state to the URL (p.195). Passed by the
   * *viewer* routes only: in the builder every page is on screen at once, so
   * "the current page" has no answer, and an author arranging widgets should
   * not be rewriting the link they will share. */
  routing?: boolean;
  /** The layout, for the page walk routing and state saving both need. */
  layout?: unknown;
  /** The id of the string variable backing page selection (p.81), if any.
   *
   * Viewer routes only, like `routing` and for the same reason: in the builder
   * every page is on screen at once, so a variable deciding which one shows
   * would have nothing to decide — and an author arranging widgets on page two
   * should not have it vanish because a filter changed. */
  pageSelection?: string;
  /** State-saving settings (p.201, p.204). Passed by the *viewer* routes only:
   * p.200 calls this a feature for "module consumers", and an author arranging
   * widgets has no state to save. */
  stateSaving?: import("@/lib/types").WorkshopModule["state_saving"];
  children: React.ReactNode;
}) {
  const enabled = Object.keys(declared).length > 0;
  const { values } = useCanvasParameters();
  const [resolved, setResolved] = useState<Record<string, unknown>>({});
  const [pending, setPending] = useState(enabled);
  // Which request's answer we are still willing to accept. Two resolves in
  // flight can land out of order, and an older one overwriting a newer one
  // would show the previous filter's results with the current filter on screen
  // - which reads as the filter being broken.
  const latest = useRef(0);

  // p.76's two non-automatic recompute behaviours: what each holding variable
  // last computed. **A ref, not state**, and the distinction matters: the
  // resolve effect below keys off the *parameter* values, and putting this in
  // state would make every capture schedule another resolve, which would
  // capture again. A recompute event bumps `recomputeTick` instead, which is
  // the one thing that should cause a re-resolve.
  const heldRef = useRef<Record<string, unknown>>({});
  // p.85's Recompute events that have not been answered yet. A ref for the same
  // reason `heldRef` is, and cleared by the resolve that carried each ask
  // rather than wholesale, so an event fired mid-request is not swallowed.
  const askRef = useRef<ReadonlySet<string>>(new Set());
  const [recomputeTick, setRecomputeTick] = useState(0);

  const resolve = useMutation({
    mutationFn: (raw: Record<string, unknown>) => {
      const ticket = ++latest.current;
      const asks = requested(declared, askRef.current);
      const held = heldFor(declared, heldRef.current, askRef.current);
      return (published
        ? canvasApi.evaluatePublishedVariables(workspaceId, appId, raw, bound, held, asks)
        : canvasApi.evaluateVariables(workspaceId, projectId, appId, raw, bound, held, asks))
        .then((data) => ({ data, ticket, held, asks }));
    },
    onSuccess: ({ data, ticket, held, asks }) => {
      if (ticket !== latest.current) return;
      // Captured before the values are published, so a widget never renders a
      // held variable in the gap between the two.
      heldRef.current = remember(declared, heldRef.current, held, data.values);
      askRef.current = settled(askRef.current, asks);
      setResolved(data.values);
      setPending(false);
    },
    onError: () => setPending(false),
  });

  const serialised = JSON.stringify(values);
  useEffect(() => {
    if (!enabled) {
      setPending(false);
      return;
    }
    setPending(true);
    const timer = setTimeout(() => resolve.mutate(values), DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialised, enabled, appId, (bound ?? []).join(","), recomputeTick]);

  // The current page lives here too: it is runtime state with exactly the
  // lifetime of the variable values beside it, and a separate provider would
  // be a second thing to mount in both routes and forget in one.
  //
  // **What is held is the *override*, not the page.** p.81 gives a module two
  // instructions - a Switch-to-Page event and a backing variable - and says
  // the event does not write the variable, so neither can be stored as "the
  // current page" without losing the other. `page-selection.ts` combines them
  // on every render; what state has to remember is only what the last event
  // said and what the variable said at the time.
  const [pageOverride, setPageOverride] = useState<PageOverride | undefined>(undefined);
  const [overlay, setOverlay] = useState<string | null>(null);
  // p.91's "Module appearance". Runtime state beside the current page and
  // the section overrides (decision 0002 §3): a published module opens light
  // for every viewer, because a saved app is not a saved session.
  const [scheme, setScheme] = useState<"light" | "dark">("light");
  // `undefined` when this module has no Variable-Based Page Selection at all,
  // which `pageState` reads differently from a variable holding "".
  //
  // **It is also `undefined` for the first few hundred milliseconds** of every
  // module that *does* have one, because `resolved` starts empty and variables
  // are computed on the server. So a backed module opens on its default page
  // and moves to the variable's page once the first resolve lands. That is the
  // right behaviour - the alternative is a blank frame - and it matches p.75's
  // lazy computation, but it is worth knowing about, because during that
  // window an event wins unconditionally and a test written without waiting
  // for the variable will believe whatever it sees.
  const pageVariable = pageSelection ? resolved[pageSelection] : undefined;
  const page = pageState(
    pageOverride,
    pageVariable,
    defaultPageNode(layout),
    (id) => pageNodeFor(layout, id),
  );
  // p.82's collapse state, by the same argument as the page above: runtime
  // state with exactly the lifetime of the variable values beside it.
  const [collapsed, setCollapsedState] = useState<Record<string, CollapseOverride>>({});
  // p.54's Tabs sections, by the same argument again. Separate from
  // `collapsed` because one section can be both collapsible and tabbed.
  const [tabs, setTabState] = useState<Record<string, TabOverride>>({});

  // And running an action (roadmap 1.3), by the same argument.
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<{ ok: boolean; message: string } | null>(null);
  // One place decides how a failure is reported, because a write can fail two
  // ways and they are the same news to whoever clicked: the request can be
  // refused (a property with no column mapped; an action deleted since the app
  // was saved - which lands here rather than at save time, on purpose, so a
  // saved document does not stop being valid because live state moved), or it
  // can be accepted and the write-back can fail afterwards. Two handlers
  // reporting separately is two chances for one of them to say "Saved." about
  // something that was not.
  const failed = (message: string) =>
    setStatus({ ok: false, message: message || "The action did not go through." });

  const runAction = useMutation({
    mutationFn: (input: {
      action: string;
      instanceId: string;
      values: Record<string, string>;
    }) => actionApi.execute(workspaceId, projectId, input.action, input.instanceId, input.values),
    onSuccess: async (result) => {
      if (!result.ok) return failed(result.error ?? "");
      setStatus({ ok: true, message: "Saved." });
      // Everything reading object data is now one write out of date.
      await invalidateCanvasReads(queryClient);
    },
    onError: (e: Error) => failed(e instanceof ApiError ? e.message : ""),
  });

  return (
    <CanvasVariableProvider value={{ declared, events, resolved, pending }}>
      <CanvasPageProvider
        value={{
          current: page,
          // Navigating to a page closes whatever was covering it: an overlay
          // left open over a page you did not open it from is a layer with no
          // way back.
          go: (id) => {
            setOverlay(null);
            // The variable's value *now* is what makes "until the variable
            // changes" checkable later. Recorded here rather than by the
            // caller: a Tabs widget and a `navigate` effect both call this,
            // and only one of them could reasonably know about p.81.
            setPageOverride({ nodeId: id, against: asPageId(pageVariable) });
          },
          overlay,
          openOverlay: setOverlay,
          closeOverlay: () => setOverlay(null),
          collapsed,
          setCollapsed: (id, override) =>
            setCollapsedState((current) => ({ ...current, [id]: override })),
          tabs,
          setTab: (id, override) =>
            setTabState((current) => ({ ...current, [id]: override })),
          scheme,
          toggleScheme: () => setScheme((s) => (s === "dark" ? "light" : "dark")),
          // p.85's Recompute: record the ask, then make a resolve happen. The
          // tick is what makes it happen at all, since none of the *parameter*
          // values changed - and the ask travels as its own field rather than
          // as a hole in `held`, because for `only_on_event` a hole in `held`
          // is what a fresh page looks like.
          recompute: (names) => {
            const next = request(declared, askRef.current, names);
            if (next === askRef.current) return;
            askRef.current = next;
            setRecomputeTick((n) => n + 1);
          },
        }}
      >
        <CanvasActionsProvider
          value={{
            run: (config, context) => {
              const instanceId = context.object?.id;
              // No subject is not a failure to report - it is a click on a
              // row nobody has selected yet, and the effect simply does not
              // apply. Reporting it would train people to ignore the strip.
              if (!instanceId) return;
              setStatus(null);
              runAction.mutate({
                action: config.action,
                instanceId,
                values: config.values ?? {},
              });
            },
            status,
            dismiss: () => setStatus(null),
          }}
        >
          {routing && <RoutingSync layout={layout} declared={declared} />}
          {/* p.91's theme, applied where every widget under it is reached at
              once. `data-scheme` redefines the tokens rather than restyling
              anything (p.59-60's rule, one level up), so a widget written
              before this existed follows it too - which is the same argument
              that block's own comment makes for sections. The wrapper is
              `display: contents` so it changes no layout: a module whose
              widgets suddenly sat inside an extra box would be a theme toggle
              that moved things. */}
          <div data-scheme={scheme} data-testid="module-scheme"
            style={{ display: "contents" }}>
            {children}
          </div>
          {/* Below the module rather than in it: p.206 ties state saving to
              the module *header*, and this is the nearest thing we have to
              module chrome that every route already renders. */}
          {stateSaving?.enabled && (
            <StateBar
              workspaceId={workspaceId}
              projectId={projectId}
              appId={appId}
              published={published}
              layout={layout}
              settings={stateSaving}
            />
          )}
          <ActionStatus status={status} onDismiss={() => setStatus(null)} />
        </CanvasActionsProvider>
      </CanvasPageProvider>
    </CanvasVariableProvider>
  );
}


/** What the last `run_action` did.
 *
 * A write triggered by an event has no form to report back into - the button
 * that fired it has already done its job and looks the same either way. So it
 * reports here, once, for the whole module: an app where a click silently
 * failed to save is the failure mode this whole effect would otherwise add.
 */
function ActionStatus({
  status,
  onDismiss,
}: {
  status: { ok: boolean; message: string } | null;
  onDismiss: () => void;
}) {
  if (!status) return null;
  return (
    <div className={`canvas-action-status${status.ok ? "" : " bad"}`} role="status">
      <span>{status.message}</span>
      <button type="button" className="btn quiet" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
  );
}
