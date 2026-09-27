-- ============================================================================
-- 0105_resource_tags.sql
-- Tags on resources (§511; `dataset-preview` p.3, `app-building` p.35,
-- `getting-started` p.66).
--
--     "About: Information including … tags, and more." (`dataset-preview` p.3)
--
--     "You can create and manage tags from the Tags section of Platform
--      Settings. Once they are created, they can be added to a promoted app
--      on the promotion UI, as well as in the filesystem." (`app-building` p.35)
--
--     "create a tag category named Training application … You can freely name
--      tags within the category" (`getting-started` p.66)
--
-- **Two tables: what the tags are, and what carries them.** Foundry's tags
-- are made in one place and applied in many, so a tag is a row of its own
-- rather than a string typed onto each resource. Typed strings drift ("PII",
-- "pii", "P.I.I.") and cannot be renamed in one go; a row can.
--
-- **A category is a string on the tag, not a table.** The pages above give it
-- no properties of its own beyond grouping, so a table would be a name with an
-- id and nothing else. `''` is "no category", which keeps the uniqueness rule
-- one index rather than a partial pair.
--
-- **Who may do what is the API's, as it is for favourites (db 0100).** The
-- policies here are the isolation boundary: a tag is visible to the members of
-- its workspace, and a link is visible exactly when its resource is, which is
-- the resources policy (db 0032) applied through the subquery. Making tags is
-- an admin's job (p.35's "Platform Settings") and applying one is an editor's on
-- the resource; both are checked by role in the route, where the role is known.
-- ============================================================================

CREATE TABLE resource_tags (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    category      text NOT NULL DEFAULT '' CHECK (length(category) <= 100),
    name          text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
    created_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Case-insensitive, so "PII" and "pii" are one tag rather than two that look
-- like one.
CREATE UNIQUE INDEX uq_resource_tags_name
    ON resource_tags (workspace_id, lower(category), lower(name));

CREATE TABLE resource_tag_links (
    resource_id   uuid NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    tag_id        uuid NOT NULL REFERENCES resource_tags(id) ON DELETE CASCADE,
    added_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    added_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (resource_id, tag_id)
);

-- "Which resources carry this tag" is the filter's query.
CREATE INDEX idx_resource_tag_links_tag ON resource_tag_links (tag_id);

ALTER TABLE resource_tags ENABLE ROW LEVEL SECURITY;
CREATE POLICY resource_tags_isolation ON resource_tags
    USING (rls_can_access_workspace(workspace_id))
    WITH CHECK (rls_can_access_workspace(workspace_id));

-- Through the resource and the tag, both under their own policies: a link is
-- visible when its resource is, and it can only join a tag from a workspace
-- the caller is in. The tag's workspace must be the resource's, or a tag from
-- one workspace could be hung on a resource in another.
ALTER TABLE resource_tag_links ENABLE ROW LEVEL SECURITY;
CREATE POLICY resource_tag_links_isolation ON resource_tag_links
    USING (EXISTS (SELECT 1 FROM resources r WHERE r.id = resource_id))
    WITH CHECK (EXISTS (
        SELECT 1 FROM resources r JOIN resource_tags t ON t.workspace_id = r.workspace_id
         WHERE r.id = resource_id AND t.id = tag_id
    ));

GRANT SELECT, INSERT, UPDATE, DELETE ON resource_tags TO platform_app;
GRANT SELECT, INSERT, DELETE ON resource_tag_links TO platform_app;
