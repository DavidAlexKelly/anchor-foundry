/**
 * `repoSettings.json`, as the editor reads it (§441, §444).
 *
 * The server's copy is `apps/api/src/services/repo_settings.py`, and the
 * division is the one every pair in this repository uses: the server owns
 * every refusal, this owns what to *offer*. **Which means they must not
 * drift** (§162, §191) — the keys and the treatment of an unreadable file are
 * the same decisions in two languages, and
 * `test_the_browser_reads_the_same_settings_file_the_server_does` reads this
 * file to check the first of them.
 *
 * **Its own module since §444**, when p.115's dataset-reference setting became
 * the second thing here to read the file. One parser, imported by both: a
 * second answer to "is this file readable" would disagree with the first the
 * moment either was made stricter (§292).
 *
 * **Named for the file rather than for the repository**, because
 * `repo-settings.ts` was already taken — by §279's module about what the
 * *Settings tab* may offer, which is a different question with a confusingly
 * similar name. Said here rather than left for whoever opens the wrong one.
 */

/** What a settings file is, once parsed. */
export type Settings = Record<string, unknown>;

/** Foundry's own settings file, at the root of the repository (p.17, p.105). */
export const SETTINGS_FILE = "repoSettings.json";

/** p.114's block. The key is ours; the behaviour is p.114's — see
 *  `repo_settings.py`, which says why it is spelled like `tagNameValidation`. */
export const COMMIT_BLOCK = "commitMessages";



/**
 * `repoSettings.json` out of the working tree, or `{}`.
 *
 * **Absent and unreadable are the same answer**, which is §299's decision
 * inherited rather than re-argued: a convention fails open, because the person
 * a syntax error blocks is rarely the person who wrote it. Here it matters
 * twice over — this reads a file somebody may be *in the middle of editing*,
 * so a half-typed brace must not disable the button they are about to press.
 */
export function settingsFrom(files: Record<string, string | undefined>): Settings {
  const raw = files[SETTINGS_FILE];
  if (raw === undefined) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Settings)
      : {};
  } catch {
    return {};
  }
}

/** p.115's dataset aliases, the editor half.
 *
 * > "Automatically change to RIDs when possible — This option will insert the
 * > RID of the dataset… The editor will present the dataset name over the RID
 * > and allow editing it as needed." (p.115)
 *
 * **Off unless the file asks**, for `commitMessages`' reason: every repository
 * here was written before the setting, and their declarations name datasets by
 * name. Turning it on changes what the *editor types for you* and nothing
 * else — a file that already names a dataset goes on working either way, which
 * is what makes this a preference rather than a migration.
 *
 * **`=== "id"`, not "anything but name"**, so a settings file carrying a value
 * nobody here understands keeps the behaviour it had rather than picking one.
 */
export const REFERENCES_BLOCK = "datasetReferences";

export function prefersIds(settings: Settings): boolean {
  const block = settings[REFERENCES_BLOCK];
  return typeof block === "object" && block !== null
    && (block as Record<string, unknown>).prefer === "id";
}
