-- ============================================================================
-- 0027_link_traversal.sql - make link types traversable between instances
-- (roadmap Objects item 3).
--
-- The gap
-- -------
-- link_types (0003) records that Person relates to Department, with a
-- cardinality. That is a *type-level* statement: it says the relationship
-- exists in the ontology, and nothing at all about which Person relates to
-- which Department. There has never been an instance-level edge anywhere in
-- this schema - no link_instances, no object_links - so "browse a link from
-- an instance" had no data to browse.
--
-- Why derived links, not materialised edge rows
-- --------------------------------------------
-- The obvious shape is a link_instances table: (link_type_id, from_id,
-- to_id), written by something. Rejected, because of where object instances
-- come from. An instance is not authored here - it is *materialised* from a
-- dataset column mapping (object_type_sources, §14) and re-materialised on
-- every sync, with stale rows deleted. The relationships arrive in the same
-- data: a Person row synced from a relational source already carries the
-- department code that points at a Department row. Storing edges would mean
--
--   * a second sync mechanism, with its own staleness, running beside the
--     one that produces the rows the edges point at, and
--   * a reconciliation problem on every resync: instance rows are upserted
--     by (source_id, primary_key), and edges keyed on instance ids would
--     have to be diffed and pruned in step with them, or they would point at
--     instances that no longer exist.
--
-- Deriving the link instead - "which instances of the far type have
-- to_property equal to this instance's from_property" - cannot go stale,
-- because there is nothing to keep in sync: the answer is a question asked
-- of the current instance data at read time. It is also how the relationship
-- is actually expressed upstream (a foreign key column), so nothing has to
-- be inferred or restated.
--
-- The cost, stated plainly: a traversal is a query per link per instance
-- rather than an index lookup on an edge table, so it is a read-time cost
-- that scales with fan-out. That is the right trade at this size - the
-- alternative pays a write-time cost *and* a correctness risk on every sync -
-- and it is where a materialised edge cache would go later if fan-out
-- became the problem. Nothing about the API shape below assumes derivation,
-- so that change would stay behind the service.
--
-- What this deliberately does not do
-- ----------------------------------
--   * No join-table relationships (A -> join object -> B). Many-to-many
--     through a third type needs a link *through* an object, which is two
--     hops and a different data model; the property pair here expresses a
--     single equality. many_to_many cardinality still works when both sides
--     hold a shared key.
--   * No expressions - the join is property-to-property equality, not
--     "upper(a) = trim(b)". A computed join key belongs in the dataset that
--     feeds the type, where the model layer can already produce it.
--   * No enforcement that the join actually matches anything. A link type
--     whose properties are mapped to columns that never line up simply
--     traverses to zero instances; that is a data problem the UI shows,
--     not a constraint to reject at definition time.
--   * No referential integrity between instances. Deriving means a dangling
--     foreign key traverses to nothing instead of erroring, which matches
--     how the upstream data behaves.
-- ============================================================================

-- The property on each end whose values are compared. Nullable, and
-- both-or-neither: every link type that already exists stays a valid
-- ontology statement (Person relates to Department) and simply is not
-- traversable until someone says which properties join. A NOT NULL default
-- would have meant inventing a join for links nobody described one for, and
-- silently traversing on the wrong column is worse than not traversing.
ALTER TABLE link_types
    ADD COLUMN from_property text,
    ADD COLUMN to_property   text;

-- '$primary_key' is a reserved reference to the instance's primary key
-- rather than one of its mapped properties. It is needed, not a convenience:
-- the far end of a foreign key is nearly always the referenced row's key,
-- and the primary key is a first-class field on an instance
-- (object_instances.primary_key), not an entry in its properties JSON. The
-- '$' prefix cannot collide with a property api_name, which must start with
-- a lowercase letter - so no property can ever be shadowed by the sentinel.
ALTER TABLE link_types
    ADD CONSTRAINT link_types_from_property_shape
        CHECK (from_property IS NULL
               OR from_property ~ '^([a-z][a-z0-9_]{0,99}|\$primary_key)$'),
    ADD CONSTRAINT link_types_to_property_shape
        CHECK (to_property IS NULL
               OR to_property ~ '^([a-z][a-z0-9_]{0,99}|\$primary_key)$'),
    -- Half a join is not a weaker join, it is an unanswerable question.
    ADD CONSTRAINT link_types_property_pair
        CHECK ((from_property IS NULL) = (to_property IS NULL));

COMMENT ON COLUMN link_types.from_property IS
    'Property api_name on the from type whose value is compared, or '
    '''$primary_key'' for the instance primary key. NULL (with to_property) '
    'means the link type is defined but not traversable.';
COMMENT ON COLUMN link_types.to_property IS
    'Property api_name on the to type compared against from_property, or '
    '''$primary_key''.';
