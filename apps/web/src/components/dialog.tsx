"use client";

/** Minimal dialog + form field primitives, styled from the token system.
 * Native <dialog> for focus trapping and Escape handling; no portal library
 * needed at this size. */

import { useEffect, useRef } from "react";

export function Dialog({
  open,
  title,
  onClose,
  children,
  wide = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={wide ? "dialog wide" : "dialog"}
      onClose={onClose}
      onClick={(e) => {
        // click on the backdrop (the dialog element itself) closes
        if (e.target === ref.current) onClose();
      }}
    >
      <div className="dialog-body">
        <h2>{title}</h2>
        {children}
      </div>
    </dialog>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

/** Client-side mirror of the API's slugify (services/workspaces.py) so forms
 * can preview the slug; the server remains authoritative. */
export function slugPreview(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63)
    .replace(/-+$/, "");
}
