-- ============================================================================
-- 0117_generated_join_tables.sql
-- A join table the platform makes for a many-to-many link (§562;
-- `object-link-types` p.200).
--
--     "It is now possible to automatically generate a join table for new link
--      types. The Generate join table option will create a dataset with the
--      correct schema based on the primary keys of the two object types you
--      have selected. This means that you can get started faster if you have
--      user edit-backed data, or if you want to provide production data later
--      on." (p.200-201)
--
-- The dataset is an ordinary one, empty at version 1, with one column for
-- each end's primary key. Its origin says the platform made it rather than a
-- person uploading it, which is what the dataset's page shows as its maker.
-- ============================================================================

ALTER TYPE dataset_origin ADD VALUE IF NOT EXISTS 'join_table';
