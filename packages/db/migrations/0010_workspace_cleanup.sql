-- ============================================================================
-- 0010_workspace_cleanup.sql
-- Workspace deletion (API) removes the row synchronously; the isolated
-- ws_* PostgreSQL schema is dropped asynchronously by the worker (see the
-- "Flagged for review" note in apps/api/src/services/workspaces.py). DDL
-- stays privileged: platform_app cannot DROP SCHEMA directly, so the drop is
-- wrapped in a SECURITY DEFINER function with two guards —
--   1. the name must match the ws_* shape provision_workspace_schema creates;
--   2. no live workspaces row may reference it (orphans only).
-- ============================================================================

CREATE FUNCTION drop_orphaned_workspace_schema(p_schema text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF p_schema !~ '^ws_[a-z0-9_]+$' THEN
        RAISE EXCEPTION 'refusing to drop non-workspace schema %', p_schema;
    END IF;
    IF EXISTS (SELECT 1 FROM workspaces w WHERE w.pg_schema = p_schema) THEN
        RAISE EXCEPTION 'schema % belongs to a live workspace', p_schema;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.schemata s WHERE s.schema_name = p_schema
    ) THEN
        RETURN false;  -- already gone: cleanup is idempotent
    END IF;
    EXECUTE format('DROP SCHEMA %I CASCADE', p_schema);
    RETURN true;
END;
$$;

-- Enumerate cleanup candidates without granting catalog-wide trust to the
-- caller's own filtering: the orphan test lives server-side.
CREATE FUNCTION list_orphaned_workspace_schemas() RETURNS SETOF text
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT s.schema_name::text
      FROM information_schema.schemata s
     WHERE s.schema_name ~ '^ws_[a-z0-9_]+$'
       AND NOT EXISTS (SELECT 1 FROM workspaces w WHERE w.pg_schema = s.schema_name)
     ORDER BY 1
$$;

REVOKE EXECUTE ON FUNCTION drop_orphaned_workspace_schema(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION list_orphaned_workspace_schemas() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION drop_orphaned_workspace_schema(text) TO platform_app;
GRANT EXECUTE ON FUNCTION list_orphaned_workspace_schemas() TO platform_app;
