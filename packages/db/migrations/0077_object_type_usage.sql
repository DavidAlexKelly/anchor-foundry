-- Usage metrics per object type (§320; `ontology.md` §6; `ontology-manager`
-- p.32-34).
--
--     "Reads: A read is recorded when an application loads objects for a
--      specified object type… Note that one read represents one load request
--      from Object Storage v1 (Phonograph) or the Object Set Service (OSS).
--      Many objects loaded or aggregated at once will only be recorded as a
--      single read. Also note that any object type or link type usage
--      happening in Ontology Manager is not included." (p.32)
--
--     "Writes: A write is recorded when an application makes edits to objects
--      of this type as the result of an Action, Function, Foundry Form, direct
--      Object Explorer edit, or API call. Note that one write represents one
--      edit request… Many objects edited in bulk at once will only be recorded
--      as a single write." (p.32)
--
--     "Interactions: The total number of reads and writes on objects of this
--      type over the last 30 days." (p.32)
--
--     "Active users: The number of unique user IDs that triggered the reads
--      and writes recorded over the last 30 days." (p.32)
--
--     "Users can see, over the last 30 days, who has used each object type,
--      when, and in which Foundry applications." (p.33)
--
-- **A counter, not a log**, and p.32's own rule is the reason. "Many objects
-- loaded at once will only be recorded as a single read" means the unit being
-- counted is the *request*, so a row per request would be a log of exactly the
-- thing p.32 says not to count per object — and a workspace whose Explorer is
-- open all day would write a row every keystroke.
--
-- The grain is therefore (type, person, day, application), which is the
-- narrowest grain every one of p.32-33's four numbers can be computed from:
--
--   * reads and writes over 30 days: sum the columns;
--   * interactions: sum both (p.32 defines it as exactly that, so it is not
--     stored — a stored total is a third number that can disagree with the two
--     it came from);
--   * active users: count distinct `user_id`, which needs the person on the
--     row and is the only reason this is not (type, day, application);
--   * p.33's "who has used each object type, when, and in which Foundry
--     applications": read the rows.
--
-- **`application` is what the caller says it is**, and that is a deliberate
-- limit. p.32 excludes one application by name — "any object type or link type
-- usage happening in Ontology Manager is not included" — and the same endpoint
-- serves the Ontology Manager's object list and the Object Explorer's, so
-- nothing on the server can tell them apart. A client that lied would skew a
-- metric; it could not read anything it was not already entitled to read, so
-- the honest place for that trust is here rather than in a permission.
--
-- **No total row and no rollup.** Thirty days of a busy workspace is a few
-- thousand rows per type; the sums are cheap and always agree with the parts.
-- A pre-aggregated total is a second copy of a number, which is the defect
-- §191 named and §316 found again in a different shape.

CREATE TABLE object_type_usage (
    object_type_id uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    -- **Nullable, and the null means something**: a read by a service account
    -- or a background job has no person behind it. Kept rather than dropped,
    -- because p.32's reads and writes counted it and only p.32's *active
    -- users* should not. `ON DELETE SET NULL` for the same reason — somebody
    -- leaving does not unmake the reads their work caused.
    user_id        uuid REFERENCES users(id) ON DELETE SET NULL,
    -- The day in UTC. A date rather than a timestamp: p.32 and p.33 ask for
    -- "the last 30 days" and "when", and a day is the coarsest grain that
    -- answers both — finer would be a log, which the header explains is the
    -- thing p.32's counting rule rules out.
    day            date NOT NULL,
    -- Which application did it (p.33). Free text rather than an enum: the set
    -- of applications is a property of this product and changes without a
    -- migration, and an unknown value here costs a mislabelled row rather than
    -- a failed write.
    application    text NOT NULL
                       CHECK (length(application) BETWEEN 1 AND 50),
    reads          integer NOT NULL DEFAULT 0 CHECK (reads >= 0),
    writes         integer NOT NULL DEFAULT 0 CHECK (writes >= 0)
);

-- **Two partial unique indexes rather than a primary key**, and the first
-- draft of this migration learned why the hard way: a `PRIMARY KEY` over these
-- four columns makes `user_id` NOT NULL, which contradicts the whole reason it
-- is nullable one screen up. The test for a service account's read caught it
-- on the first run.
--
-- Two rather than one for a second reason: Postgres treats two NULL `user_id`s
-- as distinct, so a single unique index over all four columns would let a
-- background job open a new row on every request — the log this table exists
-- not to be.
CREATE UNIQUE INDEX idx_object_type_usage_by_user
    ON object_type_usage (object_type_id, user_id, day, application)
    WHERE user_id IS NOT NULL;

CREATE UNIQUE INDEX idx_object_type_usage_anonymous
    ON object_type_usage (object_type_id, day, application)
    WHERE user_id IS NULL;

-- The read this table exists for: one type's last 30 days.
CREATE INDEX idx_object_type_usage_recent
    ON object_type_usage (object_type_id, day DESC);

-- One hop to object_types, through the SECURITY DEFINER helper rather than a
-- subselect that could recurse — the shape db 0006 gives every child of an
-- object type.
ALTER TABLE object_type_usage ENABLE ROW LEVEL SECURITY;
CREATE POLICY otu_isolation ON object_type_usage
    USING (EXISTS (SELECT 1 FROM object_types ot
                   WHERE ot.id = object_type_id
                     AND rls_can_access_workspace(ot.workspace_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON object_type_usage TO platform_app;
