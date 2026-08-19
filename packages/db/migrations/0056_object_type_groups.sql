-- ============================================================================
-- 0056_object_type_groups.sql
-- Object type groups (parity `docs/parity/ontology.md` §1.3; Foundry
-- `object-link-types` p.261-263).
--
-- > "Object type groups are a classification primitive that help users better
-- > search and explore their ontology. Groups are created and managed using
-- > Ontology Manager, generally by ontology owners and editors." (p.261)
--
-- A classification, not a container
-- ---------------------------------
-- Nothing about a group changes what an object type *is*. It carries no
-- properties, no datasource, no behaviour - p.262 lists its entire purpose as
-- search, a filterable column in the Ontology Manager table, and a section on
-- the Object Explorer home page. So the membership is its own row rather than
-- a column on `object_types`: an object type belongs to several groups (p.261
-- offers "Edit groups" in the plural from the object type page), and a group
-- holds several object types.
--
-- The rule p.263 changed on purpose, and why it decides the RLS
-- ------------------------------------------------------------
-- > "Previously, if all object types inside a group were non-discoverable to a
-- > certain user … the group was also non-discoverable to the user. As
-- > mentioned in the section above on group permissions, all groups will now
-- > be discoverable to any user that can view the ontology. This change aligns
-- > group visibility with other ontology primitives to increase clarity and
-- > transparency in governance." (p.263)
--
-- A group's visibility is therefore a fact about the *group*, never a function
-- of its members. That is one line of policy here - `rls_can_access_workspace`
-- and nothing else - and it is the line a natural implementation gets wrong,
-- because a listing built as a join to the membership table derives exactly
-- the behaviour p.263 removed: a group whose members you cannot see, or that
-- has no members at all, silently disappears.
--
-- `workspace_id` on the membership row is the same decision one level down.
-- A policy that reached through to `object_type_groups` would be the RLS shape
-- this repo has now hit three times (0008, 0009, 0015: a policy whose USING
-- clause subqueries a table whose own policy can hide the row it needs, so the
-- check fails closed and silently). The composite foreign keys below make the
-- denormalised column impossible to get wrong.
--
-- Which also spells p.192's boundary in SQL
-- -----------------------------------------
-- Because both foreign keys carry `workspace_id`, a group cannot contain an
-- object type from another workspace - the same "not supported across
-- Ontologies" rule link types have, enforced by the schema rather than
-- re-checked in Python on every write.
--
-- Both cascades delete the membership, never the thing on the other end
-- --------------------------------------------------------------------
-- Deleting a group un-classifies its object types; deleting an object type
-- removes it from its groups. Neither reaches further, and unlike 0053's
-- `ON DELETE SET NULL` there is nothing to preserve: a membership row carries
-- no configuration of its own, so there is no half-state worth keeping.
-- ============================================================================

CREATE TABLE object_type_groups (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- Same shape as every other ontology api_name (0003), because a group is
    -- searchable by it (p.262) and appears in the same result list as object
    -- types and shared properties - one that could hold a shape the others
    -- could not would be a difference with no meaning behind it.
    api_name        text NOT NULL
                        CHECK (api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    display_name    text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    description     text NOT NULL DEFAULT '',
    created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, api_name),
    -- Redundant with the primary key, and required as the target of the
    -- membership table's composite foreign key below.
    UNIQUE (id, workspace_id)
);

CREATE INDEX idx_object_type_groups_workspace
    ON object_type_groups (workspace_id);

CREATE TRIGGER trg_object_type_groups_updated BEFORE UPDATE ON object_type_groups
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE object_type_groups IS
    'A classification of object types for search and exploration (Foundry '
    'object-link-types p.261-263). Carries no schema: an object type in a '
    'group is unchanged by being in it.';

-- Needed as the second composite foreign key target. `object_types.id` is
-- already unique; this states the pair so the membership row can carry the
-- workspace without being able to disagree with it.
ALTER TABLE object_types ADD CONSTRAINT object_types_id_workspace_key
    UNIQUE (id, workspace_id);

CREATE TABLE object_type_group_members (
    group_id        uuid NOT NULL,
    object_type_id  uuid NOT NULL,
    -- Denormalised so this table's RLS policy can answer without reading
    -- another RLS-protected table. Both composite foreign keys pin it to the
    -- same value the group and the object type hold, so it cannot drift and
    -- cannot span two workspaces.
    workspace_id    uuid NOT NULL,
    added_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, object_type_id),
    FOREIGN KEY (group_id, workspace_id)
        REFERENCES object_type_groups (id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (object_type_id, workspace_id)
        REFERENCES object_types (id, workspace_id) ON DELETE CASCADE
);

-- The reverse lookup - "which groups is this object type in" - is p.261's
-- "Edit groups in the object type overview page" and p.262's filterable
-- column, so it is as hot as the forward one.
CREATE INDEX idx_otgm_object_type ON object_type_group_members (object_type_id);
CREATE INDEX idx_otgm_workspace ON object_type_group_members (workspace_id);

COMMENT ON TABLE object_type_group_members IS
    'Which object types are in which group. workspace_id is denormalised so '
    'the RLS policy need not read object_type_groups; the composite foreign '
    'keys keep it honest and confine a group to one workspace (p.192).';

-- p.263: "To view object type groups, users must have viewer permission on
-- the project that the object type group is in." A workspace is this
-- platform's ontology (0003), so that is workspace access - and crucially it
-- is *only* that. A group stays visible when its members are not, which is
-- the change p.263 describes making deliberately.
ALTER TABLE object_type_groups ENABLE ROW LEVEL SECURITY;
CREATE POLICY object_type_groups_isolation ON object_type_groups
    USING (rls_can_access_workspace(workspace_id));

ALTER TABLE object_type_group_members ENABLE ROW LEVEL SECURITY;
CREATE POLICY object_type_group_members_isolation ON object_type_group_members
    USING (rls_can_access_workspace(workspace_id));
