/**
 * p.67-69's README, and the two link forms that make it a repository's
 * documentation rather than a text file (§442; `code-repositories` p.67-69).
 *
 * > "You can provide users with documentation on projects in Code Repositories
 * > by adding a README file. README files in Code Repositories support
 * > Markdown… Edit or add a `README.md` file to your repository to get
 * > started." (p.67)
 *
 * > "You can reference any Foundry resource by pasting its Resource ID
 * > directly into the Markdown file for the README. Resources referenced like
 * > this will automatically be named and linked to the corresponding resource
 * > in platform." (p.68)
 *
 * > "To create a link to a file within your repository, use the `repo://`
 * > protocol followed by the file path… Files referenced like this will
 * > automatically open when clicked." (p.68)
 *
 * **Everything else on those pages is the Markdown module's already** —
 * headings, tables, fenced code with a language, automatic links. p.318's
 * syntax list is what `canvas/markdown.ts` was built from, so a README gets
 * all of it for nothing, including the fact that raw HTML in it is text.
 *
 * **The two link forms are done by rewriting the source, not by a second
 * parser.** `safeHref` already allows a root-relative path, so `repo://a/b`
 * and a pasted id become ordinary Markdown links before parsing — which means
 * they go through the same escaping, the same link rendering and the same
 * refusal path as every other link, instead of through a branch that would
 * have to be kept in step with them (§292).
 */

/** p.67's file, at the root. */
export const README_PATH = "README.md";

/** p.68's protocol. */
export const REPO_PROTOCOL = "repo://";

/**
 * A resource id as this platform spells one.
 *
 * Foundry's is `ri.foundry.main.dataset.<uuid>`; ours is the bare UUID that
 * `/r/{id}` takes, so that is what somebody pastes.
 *
 * **Bounded by anything a token is made of, hyphens included** — not by `\b`,
 * which was the first version and is wrong here: a hyphen *is* a word
 * boundary, so `<id>-old.sql` matched and a filename in somebody's prose
 * became a link to a resource. The ids themselves contain hyphens, which is
 * exactly why the ordinary boundary cannot tell one from the middle of a
 * longer name.
 */
const RESOURCE_ID =
  /(?<![\w-])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\w-])/gi;

/** The README out of a working tree, or null.
 *
 * **At the root, and case-sensitively.** p.67 names one file; treating
 * `readme.md` and `docs/README.md` as it too would mean a repository could
 * have two documentation pages and no way to say which one is shown. */
export function readmeFrom(files: Record<string, string | undefined>): string | null {
  const found = files[README_PATH];
  return found === undefined ? null : found;
}

/** Every resource id a README mentions, so the panel can ask what they are
 *  called. Distinct, because p.68's "named" is one question per resource
 *  however many times it appears. */
export function mentionedResources(source: string): string[] {
  return [...new Set((source.match(RESOURCE_ID) ?? []).map((id) => id.toLowerCase()))];
}

/** Where a `repo://` path goes: this repository, this file, open (§428's
 *  `?file=`, at §435's stable address). */
export function fileHref(resourceId: string, path: string): string {
  return `/r/${resourceId}?tab=files&file=${encodeURIComponent(path)}`;
}

/**
 * p.68's two rewrites, applied to the source before it is parsed.
 *
 * **Fenced and inline code are left alone**, which is the one thing this has
 * to get right: a README explaining the `repo://` syntax, or showing an id in
 * an example, would otherwise have its own examples turned into links — and
 * p.67's page is exactly the kind of document that contains them.
 *
 * `names` is what each resource is called, where the caller has found out.
 * An id nobody could resolve still becomes a link: p.68 says a pasted id is a
 * reference, and one that rendered as bare text because the lookup failed
 * would look like a typo rather than like a resource somebody cannot see.
 */
export function linkify(
  source: string,
  { repositoryId, names = {} }: { repositoryId: string; names?: Record<string, string> },
): string {
  return outsideCode(source, (text) =>
    text.replace(BOTH_FORMS, (whole, path: string | undefined) =>
      path === undefined
        ? `[${names[whole.toLowerCase()] ?? whole}](/r/${whole})`
        : `[${path}](${fileHref(repositoryId, path)})`),
  );
}

/**
 * The two forms, in **one alternation and therefore one pass**.
 *
 * Not two `replace` calls, and the browser suite is what said so: a repository
 * id is a resource id, so the link the `repo://` rewrite had just written —
 * `[daily.sql](/r/<repo-id>?tab=files&…)` — was rewritten again by the
 * resource rule into a link nested inside a link, and the href it produced
 * navigated nowhere. One pass cannot see its own output, which is the property
 * being bought rather than an optimisation.
 *
 * The path runs to whitespace or a closing bracket, so `repo://a/b.sql` inside
 * a sentence ends where the sentence does.
 */
const BOTH_FORMS = new RegExp(
  `repo:\\/\\/([^\\s)\\]]+)|${RESOURCE_ID.source}`,
  "gi",
);

/**
 * Apply `change` to everything except code.
 *
 * Fences first, then inline spans, because a fence may contain backticks and a
 * span may not contain a newline — doing it the other way round would let an
 * inline rule reach inside a fenced block.
 */
function outsideCode(source: string, change: (text: string) => string): string {
  return source
    .split(/(```[\s\S]*?```|~~~[\s\S]*?~~~)/g)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part.split(/(`[^`\n]*`)/g).map((bit, i) => (i % 2 === 1 ? bit : change(bit))).join(""),
    )
    .join("");
}

/** What the panel says when there is no README.
 *
 * **It names the file and the tab that makes one**, because p.67's instruction
 * — "edit or add a `README.md` file to your repository" — is the whole answer
 * and a panel saying "no documentation" leaves somebody looking for a setting
 * that does not exist. */
export function emptyReason(): string {
  return (
    `No ${README_PATH} yet. Add one in Files and it is shown here — Markdown, `
    + `with ${REPO_PROTOCOL} links to files in this repository and pasted `
    + `resource ids linked by name.`
  );
}
