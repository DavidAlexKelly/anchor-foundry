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

import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { canvas as canvasApi } from "@/lib/api";
import { CanvasVariableProvider, useCanvasParameters } from "./context";

const DEBOUNCE_MS = 250;

export function VariableBridge({
  workspaceId,
  projectId,
  appId,
  declared,
  events,
  published = false,
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
        ? canvasApi.evaluatePublishedVariables(workspaceId, appId, raw)
        : canvasApi.evaluateVariables(workspaceId, projectId, appId, raw))
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
  }, [serialised, enabled, appId]);

  return (
    <CanvasVariableProvider value={{ declared, events, resolved, pending }}>
      {children}
    </CanvasVariableProvider>
  );
}
