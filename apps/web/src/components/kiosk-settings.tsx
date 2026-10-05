"use client";

/**
 * Kiosk mode in Control Panel (§684; `workshop` p.610-611).
 *
 * > "Kiosk mode settings can be configured and managed per Organization from
 * > Control Panel. Once a module has been added to the kiosk mode setting's
 * > allowlist, builders with permissions to launch kiosk mode sessions can do
 * > so…" (p.610)
 * >
 * > "Active kiosk mode sessions can also be ended by Administrators from the
 * > Session Launch History table found in the kiosk mode settings section of
 * > Control Panel." (p.610)
 *
 * The organisation page is this platform's Control Panel, and this is its
 * kiosk mode section: the allowlist, and the launch history with End.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";

function when(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function KioskSettings() {
  const queryClient = useQueryClient();
  const allowed = useQuery({ queryKey: ["kiosk-modules"], queryFn: api.kioskModules });
  const listed = new Set((allowed.data ?? []).map((m) => m.app_id));
  // Searched rather than listed whole (§819): an organisation can hold more
  // modules than a dropdown should, and the first 500 silently stood for all.
  const [search, setSearch] = useState("");
  const candidates = useQuery({
    queryKey: ["kiosk-candidates", search],
    queryFn: () => api.kioskCandidates(search),
    placeholderData: (previous) => previous,
  });
  const offered = (candidates.data?.items ?? []).filter((c) => !listed.has(c.app_id));
  const unshown = (candidates.data?.total ?? 0) - (candidates.data?.items.length ?? 0);
  const sessions = useQuery({ queryKey: ["kiosk-sessions"], queryFn: api.kioskSessions });
  const [adding, setAdding] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["kiosk-modules"] });
  const allow = useMutation({ mutationFn: api.allowKiosk, onSuccess: () => { setAdding(""); refresh(); } });
  const disallow = useMutation({ mutationFn: api.disallowKiosk, onSuccess: refresh });
  const end = useMutation({
    mutationFn: api.endKioskSession,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kiosk-sessions"] }),
  });
  const failure = [allow.error, disallow.error, end.error].find(Boolean);

  return (
    <section data-testid="kiosk-settings" style={{ marginTop: 32 }}>
      <p className="eyebrow" style={{ marginBottom: 10 }}>kiosk mode</p>
      <p className="field-hint">
        Modules on this list can be opened by their builders as long-lived, read-only
        kiosk sessions, once kiosk mode is also turned on in the module&apos;s settings.
      </p>
      <table className="table" data-testid="kiosk-allowlist">
        <thead><tr><th>Module</th><th>Added</th><th aria-label="Actions" /></tr></thead>
        <tbody>
          {(allowed.data ?? []).map((m) => (
            <tr key={m.app_id}>
              <td>{m.name ?? m.app_id}</td>
              <td className="slug">{when(m.added_at)}</td>
              <td>
                <button type="button" className="btn quiet" onClick={() => disallow.mutate(m.app_id)}>
                  Remove
                </button>
              </td>
            </tr>
          ))}
          {allowed.data?.length === 0 && (
            <tr><td colSpan={3} className="field-hint">No modules yet.</td></tr>
          )}
        </tbody>
      </table>
      <div className="row-actions" style={{ marginTop: 8 }}>
        <input
          type="search"
          aria-label="Search modules"
          placeholder="Search modules or workspaces"
          data-testid="kiosk-search"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setAdding(""); }}
        />
        <select
          aria-label="Module to add"
          data-testid="kiosk-add-module"
          value={adding}
          onChange={(e) => setAdding(e.target.value)}
        >
          <option value="">Choose a module…</option>
          {offered.map((c) => (
            <option key={c.app_id} value={c.app_id}>{c.name} ({c.workspace_name})</option>
          ))}
        </select>
        <button
          type="button"
          className="btn"
          data-testid="kiosk-add"
          disabled={!adding || allow.isPending}
          onClick={() => allow.mutate(adding)}
        >
          Add to allowlist
        </button>
      </div>
      {unshown > 0 && (
        <p className="field-hint" data-testid="kiosk-more">
          {unshown} more {unshown === 1 ? "module matches" : "modules match"} - search to narrow the list.
        </p>
      )}

      <p className="eyebrow" style={{ margin: "20px 0 10px" }}>session launch history</p>
      <table className="table" data-testid="kiosk-sessions">
        <thead>
          <tr><th>Module</th><th>Launched by</th><th>Started</th><th>Status</th><th aria-label="Actions" /></tr>
        </thead>
        <tbody>
          {(sessions.data ?? []).map((s) => (
            <tr key={s.id} data-testid="kiosk-session" data-active={s.active ? "true" : "false"}>
              <td>{s.app_name ?? s.app_id} <span className="slug">v{s.version_number}</span></td>
              <td>{s.launched_by_name ?? "—"}</td>
              <td className="slug">{when(s.created_at)}</td>
              <td className="slug">
                {s.active ? `Active until ${when(s.expires_at)}`
                  : s.ended_at ? `Ended ${when(s.ended_at)}` : "Expired"}
              </td>
              <td>
                {s.active && (
                  <button type="button" className="btn quiet" data-testid="kiosk-end"
                          onClick={() => end.mutate(s.id)}>
                    End session
                  </button>
                )}
              </td>
            </tr>
          ))}
          {sessions.data?.length === 0 && (
            <tr><td colSpan={5} className="field-hint">No sessions have been launched.</td></tr>
          )}
        </tbody>
      </table>
      {failure && (
        <p className="form-error" role="alert">
          {failure instanceof ApiError ? failure.message : "That didn't work."}
        </p>
      )}
    </section>
  );
}
