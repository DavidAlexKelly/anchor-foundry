"use client";

/**
 * p.69's Ontology cleanup queue (§325; `ontology-manager` p.68-74).
 *
 * > "The Ontology cleanup tool is a safe way to delete object types… The tool
 * > aims to help Ontology editors determine the safety of deleting an object
 * > type and provides a deprecation option which informs object type users of
 * > its future removal." (p.68)
 *
 * > "By default, the table is sorted by the highest priority among the flags
 * > that an object type triggers." (p.70)
 *
 * **Nothing here re-ranks or re-decides.** The server sends the rows in p.70's
 * order with the flags already sorted worst-first; this draws them. A second
 * ordering in the browser would be free to disagree with the one that put the
 * rows where they are, and a queue whose headlines contradict its own sort is
 * worse than an unsorted one (§146).
 *
 * The wording is in `lib/ontology-cleanup.ts`.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ApiError, objects as objApi } from "@/lib/api";
import {
  NOTHING_TO_DO,
  alsoText,
  deleteWarning,
  flagHint,
  flagLabel,
  headline,
  snoozeText,
  stillInUse,
} from "@/lib/ontology-cleanup";

export function CleanupQueue({
  workspaceId,
  workspaceSlug,
}: {
  workspaceId: string;
  workspaceSlug: string;
}) {
  const [flag, setFlag] = useState("");
  const [includeSnoozed, setIncludeSnoozed] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const client = useQueryClient();

  const queue = useQuery({
    queryKey: ["ontology-cleanup", workspaceId, flag, includeSnoozed],
    queryFn: () =>
      objApi.cleanupQueue(workspaceId, {
        flag: flag || undefined,
        includeSnoozed,
      }),
  });

  async function refresh() {
    await client.invalidateQueries({ queryKey: ["ontology-cleanup"] });
  }

  const snooze = useMutation({
    mutationFn: (typeId: string) => objApi.snoozeType(workspaceId, typeId, 14),
    onSuccess: refresh,
  });
  const wake = useMutation({
    mutationFn: (typeId: string) => objApi.wakeType(workspaceId, typeId),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (typeId: string) => objApi.removeType(workspaceId, typeId),
    onSuccess: async () => {
      setConfirming(null);
      await refresh();
    },
  });

  if (queue.isPending) return <div className="state">Finding candidates…</div>;
  if (queue.isError) {
    // **Said, not drawn as an empty queue.** "Nothing needs cleaning up" and
    // "we could not tell you" are opposite answers, and this screen's buttons
    // delete things — a reader who believes the first is a reader who stops
    // checking.
    return (
      <div className="state error" data-testid="cleanup-error">
        Couldn&apos;t work out which object types need cleaning up.
      </div>
    );
  }

  const rows = queue.data ?? [];
  // Every flag present in the answer, so the filter offers only what the queue
  // can actually show — a dropdown listing a flag nothing triggers is a
  // control that looks like it works (§214).
  const offered = Array.from(new Set(rows.flatMap((r) => r.flags))).sort();

  return (
    <section data-testid="cleanup-queue">
      <div className="row-actions" style={{ marginBottom: 12 }}>
        <label className="field" style={{ maxWidth: 260 }}>
          <span>Flag</span>
          <select
            data-testid="cleanup-flag"
            value={flag}
            onChange={(e) => setFlag(e.target.value)}
          >
            <option value="">Any flag</option>
            {offered.map((f) => (
              <option key={f} value={f}>{flagLabel(f)}</option>
            ))}
          </select>
        </label>
        <label className="slug">
          <input
            type="checkbox"
            data-testid="cleanup-show-snoozed"
            checked={includeSnoozed}
            onChange={(e) => setIncludeSnoozed(e.target.checked)}
          />{" "}
          {/* p.71: "Use the table filters to view all the actions you have
              already selected." */}
          Show snoozed
        </label>
      </div>

      {rows.length === 0 ? (
        <p className="login-note" data-testid="cleanup-empty">{NOTHING_TO_DO}</p>
      ) : (
        <table className="table" data-testid="cleanup-table">
          <thead>
            <tr>
              <th>Object type</th>
              <th>Why</th>
              <th>Used</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} data-testid={`cleanup-${row.api_name}`}>
                <td>
                  <Link href={`/${workspaceSlug}/explore?type=${row.id}`}>
                    {row.display_name}
                  </Link>
                  <div className="slug">{row.api_name}</div>
                </td>
                <td>
                  <strong data-testid="cleanup-headline">{headline(row)}</strong>
                  <div className="slug">{flagHint(row.flags[0] ?? "")}</div>
                  {alsoText(row) && (
                    <div className="slug" data-testid="cleanup-also">
                      {alsoText(row)}
                    </div>
                  )}
                </td>
                <td className="count">
                  {/* **The evidence against deleting, beside the evidence
                      for.** A type flagged five ways that four hundred people
                      still read is a documentation problem, not a cleanup
                      candidate. */}
                  <span data-testid="cleanup-interactions">{row.interactions}</span>
                  {stillInUse(row) && <div className="slug">still in use</div>}
                </td>
                <td>
                  <div className="row-actions">
                    {row.snoozed_until ? (
                      <>
                        <span className="slug" data-testid="cleanup-snoozed">
                          {snoozeText(row.snoozed_until)}
                        </span>
                        <button
                          className="btn quiet"
                          style={{ padding: "3px 9px", fontSize: 12 }}
                          data-testid={`cleanup-wake-${row.api_name}`}
                          onClick={() => wake.mutate(row.id)}
                        >
                          Un-snooze
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        data-testid={`cleanup-snooze-${row.api_name}`}
                        onClick={() => snooze.mutate(row.id)}
                      >
                        Snooze
                      </button>
                    )}
                    <button
                      className="btn quiet"
                      style={{ padding: "3px 9px", fontSize: 12 }}
                      data-testid={`cleanup-delete-${row.api_name}`}
                      onClick={() => setConfirming(row.id)}
                    >
                      Delete
                    </button>
                  </div>
                  {confirming === row.id && (
                    /* **Confirmed in place, with the warning naming the type.**
                       p.71's delete removes "associated data from object
                       storage" and is the one action here that cannot be
                       undone, so the sentence says both. */
                    <div className="form-error" data-testid="cleanup-confirm">
                      <p>{deleteWarning(row)}</p>
                      <div className="row-actions">
                        <button
                          className="btn"
                          data-testid="cleanup-confirm-delete"
                          disabled={remove.isPending}
                          onClick={() => remove.mutate(row.id)}
                        >
                          {remove.isPending ? "Deleting…" : "Delete it"}
                        </button>
                        <button
                          className="btn quiet"
                          data-testid="cleanup-confirm-cancel"
                          onClick={() => setConfirming(null)}
                        >
                          Keep it
                        </button>
                      </div>
                      {remove.isError && (
                        <p data-testid="cleanup-delete-error">
                          {remove.error instanceof ApiError
                            ? remove.error.message
                            : "Couldn't delete this object type."}
                        </p>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
