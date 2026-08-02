# 0001 — Where the Code pillar's data lives

**Status:** decided
**Scope:** `ROADMAP.md` Code item 1, the design spike that item 2 onwards is
blocked on.
**Reconciles with:** Models item 5 (`model_versions`, migration 0024, `STATUS.md` §31).

---

## The question as the roadmap asks it

> Whether to build a lightweight self-hosted git backend (`dulwich`, or the
> real `git` binary against a repo directory on EFS or S3, inside the
> customer's VPC) versus federating with the customer's own external
> GitHub/GitLab.

## The decision

**Do not build a git server. Keep the system of record in Postgres, and treat
git as an optional outbound mirror to a remote the customer already owns.**

Three parts, in the order they matter:

1. **The system of record for transform code stays `model_versions`.** Not a
   fallback position — a requirement that predates this spike.
2. **The Code pillar's "repository" is a projection of that table**, not a
   second store: a browsable tree of transform source with real change-set
   history, built on the versions Models already writes.
3. **Git federation is a sync surface**, added when a customer asks for it,
   pointed at their own GitHub/GitLab/Bitbucket, with the credential in the
   existing `SecretsGateway` — the same shape as a Connection, because it is
   one: an outbound connection to a system the customer already runs.

## Why the system of record cannot be git

This is the part the roadmap item does not anticipate, and it settles most of
the rest.

`model_runs.model_version` points at the exact definition a run executed, and
that pointer is load-bearing: it is what makes "which query produced this
number?" answerable, what the quality gate records against, and what dataset
lineage resolves through. Migration 0024's comment is explicit that rollback
*appends* rather than rewinds precisely so that a run's stamped version
resolves to exactly one piece of code, forever.

A git ref does not have that property. Branches move, history can be
rewritten, and a commit reachable today can be unreachable after a force-push
and garbage collection. Making git the system of record means either
(a) accepting that a run can point at code that no longer exists, or
(b) rebuilding immutability guarantees on top of git — pinning every run to a
commit SHA *and* refusing to ever GC, which is a worse version of what the
database already gives for free.

So git cannot replace `model_versions`. Everything below follows from that.

## Why not a self-hosted git server

Given the above, a self-hosted server would be a *second* store of the same
code, and its value has to come from something other than versioning. The
plausible answers are: developers cloning the repo to edit locally, running
their own CI, and reviewing changes in tools they already use. A git server
inside the customer's VPC serves those *badly*:

- **Nobody can reach it.** The stack runs services in
  `PRIVATE_WITH_EGRESS` subnets with only the ALB public
  (`customer-stack.ts`). Making a git server clonable from a developer's
  laptop means a new public ingress with its own authentication — SSH keys or
  HTTP credentials — which is a new auth model, not a small one. That is the
  same problem `ROADMAP.md` Canvas item 7 flagged as a stretch, and it is not
  cheaper here.
- **There is nowhere to put the repo.** There is no EFS in the stack, and
  Fargate tasks are ephemeral and horizontally scaled, so a repo directory on
  a task's disk is neither durable nor shared. Adding EFS means a mount, a
  security group, a backup story, and a stateful thing in a stack whose only
  stateful components today are RDS, S3 and OpenSearch. The alternative — a
  `dulwich` object store over S3 — avoids the mount and replaces it with
  writing packfile negotiation against an object store.
- **The value would be a worse history UI.** Strip out clone-from-laptop and
  external CI, and what is left of the git server is: numbered snapshots,
  authorship, diffs, restore. All four are already in `model_versions`, with
  RLS, audit and run-stamping the git server would have to re-implement.

An in-VPC git server is therefore the option that costs the most and delivers
least: significant new infrastructure to obtain capabilities the database
already provides, minus the one capability (developer tooling interop) that a
private-subnet server cannot deliver anyway.

## Why federation is not a betrayal of "runs inside the customer's account"

The roadmap's hesitation is that federation "couples a from-the-customer's-
account-outward dependency into a platform whose entire pitch is self-
contained deployment". Worth being precise about what that pitch protects:
**the vendor does not hold the customer's data.** It has never meant the
customer may not use their own SaaS — the Connections pillar's entire purpose
is reaching out to systems the customer already runs, over an egress path the
VPC already has (`natGateways: 1`), with credentials in Secrets Manager via
`SecretsGateway`. A mirror to *the customer's own* GitHub org is that same
category of thing. A mirror to a vendor-hosted git service would not be, and
is not proposed.

Two properties keep the dependency honest, and both are non-negotiable:

- **The platform never requires the remote to function.** Models build, run
  and version with no git remote configured. Sync failure degrades to a
  reported sync error — the shape `sync_runs` already uses — not a broken
  pipeline.
- **The remote is never authoritative.** Nothing the platform does is
  authorised by the state of an external repository (see promotion, below).

### On AWS CodeCommit

The option that would have satisfied "in the customer's own account" *and*
"clonable from a laptop" is CodeCommit: IAM-authenticated, in-region,
no new auth model. AWS closed CodeCommit to new customers in 2024, so a
freshly provisioned customer account cannot be assumed to have it. Noted
because it is the obvious question a reviewer will ask, and because if that
changes it is the best federation target by a distance — **verify current
availability before implementing federation** rather than taking this
paragraph's word for it.

## What this makes the remaining items

**Item 2 (transform code first, not a general IDE)** stands, and gets
cheaper. It is a *surface* over data that already exists rather than a new
backend: a repository-shaped view of a project's model source, with a change
history that spans models rather than sitting inside one. The one genuinely
new concept it needs is the **change set** — today a save writes one
`model_versions` row per model, so "these three transforms changed together
for one reason" is not expressible. That is the commit analogue, and it is a
small table plus a save path that can take more than one model, not a git
server.

**Item 3 (round-trip with Models)** is answered by construction: there is no
round trip, because there is no second copy. Editing code through Code writes
a model version through the same service the inline editor calls, so it
triggers the same build path automatically. The roadmap's suspicion — "Models
item 5 and Code's commit history may end up being the same mechanism viewed
two ways" — is exactly right, and this decision makes them literally the same
rows.

**Item 4 (review-gated promotion)** must be platform-native, and this is a
security boundary rather than a preference. If a merged pull request on the
customer's GitHub authorised a change to what runs in the platform, then
whoever administers that GitHub org — a set of people the platform does not
manage and cannot enumerate — could change what a transform computes. The
platform already refuses this class of thing elsewhere: a published canvas
app shares a layout and never grants the viewer access to data they were not
given (`STATUS.md` §44). Approval state therefore lives in Postgres against
platform identities, with RLS like everything else. A git mirror may *carry*
the diff so reviewers can read it in a familiar tool; it may not be what says
yes.

## Consequences, stated plainly

- **Anyone expecting `git clone` on day one will be disappointed.** This
  decision deliberately trades that for not running a git server. If a
  concrete customer names local editing as a requirement, federation (item 2's
  optional half) is the answer, and it needs their remote — not ours.
- **Change sets are new schema.** Item 2 introduces one table and a
  multi-model save path; `model_versions` rows gain an optional change-set
  reference. Existing single-model saves keep working with no change set,
  because a history that suddenly required one would invalidate every version
  written before it.
- **Diffs are computed, not stored.** Two versions' `code` is all a diff
  needs; storing rendered diffs would be a second copy that can disagree with
  the thing it describes.
- **This doc is a decision, not a design.** Item 2's schema and endpoints get
  designed when item 2 is built, against this shape.
