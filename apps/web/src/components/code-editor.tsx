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
import { useEffect, useRef, useState } from "react";
import type { EditorPreferences } from "@/lib/editor-preferences";
import { DEFAULTS, monacoOptions } from "@/lib/editor-preferences";
import type { Vocabulary } from "@/lib/completions";
import { completionsFor } from "@/lib/completions";

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

/** Monaco's completion kinds, for the three vocabularies (§434).
 *
 * Icons rather than decoration: the list mixes the project's datasets with
 * Monaco's own SQL keywords, and the kind is what tells somebody at a glance
 * which of the two they are looking at.
 */
function kindOf(kind: "dataset" | "alias" | "column"): number {
  const k = monaco.languages.CompletionItemKind;
  if (kind === "dataset") return k.Class;
  if (kind === "alias") return k.Variable;
  return k.Field;
}

/**
 * p.2's IntelliSense, over the names only this platform knows (§434).
 *
 * **Registered once per language, reading the vocabulary through a ref.** A
 * provider registered per render would stack — ten renders, ten providers, ten
 * copies of every suggestion — and one registered with the vocabulary captured
 * would go on offering the datasets that existed when the editor mounted.
 */
function useCompletions(vocabulary: Vocabulary | undefined) {
  const latest = useRef<Vocabulary | undefined>(vocabulary);
  latest.current = vocabulary;

  useEffect(() => {
    const provider: monaco.languages.CompletionItemProvider = {
      // `.` so a column list appears as soon as the dot is typed; the rest
      // arrive through Monaco's own word-character triggering.
      triggerCharacters: ["."],
      provideCompletionItems(model, position) {
        const known = latest.current;
        if (!known) return { suggestions: [] };
        const before = model.getValueInRange({
          startLineNumber: position.lineNumber,
          startColumn: 1,
          endLineNumber: position.lineNumber,
          endColumn: position.column,
        });
        const word = model.getWordUntilPosition(position);
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        };
        return {
          suggestions: completionsFor(before, model.getValue(), known).map((c) => ({
            label: c.label,
            kind: kindOf(c.kind),
            detail: c.detail,
            insertText: c.label,
            range,
          })),
        };
      },
    };
    const registered = ["sql", "python"].map((language) =>
      monaco.languages.registerCompletionItemProvider(language, provider),
    );
    return () => registered.forEach((r) => r.dispose());
  }, []);
}

export function CodeEditor({
  path,
  value,
  readOnly,
  onChange,
  reveal,
  onReady,
  preferences = DEFAULTS,
  vocabulary,
}: {
  path: string;
  value: string;
  readOnly?: boolean;
  onChange?: (next: string) => void;
  /** p.20's personal editor preferences (§432). **Defaulted here rather than
   *  required**, so every caller that has no opinion gets the values this file
   *  used to hard-code — and gets them from the one module that defines them,
   *  which is what stops the Settings tab and the editor disagreeing. */
  preferences?: EditorPreferences;
  /** A line to scroll to and put the caret on (§286).
   *
   * **A `{line}` object rather than a bare number**, so asking twice for the
   * same line is two different values and the effect below fires both times.
   * Clicking the same problem twice, having scrolled away in between, is the
   * ordinary case - and a bare number would make the second click do nothing,
   * which reads as a broken panel rather than as a deduplicated request. */
  reveal?: { line: number };
  /** Called once Monaco has actually mounted (§307).
   *
   * **From `onMount`, not from the mount guard below.** `ready` is a one-tick
   * guard so Monaco measures itself against a panel that has a size; it says
   * nothing about whether Monaco has *loaded*, which is a dynamic import and
   * the thing p.15's status bar is about. Reporting the guard would tell the
   * status bar the editor was ready one tick after the page appeared, every
   * time, which is a status bar that is always right and never useful. */
  onReady?: () => void;
  /** The project's datasets and their columns (§434). Undefined until the
   *  listing arrives, which is a real state: the editor opens before it, and
   *  offering nothing is better than offering a list that is not yet true. */
  vocabulary?: Vocabulary;
}) {
  useCompletions(vocabulary);

  // Monaco measures itself on mount; rendering it before the panel has a size
  // gives a zero-height editor that never recovers.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);

  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  useEffect(() => {
    if (!reveal || !editorRef.current) return;
    // `revealLineInCenter` rather than `revealLine`: a line put at the very
    // bottom of the viewport is technically visible and practically missed.
    editorRef.current.revealLineInCenter(reveal.line);
    editorRef.current.setPosition({ lineNumber: reveal.line, column: 1 });
    editorRef.current.focus();
  }, [reveal, path]);

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
      onMount={(editor: monaco.editor.IStandaloneCodeEditor) => {
        editorRef.current = editor;
        onReady?.();
        // A file opened *by* a problem mounts with the reveal already asked
        // for, and the effect above has run before this editor existed.
        if (reveal) {
          editor.revealLineInCenter(reveal.line);
          editor.setPosition({ lineNumber: reveal.line, column: 1 });
        }
      }}
      options={{
        readOnly,
        fontFamily: "var(--font-mono)",
        lineNumbers: "on",
        scrollBeyondLastLine: false,
        automaticLayout: true,
        renderWhitespace: "selection",
        // **Suggestions inside comments, which Monaco turns off by default**
        // (§434). That default is right for most editors and wrong for this
        // one: a transform declares its output and inputs in the leading
        // comment block (`transform_declarations.py`), so the *one* place a
        // dataset name has to be exactly right is the one place Monaco would
        // not offer it. Found by a browser test that typed `-- input: raw = `
        // and was offered nothing while the same completions worked two lines
        // below in the query. Strings stay off: a literal is text, and there
        // is nothing here that knows what belongs in one.
        quickSuggestions: { other: true, comments: true, strings: false },
        // The four p.20 lets somebody choose. Spread last so a preference
        // cannot be silently overridden by a literal above it.
        ...monacoOptions(preferences),
      }}
    />
  );
}
