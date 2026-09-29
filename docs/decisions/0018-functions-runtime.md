# 0018 — A runtime for Functions

**Status:** proposed, for the owner to decide
**Roadmap:** `docs/parity/README.md`'s "one hard dependency we did not choose",
and every row tagged `[fn]`
**Builds on:** `0004-running-customer-code.md`

---

## The question

Workshop and Actions reach into Foundry's Functions in four places, each tagged
`[fn]` in the parity docs:

- function-backed columns in the Object Table (`workshop` p.221);
- function-backed layers in Chart XY (`workshop` p.278);
- Functions on Objects as a variable source (`workshop`, the FoO section);
- function-backed actions (`action-types` §15-17).

The parity README says a decision is required: leave these unbuilt, or bring a
minimal runtime into scope. Everything else on the parity roadmap is now built
or declined for a recorded reason. So this is the largest item left, and it is
the one the roadmap cannot pick up without an owner's call.

## What Foundry asks of a function

> "Functions enable code authors to write logic that can be executed quickly
> in operational contexts, such as dashboards and applications… This logic is
> executed on the server side in an isolated environment." (`functions` p.2)

Two properties together: **isolated**, and **quick**. A function-backed column
is called when a table page loads, so it has hundreds of milliseconds, not
minutes.

## Why this platform cannot simply run one

- **In the API, no.** Decision 0004 established that customer code must run
  where it cannot obtain the platform's credentials. The API's task role and
  database secret are reachable from any process on its host over link-local
  networking, and stripping the environment does not change that. A
  subprocess of the API is the escalation path 0004 describes.
- **In the transform runner, not quickly.** The runner that 0004 built (empty
  task role, closed egress, inputs and outputs as files on EFS) starts one
  Fargate task per run. `transform_dispatch.py` allows 900 seconds, because
  pulling the image and attaching an ENI often takes a minute before a line of
  code runs. That suits a build and does not suit a table column.

## Options

**A. Decline.** Mark the four `[fn]` features ⊘, as Scenarios and AIP are. No
new infrastructure and no new risk. The cost is four documented Workshop and
Actions capabilities.

**B. SQL functions, run inline.** A function is a named, versioned SQL query
over the ontology, with typed parameters. It runs in DuckDB with
`enable_external_access` off, which 0004 already accepts as a real boundary
for what SQL can express. It is quick, needs no new infrastructure, and could
ship as a series of ordinary units. The cost is a divergence: Foundry's
functions are TypeScript and Python, and a SQL function cannot express
everything they can. Ontology edits from a function-backed action would be the
awkward case.

**C. A warm isolated runner.** The same guarantees as 0004's runner, but
long-lived:

- an ECS service with an empty task role;
- egress closed;
- one inbound port, reachable only from the API's security group;
- a fresh interpreter process per call inside it, with the inputs sent in the
  request and the result returned in the response.

This gives Foundry's languages at Foundry's speed. The cost is new
infrastructure (a CDK construct, VPC wiring, a health check and scaling) and a
new network path into a component whose job is to run untrusted code. That
path would need its own threat review. It is the largest of the three.

## Recommendation

**B first, with C left open.** B delivers the four capabilities on a boundary
this platform already trusts, and the `[fn]` tags keep the divergence easy to
find. A function's registry, its versions, and the widget and action plumbing
that call it are the same under B and C. So if the owner later wants
TypeScript or Python, C replaces the executor rather than the feature.

This is a recommendation, not a decision. Until the owner chooses, the `[fn]`
rows stay ○.
