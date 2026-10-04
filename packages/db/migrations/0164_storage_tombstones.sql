-- What a deleted workspace or dataset left in the bucket, and who removes it (§864).
--
-- Deleting a workspace removes its rows by cascade and, by `services/
-- workspaces.delete`'s own comment, leaves "the ws_* pg schema and S3 prefix"
-- to "an async worker job". The job (`jobs/cleanup.py`) only ever dropped the
-- schema. Every file the workspace held stayed in the bucket as a current
-- object - so not even §852's thirty-day rule for previous versions reached it
-- - for the life of the stack. A project's deletion was the same one level
-- down: its datasets' rows went with it by cascade and their files did not.
--
-- So a deletion now leaves a tombstone naming the prefix, in the transaction
-- that deleted the row, and the worker's nightly cleanup deletes what each
-- names. A trigger rather than the API's delete routes, because a cascade is
-- not a route: a project's datasets are deleted by the database, which is the
-- only place that sees each of them go.
--
-- A dataset deleted as part of its workspace leaves no tombstone of its own:
-- by the time its trigger runs the workspace row is gone, and the workspace's
-- tombstone covers the whole prefix. A dataset deleted through the API already
-- has its files removed inline; its tombstone then names an empty prefix,
-- which costs one listing.

CREATE TABLE storage_tombstones (
    id        bigserial PRIMARY KEY,
    prefix    text NOT NULL,
    queued_at timestamptz NOT NULL DEFAULT now()
);

-- Nothing reads or writes these but the functions below: not the application
-- role (default privileges would otherwise grant it everything, 0006), and
-- not through RLS, which is on with no policy.
REVOKE ALL ON storage_tombstones FROM platform_app;
REVOKE ALL ON SEQUENCE storage_tombstones_id_seq FROM platform_app;
ALTER TABLE storage_tombstones ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION tombstone_workspace_storage() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO storage_tombstones (prefix) VALUES (OLD.s3_prefix);
    RETURN OLD;
END;
$$;

CREATE TRIGGER trg_workspaces_storage_tombstone
    AFTER DELETE ON workspaces
    FOR EACH ROW EXECUTE FUNCTION tombstone_workspace_storage();

CREATE FUNCTION tombstone_dataset_storage() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO storage_tombstones (prefix)
    SELECT w.s3_prefix || 'datasets/' || OLD.id::text || '/'
      FROM workspaces w
     WHERE w.id = OLD.workspace_id;
    RETURN OLD;
END;
$$;

CREATE TRIGGER trg_datasets_storage_tombstone
    AFTER DELETE ON datasets
    FOR EACH ROW EXECUTE FUNCTION tombstone_dataset_storage();

-- The worker's side: a page of tombstones, oldest first, and forgetting one
-- once its prefix is empty. The worker validates each prefix before deleting
-- anything; these hand back whatever was recorded.
CREATE FUNCTION list_storage_tombstones(p_limit integer)
RETURNS TABLE(id bigint, prefix text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT t.id, t.prefix FROM storage_tombstones t ORDER BY t.id LIMIT p_limit
$$;

CREATE FUNCTION forget_storage_tombstone(p_id bigint) RETURNS void
LANGUAGE sql SECURITY DEFINER
SET search_path = public
AS $$
    DELETE FROM storage_tombstones WHERE id = p_id
$$;

REVOKE EXECUTE ON FUNCTION list_storage_tombstones(integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION forget_storage_tombstone(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION list_storage_tombstones(integer) TO platform_app;
GRANT EXECUTE ON FUNCTION forget_storage_tombstone(bigint) TO platform_app;
