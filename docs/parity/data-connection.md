# Data Connection — parity specification

**Source:** `docs/pal/foundry_data-connection.pdf`, 417 pages — the largest doc in the set.

**Today:** `apps/api/src/services/connectors.py` with Postgres, MySQL/MariaDB, S3 and REST connectors behind a `SourceConnector` interface (§2–§7); sync runs with schema drift detection (§5) and sync health (§6).

**Read this one differently.** 417 pages is misleading: most of it is per-connector setup guides and agent configuration reference, and much of the rest describes infrastructure we deliberately do not have (customer-hosted agents, Rubix egress policies, streaming). **Parity here means parity with the model, not with the connector catalogue.** A connector we do not have is a day's work against an interface that exists; a concept we have not modelled is a migration.

This is stage 6 — lowest felt urgency, because it is plumbing users rarely see.

---

## 1. The core model (p.10–12)

| Concept | Foundry | Ours |
|---|---|---|
| **Source** | "a single connection to an external system, including any configuration necessary to specify and locate the target system (typically a URL) and the credentials required to successfully authenticate" | ✅ connections |
| **Connector** (source type) | the kind of system; determines available capabilities | ✅ |
| **Credential** | "a secret value required to access a particular system… all credentials are encrypted and stored securely" | ✅ `secrets.py` |
| Credential-free auth — OpenID Connect, outbound applications, cloud identity | | ◑ IAM role for S3 only |
| **Worker** | where compute for capabilities runs | ○ — implicit; ours always runs in our worker |
| **Networking / egress policies** | how target systems are reached | ✅ §263 the rule, the store and all four outbound paths; §264 the panel. ○ for agent proxy policies and host overrides (decision 0013 §1), and for **protocol** as part of a destination (p.37, decision 0013 §5) |

Foundry separates **worker** (where compute runs) from **networking** (how the target is reached), and says so explicitly because customers get it confused. We have neither concept — everything runs in our worker and reaches out directly.

**Recommendation: do not model workers.** Agent workers are legacy in Foundry's own words ("Agent worker is in the legacy phase of development. We recommend migrating existing agent worker sources to Foundry worker", p.12), and customer-hosted agents are a support burden we should not take on. **Do model egress policies** — an explicit allowlist of destinations per source is a security control we will be asked for.

---

## 2. Capabilities

| Capability | Foundry | Ours |
|---|---|---|
| **Syncs** — pull data in | ✅ TOC §18–23 | ✅ |
| File-based syncs | TOC §20 | ✅ S3 |
| Streaming syncs | TOC §19 | ○ — out of scope |
| Media set syncs | TOC §21 | ○ — tracks the media reference property type in `ontology.md` |
| **Exports** — push data out | TOC §24–25 | ◑ §265, §267 (decision 0014) — **file exports** (S3) and **table exports** (Postgres, MySQL), p.192's nothing-to-export success, p.197's refusals, p.202's per-source switch, and p.206's history. ○ for **streaming exports** (no streams to reverse), **export tasks** (p.211 recommends against them and p.206 says table exports replace them), **scheduling** (p.205 — the runner exists, the trigger does not), **exportable markings** (p.202 — no marking system to draw a list from), and **four of p.195–196's six table modes**, which are defined over a transaction log `dataset_versions` does not keep |
| **Webhooks** — outbound calls to a source | TOC §26–29 | ◑ §259, §260, §261, §262 — built (decision 0012): a request shape on a REST source, p.228's inputs and p.229's outputs, p.222's test call, p.242's per-caller history, the action rule in `action-types` p.106's two modes, p.220's Webhooks section on the source itself (§261), and the rule's own editor (§262). What is absent is named on `ontology.md` §5.2's row: function-mapped inputs, chained multi-call webhooks, the OAuth authorization-code grant, and the privileged history read |
| **Listeners** — inbound events | TOC §30–39 | ○ |
| Source exploration — browse a source before syncing | TOC §17 | ◑ |

**Webhooks are the one to prioritise**, because they are load-bearing twice: an outbound call from a source here, and an action side effect in the ontology. One implementation serves both.

---

## 3. Connector catalogue

Ours: Postgres, MySQL/MariaDB, S3, REST/HTTP.

Foundry ships dozens. Parity with the catalogue is neither achievable nor desirable — "Foundry without the bloat" argues directly against it. What matters is that the **interface** is right, which §2 of the phase-1 roadmap established by proving it with a second database connector.

The honest position: **add connectors on demand, not speculatively.** Each is roughly a day against the existing interface. The gaps most likely to be asked for first, in order: SQL Server, Snowflake, BigQuery, SFTP, Google Cloud Storage, Azure Blob.

Foundry's own fallback is worth copying: "For systems without a dedicated connector, the generic connector or REST API source may be used with code-based connectivity options" (p.10). Our REST connector already is that fallback. Make sure it is documented as such.

---

## 4. Operational

| Feature | Status | Notes |
|---|---|---|
| Sync history and status | ✅ | §6 |
| **Schema drift detection** | ✅ | §5 — recorded on `sync_runs` |
| Sync health, success rate, next run | ✅ | §6 |
| Connection security documentation | ◑ | p.5 |
| Permissions reference | ◑ | p.9 |
| Troubleshooting reference | ○ | p.6, and per-capability troubleshooting pages |
| Optimise JDBC syncs | ○ | TOC §22 |

---

## 5. Build order

1. ~~**Egress policies** — an explicit per-source destination allowlist. A security control, and the only piece of Foundry's networking model worth taking.~~ **Done (`STATUS.md` §263, §264)**: the rule and its enforcement, then the panel that lets somebody write one and put it beside what the source actually dials — p.37's step 1, which is a comparison between two lists of which only one existed. Struck in halves per §216. Decision 0013 records the design and, more usefully, the **source gap**: p.12 and p.103 describe Rubix networking policies from the outside and never specify their shape, so most of what a policy *is* here is inferred and marked as inferred. The exception is **p.37**, found after the build and worth the correction — "egress policies … allowlist the specific hosts, ports, and protocols a source is permitted to connect to" — which settles the port the decision had flagged as a guess, and names a third dimension this build deliberately does not have (decision 0013 §5: a protocol column would only ever be checked against a constant the connector already fixed). Two things the row above cannot say: **an empty list means unrestricted**, because every source that exists is already in that state and closed-by-default would break all of them at once; and **an AWS S3 source is not scopeable** — boto3 derives the host from the bucket and region at request time and p.184 lists the destinations an S3 sync reaches that nobody expected, so an allowlist there would read as covering something it does not. A custom `endpoint_url` *is* checked. `test_an_aws_bucket_is_not_scoped_by_a_policy_and_this_is_deliberate` holds that line so the limitation cannot quietly become a claim.
2. ~~**Webhooks**, shared with action side effects.~~ — **done (`STATUS.md` §259, §260)**: the resource, then the action rule in both of p.106's modes. Struck in halves per §216: a line goes stale in the commit that finishes part of it. Decision 0012 records the design, including the two constraints that no test here can see — no external call inside the transaction, and none on the event loop.
3. ~~**Exports** — the reverse direction; currently data only flows in.~~ **Done (`STATUS.md` §265, §267)**: the server half, then the screen p.203 puts on the source itself. A schedule (p.205) is still absent and is the one piece of this row left. Struck in halves per §216. Decision 0014 records the design, and the part worth reading is **§2**: p.195–196 gives six table export modes and four of them are defined over `SNAPSHOT`/`APPEND`/`UPDATE`/`DELETE` transactions. `dataset_versions` is a "snapshot per sync/upload" — every version is a complete view and there is no transaction type on it — so those four could not do what their own names say. Two are built: `mirror` (p.195's *Full dataset with truncation*) and `full` (*Full dataset without truncation*, whose duplicates p.195 calls a feature). **The gap is in the dataset model, not in exports**, and closing it would change every writer in the platform. Also absent by decision: a REST source is not an export destination, because p.17 already lists webhooks as the way to write to one and §259–§262 built that — refused with a sentence pointing there rather than left out of a dropdown.
4. **Source exploration** — browse tables and files before configuring a sync.
5. **Connectors on demand.**
6. Listeners, if an inbound-event use case ever appears.

Deliberately never: agent workers, streaming, Rubix-specific networking, the full connector catalogue.

---

## 6. Acceptance tests

- **Egress policy** — ~~a source configured for `host-a` cannot reach `host-b`, and the refusal names the policy. Mutation: remove the policy check, and the test goes red.~~ **Done (§263)**, and written literally: `test_a_policy_for_another_host_refuses_the_call` quotes this line. Every refusal here is **paired with an allowed call**, because a refusal alone passes against an implementation that refuses everything — which is what closed-by-default would have been. The mutation the line asks for is one of 29 in §263's harness and all 29 are caught; the two that matter most are "no policies refuses everything" and "the worker's copy has drifted".
- **Credential handling** — a credential is never returned by any read endpoint, at any role. This wants an explicit test rather than an assumption.
- **Schema drift** — a column removed upstream is recorded on the sync run and does not silently produce nulls.
- **Webhook** — ~~decide which way round this should be~~: **both ways round, chosen per rule** (`action-types` p.105-107, decision 0012). A *writeback* fails the action and shows why; a *side effect* leaves the object changed and records the failure without surfacing it. The tests are paired, because each passes against an implementation that got the other mode's semantics.
- **Export** — ~~an export writes what a sync of the same dataset would read back.~~ **Done (§265)**, and the shape it took is stronger than the line asked for: **both modes are run twice**, because `mirror` and `full` are indistinguishable on a first run into an empty table and p.195's difference only shows on the second. p.192's nothing-to-export success is paired with a changed dataset that *is* exported, and `full`'s refusal to skip has its own test — a single skip-test would have erased the distinction decision 0014 §3 exists to make.
