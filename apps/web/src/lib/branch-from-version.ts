/**
 * Branching a dataset from one of its historical transactions
 * (§357; `dataset-preview` p.4).
 *
 * > "You can use the **History tab** to create branches on historical
 * > transactions of your data that have not been deleted by a retention
 * > policy. Choose a previous transaction from the left panel and select the
 * > ellipsis (...) icon to **Create branch**." (p.4)
 *
 * The action itself has existed since migration 0025 — a fork copies one
 * version into an independent dataset — but it lived on the datasets *list*,
 * behind a dropdown asking which version you meant. p.4 puts it on the
 * transaction you are already reading, which is the difference this makes:
 * the version is not a question, it is the row you pressed.
 *
 * Pure, and in `lib/` rather than beside the component, because vitest cannot
 * parse `.tsx`: a rule that lives in a component is a rule with no unit test.
 */

/**
 * What a branch off version `n` is called before anyone renames it.
 *
 * **Both the source and the version**, because branching twice off the same
 * dataset at different points is the normal case and "Orders (branch)" twice
 * tells a reader nothing about which is which. Including the version also
 * makes the second branch off the *same* version collide on slug, which the
 * server already refuses by name — a better outcome than two identical
 * datasets, since the refusal says what happened.
 */
export function branchName(source: string, version: number): string {
  return `${source} v${version}`;
}

/**
 * Why a version cannot be branched, or `""` when it can.
 *
 * `size_bytes` is a HEAD against the object store taken when the history was
 * listed, so `null` means the bytes are not where the row says they are —
 * storage cleared under a dev machine, a bucket lifecycle rule, a database
 * restored against the wrong bucket. The History tab already refuses to *view*
 * such a version for exactly this reason, and branching copies the same bytes.
 *
 * **Refused here as well as on the server**, not instead of it. The server's
 * refusal is the one that counts and is tested on its own; this one exists so
 * the button says why before it is pressed rather than after, which is the
 * difference between a control that is off and one that looks broken (§214).
 *
 * p.4 scopes branching to transactions "that have not been deleted by a
 * retention policy". This platform has no retention policy at all
 * (`docs/decisions/0005` — nothing deletes an old version today), so that
 * sentence has no counterpart to copy; the state it guards against arrives by
 * the routes above instead, and this is what it is called here.
 *
 * **`undefined` counts as gone, the same as `null`.** `size_bytes` is optional
 * on `DatasetVersion`, so a response that omits it reads as absent rather than
 * measured — and the History tab's View button has always used `== null`,
 * which catches both. Refusing is also the safe direction of the two: a branch
 * offered on a version whose bytes turn out to be missing fails at the server
 * anyway, and a refusal that says why beats a request that says "conflict".
 */
export function whyNotBranchable(version: {
  size_bytes?: number | null;
}): string {
  if (version.size_bytes === null || version.size_bytes === undefined) {
    return "this version's data is no longer in storage, so there is nothing to copy";
  }
  return "";
}
