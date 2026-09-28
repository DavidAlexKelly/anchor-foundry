-- ============================================================================
-- 0132_object_backed_links.sql
-- Link types backed by an object type (§666; `object-link-types` p.197,
-- p.199).
--
--     "Backing object type: Object-backed link types expand on many-to-one
--      cardinality link types, providing first class support for object types
--      as a link type storage solution." (p.197)
--
--     "With an object-backed link, you can have the Flight Manifest object
--      type that links the Aircraft and Flight objects. Unlike a foreign key
--      or data-set backed link, this Flight Manifest object can contain
--      additional properties such as Pilot and First Mate to provide
--      additional metadata on the link." (p.199)
--
-- p.197's third relationship type, beside 0027's property pair and 0115's
-- join table. **Each backing object is one link**: a Flight Manifest that
-- names an aircraft and a flight says those two are linked, and carries what
-- else is known about that link. p.199's prerequisites are the two many-to-one
-- links from the backing type to each end, and those are what is stored here:
-- the backing type and the two links through it, whose own pairs say which
-- properties are compared. Nothing is copied from them, so a link whose
-- backing links change follows the change.
--
-- **A pair, a join table or a backing type, never two** - each is a whole
-- answer to which objects are linked (0115's rule, one more alternative).
--
-- **Deleting the backing type or either link unmaps the link rather than
-- deleting it**, as 0115 does for a join table's dataset: a link with no way
-- to follow it is still a valid ontology statement (0027), untraversable
-- until it is backed again.
-- ============================================================================

ALTER TABLE link_types
    ADD COLUMN backing_type_id uuid REFERENCES object_types(id) ON DELETE SET NULL,
    ADD COLUMN backing_from_link_id uuid REFERENCES link_types(id) ON DELETE SET NULL,
    ADD COLUMN backing_to_link_id uuid REFERENCES link_types(id) ON DELETE SET NULL,
    ADD CONSTRAINT link_types_backing_alone
        CHECK (backing_type_id IS NULL OR (from_property IS NULL AND join_from_column IS NULL)),
    ADD CONSTRAINT link_types_backing_links_distinct
        CHECK (backing_from_link_id IS DISTINCT FROM backing_to_link_id OR backing_from_link_id IS NULL);

COMMENT ON COLUMN link_types.backing_type_id IS
    'p.199''s backing object type (db 0132): each of its objects is one link, '
    'reached from the from end by backing_from_link_id and the to end by '
    'backing_to_link_id.';
