"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { completeLogin } from "@/lib/auth";

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false); // strict mode double-invoke guard: codes are single-use

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const code = params.get("code");
    if (!code) {
      setError("Missing authorization code. Restart sign-in.");
      return;
    }
    completeLogin(code)
      .then(() => router.replace("/home"))
      .catch((e) => setError(e instanceof Error ? e.message : "Sign-in failed"));
  }, [params, router]);

  if (error) {
    return (
      <div className="state error">
        {error} — <a href="/login" style={{ textDecoration: "underline" }}>back to sign in</a>
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
