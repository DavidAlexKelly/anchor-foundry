-- ============================================================================
-- 0115_link_join_tables.sql
-- Many-to-many link types backed by a join table dataset (§552;
-- `object-link-types` p.35, p.197-198).
--
--     "Join table dataset: For "many-to-many" cardinality link types. This
--      option allows you to use a join table dataset to back the link."
--      (p.197)
--
--     "In a many-to-many cardinality, select a datasource that includes all
--      combinations of links between the primary key of the first object type
--      … and the second object type." (p.35)
--
-- 0027 made a link a property pair compared for equality, and said what that
-- could not do: "No join-table relationships". One foreign key cannot say
-- that a flight had two aircraft, so a many-to-many link was one only when
-- both sides happened to hold a shared key. This is p.197's second
-- relationship type: a dataset whose rows are the pairs, one column holding
-- the `from` type's primary key and one the `to` type's.
--
-- **A join table or a property pair, never both** - they are two answers to
-- "which objects are linked", and a link with both would have to pick one.
-- And **many-to-many only**, as p.197 has it: a one-to-many link is a foreign
-- key, which the pair already expresses without a second dataset to keep.
--
-- The columns are named, not the dataset's schema re-read at traversal: a
-- rename upstream then fails the traversal with a sentence rather than
-- quietly joining on whatever column now sits in that position.
--
-- **Deleting the dataset unmaps the link rather than deleting it**, the way a
-- link with no join is still a valid ontology statement (0027): the columns
-- stay, saying what the link was joined on, and it is untraversable until a
-- join table is chosen again.
-- ============================================================================

ALTER TABLE link_types
    ADD COLUMN join_dataset_id uuid REFERENCES datasets(id) ON DELETE SET NULL,
    ADD COLUMN join_from_column text,
    ADD COLUMN join_to_column text,
    ADD CONSTRAINT link_types_join_columns_paired
        CHECK ((join_from_column IS NULL) = (join_to_column IS NULL)),
    ADD CONSTRAINT link_types_join_columns_distinct
        CHECK (join_from_column IS DISTINCT FROM join_to_column OR join_from_column IS NULL),
    ADD CONSTRAINT link_types_join_dataset_named
        CHECK (join_dataset_id IS NULL OR join_from_column IS NOT NULL),
    ADD CONSTRAINT link_types_join_table_or_pair
        CHECK (join_from_column IS NULL OR from_property IS NULL),
    ADD CONSTRAINT link_types_join_table_many_to_many
        CHECK (join_from_column IS NULL OR cardinality = 'many_to_many');
