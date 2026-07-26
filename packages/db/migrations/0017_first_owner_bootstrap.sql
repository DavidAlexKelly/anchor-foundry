-- ============================================================================
-- 0017_first_owner_bootstrap.sql
-- First-owner bootstrap (spec gap found during real deploy validation, see
-- STATUS.md §17): self-signup is deliberately disabled and the invite flow
-- deliberately refuses to create an 'owner' role (services/orgs.py), so a
-- freshly provisioned customer stack had *no* path at all to create its
-- first organisation or first user - every real deploy needed this done by
-- hand directly against Postgres.
--
-- A SECURITY DEFINER function, not an API-layer privileged connection: it
-- runs with elevated rights regardless of the caller's RLS context (the
-- ordinary platform_app-scoped request connection has none, pre-auth), the
-- same pattern already used throughout this schema (rls_is_org_admin,
-- rls_worker_for_workspace, etc.) rather than inventing a new connection
-- pathway. The one-time guard lives here, at the only point that can
-- atomically check-and-insert without a race: if this is called twice
-- concurrently on an empty database, exactly one call succeeds.
-- ============================================================================

CREATE FUNCTION platform_has_any_organisation() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (SELECT 1 FROM organisations)
$$;

REVOKE EXECUTE ON FUNCTION platform_has_any_organisation() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION platform_has_any_organisation() TO platform_app;

CREATE FUNCTION bootstrap_first_owner(
    p_org_name text,
    p_org_slug text,
    p_cognito_sub text,
    p_email text,
    p_display_name text
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_org_id uuid;
BEGIN
    -- LOCK first: without it, two concurrent callers could both pass the
    -- EXISTS check before either INSERTs. Locking the whole table is fine -
    -- this function is called at most once per deployment's lifetime, never
    -- in a hot path.
    LOCK TABLE organisations IN EXCLUSIVE MODE;
    IF EXISTS (SELECT 1 FROM organisations) THEN
        RAISE EXCEPTION 'platform already has an organisation; first-owner bootstrap is a one-time operation'
            USING ERRCODE = 'unique_violation';
    END IF;
    INSERT INTO organisations (name, slug) VALUES (p_org_name, p_org_slug) RETURNING id INTO v_org_id;
    INSERT INTO users (organisation_id, cognito_sub, email, display_name, org_role, status)
    VALUES (v_org_id, p_cognito_sub, p_email, p_display_name, 'owner', 'active');
    RETURN v_org_id;
END;
$$;

REVOKE EXECUTE ON FUNCTION bootstrap_first_owner(text, text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION bootstrap_first_owner(text, text, text, text, text) TO platform_app;
