# 0026 — No Redis until something uses it

**Status:** decided and built (§845).
**Spec:** §7 lists "ElastiCache Redis — Celery queues + API caching" among a customer stack's data stores.

---

## What was deployed

Every customer stack provisioned an encrypted `cache.t4g.small` ElastiCache replication group, with:
* a subnet group and a security group;
* ingress from the API and the worker;
* a `REDIS_URL` in every service's environment.

## What used it

Nothing.
* No code in `apps/api`, `apps/worker` or `apps/web` reads `REDIS_URL`.
* No requirements file names a Redis client or Celery.

The worker's scheduling and queueing went to Dagster, and the queues it runs on are Postgres rows (`model_runs`, `code_test_runs`, ...). The API's caches are in-process (the 30-second identity cache) or in Postgres (dataset profiles, listener rate counts).

So each stack paid for a node by the hour, and kept one more network path open, for a service no request ever reached. The same comparison found §844's worker bucket bug: every variable the apps read checked against what the stack sets, and the reverse.

## The decision

Remove it: the replication group, its subnet and security groups, the two ingress rules, the `redisEndpoint` prop and `REDIS_URL`.

On an existing stack the next deployment deletes the cache. It holds nothing, because nothing ever wrote to it.

**When something needs a shared cache or a queue that Postgres cannot serve**, add Redis back in the same change that uses it. The block removed from `constructs/data-stores.ts` is in this commit's history.
