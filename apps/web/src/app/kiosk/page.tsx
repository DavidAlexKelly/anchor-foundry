"use client";

/**
 * A kiosk session, running (§684; `workshop` p.610-612).
 *
 * > "Kiosk mode gives builders the ability to enable long-lived, restricted
 * > sessions for Workshop applications, allowing them to be safely displayed
 * > for extended periods of time." (p.610)
 *
 * **Outside the platform's shell**, so the page makes no request the session
 * would be refused - no workspace list, no notifications - and shows nothing
 * but the module and p.610's "Exit kiosk mode". Every request goes out on the
 * session's credential (`setKioskToken`), which the API holds to read-only and
 * to what the module references; this page narrows nothing itself.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, api, canvas as canvasApi, setKioskToken } from "@/lib/api";
import { forgetKioskToken, storedKioskToken } from "@/lib/kiosk";
import { PublishedModule } from "@/components/canvas/published-module";
import { readerLayout } from "@/components/canvas/reader-layout";

export default function KioskPage() {
  // Read after mount: session storage is the browser's, and the first render
  // happens where there is none.
  const [token, setToken] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    const held = storedKioskToken();
    setKioskToken(held);
    setToken(held);
  }, []);

  const current = useQuery({
    queryKey: ["kiosk-current", token],
    queryFn: api.kioskCurrent,
    enabled: !!token,
    retry: false,
  });
  const app = useQuery({
    queryKey: ["kiosk-app", current.data?.app_id],
    queryFn: () => canvasApi.getPublished(current.data!.workspace_id, current.data!.app_id),
    enabled: !!current.data,
    retry: false,
  });

  const leave = (to: string) => {
    forgetKioskToken();
    setKioskToken(null);
    window.location.assign(to);
  };
  const exit = async () => {
    const back = current.data
      ? `/${current.data.workspace_slug}/apps/${current.data.app_id}` : "/home";
    try {
      await api.exitKiosk();
    } catch {
      // Already ended is ended: leaving is still the right thing to do.
    }
    leave(back);
  };

  if (token === undefined) return null;
  const ended = [current.error, app.error].some((e) => e instanceof ApiError && e.status === 401);
  if (token === null || ended) {
    return (
      <main className="page">
        <div className="state" data-testid="kiosk-ended">
          {token === null
            ? "There is no kiosk session in this tab."
            : "This kiosk session has ended."}
        </div>
        <button type="button" className="btn" onClick={() => leave("/home")}>Leave</button>
      </main>
    );
  }
  if (current.isError || app.isError) {
    return <main className="page"><div className="state error">Couldn&apos;t open the kiosk.</div></main>;
  }
  if (!current.data || !app.data) {
    return <main className="page"><div className="state">Opening kiosk…</div></main>;
  }
  return (
    <main className="page" data-kiosk="on">
      <div className="kiosk-bar" data-testid="kiosk-bar">
        <span className="eyebrow">Kiosk mode · {app.data.name}</span>
        <button type="button" className="btn quiet" data-testid="exit-kiosk" onClick={exit}>
          Exit kiosk mode
        </button>
      </div>
      <PublishedModule
        workspaceId={current.data.workspace_id}
        app={app.data}
        definition={readerLayout(app.data.definition)}
        search={new URLSearchParams()}
        kiosk
      />
    </main>
  );
}
