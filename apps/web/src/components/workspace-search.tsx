"use client";

/** The search at the top of a workspace's pages (§990): its resources by
 * name, across every project its reader can open. `/` asks for it; the
 * arrows and Enter choose; Escape leaves. What it matches and in what order
 * is the API's; the wording and the keys are `lib/workspace-search.ts`'. */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspaceBySlug } from "@/components/use-workspace";
import { focusesSearch, hitHref, kindLabel, step, whereText } from "@/lib/workspace-search";

/** How long typing has to pause before it is asked about. */
const SETTLE_MS = 200;

export function WorkspaceSearch({ slug }: { slug: string }) {
  const router = useRouter();
  const { workspace } = useWorkspaceBySlug(slug);
  const input = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState("");
  const [asked, setAsked] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);

  useEffect(() => {
    const timer = setTimeout(() => setAsked(typed.trim()), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [typed]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // Named one by one: a KeyboardEvent's fields are getters, which a
      // spread does not copy.
      if (!focusesSearch({
        key: event.key, ctrlKey: event.ctrlKey, metaKey: event.metaKey, altKey: event.altKey,
        target: event.target as HTMLElement | null,
      })) return;
      event.preventDefault();
      input.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const hits = useQuery({
    queryKey: ["workspace-search", workspace?.id, asked],
    queryFn: () => api.searchWorkspace(workspace!.id, asked),
    enabled: !!workspace && asked.length > 0,
    staleTime: 10_000,
  });
  const found = asked ? (hits.data ?? []) : [];

  useEffect(() => setHighlight(-1), [asked]);

  function choose(index: number) {
    const hit = found[index];
    if (!hit) return;
    setOpen(false);
    setTyped("");
    input.current?.blur();
    router.push(hitHref(hit));
  }

  return (
    <div className="workspace-search" data-testid="workspace-search" style={{ position: "relative" }}>
      <input
        ref={input}
        type="search"
        data-testid="workspace-search-input"
        placeholder="Search this workspace  /"
        aria-label="Search this workspace"
        value={typed}
        onChange={(e) => {
          setTyped(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setOpen(false);
            input.current?.blur();
          } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => step(h, found.length, e.key === "ArrowDown" ? 1 : -1));
          } else if (e.key === "Enter") {
            e.preventDefault();
            choose(highlight >= 0 ? highlight : 0);
          }
        }}
        style={{ width: 280 }}
      />
      {open && asked && (
        <ul
          role="listbox"
          data-testid="workspace-search-results"
          className="card"
          style={{
            position: "absolute", top: "100%", left: 0, right: 0, zIndex: 30, margin: 0,
            padding: 4, listStyle: "none", maxHeight: 360, overflowY: "auto",
          }}
        >
          {hits.isPending && <li className="soft" style={{ padding: 6 }}>Searching…</li>}
          {hits.data && found.length === 0 && (
            <li className="soft" style={{ padding: 6 }} data-testid="workspace-search-none">
              Nothing in this workspace is called that.
            </li>
          )}
          {found.map((hit, index) => (
            <li
              key={hit.id}
              role="option"
              aria-selected={index === highlight}
              data-testid="workspace-search-hit"
              onMouseDown={(e) => {
                e.preventDefault();
                choose(index);
              }}
              onMouseEnter={() => setHighlight(index)}
              style={{
                padding: "6px 8px", cursor: "pointer", borderRadius: 4,
                background: index === highlight ? "var(--surface-2, rgba(0,0,0,0.06))" : undefined,
              }}
            >
              <strong>{hit.name}</strong>
              <div className="slug">{kindLabel(hit.kind)} · {whereText(hit)}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
