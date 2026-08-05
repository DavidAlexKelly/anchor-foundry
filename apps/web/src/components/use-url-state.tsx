"use client";

/** URL-backed application state (ROADMAP.md phase 2, item 0.4).
 *
 * **The URL is the state, not a copy of it.** Every application here reads its
 * tab, its selection and its filters straight out of `useSearchParams`, so
 * restoring from a link is not a code path — there is nothing to restore,
 * because nothing was ever kept anywhere else. The alternative, mirroring the
 * URL into `useState` on mount, has two sources of truth and drifts the first
 * time somebody uses the back button.
 *
 * Three applications had each grown their own `setParams` before this existed
 * (dataset, repository, object type). They are the same eight lines, and the
 * fourth copy is where one of them quietly starts pushing history entries
 * instead of replacing them.
 */

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";

export type UrlState = {
  params: URLSearchParams;
  /** `null` when absent, so an empty string stays distinguishable. */
  get: (key: string) => string | null;
  /** Read a key constrained to a known set, with a fallback. Keeps a
   *  hand-typed `?tab=nonsense` from rendering nothing at all. */
  oneOf: <T extends string>(key: string, allowed: readonly T[], fallback: T) => T;
  /** All values for a repeatable key (the explorer's `type`, say). */
  all: (key: string) => string[];
  /** Set, or remove where the value is `undefined`, `null` or empty. A key
   *  whose value is its default has no business in a shared link.
   *
   *  Pass a function to compute the change from what is *currently* in the
   *  URL — the `setState(fn)` idiom, and for the same reason: a value derived
   *  from the last render is wrong if a write is still in flight. Ticking two
   *  checkboxes faster than the router settles is exactly that case. */
  set: (next: Change | ((current: URLSearchParams) => Change)) => void;
};

type Change = Record<string, string | string[] | undefined | null>;

export function useUrlState(): UrlState {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  /** The last thing written, until the router catches up.
   *
   * `router.replace` does not land synchronously, so two writes in quick
   * succession — typing a property name and then its value — would each build
   * on the same stale snapshot, and the second would drop the first. Found in
   * the browser check for item 0.4, which produced `?value=NO` with no
   * `property` beside it: a query the form displayed and the server was never
   * asked. A write therefore builds on the previous *write*, not on the
   * previous render.
   */
  const pending = useRef<string | null>(null);
  if (pending.current === params.toString()) pending.current = null;

  return {
    params,
    get: (key) => params.get(key),
    oneOf: (key, allowed, fallback) => {
      const raw = params.get(key);
      return (allowed as readonly string[]).includes(raw ?? "")
        ? (raw as typeof fallback)
        : fallback;
    },
    all: (key) => params.getAll(key),
    set: (next) => {
      const search = new URLSearchParams(pending.current ?? params.toString());
      const change = typeof next === "function" ? next(new URLSearchParams(search)) : next;
      for (const [key, value] of Object.entries(change)) {
        search.delete(key);
        if (Array.isArray(value)) {
          for (const v of value) if (v !== "") search.append(key, v);
        } else if (value !== undefined && value !== null && value !== "") {
          search.set(key, value);
        }
      }
      const qs = search.toString();
      pending.current = qs;
      // replace, not push: flicking between tabs should not bury the page the
      // reader arrived from under a stack of back-button steps.
      router.replace(qs ? `?${qs}` : pathname, { scroll: false });
    },
  };
}

/** "Send someone a link to what you are looking at" — the affordance item 0.4
 * names, and the reason the state above is in the URL at all.
 *
 * It copies `window.location.href`, which is the whole point: the address bar
 * already says where you are, and a button that rebuilt the link from
 * component state could disagree with it.
 *
 * **When the clipboard is unavailable it says so and shows the link.**
 * `navigator.clipboard` only exists in a secure context, so on a plain-http
 * deployment — which this platform supports, and which a customer running it
 * on an internal network is likely to have — the write silently does nothing.
 * A button that reports success it did not have is worse than one that admits
 * it cannot help and hands over the text to copy by hand.
 */
export function CopyLinkButton({ label = "Copy link" }: { label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  const [href, setHref] = useState("");

  async function copy() {
    const url = window.location.href;
    setHref(url);
    try {
      // No explicit `if (!navigator.clipboard)` guard: an absent clipboard
      // throws on use, so the guard was a second way of saying the same thing
      // — mutation testing found it made no difference to any outcome. The
      // `catch` is what carries this, and it also covers a clipboard that
      // exists and refuses (permission denied), which a presence check would
      // have sailed straight past.
      await navigator.clipboard.writeText(url);
      setState("copied");
      window.setTimeout(() => setState("idle"), 2000);
    } catch {
      setState("manual");
    }
  }

  return (
    <span className="copy-link">
      <button type="button" className="btn quiet" onClick={copy}>
        {state === "copied" ? "Link copied" : label}
      </button>
      {state === "manual" && (
        <span className="copy-link-manual">
          <label className="slug" htmlFor="copy-link-fallback">
            Copying needs a secure connection here — this is the link:
          </label>
          <input
            id="copy-link-fallback"
            type="text"
            readOnly
            value={href}
            onFocus={(e) => e.currentTarget.select()}
          />
          <button type="button" className="btn quiet" onClick={() => setState("idle")}>
            Done
          </button>
        </span>
      )}
    </span>
  );
}
