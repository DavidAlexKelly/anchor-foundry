"use client";

/**
 * A source's egress policies (Foundry `data-connection` p.12, p.37, p.103;
 * decision 0013; §264).
 *
 * §263 built the rule and enforced it at all four outbound paths; this is the
 * screen. For a security control the gap between those two is worse than the
 * usual §252 shape — an allowlist nobody can see is one nobody is checking —
 * and p.37 writes the screen's job out in a sentence: "confirm that the correct
 * egress policies are attached to the source, and that the host, port, and
 * protocol they allow match the system you are connecting to."
 *
 * **So the panel shows both lists.** What the source is *allowed* to reach is
 * only useful next to what it will *try* to reach, and the second one is
 * otherwise spread over four fields on a different form. It does not compute
 * whether a call would be permitted: a browser that answered "allowed" where
 * the server refuses would be worse than one that says nothing, and Test — one
 * button away, running the server's own check — is the answer that is true.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Dialog, Field } from "@/components/dialog";
import { ApiError, egressPolicies as api } from "@/lib/api";
import {
  blankPolicy,
  describe,
  destinationsFor,
  draftFor,
  problem,
  summary,
  toPayload,
  type PolicyDraft,
} from "@/lib/egress-policy";
import type { Connection } from "@/lib/types";

export function EgressDialog({
  workspaceId,
  projectId,
  connection,
  canEdit,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  connection: Connection;
  canEdit: boolean;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<PolicyDraft>(blankPolicy());
  const [failed, setFailed] = useState<string | null>(null);

  const key = ["egress-policies", connection.id];
  const listed = useQuery({
    queryKey: key,
    queryFn: () => api.list(workspaceId, projectId, connection.id),
  });
  const policies = listed.data ?? [];

  const done = () => {
    setFailed(null);
    return client.invalidateQueries({ queryKey: key });
  };
  const add = useMutation({
    mutationFn: () => api.create(workspaceId, projectId, connection.id, toPayload(draft)),
    onSuccess: async () => {
      setDraft(blankPolicy());
      await done();
    },
    // The server refuses cases this form cannot see - a host that resolves
    // somewhere the platform's own guard forbids, a policy added by somebody
    // else a moment ago - so its sentence is shown rather than a generic one.
    onError: (error) =>
      setFailed(error instanceof ApiError ? error.message : "Could not add that policy."),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.remove(workspaceId, projectId, connection.id, id),
    onSuccess: done,
    onError: (error) =>
      setFailed(error instanceof ApiError ? error.message : "Could not remove that policy."),
  });

  const said = problem(draft, policies);
  const destinations = destinationsFor(connection.source_type, connection.config);

  return (
    <Dialog open wide title={`Networking — ${connection.name}`} onClose={onClose}>
      <div data-testid="egress-panel">
        {/* Decision 0013 §2's sentence. An empty table means *unrestricted*,
            which is the opposite of what an empty table looks like, so the
            state is written above it rather than inferred from it. */}
        <p className="field-hint" data-testid="egress-summary">
          {listed.isPending ? "Loading policies…" : summary(policies)}
        </p>

        {/* p.37's step 1: the destinations this source is configured to reach,
            beside the ones it is allowed to. */}
        <h3 style={{ marginBottom: 4 }}>This source is configured to reach</h3>
        {destinations.known.length > 0 && (
          <table className="table" data-testid="egress-destinations">
            <thead>
              <tr>
                <th>Destination</th>
                <th>From</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {destinations.known.map((destination) => (
                <tr key={`${destination.label}:${describe(destination)}`}>
                  <td className="slug">{describe(destination)}</td>
                  <td>{destination.label}</td>
                  <td className="row-actions">
                    {canEdit && (
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        // Fills the form rather than saving, because p.37 asks
                        // somebody to *confirm* the policies match — and a
                        // one-click write lets them agree with a suggestion
                        // they have not read.
                        onClick={() => {
                          setFailed(null);
                          setDraft(draftFor(destination));
                        }}
                      >
                        Use as a policy
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {destinations.caveat && (
          <p className="field-hint" data-testid="egress-caveat">
            {destinations.caveat}
          </p>
        )}

        <h3 style={{ marginTop: 18, marginBottom: 4 }}>Allowed destinations</h3>
        {policies.length > 0 && (
          <table className="table" data-testid="egress-policies">
            <thead>
              <tr>
                <th>Destination</th>
                <th>Why</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {policies.map((policy) => (
                <tr key={policy.id}>
                  <td className="slug">{describe(policy)}</td>
                  <td>{policy.description || <span className="field-hint">—</span>}</td>
                  <td className="row-actions">
                    {canEdit && (
                      <button
                        className="btn danger"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(policy.id)}
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {canEdit && (
          <div style={{ marginTop: 14 }}>
            <Field label="Host">
              <input
                className="input"
                data-testid="egress-host"
                value={draft.host}
                placeholder="api.example.com"
                onChange={(e) => {
                  setFailed(null);
                  setDraft({ ...draft, host: e.target.value });
                }}
              />
            </Field>
            <Field label="Port">
              <input
                className="input"
                data-testid="egress-port"
                value={draft.port}
                placeholder="any"
                onChange={(e) => {
                  setFailed(null);
                  setDraft({ ...draft, port: e.target.value });
                }}
              />
            </Field>
            {/* Said here rather than only on the row, because "any" in a box is
                a value somebody can read as the string "any". */}
            <p className="field-hint">
              Leave the port empty to allow any port on that host.
            </p>
            <Field label="Why">
              <input
                className="input"
                data-testid="egress-description"
                value={draft.description}
                placeholder="the vendor API"
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            </Field>

            <div className="row-actions" style={{ marginTop: 10 }}>
              <button
                className="btn"
                data-testid="egress-add"
                disabled={said !== null || add.isPending}
                onClick={() => add.mutate()}
              >
                {add.isPending ? "Adding…" : "Allow this destination"}
              </button>
              {/* The form's own refusal only once somebody has typed
                  something: `problem` refuses a blank draft, and a message
                  under an empty form is an error about not having started. */}
              {draft.host.trim() !== "" && said && (
                <span className="field-hint" data-testid="egress-problem">
                  {said}
                </span>
              )}
              {failed && (
                <span className="field-hint" data-testid="egress-failed">
                  {failed}
                </span>
              )}
            </div>
          </div>
        )}

        <div className="row-actions" style={{ marginTop: 16 }}>
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </Dialog>
  );
}
