-- ============================================================================
-- 0108_listener_archives.sql
-- A listener's events, archived into a backing dataset (§519;
-- `data-connection` p.264).
--
--     "Every few minutes, the listener event stream will archive into a
--      backing dataset. This dataset can be used like any other dataset in
--      the platform, allowing you to build data pipelines and back your
--      ontology." (p.264)
--
-- **Where the archive has got to is one number**, the highest event id it
-- has written. Events are appended with an identity (db 0106), so "archived
-- through 41" names exactly what is in the dataset and what is not, without
-- a flag per event.
--
-- **Deleting the dataset starts the archive again from the first event**,
-- rather than resuming at `archived_through` into a new dataset that would
-- then be missing everything before it. The events are still in
-- `listener_events`, so nothing is lost by starting over. The archiver reads
-- a NULL dataset as "from the beginning".
--
-- The worker finds listeners with unarchived events through a SECURITY
-- DEFINER function, the discovery shape db 0014 set, and archives each one
-- through a workspace-scoped connection.
-- ============================================================================

ALTER TYPE dataset_origin ADD VALUE IF NOT EXISTS 'listener';

ALTER TABLE listeners
    ADD COLUMN archive_dataset_id uuid REFERENCES datasets(id) ON DELETE SET NULL,
    ADD COLUMN archived_through   bigint NOT NULL DEFAULT 0 CHECK (archived_through >= 0),
    ADD COLUMN archived_at        timestamptz;

CREATE FUNCTION list_listeners_to_archive() RETURNS TABLE(listener_id uuid, workspace_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT l.id, l.workspace_id
      FROM listeners l
     WHERE EXISTS (
         SELECT 1 FROM listener_events e
          WHERE e.listener_id = l.id
            AND e.id > CASE WHEN l.archive_dataset_id IS NULL THEN 0 ELSE l.archived_through END
     )
     ORDER BY l.archived_at NULLS FIRST
$$;

REVOKE EXECUTE ON FUNCTION list_listeners_to_archive() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION list_listeners_to_archive() TO platform_app;
