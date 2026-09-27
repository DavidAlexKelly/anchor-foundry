"use client";

/**
 * HTTPS listeners, on the Data Connection screen (§516; `data-connection`
 * p.249-266).
 *
 * > "Navigate to Data Connection > Listeners to connect the Palantir platform
 * > to external systems and workflows." (p.261)
 *
 * A listener is made stopped, with one endpoint, and shows the address a
 * sender posts to, whether it is running, how it verifies requests, and the
 * events it has taken, newest first (p.261's stream). The rules for what may
 * be saved are `lib/listeners.ts`'s.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Field } from "@/components/dialog";
import { ApiError, api as platformApi, listeners as api } from "@/lib/api";
import { canEditProject } from "@/lib/test-runs";
import { bytesText } from "@/lib/bytes";
import {
  BLANK_LISTENER, ROTATIONS, VERIFICATIONS, curlExample, draftBody, draftProblem, endpointState,
  extendedExpiry, needsHeader, rotateBody, statusText, verificationText, whyNoRotation,
  type Listener, type ListenerDraft, type Verification,
} from "@/lib/listeners";

export function ListenersPanel({ workspaceId, projectId }: { workspaceId: string; projectId: string }) {
  const queryClient = useQueryClient();
  const key = ["listeners", projectId];
  const list = useQuery({ queryKey: key, queryFn: () => api.list(workspaceId, projectId) });
  // Managing a listener is an editor's; a reader is shown the listeners and
  // their events and offered nothing that would be refused (§214).
  const project = useQuery({
    queryKey: ["project", workspaceId, projectId],
    queryFn: () => platformApi.project(workspaceId, projectId),
  });
  const editor = canEditProject(project.data?.effective_role ?? "viewer");
  const [draft, setDraft] = useState<ListenerDraft>(BLANK_LISTENER);
  const [adding, setAdding] = useState(false);
  const create = useMutation({
    mutationFn: () => api.create(workspaceId, projectId, draftBody(draft)),
    onSuccess: async () => {
      setDraft(BLANK_LISTENER);
      setAdding(false);
      await queryClient.invalidateQueries({ queryKey: key });
    },
  });
  const problem = draftProblem(draft);
  const set = <K extends keyof ListenerDraft>(k: K, v: ListenerDraft[K]) =>
    setDraft((d) => ({ ...d, [k]: v }));

  return (
    <section className="card" data-testid="listeners-panel" style={{ marginTop: 24 }}>
      <div className="page-head" style={{ marginBottom: 8 }}>
        <div>
          <h2 style={{ margin: 0 }}>Listeners</h2>
          <p className="sub" style={{ margin: 0 }}>
            Addresses other systems send events to, for systems that cannot call this platform
            themselves.
          </p>
        </div>
        {editor && !adding && (
          <button type="button" className="btn" data-testid="listener-new" onClick={() => setAdding(true)}>
            New listener
          </button>
        )}
      </div>

      {adding && (
        <form
          data-testid="listener-form"
          onSubmit={(e) => {
            e.preventDefault();
            // Submit is disabled while there is a problem, which also stops
            // Enter in a field from submitting the form.
            create.mutate();
          }}
        >
          <Field label="Name">
            <input
              data-testid="listener-name"
              value={draft.display_name}
              maxLength={200}
              onChange={(e) => set("display_name", e.target.value)}
            />
          </Field>
          <Field label="Verification">
            <select
              data-testid="listener-verification"
              value={draft.verification}
              onChange={(e) => set("verification", e.target.value as Verification)}
            >
              {(Object.keys(VERIFICATIONS) as Verification[]).map((v) => (
                <option key={v} value={v}>{VERIFICATIONS[v].label}</option>
              ))}
            </select>
            <span className="field-hint">{VERIFICATIONS[draft.verification].hint}</span>
          </Field>
          {needsHeader(draft.verification) && (
            <Field label="Header">
              <input
                data-testid="listener-header"
                value={draft.verification_header}
                placeholder="X-Signature"
                onChange={(e) => set("verification_header", e.target.value)}
              />
            </Field>
          )}
          {draft.verification !== "none" && (
            <Field label={draft.verification === "basic" ? "username:password" : "Secret"}>
              <input
                type="password"
                data-testid="listener-secret"
                value={draft.secret}
                autoComplete="off"
                onChange={(e) => set("secret", e.target.value)}
              />
              <span className="field-hint">Kept in the secrets store; never shown again.</span>
            </Field>
          )}
          {problem && <p className="login-note" data-testid="listener-problem">{problem}</p>}
          {create.isError && (
            <div className="form-error" data-testid="listener-error">
              {create.error instanceof ApiError ? create.error.message : "Couldn't create it."}
            </div>
          )}
          <div className="form-actions">
            <button type="button" className="btn quiet" onClick={() => setAdding(false)}>Cancel</button>
            <button type="submit" className="btn" data-testid="listener-create" disabled={!!problem}>
              Create listener
            </button>
          </div>
        </form>
      )}

      {list.data?.length === 0 && !adding && (
        <p className="soft" data-testid="no-listeners">This project has no listeners.</p>
      )}
      {list.data?.map((listener) => (
        <ListenerCard
          key={listener.id}
          workspaceId={workspaceId}
          projectId={projectId}
          listener={listener}
          editor={editor}
        />
      ))}
    </section>
  );
}

function ListenerCard({
  workspaceId, projectId, listener, editor,
}: { workspaceId: string; projectId: string; listener: Listener; editor: boolean }) {
  const queryClient = useQueryClient();
  const [showing, setShowing] = useState(false);
  const events = useQuery({
    queryKey: ["listener-events", listener.id, listener.events],
    queryFn: () => api.events(workspaceId, projectId, listener.id),
    enabled: showing,
    // Senders post whenever they like, so an open list keeps up with them.
    refetchInterval: 5000,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["listeners", projectId] });
  const toggle = useMutation({
    mutationFn: () => (listener.running ? api.stop : api.start)(workspaceId, projectId, listener.id),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => api.remove(workspaceId, projectId, listener.id),
    onSuccess: refresh,
  });
  const active = listener.endpoints.find((e) => e.active);
  const [rotation, setRotation] = useState<keyof typeof ROTATIONS>("day");
  const endpointChange = useMutation({
    mutationFn: (call: () => Promise<Listener>) => call(),
    onSuccess: refresh,
  });

  return (
    <div className="card" data-testid="listener" data-name={listener.display_name} style={{ margin: "10px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
        <div>
          <strong>{listener.display_name}</strong>
          <p className="soft" style={{ margin: 0 }} data-testid="listener-status">{statusText(listener)}</p>
          <p className="soft" style={{ margin: 0 }} data-testid="listener-verification-text">
            Verification: {verificationText(listener)}
          </p>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {editor && (
            <button type="button" className="btn" data-testid="listener-toggle" onClick={() => toggle.mutate()}>
              {listener.running ? "Stop" : "Start"}
            </button>
          )}
          <button type="button" className="btn quiet" data-testid="listener-events-toggle"
                  onClick={() => setShowing((s) => !s)}>
            {showing ? "Hide events" : "Events"}
          </button>
          {editor && (
            <button type="button" className="btn quiet" data-testid="listener-delete" onClick={() => remove.mutate()}>
              Delete
            </button>
          )}
        </div>
      </div>
      {active && (
        <>
          <p className="slug" style={{ margin: "8px 0 2px" }}>Endpoint</p>
          <code data-testid="listener-url">{active.url}</code>
          <pre className="soft" data-testid="listener-curl" style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
            {curlExample(active.url)}
          </pre>
        </>
      )}
      {/* p.258-259's rotation (§517): every endpoint with what it is doing,
          and the way to move senders to a new address without downtime. */}
      <ul className="link-list" data-testid="listener-endpoints" style={{ margin: "4px 0" }}>
        {listener.endpoints.filter((e) => !e.active).map((endpoint) => (
          <li key={endpoint.id} data-testid="listener-endpoint">
            <code style={{ fontSize: 12 }}>{endpoint.url}</code>{" "}
            <span className="soft" data-testid="listener-endpoint-state">
              {endpointState(endpoint, Date.now())}
            </span>
            {editor && !endpoint.expired && endpoint.expires_at && (
              <button type="button" className="btn quiet" data-testid="listener-endpoint-extend"
                      onClick={() => endpointChange.mutate(() => api.extend(
                        workspaceId, projectId, listener.id, endpoint.id,
                        extendedExpiry(endpoint.expires_at as string, Date.now())))}>
                Extend a day
              </button>
            )}
            {editor && (
              <button type="button" className="btn quiet" data-testid="listener-endpoint-delete"
                      onClick={() => endpointChange.mutate(() => api.deleteEndpoint(
                        workspaceId, projectId, listener.id, endpoint.id))}>
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>
      {editor && (
        whyNoRotation(listener.endpoints) ? (
          <p className="soft" data-testid="listener-no-rotation">{whyNoRotation(listener.endpoints)}</p>
        ) : (
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <select
              data-testid="listener-rotation"
              value={rotation}
              onChange={(e) => setRotation(e.target.value as keyof typeof ROTATIONS)}
            >
              {(Object.keys(ROTATIONS) as (keyof typeof ROTATIONS)[]).map((k) => (
                <option key={k} value={k}>{ROTATIONS[k]}</option>
              ))}
            </select>
            <button type="button" className="btn quiet" data-testid="listener-rotate"
                    onClick={() => endpointChange.mutate(() => api.rotate(
                      workspaceId, projectId, listener.id, rotateBody(rotation, Date.now())))}>
              Rotate endpoint
            </button>
          </div>
        )
      )}
      {endpointChange.isError && (
        <div className="form-error" data-testid="listener-endpoint-error">
          {endpointChange.error instanceof ApiError ? endpointChange.error.message : "Couldn't change the endpoint."}
        </div>
      )}
      {showing && (
        <div data-testid="listener-events">
          {events.data?.length === 0 && <p className="soft">Nothing received yet.</p>}
          {events.data?.map((event) => (
            <div key={event.id} data-testid="listener-event" style={{ borderTop: "1px solid var(--line)", padding: "6px 0" }}>
              <p className="slug" style={{ margin: 0 }}>
                {new Date(event.received_at).toLocaleString()} · {event.content_type ?? "no content type"} ·{" "}
                {bytesText(event.size_bytes)}
              </p>
              <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap" }} data-testid="listener-event-body">
                {event.preview === null
                  ? "Not text; kept as it arrived."
                  : event.preview + (event.truncated ? "…" : "")}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
