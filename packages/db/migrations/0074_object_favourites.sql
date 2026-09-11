-- Favouriting an individual object (§312; `ontology.md` §3; `getting-started` p.34).
--
--     "Object Explorer is an application you can use to explore objects and
--      links in the platform. When you navigate to an individual object view,
--      you can select the star next to its title to save it as a favorite.
--      This will add the object to your sidebar." (p.34)
--
--     "Think of favorites as shortcuts that you can add and remove to keep
--      frequently used resources close at hand." (p.34)
--
-- **A shortcut, which is why §309 had to come first.** A favourite is only
-- worth storing if it can be reopened, and until an object had a URL there was
-- nowhere for one to point. That is the whole reason this table holds a *type*
-- as well as an instance: the instance store is partitioned by object type, so
-- there is no read that takes an instance id alone.
--
-- **Per user, and that is the feature rather than a caution.** p.34 calls
-- these shortcuts kept "close at hand" and puts them in *your* sidebar. A
-- shared favourites list would be a different feature — a curated set somebody
-- maintains for a team — and pretending one is the other means everybody's
-- shortcuts arrive in everybody else's sidebar.
--
-- **No foreign key to the object**, because there is nothing to point at: an
-- instance lives in the instance store (Postgres or OpenSearch, db 0035) and
-- not in a table this schema can reference. So a favourite can outlive what it
-- names, which is a real state rather than a defect — p.34's shortcut to a
-- thing that has since been deleted is exactly the case §309's dead-link
-- message was written for, and the list says so rather than hiding the row.

CREATE TABLE object_favourites (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- The type *is* referenced, because it is a real row: deleting an object
    -- type takes its favourites with it, which is right — the shortcut cannot
    -- be resolved once the type it names is gone, and leaving it would leave a
    -- row nothing can ever render.
    object_type_id  uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    instance_id     uuid NOT NULL,
    -- What the object was called when it was starred. **Stored, deliberately.**
    -- The title comes from the type's title property, and resolving it means
    -- reading every favourited object on every render of the sidebar — a list
    -- of ten shortcuts would be ten reads against the instance store before
    -- anything appears. A name that has since changed is a smaller wrong than
    -- a sidebar that takes a second to draw, and opening the favourite shows
    -- the current object either way.
    label           text NOT NULL DEFAULT '' CHECK (length(label) <= 500),
    created_at      timestamptz NOT NULL DEFAULT now(),
    -- Starring twice is the same star. The uniqueness is what makes the button
    -- a toggle rather than an accumulator.
    UNIQUE (user_id, object_type_id, instance_id)
);

CREATE INDEX object_favourites_mine
    ON object_favourites (user_id, workspace_id, created_at DESC);

ALTER TABLE object_favourites ENABLE ROW LEVEL SECURITY;

-- **Two conditions, and the first is the point.** Workspace access alone would
-- let a colleague read everybody's shortcuts, which is the thing the per-user
-- design exists to prevent — and a rule that lives only in a service is one
-- the next writer of a SELECT does not meet.
CREATE POLICY object_favourites_isolation ON object_favourites
    USING (user_id = rls_current_user_id()
           AND rls_can_access_workspace(workspace_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON object_favourites TO platform_app;

COMMENT ON TABLE object_favourites IS
    'p.34''s favourite objects (db 0074). A per-user shortcut to one object, '
    'carrying the type because the instance store is partitioned by it, and a '
    'stored label so a sidebar of ten does not cost ten instance reads.';
