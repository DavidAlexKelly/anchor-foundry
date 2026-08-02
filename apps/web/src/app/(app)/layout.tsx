"use client";

/** The application route group (ROADMAP.md phase 2, section 0 item 3).
 *
 * Deliberately outside `(platform)`: an application owns the whole viewport.
 * Inheriting the platform topbar and project sidebar would leave a Workshop
 * module or a code editor squeezed into the middle of a page about something
 * else, which is exactly the shape this phase exists to get away from.
 *
 * The auth guard is repeated here rather than lifted somewhere shared, because
 * the two groups genuinely redirect differently: `(platform)` keeps its chrome
 * while it checks, and this one has no chrome to keep.
 */

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { getToken, loginHrefFor } from "@/lib/auth";

export default function ApplicationLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // A shared /r/{id} link is always loaded cold - sessionStorage is per-tab -
    // so the path has to survive the trip through sign-in.
    if (!getToken()) router.replace(loginHrefFor(pathname, window.location.search));
  }, [router, pathname]);

  return <div className="app-viewport">{children}</div>;
}
