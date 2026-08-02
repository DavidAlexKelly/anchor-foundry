# 0003 — Multi-file repositories, on Postgres

**Status:** decided
**Roadmap:** phase 2, item 2.1 (blocking for 2.2–2.8)
**Extends** `0001-where-code-lives.md`. It does not reopen it: there is still no git server.

---

## The question

Decision 0001 settled where transform code lives — `model_versions`, in Postgres, with git as an optional outbound mirror. It covered **one file per model**. Section 2 wants what Foundry's Code Repositories has: many files, directories, branches, diffs, and a review that reads them. None of that fits "one text column per model version", so the shape has to be decided before 2.2 puts an editor on top of it.

## The thing that must not break

`model_runs.model_version` points at the exact definition a run executed. Migration 0024 appends rather than rewinds precisely so that pointer resolves to **exactly one piece of code, forever** — it is what makes "which query produced this number?" answerable, what the quality gate records against, and what lineage resolves through.

That constraint is what shapes everything below, and it is the one a repository could quietly destroy: if a run's code were "whatever `main` says today", every historical answer would change the next time somebody committed.

## Decision

### 1. Two stores, one direction of flow

- **A repository is where code is authored.** Files, branches, commits, review.
- **`model_versions.code` stays the immutable execution record.** Publishing a transform from a repository *creates a version*, copying the source in as it stood at that commit.
- A version additionally records **where it came from** — repository, commit, path — so the trail is complete in both directions.

The copy is deliberate, and it is not redundancy: a version's `code` must be readable without resolving a commit that may since have been on a branch somebody deleted. **A record of what ran must not change when live state does** — the same rule the dataset versions, the audit log and the Workshop format all follow.

So: 0001's "the repository is a projection of `model_versions`" is **superseded in one direction only**. Repositories are no longer derived from versions; versions are now derived from repositories. Nothing about a *run's* provenance changes.

### 2. Git's data model, without git — and without trees

Content-addressed blobs, keyed by SHA-256 of the content, so a file unchanged across a hundred commits is one row. That much is git's design and it is the right one.

**Trees are not.** Git splits a snapshot into nested tree objects so a deep repository can share unchanged subtrees. A transforms repository here is tens of files, one or two levels deep, and the cost of that design is that reading a path means walking objects and every operation has an intermediate to get wrong. Instead a commit carries a **flat manifest**: `{path: blob_sha}` for the whole snapshot.

What that buys:

- **A diff is a dict comparison** — three sets, no walking.
- **A checkout is one join** — manifest to blobs.
- **A commit is verifiable by reading it**, which matters more than it sounds for the piece of the system that decides what code ran.

What it costs: the manifest repeats every path on every commit. At a hundred files and a few hundred bytes of paths, a commit's manifest is smaller than most single source files, and blobs — the actual content — are still shared. If a repository ever gets large enough for that to hurt, the fix is trees, and this decision is where to come back to.

### 3. Fast-forward only

A branch moves only to a commit that has its current head as an ancestor. No three-way merge.

Merging text in a browser is a product in itself — conflict markers, a resolution UI, and a whole class of "merged wrong" bugs whose blast radius is production transforms. Fast-forward covers what a review workflow actually needs: branch, commit, review, land. When somebody has a concrete need for divergent branches, that is the moment to design for it, with the case in hand.

A rejected non-fast-forward says so in a sentence naming the branch and its head, because the alternative — accepting it and silently discarding commits — is the failure mode this rule exists to prevent.

### 4. Immutability, and what may still change

Blobs and commits are immutable once written; branches are mutable pointers. That split is what makes a commit id safe to store on a model version.

Deleting a branch does **not** delete its commits. They are still referenced by any version published from them, and a version whose commit vanished would be a record that changed after the fact. Unreferenced commits are garbage, not errors, and collecting them is a separate decision with a separate risk profile — named here, not designed here.

### 5. Workspace-scoped deduplication

Blobs are keyed by `(workspace_id, sha256)`, not by hash alone. Two workspaces with identical file content get two rows.

This costs storage and buys the isolation property the whole platform rests on: a shared blob table would make "does this hash exist?" a cross-tenant question, and existence is information. The same reasoning as everywhere else in this schema — RLS is a visibility backstop, and it can only be one if rows belong to a workspace.

## What this does not decide

- **The editor.** Monaco, the file tree, the working set: 2.2 and 2.3.
- **What a transform declares.** How code in a repository names the dataset it produces, and how lineage reads it: 2.5.
- **Garbage collection** of unreferenced commits.
- **Git mirroring.** Still 0001's answer: an outbound sync surface, added when a customer asks, pointed at a remote they own. A flat manifest converts to a git tree cleanly, so nothing here forecloses it.
- **Binary files.** Blobs are `text`. A transforms repository holds source; the day something needs bytes, that is a column type and a size cap, decided then.

## Proof

`apps/api/tests/test_repositories.py`, against real Postgres:

- the same content committed twice stores one blob,
- a commit's manifest resolves to exactly the files committed,
- a diff between two commits reports added, modified and deleted paths, and reports a file whose content is unchanged as unchanged even when it moved,
- a non-fast-forward branch move is refused in a sentence,
- deleting a branch leaves its commits readable,
- two workspaces with identical content do not share a row.
