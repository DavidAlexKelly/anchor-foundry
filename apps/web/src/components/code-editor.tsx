"use client";

/** Monaco, bundled (ROADMAP.md phase 2, item 2.2).
 *
 * **Nothing here is fetched at runtime, and that is the whole point of this
 * file.** `@monaco-editor/react` defaults to pulling Monaco from jsDelivr; the
 * deployed stack runs inside the customer's VPC behind a strict egress policy,
 * so a CDN import is an editor that works on a laptop and is a blank rectangle
 * in production. `loader.config({ monaco })` hands it the copy webpack has
 * bundled instead.
 *
 * Loaded through `next/dynamic` with `ssr: false`: Monaco touches `window` and
 * `document` at module scope, and it is ~1 MB of JavaScript that no page other
 * than an editor should pay for.
 */

import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import { useEffect, useState } from "react";

// Route every worker request at the plain editor worker. The languages this
// editor offers - SQL, Python, Markdown - are tokenised by Monarch on the main
// thread and have no worker-backed language service of their own; the ones that
// do (TypeScript, JSON) are not offered. Without this, Monaco asks for a worker
// URL, does not find one, and logs on every keystroke.
if (typeof window !== "undefined") {
  (window as unknown as { MonacoEnvironment?: unknown }).MonacoEnvironment = {
    getWorker() {
      return new Worker(
        new URL("monaco-editor/esm/vs/editor/editor.worker.js", import.meta.url),
      );
    },
  };
  loader.config({ monaco });
}

/** Extension → Monaco language id. Unknown extensions get plain text rather
 * than a guess: mis-highlighted code reads as broken code. */
const LANGUAGES: Record<string, string> = {
  sql: "sql",
  py: "python",
  md: "markdown",
  markdown: "markdown",
  json: "json",
  yml: "yaml",
  yaml: "yaml",
  txt: "plaintext",
};

export function languageFor(path: string): string {
  const extension = path.includes(".") ? path.split(".").pop()!.toLowerCase() : "";
  return LANGUAGES[extension] ?? "plaintext";
}

export function CodeEditor({
  path,
  value,
  readOnly,
  onChange,
}: {
  path: string;
  value: string;
  readOnly?: boolean;
  onChange?: (next: string) => void;
}) {
  // Monaco measures itself on mount; rendering it before the panel has a size
  // gives a zero-height editor that never recovers.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  if (!ready) return <div className="code-editor-loading">Loading editor…</div>;

  return (
    <Editor
      // Keyed by path so switching files swaps the model rather than replaying
      // the new text into the old one - which would put the change in the undo
      // stack of a file it did not come from.
      key={path}
      height="100%"
      path={path}
      language={languageFor(path)}
      value={value}
      onChange={(next: string | undefined) => onChange?.(next ?? "")}
      loading={<div className="code-editor-loading">Loading editor…</div>}
      options={{
        readOnly,
        minimap: { enabled: false },
        fontSize: 12.5,
        fontFamily: "var(--font-mono)",
        lineNumbers: "on",
        scrollBeyondLastLine: false,
        automaticLayout: true,
        renderWhitespace: "selection",
        tabSize: 2,
      }}
    />
  );
}
