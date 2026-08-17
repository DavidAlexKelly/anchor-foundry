-- ============================================================================
-- 0051_edit_only_properties.sql
-- Edit-only properties (parity `docs/parity/ontology.md` §1.2; Foundry
-- `object-link-types` p.113-115).
--
-- > "Edit-only properties allow you to define Ontology properties that are not
-- > directly mapped to a column in the backing dataset of the object type.
-- > This is particularly useful for situations where you may want to store
-- > additional information alongside your object types without modifying the
-- > underlying dataset." (p.113)
--
-- **A stored flag, not "absent from every mapping".** The two are the same
-- state and different intentions: a property nobody mapped might be a
-- deliberate edit-only property, or it might be a column somebody renamed
-- upstream - and telling those apart is exactly what schema drift detection
-- (0018) exists to do. Deriving the flag would make drift undetectable for
-- every property it happened to describe, which is the one case drift matters
-- most. So the ontology says which it is, and `services/ontology.py` refuses
-- to map a property that says it is edit-only.
--
-- **The value lives only in the instance store.** p.113's "not mapped to a
-- column" is not a UI hint: there is no column to write it to, so an action
-- writes it to the instance and skips the dataset append that every other
-- property gets. That in turn is why a sync must *merge* rather than replace -
-- see `services/instances.upsert_instances`, where a replacing upsert
-- destroyed these values on Postgres while OpenSearch's `doc` merge quietly
-- kept them. Two stores, two answers, no error: the disagreement this column
-- made visible.
--
-- Default false, so every property that exists today is exactly what it was.
-- ============================================================================

ALTER TABLE object_type_properties
    ADD COLUMN edit_only boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN object_type_properties.edit_only IS
    'This property has no column in any backing dataset (Foundry '
    'object-link-types p.113). Written by actions straight to the instance '
    'store and never appended to the dataset; preserved across syncs rather '
    'than overwritten. Mapping one to a column is refused - untoggle it '
    'first, which is p.114''s own flow.';
