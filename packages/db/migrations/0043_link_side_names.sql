-- ============================================================================
-- 0043_link_side_names.sql
-- Per-side display names on a link type (parity `docs/parity/ontology.md` §2;
-- Foundry `object-link-types` p.192).
--
-- > "A link type is **bidirectional**: it always has two sides, one for each of
-- > the two object types it relates. Each side of a link type can be traversed
-- > independently and **has its own display name** and API name. For example, a
-- > single Flight ↔ Aircraft link type includes a Flight side and an Aircraft
-- > side."
--
-- We name a link type once, so both directions read the same and one of them
-- reads backwards: from an Employee, "Employment" is a poor label for the
-- company, and from the Company it is a poor label for the people. Foundry's
-- example is the fix - Employee → *Employer*, Company → *Employees*.
--
-- **Which name goes with which side.** `to_side_name` names the side you reach
-- by traversing from → to, and `from_side_name` names the side you reach going
-- the other way. That matches p.192's reading: the *Aircraft side* of a Flight
-- ↔ Aircraft link is the one a flight traverses to reach its aircraft.
--
-- **Nullable, falling back to `display_name`.** Every existing link type keeps
-- exactly the label it has today, and a builder who does not care about the
-- distinction never has to fill these in. A NOT NULL default of '' would have
-- meant the same thing while making "unset" and "deliberately blank"
-- indistinguishable.
--
-- **Self-links need no schema change** and never did: `from_object_type_id` and
-- `to_object_type_id` may already be equal, and `link_types_for_type` returns
-- such a link twice on purpose, once per direction. What was missing is exactly
-- what this migration adds - two names, so the two directions can be told
-- apart. `ontology.md` §2 listed self-links as absent; that was wrong about the
-- traversal and right about the naming.
-- ============================================================================

ALTER TABLE link_types
    ADD COLUMN from_side_name text,
    ADD COLUMN to_side_name   text;

ALTER TABLE link_types
    ADD CONSTRAINT link_types_from_side_name_length
        CHECK (from_side_name IS NULL OR length(from_side_name) BETWEEN 1 AND 200),
    ADD CONSTRAINT link_types_to_side_name_length
        CHECK (to_side_name IS NULL OR length(to_side_name) BETWEEN 1 AND 200);

COMMENT ON COLUMN link_types.from_side_name IS
    'Label for the side reached by traversing to -> from (Foundry p.192). '
    'NULL falls back to display_name.';
COMMENT ON COLUMN link_types.to_side_name IS
    'Label for the side reached by traversing from -> to (Foundry p.192). '
    'NULL falls back to display_name.';
