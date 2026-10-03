"use client";

/**
 * p.255's proposal to promote an object type (§767).
 *
 * > "Only users with the `Ontology Owner` role on the ontology level can
 * > directly apply the `promoted` status. Other users must submit a proposal
 * > for review and approval by an `Ontology Owner`." (p.255)
 *
 * Two halves. `PromotionRequestControl` sits under the object type's status
 * field, where `promoted` is left out for anyone but an admin, and asks.
 * `PromotionRequestsPanel` is where an admin answers. Approving applies the
 * status as the admin's own edit would, on the server.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Field } from "@/components/dialog";
import { ApiError, objects as objApi } from "@/lib/api";
import { pendingFor, promotionOffer, requestLine } from "@/lib/promotion-requests";
import type { OntologyStatus } from "@/lib/types";

function useRequests(workspaceId: string) {
  return useQuery({
    queryKey: ["promotion-requests", workspaceId],
    queryFn: () => objApi.promotionRequests(workspaceId),
  });
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Could not save.";
}

export function PromotionRequestControl({
  workspaceId,
  typeId,
  status,
  canPromote,
}: {
  workspaceId: string;
  typeId: string;
  /** The type's stored status: a proposal is about what is saved. */
  status: OntologyStatus;
  canPromote: boolean;
}) {
  const requests = useRequests(workspaceId);
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const pending = pendingFor(requests.data ?? [], typeId);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["promotion-requests", workspaceId] });
  const ask = useMutation({
    mutationFn: () => objApi.requestPromotion(workspaceId, typeId, reason),
    onSuccess: async () => {
      setReason("");
      await refresh();
    },
  });
  const withdraw = useMutation({
    mutationFn: (id: string) => objApi.decidePromotion(workspaceId, id, "withdraw"),
    onSuccess: refresh,
  });

  if (!requests.data) return null;
  const offer = promotionOffer(status, canPromote, pending);
  if (offer === "none") return null;
  return (
    <div data-testid="promotion-request">
      {offer === "waiting" && pending && (
        <p className="field-hint" data-testid="promotion-waiting">
          Promotion requested, waiting for an admin. {requestLine(pending)}
          {pending.mine && (
            <button
              type="button"
              className="btn quiet"
              style={{ marginLeft: 8, padding: "2px 8px", fontSize: 12 }}
              data-testid="promotion-withdraw"
              disabled={withdraw.isPending}
              onClick={() => withdraw.mutate(pending.id)}
            >
              Withdraw
            </button>
          )}
        </p>
      )}
      {offer === "ask" && (
        <Field
          label="Request promotion"
          hint="p.255 — only a workspace admin can promote an object type. Others propose it, and an admin approves."
        >
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="text"
              data-testid="promotion-reason"
              placeholder="Why it is ready"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <button
              type="button"
              className="btn quiet"
              data-testid="promotion-ask"
              disabled={ask.isPending}
              onClick={() => ask.mutate()}
            >
              Request
            </button>
          </div>
        </Field>
      )}
      {(ask.isError || withdraw.isError) && (
        <p className="form-error" data-testid="promotion-error">
          {errorText(ask.error ?? withdraw.error)}
        </p>
      )}
    </div>
  );
}

export function PromotionRequestsPanel({
  workspaceId,
  isAdmin,
}: {
  workspaceId: string;
  isAdmin: boolean;
}) {
  const requests = useRequests(workspaceId);
  const queryClient = useQueryClient();
  const [notes, setNotes] = useState<Record<string, string>>({});
  const decide = useMutation({
    mutationFn: ({ id, verdict }: { id: string; verdict: "approve" | "reject" }) =>
      objApi.decidePromotion(workspaceId, id, verdict, notes[id] ?? ""),
    onSuccess: async (decided) => {
      await queryClient.invalidateQueries({ queryKey: ["promotion-requests", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["object-type", decided.object_type_id] });
    },
  });

  // Nothing waiting is nothing to show: a heading over an empty list would
  // sit on every ontology page saying so.
  if (!requests.data || requests.data.length === 0) return null;
  return (
    <>
      <div className="page-head" style={{ marginTop: 32 }}>
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Promotion requests</h2>
          <p className="sub">
            {isAdmin
              ? "Object types somebody has asked you to promote (p.255)"
              : "Waiting for a workspace admin to approve (p.255)"}
          </p>
        </div>
      </div>
      <table className="table" data-testid="promotion-requests" style={{ marginBottom: 28 }}>
        <thead>
          <tr><th>Object type</th><th>Request</th><th aria-label="Decision" /></tr>
        </thead>
        <tbody>
          {requests.data.map((r) => (
            <tr key={r.id} data-testid={`promotion-row-${r.object_type_api_name}`}>
              <td>
                <strong>{r.object_type_name}</strong>
                <div className="slug">{r.object_type_api_name} · {r.object_type_status}</div>
              </td>
              <td>{requestLine(r)}</td>
              <td>
                {isAdmin && (
                  <div className="row-actions">
                    <input
                      type="text"
                      aria-label={`Note on ${r.object_type_api_name}`}
                      placeholder="Note (optional)"
                      value={notes[r.id] ?? ""}
                      onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })}
                    />
                    <button
                      type="button"
                      className="btn"
                      aria-label={`Approve promotion of ${r.object_type_api_name}`}
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: r.id, verdict: "approve" })}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="btn quiet"
                      aria-label={`Reject promotion of ${r.object_type_api_name}`}
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: r.id, verdict: "reject" })}
                    >
                      Reject
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {decide.isError && (
        <p className="form-error" data-testid="promotion-decide-error">
          {errorText(decide.error)}
        </p>
      )}
    </>
  );
}
