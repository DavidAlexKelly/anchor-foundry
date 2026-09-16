/**
 * Rolling a dataset back to one of its earlier versions
 * (§361; `data-lineage` p.73, p.75-76).
 *
 * > "Select the transaction to roll back to. Select **Rollback to
 * >  transaction**. A confirmation dialog will be displayed." (p.75-76)
 *
 * Sits beside `branch-from-version.ts` because the two are the same shape —
 * an act offered on the History row you are already reading rather than behind
 * a dropdown asking which version you meant — and pure, in `lib/` rather than
 * beside the component, because vitest cannot parse `.tsx`: a rule that lives
 * in a component is a rule with no unit test.
 *
 * **The interesting part of this module is that it does not copy p.76's
 * warning.** Foundry asks you to "acknowledge the warning that a rollback
 * cannot easily be undone". Here it can: a rollback appends a version pointing
 * at the old one's file and deletes nothing, so rolling back to the version
 * you were on puts it back (`test_dataset_rollback.py` asserts exactly that).
 * Repeating a warning that is not true of this platform would frighten
 * somebody out of a reversible act, which is the §214 failure pointed the
 * other way: not a control that looks like it works, but a caution that looks
 * like it is warranted.
 */

/** The shape this module reads — the History tab's rows, and no more. */
export type RollbackVersion = {
  version_number: number;
  size_bytes?: number | null;
};

/**
 * Why a version cannot be rolled back to, or `""` when it can.
 *
 * Two reasons, and they are the server's two refusals said before the press
 * rather than after (`services/datasets.roll_back`). **Refused here as well as
 * there, not instead of it**: the server's is the one that counts and is
 * tested on its own; this one is the difference between a control that is off
 * and one that looks broken.
 *
 * `size_bytes` is a HEAD taken when the history was listed, so `null` — or
 * absent, since the field is optional — means the bytes are not where the row
 * says they are. `whyNotBranchable` reads it the same way for the same reason.
 */
export function whyNotRollbackable(
  version: RollbackVersion,
  currentVersion: number,
): string {
  if (version.version_number === currentVersion) {
    return "this is the version the dataset is on";
  }
  if (version.size_bytes === null || version.size_bytes === undefined) {
    return "this version's data is no longer in storage, so there is nothing to roll back to";
  }
  return "";
}

/**
 * What the confirmation says, in the reader's own numbers.
 *
 * Three sentences, each of which is a thing that is true here and that a
 * person about to press Rollback cannot see from the row:
 *
 * 1. **What the data becomes**, named as a version rather than as "earlier",
 *    because the History tab has just shown them several.
 * 2. **That the history is kept**, which is where this differs from Foundry
 *    (p.70 crosses the skipped transactions out) and is what makes the act
 *    reversible.
 * 3. **That the logic is not rolled back with it** — p.74: "the logic backing
 *    the dataset will be left unchanged and will need to be updated in order
 *    to apply to the next build". That one *is* copied, because it is true
 *    here too: rolling back a model's output does not touch the model, so the
 *    next build overwrites what the rollback restored.
 */
export function rollbackSummary(
  version: number,
  currentVersion: number,
  origin: string,
): string[] {
  const lines = [
    `The dataset's data becomes what it was at v${version}, as a new v${currentVersion + 1}.`,
    `Nothing is deleted: v${currentVersion} stays in the history and readable, so this can be rolled back again.`,
  ];
  if (isRebuilt(origin)) {
    lines.push(
      "The logic that builds this dataset is not rolled back with it, so the next build will overwrite this.",
    );
  }
  return lines;
}

/**
 * Whether something will write this dataset again on its own.
 *
 * Decided here rather than in the dialog so p.74's warning is shown exactly
 * where it can come true. **An uploaded dataset and a fork have no logic**:
 * nothing rebuilds them, so the restored data stays until a person replaces
 * it, and a warning about "the next build" would be a sentence the reader has
 * to work out does not apply to them — which is how a dialog teaches people to
 * skip its text.
 *
 * A sync counts alongside a model output. Foundry's sentence is about a
 * JobSpec, but the property that matters is "something else writes this on a
 * schedule", and a connection sync does.
 */
export function isRebuilt(origin: string): boolean {
  return origin === "model_output" || origin === "sync";
}
