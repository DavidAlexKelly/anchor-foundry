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
| **Networking / egress policies** | how target systems are reached | ○ |

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
| **Exports** — push data out | TOC §24–25 | ○ |
| **Webhooks** — outbound calls to a source | TOC §26–29 | ○ — also an action side effect (`ontology.md` §5.2) |
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

1. **Egress policies** — an explicit per-source destination allowlist. A security control, and the only piece of Foundry's networking model worth taking.
2. **Webhooks**, shared with action side effects.
3. **Exports** — the reverse direction; currently data only flows in.
4. **Source exploration** — browse tables and files before configuring a sync.
5. **Connectors on demand.**
6. Listeners, if an inbound-event use case ever appears.

Deliberately never: agent workers, streaming, Rubix-specific networking, the full connector catalogue.

---

## 6. Acceptance tests

- **Egress policy** — a source configured for `host-a` cannot reach `host-b`, and the refusal names the policy. Mutation: remove the policy check, and the test goes red.
- **Credential handling** — a credential is never returned by any read endpoint, at any role. This wants an explicit test rather than an assumption.
- **Schema drift** — a column removed upstream is recorded on the sync run and does not silently produce nulls.
- **Webhook** — a failing webhook does not roll back the action that fired it, and the failure is visible. (Decide which way round this should be, then test it — silence is the bad outcome either way.)
- **Export** — an export writes what a sync of the same dataset would read back.
