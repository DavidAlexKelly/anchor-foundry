"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { clearSignedIn, isSignedIn, loginHrefFor } from "@/lib/auth";
import { AnchorGlyph } from "@/components/glyph";
import { NotificationBell } from "@/components/notification-bell";

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isSignedIn()) router.replace(loginHrefFor(pathname, window.location.search));
  }, [router, pathname]);

  const me = useQuery({ queryKey: ["me"], queryFn: api.me, enabled: isSignedIn() });

  async function signOut() {
    try {
      // Clears the httpOnly cookie as well as auditing - this call is now
      // the only thing that *can* end the session, since the credential is
      // no longer reachable from here.
      await api.logout();
    } catch {
      /* a failed audit must not strand somebody signed in */
    }
    clearSignedIn();
    router.replace("/login");
  }

  return (
    <>
      <header className="topbar">
        <Link className="wordmark" href="/home">
          <AnchorGlyph /> ANCHOR
        </Link>
        <nav>
          <Link href="/home" aria-current={pathname === "/home"}>
            Workspaces
          </Link>
          <Link href="/org" aria-current={pathname.startsWith("/org")}>
            Organisation
          </Link>
        </nav>
        <div className="spacer" />
        <div className="identity">
          {/* p.91 puts notifications in the Workspace bar rather than on a
              page: a notification is addressed to a person, and somebody who
              works in three workspaces has one inbox. */}
          <NotificationBell />
          {me.data && <span>{me.data.display_name}</span>}
          <button onClick={signOut}>Sign out</button>
        </div>
      </header>
      {children}
    </>
  );
}
