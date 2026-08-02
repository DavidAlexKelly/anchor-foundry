"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { bootstrap } from "@/lib/api";
import { beginLogin, cognitoConfig, devAuthEnabled, safeReturnPath, setToken } from "@/lib/auth";
import { AnchorGlyph } from "@/components/glyph";

function LoginInner() {
  const router = useRouter();
  // Set by the route guards when they bounce an unauthenticated request. A
  // shared /r/{id} link is always loaded cold, so losing it here would make
  // resource links useless to whoever they were sent to.
  const nextPath = safeReturnPath(useSearchParams().get("next")) ?? "/home";
  const [error, setError] = useState<string | null>(null);
  const [devToken, setDevToken] = useState("");
  const [busy, setBusy] = useState(false);
  // Only ever true right after a fresh deploy, before anyone has bootstrapped
  // an organisation - not worth showing an error state if this check fails.
  const bootstrapStatus = useQuery({
    queryKey: ["bootstrap-status"],
    queryFn: bootstrap.status,
    retry: false,
  });
  // Starts false to match the server-rendered HTML exactly (window/env vars
  // aren't available during SSR); flips after mount once we can actually
  // check. Computing this inline during render (typeof window !== "undefined")
  // causes a client/server markup mismatch — React hydration errors #418/#423.
  const [hostedUiConfigured, setHostedUiConfigured] = useState(false);

  useEffect(() => {
    setHostedUiConfigured(cognitoConfig() !== null);
  }, []);

  async function onSignIn() {
    setBusy(true);
    setError(null);
    try {
      await beginLogin();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed");
      setBusy(false);
    }
  }

  function onDevSignIn() {
    if (!devToken.trim()) {
      setError("Paste an access token first");
      return;
    }
    setToken(devToken.trim());
    router.replace(nextPath);
  }

  return (
    <div className="login-split">
      <aside className="login-brand">
        <div className="wordmark">
          <AnchorGlyph size={20} /> ANCHOR
        </div>
        <h1>Your data platform, anchored in your own AWS account.</h1>
        <div className="tenets">
          data stays in your account
          <br />
          export anything, anytime
          <br />
          deployed in twenty minutes
        </div>
      </aside>
      <main className="login-panel">
        <div className="login-box">
          <h2>Sign in</h2>
          <p className="sub">Use the account your organisation created for you.</p>
          {bootstrapStatus.data?.needs_setup && (
            <p className="login-note" style={{ marginBottom: 16 }}>
              This deployment hasn&apos;t been set up yet.{" "}
              <Link href="/setup" style={{ textDecoration: "underline" }}>
                Set up your organisation
              </Link>
            </p>
          )}
          <button className="btn" onClick={onSignIn} disabled={busy || !hostedUiConfigured}>
            {busy ? "Redirecting…" : "Continue to sign in"}
          </button>
          {!hostedUiConfigured && (
            <p className="login-note">
              Sign-in isn&apos;t configured yet. An administrator needs to set the
              authentication environment for this deployment.
            </p>
          )}
          {devAuthEnabled() && (
            <div style={{ marginTop: 24 }}>
              <p className="eyebrow">local development</p>
              <input
                style={{
                  width: "100%",
                  padding: "8px 10px",
                  marginTop: 8,
                  border: "1px solid var(--line-strong)",
                  borderRadius: "var(--radius)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                }}
                placeholder="Paste an access token"
                value={devToken}
                onChange={(e) => setDevToken(e.target.value)}
              />
              <button className="btn quiet" style={{ marginTop: 8 }} onClick={onDevSignIn}>
                Use token
              </button>
            </div>
          )}
          {error && <p className="login-note" style={{ color: "var(--danger)" }}>{error}</p>}
          <p className="login-note">
            No self-service sign-up - accounts are created by your organisation&apos;s
            administrators.
          </p>
        </div>
      </main>
    </div>
  );
}

// useSearchParams needs a Suspense boundary or `next build` fails when it
// prerenders this route - the callback page has the same wrapper for the same
// reason.
export default function LoginPage() {
  return (
    <Suspense fallback={<div className="state">Loading…</div>}>
      <LoginInner />
    </Suspense>
  );
}
