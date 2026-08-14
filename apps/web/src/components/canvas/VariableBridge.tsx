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
import { RoutingSync } from "./RoutingSync";

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
  /** The layout, for the page walk routing needs. Only read when `routing`. */
  layout?: unknown;
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

  const resolve = useMutation({
    mutationFn: (raw: Record<string, unknown>) => {
      const ticket = ++latest.current;
      return (published
        ? canvasApi.evaluatePublishedVariables(workspaceId, appId, raw, bound)
        : canvasApi.evaluateVariables(workspaceId, projectId, appId, raw, bound))
        .then((data) => ({ data, ticket }));
    },
    onSuccess: ({ data, ticket }) => {
      if (ticket !== latest.current) return;
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
  }, [serialised, enabled, appId, (bound ?? []).join(",")]);

  // The current page lives here too: it is runtime state with exactly the
  // lifetime of the variable values beside it, and a separate provider would
  // be a second thing to mount in both routes and forget in one.
  const [page, setPage] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<string | null>(null);

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
            setPage(id);
          },
          overlay,
          openOverlay: setOverlay,
          closeOverlay: () => setOverlay(null),
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
          {children}
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
