/**
 * Uncommitted edits that survive a reload (§281; `code-repositories.md` §2.3).
 *
 * The spec's own warning, and the reason this comes before multi-file tabs:
 *
 * > "Uncommitted edits live in `useState` keyed by path with no persistence
 * > anywhere. That survives switching files but not a page reload — so a
 * > five-tab editor with unsaved work is five ways to lose work at once. Tabs
 * > are what make the loss expensive; ship `localStorage` keyed by repository
 * > and branch first."
 *
 * **Keyed by branch as well as repository**, because the same path on two
 * branches is two different files with two different drafts, and a draft that
 * followed you across a branch switch would silently paste one branch's work
 * onto another's — the one outcome worse than losing it.
 *
 * Every read and write is wrapped: `localStorage` throws outright in some
 * contexts (a private window, a browser set to block site data, a thumbnailer)
 * and a draft store that took the editor down with it would be a feature that
 * costs more than it saves.
 */

/** Serialised drafts above this are refused rather than attempted.
 *
 * `localStorage` is a few megabytes *per origin*, shared by every repository
 * and branch a person has open — so the cap is per key and deliberately well
 * under it. A quota error arrives after the write is attempted and takes the
 * whole key with it, which would lose drafts that were previously safe; a
 * refusal keeps what is already stored and can be reported. */
export const DRAFT_LIMIT_BYTES = 512 * 1024;

/** What a save did, so a caller can say something true about it. */
export type SaveOutcome = "saved" | "cleared" | "too-large" | "unavailable";

export function draftKey(repositoryId: string, branch: string): string {
  // The branch is user-supplied and can hold anything a git ref can, `:`
  // included, so it goes last and is not parsed back out. Nothing reads this
  // key apart from the functions below, which always have both halves.
  return `anchor.drafts.${repositoryId}.${branch}`;
}

/**
 * The drafts stored under this key, or an empty map.
 *
 * **Never throws and never returns a partial answer.** Anything unreadable —
 * absent, blocked, corrupt, or the wrong shape — is "no drafts", because an
 * editor that opened with half a draft in it would be worse than one that
 * opened clean.
 */
export function readDrafts(key: string): Record<string, string | null> {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Record<string, string | null> = {};
    for (const [path, value] of Object.entries(parsed as Record<string, unknown>)) {
      // `null` is a real value here: it is how the editor records a deletion.
      if (value === null || typeof value === "string") out[path] = value;
    }
    return out;
  } catch {
    return {};
  }
}

/**
 * Store these drafts, or say why not.
 *
 * **An empty map removes the key rather than storing `{}`.** A repository
 * somebody edited and then reverted should leave nothing behind — otherwise
 * the store fills with the shape of every repository ever opened, and "has
 * drafts" stops being answerable by the presence of a key.
 */
export function writeDrafts(
  key: string,
  drafts: Record<string, string | null>,
): SaveOutcome {
  try {
    if (Object.keys(drafts).length === 0) {
      window.localStorage.removeItem(key);
      return "cleared";
    }
    const serialised = JSON.stringify(drafts);
    // Measured in bytes rather than characters: a file of accented text or
    // CJK is two to three times its length once encoded, and a cap that
    // counted characters would let through what the quota then refuses.
    if (new Blob([serialised]).size > DRAFT_LIMIT_BYTES) return "too-large";
    window.localStorage.setItem(key, serialised);
    return "saved";
  } catch {
    // Quota exhausted by *other* keys, or storage unavailable. Reported rather
    // than swallowed: the editor still works, and the author deserves to know
    // that closing the tab now loses this.
    return "unavailable";
  }
}

export function clearDrafts(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Nothing to do and nothing to say: the drafts are being discarded anyway.
  }
}

/** What to tell somebody whose drafts are not being kept.
 *
 * Only ever shown for the two outcomes that mean work is at risk — a save and
 * a clear are the system working, and narrating them would train people to
 * ignore the line that matters. */
export function saveWarning(outcome: SaveOutcome): string | null {
  if (outcome === "too-large") {
    return "These edits are too large to keep in the browser — they will be lost if you reload before committing.";
  }
  if (outcome === "unavailable") {
    return "This browser is not storing drafts, so unsaved edits will be lost if you reload before committing.";
  }
  return null;
}

/**
 * What to ask before throwing uncommitted work away (§288).
 *
 * `code-repositories.md` §2.2's Reset: *"Reset the contents of all files to
 * match the latest commit on your remote branch. This will clear any changes
 * that have not yet been committed on your branch"* (p.13).
 *
 * **It asks, because it is the one control here that destroys work and it sits
 * beside the one that saves it.** Commit and Discard are two buttons in one
 * bar, and the cost of the wrong one is everything typed since the last
 * commit - which, since drafts persist, may be days of it rather than the
 * current session.
 *
 * The count is in the question because "discard your changes?" and "discard
 * changes to 7 files?" are answered differently by the same person.
 */
export function discardQuestion(fileCount: number): string {
  return (
    `Discard uncommitted changes to ${fileCount} file${fileCount === 1 ? "" : "s"}? ` +
    "They are not saved anywhere else, so this cannot be undone."
  );
}
