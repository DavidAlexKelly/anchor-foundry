-- p.32's usage metrics for **link types** (§620; `ontology-manager` p.32-34).
--
-- > "Usage metrics — reads, writes, interactions over 30 days" … "any object
-- > type or link type usage happening in Ontology Manager is not included."
-- > (p.32)
--
-- db 0077 counted object types and said of link types that "the same table
-- would serve, but no read path names one". Traversing a link names one now
-- (an object's links panel, a set reached by a link), so link types get the
-- same counter: db 0077's shape exactly, keyed by the link type, so the two
-- read the same way and one service answers both.
CREATE TABLE link_type_usage (
    link_type_id uuid NOT NULL REFERENCES link_types(id) ON DELETE CASCADE,
    -- Nullable and meaningful, as in db 0077: a background job's read has no
    -- person behind it, and p.32's active users count people.
    user_id      uuid REFERENCES users(id) ON DELETE SET NULL,
    day          date NOT NULL,
    application  text NOT NULL CHECK (length(application) BETWEEN 1 AND 50),
    reads        integer NOT NULL DEFAULT 0 CHECK (reads >= 0),
    writes       integer NOT NULL DEFAULT 0 CHECK (writes >= 0)
);

-- db 0077's two partial unique indexes, for db 0077's two reasons.
CREATE UNIQUE INDEX idx_link_type_usage_by_user
    ON link_type_usage (link_type_id, user_id, day, application)
    WHERE user_id IS NOT NULL;

CREATE UNIQUE INDEX idx_link_type_usage_anonymous
    ON link_type_usage (link_type_id, day, application)
    WHERE user_id IS NULL;

CREATE INDEX idx_link_type_usage_recent
    ON link_type_usage (link_type_id, day DESC);

ALTER TABLE link_type_usage ENABLE ROW LEVEL SECURITY;
CREATE POLICY ltu_isolation ON link_type_usage
    USING (EXISTS (SELECT 1 FROM link_types lt
                   WHERE lt.id = link_type_id
                     AND rls_can_access_workspace(lt.workspace_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON link_type_usage TO platform_app;

COMMENT ON TABLE link_type_usage IS
    'p.32''s usage counter for link types (db 0129): db 0077''s shape, one row '
    'per link type, person, day and application.';
