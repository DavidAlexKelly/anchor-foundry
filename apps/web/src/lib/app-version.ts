/**
 * Which version of a module a link opens (§314; `workshop` p.166).
 *
 *     "For testing purposes, you can change the `/latest/` to `/dev/` in the
 *      URL, and the link will now redirect to the last saved version of the
 *      Workshop application instead of the last published version." (p.166)
 *
 * **A query parameter rather than a path segment**, which is a divergence with
 * a reason. p.166 has `/latest/` and `/dev/` in the path; every other piece of
 * linkable state in this platform lives in the query string, through
 * `useUrlState` — the open file in a repository, the Explorer's search, the
 * object it has open (§309). A second convention for one flag would be two
 * ways of saying where you are, and the one that got less use would be the one
 * that broke.
 *
 * What p.166 is *for* survives the translation intact: a URL somebody edits by
 * hand to see what they have saved without publishing it.
 */

export const VERSION_PARAM = "version";

/** p.166's two. `latest` is the default and needs no parameter. */
export type AppVersion = "latest" | "saved";

/**
 * Which version this URL asks for.
 *
 * **Anything unrecognised is `latest`**, deliberately. A mistyped parameter
 * should show the published module — the thing everybody else sees — rather
 * than a draft, because the failure mode of guessing the other way is showing
 * unpublished work to somebody who typed a character wrong.
 */
export function versionFrom(raw: string | null): AppVersion {
  return raw === "saved" ? "saved" : "latest";
}

/**
 * What the banner says, or nothing.
 *
 * **Nothing on `latest`**, because that is the ordinary case and a banner on
 * every published module is one nobody reads. On `saved` it is worth saying
 * twice over: p.166 calls this "for testing purposes", and somebody who has
 * arrived on a hand-edited link needs to know that what they are looking at is
 * not what their colleagues see.
 */
export function versionNote(version: AppVersion): string | null {
  return version === "saved"
    ? "This is the last saved version, not the published one. Other people see " +
        "the published version until you publish again."
    : null;
}

/**
 * Whether the module on screen differs from the published one.
 *
 * Only meaningful on `saved`: on `latest` the two are the same thing by
 * definition. `null` when it cannot be told — an app that has never been
 * published has no version to differ from, and saying "1 change ahead" of
 * nothing would be arithmetic rather than information.
 */
export function aheadOfPublished(
  version: AppVersion,
  currentVersion: number,
  publishedVersion: number | null,
): number | null {
  if (version !== "saved" || publishedVersion === null) return null;
  const ahead = currentVersion - publishedVersion;
  return ahead > 0 ? ahead : null;
}

/** The sentence for that count, in the builder's own terms. */
export function aheadNote(ahead: number | null): string | null {
  if (ahead === null) return null;
  return ahead === 1
    ? "1 save ahead of what is published."
    : `${ahead} saves ahead of what is published.`;
}
