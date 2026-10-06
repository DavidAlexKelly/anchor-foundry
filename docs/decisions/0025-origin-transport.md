# 0025 — How CloudFront reaches the services, and who else can

**Status:** proposed, not built (§842). It changes a deployed stack's network edge, and this repository has no AWS account to deploy it to. The construct checks can show the template says what is intended, but not that a customer stack still answers afterwards. Building it should happen where a stack can be deployed and visited before and after.
**Roadmap:** `docs/roadmap-phase-3-fidelity.md` E.11.
**Found by:** an audit of `infra/cdk` (§842), reading `constructs/services.ts` and `stacks/customer-stack.ts` against the comments that describe them.

---

## What a deployed stack does today

* A viewer reaches **CloudFront over HTTPS**: `viewerProtocolPolicy: REDIRECT_TO_HTTPS`, on CloudFront's own `*.cloudfront.net` certificate.
* CloudFront reaches the **load balancer over plain HTTP** (`OriginProtocolPolicy.HTTP_ONLY`). Every request crosses that hop unencrypted: the session cookie, the bearer token, an uploaded file, a query's results.
* The load balancer is **internet-facing**, with an HTTP listener on port 80 **open to 0.0.0.0/0** (`addListener("Http", { port: 80, open: true })`). Anyone who learns its DNS name can skip CloudFront and talk to the services directly, in plain HTTP. The regional WAF is on the load balancer, so it still applies; CloudFront's TLS does not.

The comments say this was meant to be temporary. `services.ts` says *"the control plane attaches the ACM certificate + HTTPS listener once the customer subdomain is issued (Route 53 + ACM, spec §7). HTTP-to-HTTPS redirect is added at that point."* `customer-stack.ts` says *"ALB TLS added post-cert issuance."* **Nothing does that.** `apps/control-plane` issues no certificate, creates no listener and changes no origin policy. Every stack ever deployed has the arrangement above.

## Options

### A. Keep the load balancer public; let only CloudFront reach it

Restrict the listener's security group to the AWS-managed prefix list `com.amazonaws.global.cloudfront.origin-facing`. Have CloudFront add a per-stack secret header that a listener rule requires, answering 403 otherwise. The prefix list admits *every* CloudFront distribution, anyone's, and the header is what tells this one apart.

* Ends direct access. **Does not encrypt the CloudFront-to-origin hop.**
* The prefix list's id is per region, found with `ec2.PrefixList.fromLookup`, a synth-time context lookup the provisioner can make with its credentials.
* The header value has to reach both CloudFront and the listener rule without being written into the template in clear.

### B. Make the load balancer internal; reach it through a CloudFront VPC origin (recommended)

CloudFront's VPC origins (`origins.VpcOrigin.withApplicationLoadBalancer`, present in the aws-cdk-lib 2.272 that §838 moved to) connect to a load balancer in **private** subnets. The load balancer stops being internet-facing, so there is nothing to bypass. The hop to it stays inside AWS's network, which is where the origin-transport concern mostly lives.

* `internetFacing: false`, in private subnets. The listener admits only the VPC origin's security group, not `0.0.0.0/0`.
* The WAF stays on the load balancer, or moves to CloudFront (a `CLOUDFRONT`-scoped web ACL, created in us-east-1). Either holds.
* **It replaces the load balancer** on an existing stack: `internetFacing` cannot change in place. CloudFront's origin moves with it in the same deployment, and the old one is deleted after. A rolling deployment should see no gap, but that is exactly the claim that needs a deployed stack to confirm.
* HTTPS on the internal hop (an ACM certificate on the load balancer) is optional on top. It needs a domain, which is the step the comments assumed and nothing built.

### C. Do what the comments say: a customer subdomain, ACM, and an HTTPS listener

Spec §7's plan. It needs Route 53 and certificate issuance in the control plane, a domain per customer, and an origin policy change after issuance. It is the most work, it is the only option that also gives customers their own hostname, and it still leaves the load balancer public unless combined with A or B.

## Recommendation

**B, then C when customer hostnames are wanted.** B closes both gaps — the open listener and the unencrypted public hop — without needing a domain, and it is a change of a few lines in `services.ts` and `customer-stack.ts`. It should be built where a stack can be deployed, measured (a request through CloudFront succeeds; the load balancer's DNS name no longer resolves publicly), and rolled back if the replacement misbehaves. Until then, this record and E.11 say plainly that the gap exists.
