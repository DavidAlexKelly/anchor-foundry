-- ============================================================================
-- 0100_favourites_over_resources.sql
-- A favourite is a shortcut to a *resource* as well as to an object (§436).
--
--     "You can add and remove favorites with the star icon while navigating
--      the folder structure or from within an open resource in a Palantir
--      platform application." (`getting-started` p.34)
--
-- **p.34's first sentence, which db 0074 did not build.** §312 read the
-- paragraph below it — the object view's star — and built that, correctly and
-- completely. The sentence above it is about resources, and Workshop p.47
-- depends on it: "toggle the ability for users to favorite the module in view
-- mode" is this mechanism pointed at a module.
--
-- **One table, not a second one.** A favourite is a label and a way back, and
-- the only difference between the two kinds is which of those two shapes the
-- way back has. Two tables would mean two services, two caps, two listings and
-- a sidebar that merges them — four places for the same idea to drift apart
-- (§292). The discriminated-column shape is db 0039's, which chose it for the
-- same reason: `code_proposal_comments` anchors to a model *or* to a path.
--
-- **The cap stays shared**, because it is a rule about a sidebar rather than
-- about a kind: a hundred shortcuts is already past "close at hand", and
-- counting the two kinds separately would let somebody keep two hundred.
--
-- **The workspace stays NOT NULL.** Every resource has one (db 0003) and the
-- row policy is built on it — a nullable workspace would be a favourite the
-- isolation rule could not place.
-- ============================================================================

ALTER TABLE object_favourites RENAME TO favourites;

-- The names go with it. An index called `object_favourites_mine` on a table
-- that holds resource rows is a comment that has stopped being true, and index
-- names are read exactly when somebody is trying to understand a slow query.
ALTER INDEX object_favourites_mine RENAME TO favourites_mine;
ALTER TABLE favourites
    RENAME CONSTRAINT object_favourites_user_id_object_type_id_instance_id_key
                   TO favourites_object_once;
ALTER POLICY object_favourites_isolation ON favourites
    RENAME TO favourites_isolation;

ALTER TABLE favourites
    ALTER COLUMN object_type_id DROP NOT NULL,
    ALTER COLUMN instance_id DROP NOT NULL,
    ADD COLUMN resource_id uuid REFERENCES resources(id) ON DELETE CASCADE;

-- **A real foreign key, unlike the object half.** 0074 has none because an
-- instance lives in a store this schema cannot reference; a resource is a row
-- here, so deleting it takes its shortcuts with it. A favourite to a resource
-- that no longer exists is a row nothing can ever render, and §309's
-- dead-link message — which is why the object half keeps its orphans — has
-- nothing to say about a resource id that resolves to nothing.
ALTER TABLE favourites
    ADD CONSTRAINT favourites_one_subject
        CHECK (num_nonnulls(instance_id, resource_id) = 1),
    -- An object favourite carries both halves of its key or neither. Without
    -- this, a row could name a type and no instance and satisfy the rule above
    -- by having a resource — which is two subjects wearing one.
    ADD CONSTRAINT favourites_object_is_whole
        CHECK ((object_type_id IS NULL) = (instance_id IS NULL)),
    ADD CONSTRAINT favourites_resource_once UNIQUE (user_id, resource_id);

COMMENT ON TABLE favourites IS
    'p.34''s favourites (db 0074, widened by db 0100). A per-user shortcut to '
    'one object or one resource, with a stored label so a sidebar of ten does '
    'not cost ten reads. Exactly one subject per row.';

COMMENT ON COLUMN favourites.resource_id IS
    'The resource this is a shortcut to (db 0100). Null on an object '
    'favourite, which names a type and an instance instead.';
