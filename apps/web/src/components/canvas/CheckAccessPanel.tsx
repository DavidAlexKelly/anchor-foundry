"use client";

/** p.92's Check access panel (§412).
 *
 * > "You can use the Check access panel in the sidebar to easily check a
 * > user's access on a Workshop module. This will show if they meet the access
 * > requirement on the Workshop module, as well as additional data
 * > requirements to see object types, link types, action types, and
 * > functions." (p.92)
 *
 * What the answer *means* is `check-access.ts`'s, and it is a separate file so
 * the wording of a refusal can be tested: the panel's value is entirely in
 * being read correctly, and "cannot open" appearing where "can open, cannot
 * act" belongs would send a builder to change the wrong setting.
 *
 * **Nothing is asked until somebody is named.** An access check is a question
 * about a person, and a panel that opened onto the first name in the directory
 * would put an answer about a stranger on the screen under a heading the
 * builder did not write.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { canvas as canvasApi, api } from "@/lib/api";
import {
  KINDS, NO_FUNCTIONS, STATUS_LABELS, byKind, label, met, moduleReason,
  moduleVerdict, summary,
} from "./check-access";

export function CheckAccessPanel({
  workspaceId,
  projectId,
  appId,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
}) {
  const [userId, setUserId] = useState("");

  const members = useQuery({
    queryKey: ["org-members"],
    queryFn: () => api.orgMembers(),
  });

  const access = useQuery({
    queryKey: ["module-access", appId, userId],
    queryFn: () => canvasApi.checkAccess(workspaceId, projectId, appId, userId),
    enabled: userId !== "",
  });

  const answer = access.data;
  const rows = answer ? byKind(answer.resources) : [];

  return (
    <div className="canvas-access" data-testid="access-panel">
      <label className="field">
        <span className="field-label">Check access for</span>
        <select
          data-testid="access-user"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
        >
          <option value="">Choose a user…</option>
          {(members.data ?? []).map((u) => (
            <option key={u.id} value={u.id}>
              {u.display_name} ({u.email})
            </option>
          ))}
        </select>
      </label>

      {userId === "" && (
        <p className="soft" data-testid="access-idle">
          Pick somebody to see what this module needs of them.
        </p>
      )}
      {access.isPending && userId !== "" && <p className="soft">Checking…</p>}
      {access.isError && (
        <p className="state error" data-testid="access-error">
          Couldn&apos;t check this user&apos;s access.
        </p>
      )}

      {answer && (
        <>
          {/* p.92's first half. Its own block above the requirements, because
              it is the one a builder can act on without reading further - and
              because the module answer and the data answers are different
              questions with different remedies. */}
          <div
            className="canvas-access-verdict"
            data-testid="access-module"
            data-open={answer.can_open ? "yes" : "no"}
            data-edit={answer.can_edit ? "yes" : "no"}
          >
            <strong>{moduleVerdict(answer)}</strong>
            <span className="soft" data-testid="access-reason">
              {moduleReason(answer)}
            </span>
          </div>

          {/* p.92's second half, and the sentence that makes the first half
              worth showing: the two can disagree. */}
          <p className="field-label">Data requirements</p>
          <p
            className={
              answer.resources.every((r) => met(r.status)) ? "soft" : "warn"
            }
            data-testid="access-summary"
          >
            {summary(answer)}
          </p>

          {rows.length > 0 && (
            <ul className="canvas-access-rows" data-testid="access-rows">
              {rows.map((r) => (
                <li
                  key={`${r.kind}:${r.id}`}
                  data-kind={r.kind}
                  data-status={r.status}
                >
                  <span className="canvas-access-name">{label(r)}</span>
                  <span className="soft">
                    {KINDS.find((k) => k.kind === r.kind)?.label ?? r.kind}
                  </span>
                  <span className={met(r.status) ? "good" : "warn"}>
                    {STATUS_LABELS[r.status]}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {/* Said rather than omitted: a missing row reads as a check that
              passed, and p.92 lists functions fourth. */}
          <p className="soft" data-testid="access-functions">{NO_FUNCTIONS}</p>
        </>
      )}
    </div>
  );
}
