-- ============================================================================
-- 0109_listener_ingress.sql
-- A listener's ingress allowlist (§520; `data-connection` p.254-255).
--
--     "A subdomain with custom ingress will have a separate ingress
--      configuration from its parent domain … listener subdomains can be
--      configured to allow ingress from entire countries or specific IP
--      ranges that you otherwise do not want to allow to access the rest of
--      your enrollment." (p.254)
--
--     "Configuring a small IP range (smaller than the primary enrollment
--      ingress allow list) to allow requests to a listener with only basic
--      authorization or header secret verification available." (p.255)
--
-- **Per listener, not per subdomain.** This platform serves one domain, so
-- p.254's subdomain is not a thing to create; what p.255 wants from it is a
-- narrower allowlist for one listener, and that is a column. Empty is p.255's
-- "inherited ingress": no restriction beyond what reaches the platform at all.
--
-- Fifty ranges: a list longer than that is a country, and countries are not
-- IP ranges this platform knows.
-- ============================================================================

ALTER TABLE listeners
    ADD COLUMN ingress_allowlist cidr[] NOT NULL DEFAULT '{}'
        CHECK (cardinality(ingress_allowlist) <= 50);

DROP FUNCTION listener_for_token(text);

CREATE FUNCTION listener_for_token(p_token text)
RETURNS TABLE(listener_id uuid, endpoint_id uuid, running boolean, verification text,
              verification_header text, secret_arn text, expired boolean,
              ingress_allowlist text[])
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT l.id, e.id, l.running, l.verification, l.verification_header, l.secret_arn,
           (e.expires_at IS NOT NULL AND e.expires_at <= now()),
           l.ingress_allowlist::text[]
      FROM listener_endpoints e
      JOIN listeners l ON l.id = e.listener_id
     WHERE e.token = p_token
$$;

REVOKE EXECUTE ON FUNCTION listener_for_token(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION listener_for_token(text) TO platform_app;
