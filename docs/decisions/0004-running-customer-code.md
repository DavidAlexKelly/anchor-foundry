# 0004 — Where customer transform code runs

**Status:** decided
**Roadmap:** phase 2, item 2.5 (blocking for turning Python transforms on)
**Builds on:** `apps/worker/src/anchor_worker/python_sandbox.py`, which already says it is not a security boundary. This says what it is not a boundary *against*, which turns out to matter more than expected.

---

## The question

Item 2.5 is "code in a repository declares the dataset it produces, and a build runs it". The running part needs a decision first, because Python transforms are written today, stored today, and deliberately **not executed** — the API leaves a `language='python'` run queued rather than running it. Turning that on is the change this document gates.

## Threat model, stated properly

The existing sandbox docstring is honest that it is "not a hard multi-tenant security boundary". What it does not say is who the adversary is, and that changes the answer.

**The author is a customer employee with editor access to a project**, writing a transform in the customer's own deployment, in the customer's own AWS account. They are not an anonymous attacker, and they already have legitimate access to the data in their project. So the bar is *not* "run arbitrary hostile code safely" — a genuinely hard problem.

The bar is: **a transform must not reach anything its author could not already reach**, and must not take the platform down trying.

By that measure, process isolation with resource caps is close to the right shape. One thing is not.

## The finding

`python_sandbox.py` builds the subprocess environment as an explicit allowlist — `{"PATH": …, "HOME": tmp}` — so no database URL and no AWS keys are inherited. That is correct and it is where the reasoning stopped.

**In the deployed stack, credentials do not arrive in the environment.** ECS delivers the task role over the network, from `169.254.170.2`. Stripping `os.environ` does not touch it, and the existing docstring already notes that the sandbox "does not stop the transform from opening a network socket" — the two facts had simply never been put next to each other.

What the worker's task role holds (`infra/cdk/src/constructs/services.ts`):

- `dataBucket.grantReadWrite` — **the whole data bucket**, every project and every workspace in that deployment.
- `appDbSecret.grantRead` — the application database secret.

And the second is worse than it looks. The credential is `platform_app`, which RLS *does* apply to — but `rls_worker_for_workspace` (migration 0006) grants visibility to any connection that sets

```sql
SET app.service = 'worker';
SET app.workspace_id = '<any workspace>';
```

That is the worker's own escape hatch, and it is sound precisely because only the worker process holds those credentials. A transform that can read the secret can set those two settings and read **every workspace in the deployment**.

So: three HTTP requests from inside a transform — fetch task credentials, fetch the secret, connect — and workspace isolation is gone. Not a live vulnerability, because Python transforms do not execute at all today. Exactly the constraint that has to be settled before they do, which is why this was spiked rather than built.

## Decision

**A transform runs in a process that cannot obtain the platform's credentials.** Three parts, in the order they must be built.

### 1. The runner's task role grants nothing — and this is the control

Not "narrower than the worker" — nothing. Input Parquet is staged into the working directory by the *caller*, which holds the credentials; the output is read back the same way. The runner never touches S3, never touches Postgres, and has no role worth stealing.

**Corrected after building it** (`STATUS.md` §64): the first draft of this document made the network rule the control and the empty role the second layer. That is backwards. ECS delivers task credentials over **link-local** networking, which a security group does not filter — so no egress rule stops a transform *obtaining* credentials. Only their emptiness stops them mattering. The ordering decides which of the two must never be quietly relaxed, so it is worth being right about.

### 2. Egress is closed, and that is the blast radius

A transform needs no network: its inputs arrive as files and its output is a file, which is already how `python_sandbox.py` works. Closed egress does not prevent credential theft; it prevents anything stolen — or anything read — from leaving, in a product whose premise is that data stays inside the customer's boundary. `AWS_EC2_METADATA_DISABLED` sits behind both as a third layer that removes a confusing failure mode rather than as a mechanism.

**A no-egress task cannot start without help.** Fargate pulls the image and ships logs over the task ENI, so the stack also gains VPC endpoints for ECR, ECR Docker, CloudWatch Logs and S3 — about $21–24 a month per deployment. Without them the container never runs and CloudWatch shows an empty log stream.

### 3. Until both exist, Python stays off

The API already leaves Python runs queued. That stays true until the runner has its own task definition and its own empty role. Shipping execution first and hardening later would mean shipping the escalation path described above, in a product whose entire premise is that data stays inside the customer's boundary.

SQL transforms are unaffected: they run through DuckDB with `enable_external_access` off, which is a real boundary for what SQL can express.

## Declarations are read statically, never by import

A transform declares its inputs and outputs. Foundry evaluates a decorator at import time to find them; **this platform must not**, because importing a module to read its decorators *is* executing it — the thing the whole document is about. Reading a declaration would become the same risk as running the transform, on the API's request path, before any sandbox is involved.

So declarations are parsed from the source with `ast`, which does not execute anything:

```python
@transform(output="daily_orders", inputs={"orders": "raw_orders"})
def build(orders): ...
```

Only literals are read. A declaration built by calling a function, or assembled from a variable, is **refused** rather than guessed at — a lineage graph that is right most of the time is worse than one that tells you it cannot read a file, because nobody checks the edges they cannot see.

SQL transforms declare the same way, in a leading comment, so both languages answer the same question in the same place:

```sql
-- output: daily_orders
-- input: orders = raw_orders
```

## And the same file has to run — added in §272

The section above says what a declaration *looks like*, and for a long time that was all it said. The runner had its own contract, written in `python_sandbox.py`: each input arrives as a module-level name and the script assigns `output`. Both documents were right about themselves and nothing checked them against each other, so **the shape printed above could not run at all** — `@transform` was undefined in the namespace the sandbox execs into, and a repository-authored Python transform died on `NameError` before reaching any of the sandbox's actual limits. Even given a no-op decorator, the function's return value went nowhere, because nothing called it.

It survived because no test crossed the seam: every file in the publish suite was `.sql`, and every file in the sandbox suite was a script.

So the runtime contract is written down here, beside the syntax it belongs to:

- **The declared shape runs by calling the function**, with the declared inputs passed **by keyword under their aliases**. Keyword and not position, for the same reason `@transform` itself takes no positional arguments: the file says which name means what, and binding by position would let a transform whose parameters are in a different order read the wrong dataset and still produce a table.
- **The script shape stays, and takes precedence.** Every model authored before repositories existed is a script, and a run is stamped to the exact code that produced it (decision 0001) — a contract change that made an old definition mean something new would rewrite history rather than extend it. A file with both is a script that also declares, and the assignment is what ran last.
- **The decorator defined in the runner records and returns; it never parses.** Reading a declaration by importing the file is the thing this whole document refuses. The runner's `transform` exists so the file can *find* the name, not so anything can learn what it says.
- **One file declares one transform, in both languages.** SQL refused a second `-- output:` from the start; Python returned the first of two decorated functions and dropped the second silently — not built, not scheduled, not in the lineage graph, with a stale dataset as its only symptom. Both refuse now, and the Python refusal names both functions, because the fix is to split the file.

## What this does not decide

- **The scheduler side**: how a run is dispatched to the runner task, and what happens when the task cannot start.
- **Dependencies.** A transform that wants pandas gets whatever the runner image ships. Per-repository dependency sets are a build system, and a separate decision.
- **Whether the sandbox is ever enough for hostile code.** It is not, and it is not meant to be. If this platform ever runs code from someone who is not the customer's own employee, that is a different threat model and this document does not cover it.

## Proof

`apps/api/tests/test_transform_declarations.py`: declarations are read from source without executing it (a module whose import would raise still parses), non-literal declarations are refused with a reason, both languages produce the same structure, and a file declaring no transform is not an error — it is a helper.
