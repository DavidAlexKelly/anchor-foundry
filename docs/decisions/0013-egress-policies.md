# 0013 — Egress policies: an allowlist that has to be turned on

**Status:** decided, **not yet built**.
**Parity items:** `docs/parity/data-connection.md` §1 (networking) and build order item 1 — *"an explicit per-source destination allowlist. A security control, and the only piece of Foundry's networking model worth taking."*
**Source:** `docs/pal/foundry_data-connection.pdf` (417 pp), cited `(p.N)`.
**Follows:** decision 0012, which is built. Webhooks made outbound calls a first-class feature — an editor can now make the platform issue a POST with a body to any host that resolves — and this is the control that scopes them.

---

## The source gap, named first

**There is no egress policy reference page in the set.** The 417-page Data Connection PDF describes the *concept* in four places and configures it in Control Panel, whose documentation this repo does not have. So this decision is designed from fragments and marks what was inferred, the way §251 did for interfaces.

What the document actually says:

> "For Foundry worker sources, networking is configured via egress policies. They define at a granular level how each target system can be reached from Foundry, and which egress destinations are permitted." (p.12)

> "Network egress from Foundry is managed and administered in-platform via direct connection egress policies." (p.22)

> "Add egress policies. Configure direct connection or agent proxy egress policies to define how the Foundry worker should reach your source systems." (p.49, step 6 of source setup)

> "Use this ad-hoc domain instead of `10.0.0.1` in your source **and egress policy** configuration." (p.103)

Four facts fall out and they are the whole model: a policy belongs to a **source**; a source may have **several** ("both direct connection and agent proxy policies can be assigned to the same source", p.12); a policy names a **destination**, by domain rather than by address (p.103's whole point is that you give the policy a name, not an IP); and the set is an **allowlist** — "which egress destinations are permitted".

**Inferred, and flagged as such:** that a policy carries a port. The document never says so. It is included because a destination allowlist that cannot say "port 443 only" is a weaker control than the one somebody asking for this feature means, and because every other allowlist in this class has one. If that turns out to be wrong it is a column nobody has to use.

## The decision

**A per-source allowlist of destinations, empty by default and enforced at every outbound call.**

### 1. Only direct connection policies

p.12 names two types. **Agent proxy policies are ⊘**, for the reason `data-connection.md` §1 already gives and this decision does not re-litigate: they need a customer-hosted agent, agent workers are legacy in Foundry's own words (p.12), and that file's build order says "deliberately never: agent workers". A policy type that requires infrastructure this platform will not have is a form that cannot work (§214).

So there is one policy type and it does not need a discriminator column. When a second arrives it will need a migration; that is cheaper than a column that has held one value for its whole life.

### 2. Empty means unrestricted, and the screen says so

This is the decision, and the alternative is defensible enough to be worth arguing against.

**Closed-by-default is what an allowlist normally means**, and Foundry's model is closed: p.49 makes adding policies step 6 of *setting up a source*, so a Foundry source never exists without them. Copying that literally would mean every connection already in every deployment stops working the moment this ships — every sync, every webhook, every action that fires one — because none of them has a policy and none of their authors was ever asked for one.

There is no migration that fixes this. "Grant each existing source a policy for its own host" sounds right and is wrong twice: a REST source's `base_url` is one destination and its OAuth `token_url` may be another (p.12's own example is a source needing both), and an S3 source's real destinations include STS, which p.184 names as a thing people forget and then debug for an afternoon. A migration that guesses would produce policies that are *almost* right, which is worse than none: it looks configured.

So: **a source with no policies is unrestricted, and a source with any policy is restricted to them.** The control is opt-in, and what makes that honest rather than a cop-out is that the absence is *stated* — the source screen says "this source may reach any address" where the policy list would be, rather than showing an empty list that reads as "nothing is allowed". §214's rule applied to a control's absence rather than to its presence.

**What this deliberately gives up** is the guarantee that every source is scoped. What it buys is that the feature can be adopted per source, by the person who knows that source's destinations, instead of arriving as a platform-wide outage. If a deployment wants the strong version, the missing piece is an organisation-level "require a policy on every source" switch — named here so nobody thinks it was overlooked, and not built because a setting nobody can satisfy yet is §214 again.

### 3. Enforced where the call is made, not where it is configured

Every outbound destination in this platform passes through one of four places:

| Path | Checked at send time today? |
|---|---|
| REST sync | **yes** — `RestConnector._fetch_page` calls `_check_url` |
| Webhook | **yes** — `webhook_calls._send` calls `_check_url` |
| OAuth token fetch | **no** — `RestConnector._oauth_token` opens `token_url` directly; only `validate_config` checks it, at configure time |
| Database and object storage | **no** — a host and port, never a URL, so `_check_url` was never on that path |

Two of the four are unchecked at send time, and both were found by writing this table rather than by a test. The third row is the sharper one: `token_url` *is* checked when the connection is saved, so it looks covered — and §259 already recorded why that is not the same thing, since `_check_url` resolves the hostname when it runs and a name's answer can change afterwards. The same rebinding argument that kept the webhook's send-time check applies here and nothing was making it.

The check goes beside `_check_url`, which already refuses the link-local range and is already called on the first two. **That is the argument for putting it there rather than in a route**: a guard at the point of configuration is a guard a second configuration path can miss, and §259 already recorded why `_check_url` runs at send time rather than only at save time — a hostname's answer can change between the two.

The last row is the one that shapes the interface: a Postgres connection's `host` is not a URL, so `_check_url` was never on that path and never could be. **The policy check therefore takes a host and a port**, and `_check_url` becomes one caller of it rather than its home — which is also what lets the token fetch be fixed by adding a call rather than by restructuring it.

### 4. A refusal names the policy, not the address

`data-connection.md`'s acceptance test asks for this in its own words — *"a source configured for `host-a` cannot reach `host-b`, and the refusal names the policy"* — and it is worth keeping because the failure it prevents is specific. "Could not reach `internal.example.com`" sends somebody to check DNS, a firewall and the far end's health before they think to look at a list in the platform. "This source is not allowed to reach `internal.example.com`; its egress policies allow `api.example.com:443`" ends the investigation in one line.

## What this does not build

* **Agent proxy policies** (p.12) — §1 above.
* **Host overrides** (p.102-103), which map a name to an address on an agent host. They exist to give a private IP a name *so that a policy can name it*, and with no agent there is nothing to override on.
* **Ingress** (p.253-255) — listener subdomains and IP allowlists are the other direction, and listeners are `data-connection.md`'s item 6.
* **An enrollment-wide requirement** that every source carry a policy — §2 above.
* **CIDR ranges as destinations.** p.103 pushes people towards names precisely because addresses move; a range is what an infrastructure team writes when it does not know the names, and offering it would invite the allowlist to be widened until it means nothing. A single address is allowed, because "this one host" is a legitimate thing to say.

## The acceptance tests this owes

* A source with one policy reaches the host it names and is refused the one it does not, **and the refusal names the policy**.
* A source with **no** policies reaches anything the platform itself allows — the presence half, without which the test above passes against an implementation that refuses everything.
* The link-local refusal still fires for a source whose policies would otherwise permit it. Two controls, and the platform's own is not overridable by a source's.
* A policy on a port refuses the same host on another port.
* A webhook, a REST sync and an OAuth token fetch are all checked — three call sites, and a test per site, because the guard being in `_check_url` is not the same claim as every path reaching it.
* A **database** source's host is checked, which is the row that does not go through `_check_url`.
