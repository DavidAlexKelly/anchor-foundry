-- §804: the object list's order, served from an index.
--
-- Roadmap phase 3, E.4 measured the first page of a million-object type at a
-- p50 of 0.7 s and a p95 of 2.9 s. Every list orders by `updated_at DESC,
-- primary_key` (`instances.list_for_type`), and the index was on
-- `(object_type_id, updated_at DESC)` alone - so for the commonest table of
-- all, one written by a single sync where every object shares one
-- `updated_at`, the tie-break was a sort of every row: 400 ms of planning
-- nothing and scanning a million entries to return fifty. With the key in
-- the index the first page is read off its front (0.09 ms), and a page five
-- thousand in is 1.7 ms.
--
-- It replaces the old index rather than joining it: the old one is this
-- one's prefix, so anything it served this serves, and keeping both would
-- be a second index for every sync to maintain.
--
-- Not CONCURRENTLY: a migration runs in a transaction, which that cannot.
-- The build holds writes to `object_instances` for its duration - about a
-- second per million rows here - once, at deploy.

CREATE INDEX IF NOT EXISTS idx_object_instances_type_order
    ON object_instances (object_type_id, updated_at DESC, primary_key);

DROP INDEX IF EXISTS idx_object_instances_type;
