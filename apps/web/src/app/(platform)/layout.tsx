"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import { AnchorGlyph } from "@/components/glyph";

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const me = useQuery({ queryKey: ["me"], queryFn: api.me, enabled: !!getToken() });

  async function signOut() {
    try {
      await api.logout(); // audit the event; token invalidation is client-side (§9)
    } catch {
      /* signing out locally regardless */
    }
    clearToken();
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
          {me.data && <span>{me.data.display_name}</span>}
          <button onClick={signOut}>Sign out</button>
        </div>
      </header>
      {children}
    </>
  );
}
