"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { sync as syncApi } from "@/lib/api";
import {
  FOLLOW_EVERY_MS, RUNNING_TEXT, endedText, followedRun, stillRunning,
} from "@/lib/sync-progress";
import type { SyncResult } from "@/lib/types";

/** A sync that outlasted its request (§967), followed through the
 * connection's run history until it ends. */
export function SyncFollow({
  workspaceId,
  projectId,
  connectionId,
  result,
  onEnded,
}: {
  workspaceId: string;
  projectId: string;
  connectionId: string;
  result: SyncResult;
  onEnded?: () => void;
}) {
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: ["sync-runs", connectionId],
    queryFn: () => syncApi.runs(workspaceId, projectId, connectionId),
    refetchInterval: (query) =>
      stillRunning(result, query.state.data) ? FOLLOW_EVERY_MS : false,
  });
  const running = stillRunning(result, runs.data);
  const run = followedRun(result, runs.data);

  useEffect(() => {
    if (running) return;
    void queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["connections", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["sync-health", projectId] });
    onEnded?.();
    // Once, when it ends.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  if (running || !run) {
    return (
      <p className="login-note" style={{ margin: 0 }} data-testid="sync-running">
        {RUNNING_TEXT}
      </p>
    );
  }
  const ended = endedText(run);
  return ended.ok ? (
    <p className="login-note" style={{ margin: 0 }} data-testid="sync-result">
      {ended.text}
    </p>
  ) : (
    <div className="form-error" data-testid="sync-result">{ended.text}</div>
  );
}
