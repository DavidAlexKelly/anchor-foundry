"use client";

/**
 * p.610's Open kiosk button and its modal (§684).
 *
 * > "The Open kiosk button will appear in the top right corner of the module.
 * > Selecting this button opens a modal that outlines the contents of the
 * > currently published version of the module that will be visible for the
 * > duration of the session. This includes object types, link types,
 * > functions, and other embedded Foundry applications. After reviewing the
 * > scope of the module's content, select Launch session to start a kiosk mode
 * > session." (p.610)
 *
 * **Drawn only when a launch would work**: the module's toggle is on, it is on
 * the organisation's allowlist, and this person builds it. A button that
 * opened a modal saying "you cannot" would be one most readers see and none
 * can use. The credential it returns goes to this tab's session storage and
 * nowhere else - not the URL, where it would outlive the session in history.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Dialog } from "@/components/dialog";
import { ApiError, canvas as canvasApi } from "@/lib/api";
import { KIOSK_STORAGE_KEY } from "@/lib/kiosk";
import type { KioskScopeEntry } from "@/lib/types";

const KINDS: [key: "object_types" | "link_types" | "action_types" | "apps", label: string][] = [
  ["object_types", "Object types"],
  ["link_types", "Link types"],
  ["action_types", "Action types"],
  ["apps", "Modules"],
];

export function KioskLauncher({ workspaceId, appId }: { workspaceId: string; appId: string }) {
  const [open, setOpen] = useState(false);
  const state = useQuery({
    queryKey: ["kiosk", workspaceId, appId],
    queryFn: () => canvasApi.kioskAvailability(workspaceId, appId),
    retry: false,
  });
  const launch = useMutation({
    mutationFn: () => canvasApi.launchKiosk(workspaceId, appId),
    onSuccess: (session) => {
      try {
        sessionStorage.setItem(KIOSK_STORAGE_KEY, session.token);
      } catch {
        // Nowhere to keep it: the session is refused rather than put in a URL.
        return;
      }
      window.location.assign("/kiosk");
    },
  });
  if (!state.data?.available) return null;
  const scope = state.data.scope;
  return (
    <>
      <button type="button" className="btn" data-testid="open-kiosk" onClick={() => setOpen(true)}>
        Open kiosk
      </button>
      {open && (
        <Dialog open title="Launch kiosk session" onClose={() => setOpen(false)}>
          <p className="field-hint">
            A kiosk session is read-only and lasts a week, or until it is exited or an
            administrator ends it. It shows version {state.data.version_number ?? "—"} of this
            module and can see only what the module references (p.611).
          </p>
          <h3 style={{ fontSize: 13.5, margin: "12px 0 6px" }}>Content in scope</h3>
          <div data-testid="kiosk-scope">
            {KINDS.map(([key, label]) => (
              <ScopeList key={key} label={label} entries={scope[key]} />
            ))}
          </div>
          {launch.isError && (
            <p className="form-error" role="alert">
              {launch.error instanceof ApiError ? launch.error.message : "Couldn't launch the session."}
            </p>
          )}
          <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
            <button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button>
            <button
              type="button"
              className="btn primary"
              data-testid="launch-kiosk"
              disabled={launch.isPending}
              onClick={() => launch.mutate()}
            >
              Launch session
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}

function ScopeList({ label, entries }: { label: string; entries: KioskScopeEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <div style={{ marginBottom: 8 }}>
      <p className="eyebrow" style={{ margin: "0 0 2px" }}>{label}</p>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {entries.map((entry) => (
          <li key={entry.id}>
            {/* p.611: something referenced but not visible to the launcher is
                in scope and still missing - said, rather than left out. */}
            {entry.name || <span className="field-hint">Not visible to you ({entry.id})</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
