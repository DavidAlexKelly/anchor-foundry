"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { completeLogin, consumeReturnPath } from "@/lib/auth";
import { callbackError } from "@/lib/auth-errors";

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false); // strict mode double-invoke guard: codes are single-use

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    // Cognito's own reason first: a refused sign-in comes back with an error
    // instead of a code, and "missing code" would hide why (§816).
    const refused = callbackError(new URLSearchParams(params.toString()));
    if (refused) {
      setError(refused);
      return;
    }
    const code = params.get("code");
    if (!code) {
      setError("Missing authorization code. Restart sign-in.");
      return;
    }
    completeLogin(code)
      .then(() => router.replace(consumeReturnPath() ?? "/home"))
      .catch((e) => setError(e instanceof Error ? e.message : "Sign-in failed"));
  }, [params, router]);

  if (error) {
    return (
      <div className="state error" data-testid="sign-in-error">
        {error} - <a href="/login" style={{ textDecoration: "underline" }}>back to sign in</a>
      </div>
    );
  }
  return <div className="state">Completing sign-in…</div>;
}

export default function CallbackPage() {
  return (
    <Suspense fallback={<div className="state">Completing sign-in…</div>}>
      <CallbackInner />
    </Suspense>
  );
}
