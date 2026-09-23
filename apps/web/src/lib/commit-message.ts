/**
 * p.114's commit message rule, as the editor sees it (§441;
 * `code-repositories` p.114).
 *
 * > "By default commit messages will be auto-generated when clicking the commit
 * > button or when building a dataset. You can encourage more meaningful
 * > messages by disabling this option. The commit message dialog will open
 * > before each commit and require a message to be submitted."
 *
 * **The server owns the refusal and this owns what to offer**, which is the
 * division every pair in this repository uses. `services/repo_settings.py`
 * refuses the commit; what is here decides whether the button is offered at
 * all, and says why when it is not — because p.114's whole point is that the
 * requirement is met *before* the press rather than reported after it.
 *
 * **Which means these two must not drift** (§162, §191). The keys, the
 * `is true` reading of `required`, and the treatment of an unreadable file are
 * the same three decisions in two languages, and
 * `test_the_browser_reads_the_same_settings_file_the_server_does` in
 * `apps/api/tests/test_repository_routes.py` reads this file to check the
 * first of them. The rest is held by the browser suite pressing the button.
 *
 * Pure and in `lib/` because vitest cannot parse `.tsx`.
 */
// Relative, not `@/`: **value** imports, and vitest resolves no path alias.
import { COMMIT_BLOCK, SETTINGS_FILE, type Settings } from "./settings-file";

// Re-exported because callers have imported them from here since §441, and a
// name that moves is a name every caller has to be found for. The one
// implementation is in `settings-file.ts` (§292, §444).
export { COMMIT_BLOCK, SETTINGS_FILE, settingsFrom } from "./settings-file";

/**
 * Whether this repository asks every commit to say what changed.
 *
 * **`=== true`, not truthy.** A settings file carrying `"required": "no"`
 * would otherwise turn the rule on, which is the opposite of what whoever
 * typed it meant — and the server reads it the same way.
 */
export function messageRequired(settings: Settings): boolean {
  const block = settings[COMMIT_BLOCK];
  return typeof block === "object" && block !== null
    && (block as Record<string, unknown>).required === true;
}

/**
 * Why the commit button will not go, or null when it will.
 *
 * The repository's own `errorMessage` where it set one — a sentence somebody
 * wrote for their colleagues says why the rule exists, and "a commit message
 * is required" does not.
 *
 * **Whitespace is empty**, matching the server: a space typed to get past a
 * check is the check working exactly as badly as no check at all.
 */
export function messageProblem(message: string, settings: Settings): string | null {
  if (!messageRequired(settings)) return null;
  if (message.trim()) return null;
  const block = settings[COMMIT_BLOCK] as Record<string, unknown> | undefined;
  const said = block?.errorMessage;
  return typeof said === "string" && said.trim()
    ? said
    : `This repository asks every commit to say what changed, which is set in ${SETTINGS_FILE}.`;
}

/** What the empty field invites.
 *
 * **It says the message is required where it is**, rather than leaving that to
 * a refusal the reader meets after typing a diff's worth of work. */
export function messagePlaceholder(settings: Settings): string {
  return messageRequired(settings)
    ? "What changed, and why — this repository requires it"
    : "What changed, and why";
}
