# 0012 — Webhooks: the two failure semantics, and where an external call may sit

**Status:** decided, **not yet built**.
**Parity items:** `docs/parity/ontology.md` §5.2 (side effects, build order item 10's second half) and `docs/parity/data-connection.md` §2 (Webhooks, build order item 2). One implementation serves both, which is why that line has said "load-bearing twice" since it was written.
**Source:** `docs/pal/foundry_action-types.pdf` (174 pp) for the action's half, cited `(a-p.N)`; `docs/pal/foundry_data-connection.pdf` (417 pp) for the resource's half, cited `(d-p.N)`.
**Follows:** decision 0008, which is built. This is the first feature that wants to do something *outside* Postgres in the middle of an action, so 0008's transaction boundary is the thing it has to be designed around rather than the thing it may ignore.

---

## The problem, in one sentence

**An action that writes to an external system has two failure semantics, they are opposites, and picking one for everybody is wrong.**

Foundry does not pick. It offers both and puts the choice on the rule (a-p.105–107):

| Mode | When it runs | Failure shown? | How many | Order |
|---|---|---|---|---|
| **Writeback** | before object changes | **yes**, and the action is refused | **at most one** | n/a |
| **Side effect** | after object changes | no | many | "no particular order" |

Both sentences behind that table are load-bearing:

> "When configured as a writeback, the webhook will be executed before any other rules are evaluated; if the webhook execution fails, no other changes will be made." (a-p.106)

> "Because the action stops being applied when a writeback webhook fails, you can only configure a single webhook as a writeback." (a-p.106)

> "You should use side effect webhooks when you want to send best-effort notifications or write back to multiple external systems." (a-p.107)

And the honesty about what a writeback does *not* buy, which is the sentence a design would be tempted to leave out:

> "…it is still possible that the external request may succeed but Ontology changes could fail." (a-p.106)

There is no distributed transaction here and Foundry does not claim one. A writeback buys **one** of the two orderings — never-external-without-local is not on offer, only never-local-without-external.

## The decision

**One `webhook` rule kind with a `mode`, placed at the two points the executor already has, and never inside the Postgres transaction.**

### 1. The two placements already exist, and they are the two the document describes

`routes/actions.py` has exactly three regions, and §257's notifications already use two of them:

```
pre-write block      resolve everything that must be able to refuse the action
  open_run
    stage_version / commit_versions      ← one Postgres transaction (0008)
  close_run
post-commit block    if ok:  do what only makes sense once the write landed
```

A **writeback** goes in the pre-write block, beside `_pending_notifications` and for a stronger version of the same reason: p.96's permission check is there because a refusal must happen while the action can still be refused, and a writeback's whole purpose is to be able to refuse. A **side effect** goes in the post-commit block, beside `notification_store.deliver`, under the same `if ok:` — "modifications to Foundry objects will occur before side effects are applied" (the sentence runs across a-p.106–107) is that guard, stated from the other side.

That the two modes land on two blocks that already exist, for reasons already written down, is the main evidence this reading of the document is right.

### 2. No external call inside the transaction, and that is not negotiable

The pre-write block runs **before** `open_run`; the post-commit block runs **after** `close_run`. Neither holds the transaction that `commit_versions` opens.

This is worth stating as a decision rather than an implementation detail because the tempting alternative reads better: put the writeback inside the transaction and roll back on failure, and you get the transactionality a-p.106 says you cannot have. What you would actually get is a Postgres transaction — holding row locks on `datasets`, `dataset_versions` and the action's own row — kept open across a network call to a system that may be slow, unreachable, or a black hole for the full timeout. One slow external system would then hold locks that block every other action against the same dataset, and it would do it under exactly the conditions where the external system is already having a bad day.

The ordering 0008 chose for storage is the same argument and is already written down there: *"the expensive, slow, non-transactional part happens first and is discardable, and the cheap, atomic part happens last."* An external call is the most non-transactional thing in the system, so it goes furthest from the commit.

### 3. Where we knowingly differ: a side effect is synchronous

a-p.106's table says a side effect's timing "may be after user sees success message", and a-p.107 says "executing the side effects may happen after the success message is shown". Foundry's side effects are asynchronous; ours will run inside the request, after the commit, before the response.

**Named as a deviation rather than smoothed over**, because it has a cost somebody will feel: a slow external system makes every action that fires it slow, even though the action has already succeeded. The mitigations are a hard per-call timeout and the fact that a side-effect failure cannot fail the action — but the latency is real and this platform has nowhere else to put it. The worker exists and is schedule-driven (§14, §16); per-action work has no queue, and building one is a larger decision than this one. If per-action async work ever arrives, this is the first thing that should move onto it, and this paragraph is the note saying so.

### 3a. The call goes through `anyio.to_thread.run_sync`, for a different reason than §3

§3 is about latency somebody can see. This is about latency **nobody** can see, and it is the more dangerous of the two.

`connectors.RestConnector` makes its requests with blocking `urllib`, which is correct where it runs today: a sync executes in the worker, where blocking is the whole point. A webhook executes inside `async def execute_action`, and a blocking twenty-second call there does not slow *that* request — it stops the event loop, so every other request the process is serving stops with it. One unreachable external host would look like the API going down, and nothing in the logs would connect the two.

So the outbound call goes through `anyio.to_thread.run_sync`, which this repo already uses in six places for exactly this reason (`routes/datasets.py`'s ingest, `services/models.py`'s health checks). Named here rather than left to the implementation because the failure it prevents is invisible in every test that runs one request at a time — which is every test in this repo.

### 4. A webhook is a resource on a connection, not a URL on a rule

d-p.216: *"Each webhook is associated with a single source in Data Connection. The source stores the credentials necessary for connecting to the external system."* d-p.220: *"The source is meant to contain the minimal set of secrets and connection details required to establish a connection. When configuring individual webhooks using this source, you will have an opportunity to add additional request details, including the relative path, query parameters, headers, and body content."*

So the split is: the **connection** owns the base URL, the auth and the secrets; the **webhook** owns the method, relative path, query params, headers and body template; the **rule** owns the mapping from action parameters to webhook inputs.

Three reasons to keep that split rather than letting a rule name a URL directly:

* **The secret has one home.** `secrets.py` already encrypts a connection's credentials and no read endpoint returns them. A URL-on-a-rule design would need a second place to put a bearer token, and the second place is the one that leaks.
* **`connectors._check_url` already exists and is already right.** It refuses non-http(s), refuses plaintext unless asked, and refuses the link-local range because that is where cloud instance metadata lives. A rule that carried its own URL would either duplicate that guard or skip it, and an editor who can write an action would become an editor who can read the task role's credentials.
* **An egress allowlist has somewhere to hang.** `data-connection.md` §1 already recommends modelling egress policies per source. A webhook that is defined against a source inherits whatever that grows into; a webhook that carries a URL does not.

### 5. Outputs, and the one thing a side effect cannot have

a-p.110: *"When a Webhook is configured as a writeback Webhook, you can use its output parameters in subsequent rules."* a-p.111 names the surface: *"select **Writeback response** when populating the value for a logic rule."*

Only a writeback can do this, and the reason is structural rather than a restriction: a side effect runs after every rule, so there is no subsequent rule for its output to reach. The rule config gains a value source alongside the ones it has (`parameter`, static, object property): `{"kind": "webhook_output", "name": "..."}`, resolvable only when a writeback ran earlier in the same action.

Outputs are extracted by a named path into the JSON response (d-p.235: *"capturing top-level fields from a JSON response by name"*, and JSON extractors for more). The first cut takes the by-name and dotted-path form the REST connector's `_json_path` already implements, because a second path language in the same repo is a second thing to be wrong.

### 6. Stored responses are the sensitive part

d-p.242 is unusually explicit, and it is the half a first implementation would skip:

> "By default, inputs passed to the webhook and the full response will only be visible to the user who called the webhook. This protects any sensitive data passed in or returned from the webhook call."

> "This option may be disabled entirely for a webhook that is known to return sensitive information that should not be stored in the webhook history."

So: a `webhook_runs` row records what was sent and what came back; RLS scopes it to the caller the way db 0066 scopes a notification to its recipient; and the webhook carries a `store_responses` flag that turns the body off while leaving the status and timing on. d-p.247 gives the concrete case — an OAuth token in the first call's response — and the answer there is the flag, not a redaction pass.

The privileged read (`webhooks:read-privileged-data`, granted to nobody by default) is **not** built: this platform has no custom-role mechanism to hang it on, so there is no honest way to offer it. Absent rather than approximated, which is §214's rule.

## What this does not build

* **Function-mapped inputs** (a-p.107–110) — needs Functions, which `ontology.md` §1.3 marks ○. This is also what a-p.110's "call the webhook once per payload in a list" depends on, so that goes with it.
* **Multi-call chained webhooks** (d-p.234–236) — a webhook whose task body is an *array* of calls, with each call reading the previous one's response. Its own unit; the single-call shape has to be right first. d-p.237's rule that "only one call is allowed to use an unsafe HTTP method" is a constraint on *that* feature and is noted here so it is not reinvented.
* **OAuth 2.0 outbound applications** (d-p.243–247) — the authorization-code grant with a token-parsing first call. `RestConfig` has `oauth2_client_credentials` and that is what a webhook gets.
* **The connector catalogue's webhook task types** — Salesforce's four (d-p.237), SAP's (d-p.240). `data-connection.md` §3 already argues against catalogue parity; the REST source is Foundry's own recommended path for Salesforce now anyway (d-p.237).

## The acceptance tests this owes

`data-connection.md` §6 already asks for one and leaves the semantics open — *"a failing webhook does not roll back the action that fired it, and the failure is visible. (Decide which way round this should be, then test it — silence is the bad outcome either way.)"* This decision answers it: **both ways round, chosen per rule**, so the tests are paired.

* A **writeback** that fails leaves the object unchanged, refuses the action, and the refusal reaches the caller naming the webhook.
* A **side effect** that fails leaves the object **changed**, returns success, and the failure is recorded on the run rather than lost.
* The pair is the point: each test passes against an implementation that got the other mode's semantics, so neither is worth writing alone.
* A second writeback on one action is refused at save time (a-p.106), not at run time.
* A webhook cannot reach the link-local range, and the refusal names the guard.
* A stored response is not readable by somebody who did not run the action.
* With `store_responses` off, the run records status and timing and no body.
