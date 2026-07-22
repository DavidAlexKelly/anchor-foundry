"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { beginLogin, cognitoConfig, devAuthEnabled, setToken } from "@/lib/auth";
import { AnchorGlyph } from "@/components/glyph";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [devToken, setDevToken] = useState("");
  const [busy, setBusy] = useState(false);

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
    router.replace("/home");
  }

  const hostedUiConfigured = typeof window !== "undefined" && cognitoConfig() !== null;

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
            No self-service sign-up — accounts are created by your organisation&apos;s
            administrators.
          </p>
        </div>
      </main>
    </div>
  );
}
