-- ============================================================================
-- 0028_object_type_versions.sql - a change history for object type
-- definitions (roadmap Objects item 5).
--
-- The roadmap says "changing an object type has no audit/version trail
-- today". True, and understated: **there is no way to change one at all.**
-- `create_type` and `delete_type` are the entire surface, and delete
-- cascades - a type's properties, its dataset mappings, its link types, its
-- actions and every materialised instance go with it (0003, 0012, 0013). So
-- the only route to "rename a property" has been to destroy the ontology
-- around it and rebuild by hand. Versioning a change that cannot be made is
-- not a feature, so this migration is half of a pair: an append-only history
-- here, and the edit operation it records in services/ontology.py.
--
-- Same shape as 0024 (model_versions), deliberately, and for the same reason
-- given there: an append-only table of numbered snapshots with the live rows
-- holding the current one, so nothing about the current-state read path
-- changes. **Rollback appends rather than rewinding** - restoring version 2
-- writes a version 5 whose content equals version 2's - so the history stays
-- a true record of what the type was at every point, including that somebody
-- reverted.
--
-- Why the snapshot stores the title property's **api_name**, not its id
-- ------------------------------------------------------------------
-- An edit rewrites `object_type_properties`: rows for removed properties are
-- deleted, and a retype is a delete plus an insert, so property ids do not
-- survive an edit. A history record holding `title_property_id` would
-- therefore dangle precisely when it was needed - the same principle already
-- applied to `model_versions.inputs`, `datasets.forked_from_dataset_id` and
-- `link_types.from_property`: a record of what happened must not change, or
-- break, when live state does. The api_name is the stable name (0003's own
-- comment calls it that), so that is what a snapshot keeps.
--
-- What is deliberately *not* versioned
-- -----------------------------------
--   * `api_name` on the type itself, because it is not editable. 0003 calls
--     it "the stable machine name used by the GraphQL API and exports" -
--     external consumers hold it, so changing it breaks them by definition,
--     and no in-product warning can reach an exporter. It stays immutable
--     after creation, like `models.language`.
--   * `title_property_id`'s *id* form, per above.
--   * Nothing else on the type is excluded. Unlike a model - where
--     trigger_mode and cron_schedule are how it runs rather than what it
--     computes - every remaining column on an object type (display_name,
--     description, icon, colour, properties) is part of the definition a
--     consumer sees, so all of it is snapshotted.
--
-- What this migration does **not** do, and why
-- ------------------------------------------
--   * It does not touch existing instances when a property disappears. A
--     stored instance keeps a properties key the type no longer declares;
--     the browse UI reads the type's property list, so an undeclared key
--     simply does not render, and the next sync rewrites the row without it.
--     Deleting data across a store this migration cannot reach (instances
--     may live in OpenSearch, §35) to tidy up a definition change would be a
--     destructive side effect of an administrative edit.
--   * It adds no foreign key from a version to a property row, for the same
--     reason the title property is stored by name.
--   * It does not enforce the impact rules. Whether a change is breaking
--     depends on `column_mappings` and `editable_properties` jsonb and on
--     `link_types` join columns - a cross-table judgement with a message to
--     compose, which belongs in the service, not in a CHECK.
-- ============================================================================

CREATE TABLE object_type_versions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_type_id uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    version_number integer NOT NULL CHECK (version_number > 0),
    display_name   text NOT NULL,
    description    text NOT NULL DEFAULT '',
    icon           text NOT NULL DEFAULT 'cube',
    colour         text NOT NULL DEFAULT '#4f46e5',
    -- [{"api_name", "display_name", "data_type", "required", "description",
    --   "sort_order"}, ...] exactly as the type declared them when saved.
    properties     jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- The title property's api_name, or NULL for none. Not an id - see above.
    title_property text,
    -- Set when this version was created by restoring an earlier one, so the
    -- history can say "reverted to v2" rather than showing an unexplained
    -- reappearance of an old definition.
    restored_from  integer,
    created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (object_type_id, version_number)
);

CREATE INDEX idx_object_type_versions_type
    ON object_type_versions (object_type_id, version_number DESC);

-- One hop to object_types, resolved through the rls_can_access_workspace
-- SECURITY DEFINER helper rather than a subselect that could recurse - the
-- same shape 0006 gives object_type_properties (the class of bug 0008/0009
-- fixed).
ALTER TABLE object_type_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY otv_isolation ON object_type_versions
    USING (EXISTS (SELECT 1 FROM object_types ot
                   WHERE ot.id = object_type_id
                     AND rls_can_access_workspace(ot.workspace_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON object_type_versions TO platform_app;

-- Backfill: every existing type gets a version 1 from its current state, so
-- "every object type has at least one version" holds from here on and the
-- API never has to special-case an empty history.
INSERT INTO object_type_versions (
    object_type_id, version_number, display_name, description, icon, colour,
    properties, title_property, created_by, created_at)
SELECT ot.id, 1, ot.display_name, ot.description, ot.icon, ot.colour,
       COALESCE(
           (SELECT jsonb_agg(jsonb_build_object(
                       'api_name', p.api_name,
                       'display_name', p.display_name,
                       'data_type', p.data_type,
                       'required', p.required,
                       'description', p.description,
                       'sort_order', p.sort_order)
                   ORDER BY p.sort_order, p.api_name)
              FROM object_type_properties p WHERE p.object_type_id = ot.id),
           '[]'::jsonb),
       (SELECT p.api_name FROM object_type_properties p
         WHERE p.id = ot.title_property_id),
       ot.created_by, ot.created_at
  FROM object_types ot;
