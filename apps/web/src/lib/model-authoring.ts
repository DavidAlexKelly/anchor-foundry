/**
 * Where a transform is authored, and what a screen may therefore offer (§275).
 *
 * The pure half of the Models page's relationship with repositories. The server
 * owns what is *legal* — `services/models.py` refuses a direct edit to a
 * repository-authored model, and db 0038 says why — and this owns what to
 * *offer*, which is the split every pair in this repository uses.
 *
 * **It exists because the offer was wrong.** `ModelOut` has declared
 * `source_repo_id` since §94 and the shared `Model` type did not, so no screen
 * could read it, and the Models page showed an editable body and a Save button
 * for every model including the ones the server refuses. A control that looks
 * like it works is §214's shape, and the field being on the wire but absent
 * from the type is how it stayed invisible.
 */
import type { Model } from "./types";

/** Just enough of a model to answer these questions — so a caller holding a
 *  list row rather than a full model can still ask. */
export type Authored = Pick<Model, "source_repo_id" | "source_path">;

export function authoredInRepository(model: Authored): boolean {
  // **`source_path` as well, not `source_repo_id` alone.** db 0038 holds them
  // together with a CHECK constraint, so in practice one implies the other -
  // but this is a *browser* reading JSON, and the constraint is not here. A
  // model with a repository and no path would render "authored at undefined"
  // and offer a link to nowhere.
  return Boolean(model.source_repo_id && model.source_path);
}

/** Whether this screen may offer to edit the transform's body and inputs.
 *
 * Not "may the user edit anything": trigger mode, schedule and health policy
 * stay editable on a repository-authored model, because `models.update` gates
 * only what a transform *computes*. Gating the rest would make a project that
 * requires review unable to pause a job — the reason that line is drawn where
 * it is in the service.
 */
export function canEditBody(model: Authored): boolean {
  return !authoredInRepository(model);
}

/** Whether to offer moving this transform into a repository (§274).
 *
 * One-way, so the button is offered exactly once. Adoption does not change what
 * runs — the code is copied through and the declaration is written from what
 * the model already says — which is why it is not the review gate's business.
 */
export function canAdopt(model: Authored): boolean {
  return !authoredInRepository(model);
}

/** Why the body is read-only here, phrased for whoever came to edit it.
 *
 * Names the file, because the next thing this reader wants is to open it, and
 * a message that only says "this is read-only" makes them go looking.
 *
 * **Two refusals, and they are different questions** (§277). Whether this
 * definition is *authored elsewhere* is db 0038's rule, and the answer is "go
 * to the file". Whether this project *requires review* is `require_code_review`
 * (`services/models.py`), and the answer used to be "open a proposal" — which
 * was true while the Code pillar page existed to open one on, and is the thing
 * B.1 deletes. For a transform that is not yet a file there is now one path:
 * move it into a repository, and propose the commit there.
 *
 * Collapsing the two would make "your project requires review" read as "this
 * file lives somewhere else", which sends the reader looking for a file that
 * does not exist.
 */
export function readOnlyReason(
  model: Authored,
  { reviewRequired = false }: { reviewRequired?: boolean } = {},
): string | null {
  if (authoredInRepository(model)) {
    return (
      `This transform is authored in a repository, at ${model.source_path}. ` +
      `Edit the file and publish it — a direct edit here would make the ` +
      `repository describe a pipeline that is not the one running.`
    );
  }
  if (reviewRequired) {
    return (
      `This project requires code review, so a transform cannot be changed ` +
      `directly. Move it into a repository, then propose the commit there — ` +
      `a review reads a diff, and a diff needs a file.`
    );
  }
  return null;
}

/**
 * The path a model would be adopted to, or null to let the server derive one.
 *
 * **Deliberately does not re-implement the server's rule.** `transform_adoption
 * .default_path` runs the model's name through `datasets.slugify`, and a second
 * copy of that in TypeScript is the mirrored-list problem §191 found: two
 * copies agree until one changes, and the disagreement here would be a file
 * written at a path the screen did not predict. So an empty box means "you
 * choose", the server answers, and the result is displayed — one rule, in the
 * place that owns it.
 *
 * What this *can* do without a second copy is refuse a path that is obviously
 * wrong before a round trip: the extension has to match the language, because
 * publishing reads the language off the path.
 */
export function pathProblem(path: string, language: Model["language"]): string | null {
  const trimmed = path.trim();
  if (!trimmed) return null; // empty means "derive one"
  const wanted = language === "python" ? ".py" : ".sql";
  if (!trimmed.endsWith(wanted)) {
    return `A ${language} transform has to be in a ${wanted} file — publishing reads the language from the path.`;
  }
  if (trimmed.startsWith("/") || trimmed.includes("..")) {
    return "Give a path inside the repository, without a leading slash.";
  }
  return null;
}

/** How to describe where a transform lives, in a sentence a header can hold. */
export function authoringSummary(model: Authored): string {
  return authoredInRepository(model)
    ? `Authored in a repository · ${model.source_path}`
    : "Authored here";
}
