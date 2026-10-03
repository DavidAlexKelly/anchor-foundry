# 0018 — A runtime for Functions

**Status:** decided: **B**, SQL functions run inline (§768). It was taken under the owner's standing instruction to choose the next roadmap step without stopping to confirm. It adds no infrastructure, so it is reversed by removing the `functions` tables and their consumers.
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

## Decision, and what B is here (§768)

B, as recommended. What follows is the shape, so the four consumer units
(§770 onwards) build on one thing.

* **A function** is a workspace resource: `api_name`, display name and
  description, and **versions**. Following `functions` p.49-50, a version is a
  semantic version the author chooses ("Versions for function releases are
  chosen by their publishers and are immutable after creation"). A new one
  must be greater than every earlier one. A consumer names the version it
  calls.
* **A version** carries:
  * typed **parameters**, in the scalar types of p.80's variable mapping plus
    an object reference;
  * the **object types it reads**, each loaded as a table named by its
    `api_name`;
  * an **output kind**;
  * the **SQL**.
  Parameters are bound as `$name`, never interpolated.
* **The outputs are p.80's**: a value (boolean, string, number, date,
  timestamp), an array of one of those, an object set (the rows' first column
  is primary keys), and a table for the test run. Each consumer unit adds the
  shape it needs, such as an Object Table column's key-to-value map.
* **The boundary is the transform preview's.** The SQL runs in an in-memory
  DuckDB connection after the inputs are materialised and
  `enable_external_access` is switched off. It has a memory limit, a
  per-type row cap, and a timeout that interrupts the connection. The inputs
  are read through the instance store under the caller's own access, so a
  function sees what its caller may see (p.77's "differing access to
  individual objects").
* **Divergence, stated:** Foundry's functions are TypeScript and Python and
  can call APIs (p.2). These are SQL over the ontology and call nothing.
  Ontology edits, which function-backed actions need (p.81), are the awkward
  case named above, and that unit decides them. Option C remains the way to
  Foundry's languages: it replaces the executor, not the registry or the
  consumers.
