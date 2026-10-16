-- The worker's half of a retention policy (§965; decision 0005; db 0170).
--
-- 0170 said which versions a policy lets go. These are what the worker's
-- sweeper calls to act on that, and nothing else marks a version expired.
-- The order is mark, then delete, then unmark if the delete failed: a reader
-- never finds a version said to be kept whose bytes are gone, and a sweep
-- that stops between the two leaves bytes behind rather than a hole.

-- Every dataset with a policy: the sweeper's candidates, across workspaces.
CREATE FUNCTION datasets_with_retention()
RETURNS TABLE (dataset_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT id FROM datasets WHERE retention_versions IS NOT NULL ORDER BY id
$$;

-- Mark one version expired, and with it every expirable version of the same
-- dataset sharing its file, so they go together (0170's rule lets them go
-- only together). Asked again here, under a lock on the dataset, rather than
-- trusted from when the sweeper listed it: a policy changed, a version
-- written or an export run since then all count. Returns the file whose
-- bytes the caller now removes ('' for a version that never had one), or
-- NULL when the version may not go.
CREATE FUNCTION expire_dataset_version(p_dataset uuid, p_version integer)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_key text;
BEGIN
    PERFORM 1 FROM datasets WHERE id = p_dataset FOR UPDATE;
    SELECT e.s3_manifest_key INTO v_key
      FROM expirable_dataset_versions(p_dataset) e
     WHERE e.version_number = p_version;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF v_key IS NULL THEN
        UPDATE dataset_versions SET expired_at = now()
         WHERE dataset_id = p_dataset AND version_number = p_version;
        RETURN '';
    END IF;
    UPDATE dataset_versions SET expired_at = now()
     WHERE dataset_id = p_dataset
       AND s3_manifest_key = v_key
       AND version_number IN (SELECT version_number FROM expirable_dataset_versions(p_dataset));
    RETURN v_key;
END;
$$;

-- Undo a mark whose delete failed: the bytes are all still there.
CREATE FUNCTION unexpire_dataset_version(p_dataset uuid, p_key text)
RETURNS void
LANGUAGE sql SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE dataset_versions SET expired_at = NULL
     WHERE dataset_id = p_dataset AND s3_manifest_key = p_key
$$;

REVOKE EXECUTE ON FUNCTION datasets_with_retention() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION expire_dataset_version(uuid, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION unexpire_dataset_version(uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION datasets_with_retention() TO platform_app;
GRANT EXECUTE ON FUNCTION expire_dataset_version(uuid, integer) TO platform_app;
GRANT EXECUTE ON FUNCTION unexpire_dataset_version(uuid, text) TO platform_app;
