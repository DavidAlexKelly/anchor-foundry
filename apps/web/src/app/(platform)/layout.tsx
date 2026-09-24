"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
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
      {/* In a Suspense boundary because it reads the query string, which a
          statically rendered page does not have until the client does — and a
          layout that read it bare would fail `next build` for every page under
          it. */}
      <Suspense fallback={null}>
        <Topbar signOut={signOut} pathname={pathname} name={me.data?.display_name} />
      </Suspense>
      {children}
    </>
  );
}

/** The platform's top bar — **unless the page is framed** (`workshop` p.547;
 * §455).
 *
 * > "When embedding another Foundry application, you can hide the Foundry
 * > sidebar by adding the `embedded=true` URL query parameter."
 *
 * This platform's chrome is a top bar rather than a sidebar, and it is the
 * thing p.547 is about: a module framing one of these pages would otherwise
 * show a second wordmark, a second navigation and a second Sign out button
 * *inside* its own, which is a page that cannot tell where it is.
 *
 * **Only the bar goes.** The sign-in redirect above still runs, so
 * `embedded=true` hides chrome and grants nothing — a framed page nobody is
 * signed in to still sends its viewer to log in.
 */
function Topbar({
  signOut, pathname, name,
}: {
  signOut: () => void;
  pathname: string;
  name: string | undefined;
}) {
  const embedded = useSearchParams().get("embedded") === "true";
  if (embedded) return null;
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
          {name && <span>{name}</span>}
          <button onClick={signOut}>Sign out</button>
        </div>
      </header>
    </>
  );
}
