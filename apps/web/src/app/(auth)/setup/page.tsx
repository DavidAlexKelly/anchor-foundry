"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ApiError, bootstrap } from "@/lib/api";
import { Field, slugPreview } from "@/components/dialog";
import { AnchorGlyph } from "@/components/glyph";

export default function SetupPage() {
  const status = useQuery({ queryKey: ["bootstrap-status"], queryFn: bootstrap.status });

  const [orgName, setOrgName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");

  const create = useMutation({
    mutationFn: () =>
      bootstrap.firstOwner({
        organisation_name: orgName,
        organisation_slug: slug,
        owner_email: email,
        owner_display_name: displayName,
      }),
  });

  function onNameChange(value: string) {
    setOrgName(value);
    if (!slugTouched) setSlug(slugPreview(value));
  }

  return (
    <div className="login-split">
      <aside className="login-brand">
        <div className="wordmark">
          <AnchorGlyph size={20} /> ANCHOR
        </div>
        <h1>Set up this deployment.</h1>
        <div className="tenets">
          one-time, first-run only
          <br />
          creates your organisation
          <br />
          and its first owner account
        </div>
      </aside>
      <main className="login-panel">
        <div className="login-box">
          {status.isPending && <p className="sub">Checking deployment status…</p>}

          {status.isSuccess && !status.data.needs_setup && (
            <>
              <h2>Already set up</h2>
              <p className="sub">
                This deployment already has an organisation. Sign in instead.
              </p>
              <Link className="btn" href="/login" style={{ display: "block", textAlign: "center" }}>
                Go to sign in
              </Link>
            </>
          )}

          {status.isError && (
            <>
              <h2>Set up this deployment</h2>
              <p className="login-note" style={{ color: "var(--danger)" }}>
                Couldn&apos;t check deployment status. Reload and try again.
              </p>
            </>
          )}

          {status.isSuccess && status.data.needs_setup && !create.isSuccess && (
            <>
              <h2>Set up this deployment</h2>
              <p className="sub">
                Create the first organisation and its owner account. This can only be
                done once.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  create.mutate();
                }}
              >
                <Field label="Organisation name">
                  <input
                    type="text"
                    value={orgName}
                    onChange={(e) => onNameChange(e.target.value)}
                    required
                    maxLength={200}
                    autoFocus
                  />
                </Field>
                <Field label="Organisation slug" hint="Used in URLs; lowercase letters, numbers, hyphens">
                  <input
                    type="text"
                    value={slug}
                    onChange={(e) => {
                      setSlugTouched(true);
                      setSlug(e.target.value);
                    }}
                    required
                    pattern="[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
                    maxLength={63}
                  />
                </Field>
                <Field label="Your email" hint="Cognito emails a temporary password here">
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </Field>
                <Field label="Your name">
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    required
                    maxLength={120}
                  />
                </Field>
                {create.isError && (
                  <div className="form-error">
                    {create.error instanceof ApiError && create.error.status === 409
                      ? "This deployment was just set up by someone else. Sign in instead."
                      : "Couldn't create the organisation. Check the details and try again."}
                  </div>
                )}
                <div className="form-actions">
                  <button
                    type="submit"
                    className="btn"
                    style={{ width: "100%" }}
                    disabled={
                      create.isPending || !orgName.trim() || !slug.trim() ||
                      !email.trim() || !displayName.trim()
                    }
                  >
                    {create.isPending ? "Creating…" : "Create organisation"}
                  </button>
                </div>
              </form>
            </>
          )}

          {create.isSuccess && (
            <>
              <h2>Organisation created</h2>
              <p className="sub">
                We&apos;ve emailed <strong>{email}</strong> a temporary password. Sign in
                with it to finish setting up your account.
              </p>
              <Link className="btn" href="/login" style={{ display: "block", textAlign: "center" }}>
                Go to sign in
              </Link>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
